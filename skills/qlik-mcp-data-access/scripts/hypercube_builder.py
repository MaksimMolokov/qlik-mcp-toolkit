"""Validate and format Qlik Engine hypercube arguments before an MCP tool call.

This module never calls mcp__qlik__* itself — a script cannot reach the MCP
transport. It only prepares/validates arguments and parses responses that the
agent obtained via a native tool call.
"""

from __future__ import annotations

import re
from typing import Any

HARD_MAX_ROWS = 5000
HARD_MAX_CELLS = 9900


def estimate_dimension_product(distinct_values: list[int]) -> int:
    """Worst-case row count of a dimensioned hypercube (product of cardinalities)."""
    product = 1
    for value in distinct_values:
        product *= max(value, 1)
    return product


def check_row_budget(distinct_values: list[int], max_rows: int, num_columns: int) -> list[str]:
    """Return a list of problems; empty list means the plan is safe to send."""
    problems: list[str] = []
    if max_rows > HARD_MAX_ROWS:
        problems.append(f"max_rows={max_rows} превышает жёсткий лимит сервера {HARD_MAX_ROWS}")
    if max_rows * num_columns > HARD_MAX_CELLS:
        problems.append(
            f"columns*max_rows={num_columns * max_rows} превышает лимит ячеек {HARD_MAX_CELLS}"
        )
    worst_case = estimate_dimension_product(distinct_values)
    if worst_case > HARD_MAX_ROWS:
        problems.append(
            f"произведение cardinality измерений ({worst_case}) может дать больше "
            f"{HARD_MAX_ROWS} строк — сузь через Set Analysis в measure, снизь max_rows "
            "до top-N, или разбей запрос по категориям"
        )
    return problems


_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def set_analysis_clause(field: str, values: list[Any], *, is_range: bool = False) -> str:
    """Build one `{<Field={...}>}` clause with correct quoting per value type.

    Numbers -> unquoted. Text -> single-quoted (exact match). Range/comparison
    strings (e.g. ">=2024<=2026") -> double-quoted. Never mixes types in one
    clause without the caller being explicit via `is_range`.
    """
    if is_range:
        if len(values) != 1 or not isinstance(values[0], str):
            raise ValueError("is_range=True требует ровно одну строку-выражение диапазона")
        rendered = f'"{values[0]}"'
    else:
        rendered_values = []
        for value in values:
            if isinstance(value, (int, float)):
                rendered_values.append(str(value))
            elif isinstance(value, str) and _NUMBER_RE.match(value):
                raise ValueError(
                    f"значение {value!r} похоже на число, но передано строкой — "
                    "числа передавай БЕЗ кавычек (int/float), иначе Qlik ищет ТЕКСТ"
                )
            else:
                escaped = str(value).replace("'", "''")
                rendered_values.append(f"'{escaped}'")
        rendered = ",".join(rendered_values)
    return f"{{<[{field}]={{{rendered}}}>}}"


def build_id_list_sort_expression(field: str, ids: list[Any]) -> dict[str, Any]:
    """Build a `dimensions[]` entry that addresses an EXACT known list of IDs
    inside a large dimension, when the server rejects a calculated dimension
    as the filtering mechanism (`={If(...)}` -> KeyError: 'field').

    Working alternative: a REAL field as dimension + `qSortByExpression`
    built from pure Set Analysis — `Count({<[Field]={'id1','id2',...}>}
    [Field])` evaluates to 1 for the wanted IDs and 0 for everything else —
    sorting descending by this expression with `max_rows=len(ids)` reliably
    surfaces exactly the wanted rows regardless of table size.
    """
    if field.startswith("="):
        raise ValueError(
            "вычисляемое измерение запрещено (ломает кэш модели / row-level scan) — "
            "используй build_dimension() с реальным полем"
        )
    clause = set_analysis_clause(field, ids)
    expr = f"Count({clause} [{field}])"
    return {"field": field, "sort_by": {"qSortByExpression": -1, "qExpression": expr}}


def build_dimension(field: str, *, sort_by_expression: str | None = None) -> dict[str, Any]:
    """Build a `dimensions[]` entry. Never pass a calculated dimension
    (`=Year(...)`, `=If(...)`) — only a real plain field name."""
    if field.startswith("="):
        raise ValueError(
            "вычисляемое измерение запрещено (ломает кэш модели / row-level scan) — "
            "используй готовое поле календаря/модели"
        )
    entry: dict[str, Any] = {"field": field}
    if sort_by_expression:
        entry["sort_by"] = {"qSortByExpression": -1, "qExpression": sort_by_expression}
    return entry


def build_measure(expression: str, label: str) -> dict[str, str]:
    if re.search(r"\bif\s*\(", expression, re.IGNORECASE):
        raise ValueError(
            f"measure {label!r} содержит If() внутри агрегата — per-row scan, "
            "перепиши через Set Analysis: Sum({<Field={...}>} Expr)"
        )
    return {"expression": expression, "label": label}


def parse_compact_response(response: dict[str, Any]) -> dict[str, Any]:
    """Extract the plain fields worth checking from a hypercube response."""
    return {
        "tool_call_seconds": response.get("tool_call_seconds"),
        "total_rows": response.get("total_rows"),
        "returned_rows": response.get("returned_rows"),
        "truncation_warning": response.get("truncation_warning"),
        "error": response.get("error"),
        "error_category": response.get("error_category"),
    }


def is_transient_connection_error(response: dict[str, Any]) -> bool:
    """True when the failure is the known first-call-after-idle WebSocket
    timeout (CreateSessionObject / OpenDoc), which a retry usually fixes.

    Live-observed 2026-08-04 through 2026-08-07 (28+ live calls across two
    sessions): identical hypercube calls repeatedly failed with
    `error_category: connection_error`, `failed_step: CreateSessionObject`,
    after ~183s (matches server default `QLIK_WS_TIMEOUT`); an immediate
    retry with the SAME arguments usually succeeded in 2-24s. Treat this
    pattern as retry (see `is_jwt_bootstrap_error` below for a second,
    distinct failure class). Stage-2 regression (07.08.2026) observed this
    failing on the FIRST attempt in >50% of live calls, including at least
    two cases where it failed AGAIN on a connection that had just succeeded
    seconds earlier — do not assume "warm connection = safe from this", and
    do not assume one retry is always enough (see SKILL.md step 10: retry
    up to two times before reporting).
    """
    return response.get("error_category") == "connection_error" and response.get(
        "failed_step"
    ) in {"CreateSessionObject", "OpenDoc", None}


def is_jwt_bootstrap_error(response: dict[str, Any]) -> bool:
    """True for a second, distinct transient failure class first observed
    2026-08-07 (stage-2 regression, cycle 006): the JWT session bootstrap
    itself times out (`QlikConnectionError`/`JwtBootstrapError`,
    `failed_stage: ensure_app`, message containing "csrftoken request
    failed" / SSL handshake timeout, ~47-60s elapsed) — NOT the usual
    Engine `CreateSessionObject` WebSocket timeout. Same remediation
    applies (retry the identical call), but log/report it separately if it
    recurs — it may indicate a different upstream problem (proxy/network)
    than the documented Engine WS-reconnect bug.
    """
    error_text = str(response.get("error", ""))
    return response.get("error_type") == "QlikConnectionError" or "JwtBootstrapError" in error_text or (
        "csrftoken" in error_text and "timed out" in error_text.lower()
    )


def build_hypercube_request_modern(
    app_id: str,
    dimensions: list[dict[str, Any]],
    measures: list[dict[str, Any]],
    *,
    sort_by: str | None = None,
    sort_order: str = "desc",
    limit: int = 1000,
    exclude_null_dimensions: bool = True,
) -> dict[str, Any]:
    """Build a top-level modern-schema `engine_create_hypercube` request, per
    github.com/bintocher/qlik-sense-mcp README (v1.6.0+): `sort_by` (measure
    label / expression / dimension field name, plain string — NOT the legacy
    per-dimension `{"qSortByExpression": ...}` object), `sort_order`,
    `limit` (replaces `max_rows`), `exclude_null_dimensions`.

    ✅ CONFIRMED LIVE 2026-08-07 after the project's server upgrade to
    `qlik-sense-mcp-server 1.7.2` — use this as the PRIMARY builder for
    ranking/top-N/simple sorted hypercubes going forward (see
    `references/live-test-results.json` -> `post_upgrade_verification_2026-08-07`,
    `references/tool-catalog.md`). It is also faster than the legacy
    `qSortByExpression` trick on large tables (server changelog reports
    ~1400x on a 91M-row table sorted by measure). Still worth a quick sanity
    check against the ACTUAL tool schema shown by the MCP client at the
    start of a session (`tools/list`) before relying on it blindly — the
    server is not version-pinned (`uvx` without `--refresh`), so it could in
    theory be downgraded/reinstalled outside this project's control. If the
    live schema lacks a top-level `sort_by`, fall back to
    `build_dimension()`/legacy shape below, which works on every version.
    For addressing an exact known list of IDs inside a large dimension,
    `build_id_list_sort_expression()` (legacy Set-Analysis trick) may still
    be needed even on modern — `sort_by` sorts by measure/dimension value,
    not by list membership.
    """
    request: dict[str, Any] = {
        "app_id": app_id,
        "dimensions": dimensions,
        "measures": measures,
        "limit": limit,
        "exclude_null_dimensions": exclude_null_dimensions,
    }
    if sort_by:
        request["sort_by"] = sort_by
        request["sort_order"] = sort_order
    return request

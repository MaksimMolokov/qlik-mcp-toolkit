"""Task-local Qlik result cache — no credentials, no MCP calls from here.

Population-lock support: keeps the exact rows of a previous answer so
follow-ups ("из этих", "среди них", "отсортируй предыдущий список") are
answered by local derivation, never by a silently broadened new query.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1
import os
DEFAULT_PATH = Path(os.environ.get("QLIK_MCP_TOOLKIT_HOME", str(Path.home() / ".qlik-mcp-toolkit"))) / "session-context.json"

_FORBIDDEN_KEYS = {"jwt", "token", "authorization", "headers"}


def empty_store(session_key: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "session_key": session_key,
        "updated_at": None,
        "active_result_key": None,
        "apps": {},
        "queries": {},
        "derivations": [],
    }


def load(path: Path = DEFAULT_PATH, session_key: str | None = None) -> dict[str, Any]:
    if not path.exists():
        return empty_store(session_key)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported Qlik session-context schema")
    stored_key = value.get("session_key")
    if session_key and stored_key and stored_key != session_key:
        return empty_store(session_key)
    for key, fallback in (("apps", {}), ("queries", {}), ("derivations", [])):
        value.setdefault(key, fallback)
    value.setdefault("active_result_key", None)
    return value


def save(store: dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    store["schema_version"] = SCHEMA_VERSION
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def normalized_query_key(
    *, app_id: str, metric: str, period: Any, filters: Any, dimensions: Any, selection_semantics: str
) -> str:
    canonical = json.dumps(
        {
            "app_id": app_id,
            "metric": metric,
            "period": period,
            "filters": filters,
            "dimensions": dimensions,
            "selection_semantics": selection_semantics,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _without_secrets(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k.lower() not in _FORBIDDEN_KEYS}


def upsert_query(store: dict[str, Any], key: str, record: dict[str, Any]) -> None:
    safe = _without_secrets(record)
    safe.setdefault("validation_status", "suspect")
    store.setdefault("queries", {})[key] = safe
    store["active_result_key"] = key


def reusable_query(
    store: dict[str, Any], key: str, current_reload_fingerprint: str | None = None
) -> dict[str, Any] | None:
    record = store.get("queries", {}).get(key)
    if not record or record.get("validation_status") != "validated":
        return None
    if current_reload_fingerprint is not None and record.get("reload_fingerprint") != current_reload_fingerprint:
        return None
    return record


def active_rows(store: dict[str, Any]) -> list[dict[str, Any]]:
    key = store.get("active_result_key")
    record = store.get("queries", {}).get(key, {})
    if record.get("validation_status") != "validated":
        return []
    return list(record.get("rows") or [])


def population_size(store: dict[str, Any]) -> int:
    return len(active_rows(store))


def check_population_bound(store: dict[str, Any], new_row_count: int) -> list[str]:
    """Population-lock guard: a follow-up answer must never contain more rows
    than the population it claims to derive from. Empty list = OK."""
    size = population_size(store)
    if size and new_row_count > size:
        return [
            f"новый результат содержит {new_row_count} строк, а зафиксированная "
            f"популяция — {size}. Фильтр по списку сущностей не применился — "
            "не показывай этот ответ, разберись и повтори запрос"
        ]
    return []


def derive_rows(
    store: dict[str, Any],
    *,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
    fields: list[str] | None = None,
    sort_key: str | None = None,
    reverse: bool = False,
    limit: int | None = None,
    operation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source_key = store.get("active_result_key")
    rows = active_rows(store)
    if predicate is not None:
        rows = [row for row in rows if predicate(row)]
    if sort_key is not None:
        rows.sort(key=lambda row: (row.get(sort_key) is None, row.get(sort_key)), reverse=reverse)
    if limit is not None:
        rows = rows[:limit]
    if fields is not None:
        rows = [{field: row.get(field) for field in fields} for row in rows]
    store.setdefault("derivations", []).append(
        {
            "derived_from_query_key": source_key,
            "operation": operation or {},
            "result": rows,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return rows

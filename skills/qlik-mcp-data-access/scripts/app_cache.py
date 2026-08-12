"""Persistent, cross-session cache of per-app semantic contracts.

Keyed by app_id + reload_fingerprint, stored at
`D:\\Claude\\Work\\MCP qlik\\app-cache.json` — separate from
qlik-mcp-session-context's task-local store, which only lives for one
conversation. This cache is meant to survive across conversations/days, so a
new conversation does not have to re-read the full `get_app_script` (tens of
thousands of characters) every time it touches an already-known app.

Scripts only read/write this file; they never call mcp__qlik__* — the agent
does, then hands the result here to cache or compare.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import os
CACHE_PATH = Path(os.environ.get("QLIK_MCP_TOOLKIT_HOME", str(Path.home() / ".qlik-mcp-toolkit"))) / "app-cache.json"
SCHEMA_VERSION = 1

_FORBIDDEN_KEYS = {"jwt", "token", "authorization", "headers"}


def _without_secrets(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k.lower() not in _FORBIDDEN_KEYS}


def load(path: Path = CACHE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "apps": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    value.setdefault("apps", {})
    return value


def save(store: dict[str, Any], path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    store["schema_version"] = SCHEMA_VERSION
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


def reload_fingerprint(app_details: dict[str, Any]) -> str:
    """Cheap fingerprint from get_apps/get_app_details fields — no need to
    open the app just to check whether the cache is still valid."""
    canonical = json.dumps(
        {
            "modified_dttm": app_details.get("modified_dttm") or app_details.get("modifiedDate"),
            "reload_dttm": app_details.get("reload_dttm") or app_details.get("lastReloadTime"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_cached_contract(store: dict[str, Any], app_id: str, current_fingerprint: str) -> dict[str, Any] | None:
    entry = store.get("apps", {}).get(app_id)
    if not entry:
        return None
    if entry.get("reload_fingerprint") != current_fingerprint:
        return None
    return entry


def upsert_contract(
    store: dict[str, Any],
    app_id: str,
    *,
    name: str,
    reload_fingerprint: str,
    qrs_description: str,
    script_description_summary: str,
    key_metrics: list[str],
    known_traps: list[str],
) -> None:
    store.setdefault("apps", {})[app_id] = _without_secrets(
        {
            "name": name,
            "reload_fingerprint": reload_fingerprint,
            "qrs_description": qrs_description,
            "script_description_summary": script_description_summary,
            "key_metrics": key_metrics,
            "known_traps": known_traps,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    )

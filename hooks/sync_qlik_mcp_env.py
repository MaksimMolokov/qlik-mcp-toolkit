#!/usr/bin/env python3
"""Copy the user's personal Qlik MCP credentials into plugin MCP configs.

Sources (never committed, never logged):
  Cursor: %USERPROFILE%\\.cursor\\mcp.json  → mcpServers.qlik.env
  Codex:  %USERPROFILE%\\.codex\\config.toml → [mcp_servers.qlik.env]

Targets: every qlik-mcp-toolkit .mcp.json under ~/.cursor and ~/.codex.
After a plugin update those files reset to ${QLIK_*} placeholders; this hook
writes the user's own URL and JWT back.

Stdout: a single JSON object. Secret values are never logged.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CURSOR_HOME = Path.home() / ".cursor"
CODEX_HOME = Path.home() / ".codex"
USER_MCP_JSON = CURSOR_HOME / "mcp.json"
CODEX_CONFIG = CODEX_HOME / "config.toml"
LOG_PATH = CURSOR_HOME / "hooks" / "logs" / "update-qlik-mcp.log"

SEARCH_ROOTS = (
    CURSOR_HOME / "plugins",
    CURSOR_HOME / "hooks" / "repos",
    CODEX_HOME / "plugins",
    CODEX_HOME / ".tmp" / "marketplaces",
)
SOURCE_FILES = (USER_MCP_JSON, CODEX_CONFIG)
ENV_KEYS = ("QLIK_SERVER_URL", "QLIK_JWT_TOKEN")
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
DUMMY_RE = re.compile(r"^(YOUR_|CHANGE_ME|TODO|XXX|INSERT_)", re.IGNORECASE)
TOML_ENV_SECTION_RE = re.compile(
    r"^\[mcp_servers\.qlik\.env\]\s*$",
    re.MULTILINE,
)
TOML_ASSIGN_RE = re.compile(
    r'^(QLIK_SERVER_URL|QLIK_JWT_TOKEN)\s*=\s*"(.*)"\s*$'
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{utc_now()} {message}\n")
    except OSError:
        pass


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def read_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def is_placeholder(value: str) -> bool:
    text = value.strip()
    return (not text) or bool(PLACEHOLDER_RE.match(text)) or bool(DUMMY_RE.match(text))


def is_usable(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if is_placeholder(text):
        return False
    if key == "QLIK_SERVER_URL":
        parsed = urlparse(text)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    if key == "QLIK_JWT_TOKEN":
        return len(text) >= 40
    return bool(text)


def url_host(url: str) -> str:
    return urlparse(url).netloc or "unknown-host"


def pick_usable(env: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(env, dict):
        return {}
    creds: dict[str, str] = {}
    for key in ENV_KEYS:
        value = env.get(key)
        if is_usable(key, value):
            creds[key] = str(value).strip()
    return creds


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_cursor_creds() -> dict[str, str]:
    data = load_json(USER_MCP_JSON)
    if not data:
        return {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return {}
    qlik = servers.get("qlik")
    if not isinstance(qlik, dict):
        return {}
    return pick_usable(qlik.get("env"))


def read_codex_toml_section(text: str) -> dict[str, str]:
    match = TOML_ENV_SECTION_RE.search(text)
    if not match:
        return {}
    creds: dict[str, str] = {}
    for line in text[match.end():].splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            break
        assign = TOML_ASSIGN_RE.match(stripped)
        if not assign:
            continue
        key, value = assign.group(1), assign.group(2).replace('\\"', '"')
        if is_usable(key, value):
            creds[key] = value
    return creds


def read_codex_creds() -> dict[str, str]:
    if not CODEX_CONFIG.is_file():
        return {}
    try:
        text = CODEX_CONFIG.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import tomllib

        data = tomllib.loads(text)
        qlik = ((data.get("mcp_servers") or {}).get("qlik") or {})
        creds = pick_usable(qlik.get("env") if isinstance(qlik, dict) else None)
        if creds:
            return creds
    except Exception:
        pass
    return read_codex_toml_section(text)


def read_env_creds() -> dict[str, str]:
    return pick_usable({key: os.environ.get(key) for key in ENV_KEYS})


def read_user_creds() -> tuple[dict[str, str], list[str]]:
    sources: list[tuple[str, dict[str, str]]] = [
        (str(USER_MCP_JSON), read_cursor_creds()),
        (str(CODEX_CONFIG), read_codex_creds()),
        ("environment", read_env_creds()),
    ]
    merged: dict[str, str] = {}
    used: list[str] = []
    for label, creds in sources:
        added = False
        for key, value in creds.items():
            if key not in merged:
                merged[key] = value
                added = True
        if added:
            used.append(label)
    return merged, used


def iter_plugin_mcp_files() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    skip = {path.resolve() for path in SOURCE_FILES if path.is_file()}
    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for name in (".mcp.json", "mcp.json"):
            for path in root.rglob(name):
                if "qlik-mcp-toolkit" not in path.parts:
                    continue
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if resolved in skip or resolved in seen:
                    continue
                seen.add(resolved)
                found.append(path)
    return found


def inject_into_file(path: Path, creds: dict[str, str]) -> bool:
    data = load_json(path)
    if not data:
        return False
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return False
    changed = False
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        env = server.get("env")
        if not isinstance(env, dict):
            env = {}
        touches_qlik = name == "qlik" or any(key in env for key in ENV_KEYS)
        if not touches_qlik:
            continue
        server["env"] = env
        for key, value in creds.items():
            if env.get(key) != value:
                env[key] = value
                changed = True
    if not changed:
        return False
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return True


def sync_credentials() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "source": [],
        "url_host": None,
        "token_present": False,
        "updated": [],
        "unchanged": [],
        "skipped": [],
        "error": None,
    }
    creds, used = read_user_creds()
    result["source"] = used
    result["token_present"] = "QLIK_JWT_TOKEN" in creds
    if "QLIK_SERVER_URL" in creds:
        result["url_host"] = url_host(creds["QLIK_SERVER_URL"])
    missing = [key for key in ENV_KEYS if key not in creds]
    if missing:
        result["error"] = (
            "no usable "
            + " / ".join(missing)
            + " in ~/.cursor/mcp.json or ~/.codex/config.toml [mcp_servers.qlik.env]"
        )
        return result

    targets = iter_plugin_mcp_files()
    if not targets:
        result["error"] = "no qlik-mcp-toolkit .mcp.json files found under ~/.cursor or ~/.codex"
        return result

    for path in targets:
        try:
            if inject_into_file(path, creds):
                result["updated"].append(str(path))
            else:
                result["unchanged"].append(str(path))
        except OSError as exc:
            result["skipped"].append(f"{path}: {exc}")

    result["ok"] = not result["skipped"] or bool(result["updated"] or result["unchanged"])
    if result["skipped"] and not result["updated"] and not result["unchanged"]:
        result["error"] = "failed to write plugin MCP files"
        result["ok"] = False
    return result


def format_context(result: dict[str, Any]) -> str:
    lines = ["[qlik-mcp env sync]"]
    if result.get("error"):
        lines.append(f"Credentials: error — {result['error']}")
        return "\n".join(lines)
    host = result.get("url_host") or "configured-host"
    source = ", ".join(result.get("source") or []) or "user MCP config"
    updated = result.get("updated") or []
    unchanged = result.get("unchanged") or []
    if updated:
        lines.append(
            f"Credentials: copied {host} + JWT from {source} "
            f"into {len(updated)} plugin MCP file(s)."
        )
    elif unchanged:
        lines.append(
            f"Credentials: plugin MCP already has {host} + JWT from {source} "
            f"({len(unchanged)} file(s))."
        )
    else:
        lines.append("Credentials: nothing to sync.")
    return "\n".join(lines)


def output_for_event(event: str, result: dict[str, Any]) -> dict[str, Any]:
    if event == "SessionStart":
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": format_context(result),
            }
        }
    if event == "sessionStart":
        return {"additional_context": format_context(result)}
    return {}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    payload = read_stdin()
    event = str(payload.get("hook_event_name") or os.environ.get("CURSOR_HOOK_EVENT") or "")
    try:
        result = sync_credentials()
        log(
            "env-sync "
            + json.dumps(
                {
                    "ok": result.get("ok"),
                    "url_host": result.get("url_host"),
                    "token_present": result.get("token_present"),
                    "source_count": len(result.get("source") or []),
                    "updated": len(result.get("updated") or []),
                    "unchanged": len(result.get("unchanged") or []),
                    "error": result.get("error"),
                },
                ensure_ascii=False,
            )
        )
        emit(output_for_event(event, result))
    except Exception as exc:
        log(f"env-sync fatal: {exc!r}")
        emit({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

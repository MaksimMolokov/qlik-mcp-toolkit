#!/usr/bin/env python3
"""Plugin hook: keep a local git clone of qlik-mcp-toolkit on origin/main.

Runs on Cursor workspaceOpen / sessionStart. Only updates an install under
~/.cursor/plugins/local/ — marketplace cache is pinned by Cursor and must
not be mutated. Also bumps qlik-sense-mcp-server in ~/.cursor/mcp.json when
a newer version is on PyPI.

Stdout must be a single JSON object. Logs go to a file, never stdout.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOOKS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = Path(os.environ.get("CURSOR_PLUGIN_ROOT") or HOOKS_DIR.parent)
LOCAL_PLUGIN_DIR = Path.home() / ".cursor" / "plugins" / "local" / "qlik-mcp-toolkit"
USER_MCP_JSON = Path.home() / ".cursor" / "mcp.json"
LOG_PATH = Path.home() / ".cursor" / "hooks" / "logs" / "update-qlik-mcp.log"

SKILLS_REPO = "https://github.com/MaksimMolokov/qlik-mcp-toolkit.git"
MCP_GITHUB_REPO = "https://github.com/bintocher/qlik-sense-mcp.git"
MCP_PACKAGE = "qlik-sense-mcp-server"
PIN_RE = re.compile(rf"({re.escape(MCP_PACKAGE)})==([0-9]+(?:\.[0-9]+)*)")

GIT_TIMEOUT = 45
HTTP_TIMEOUT = 15
GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


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


def parse_version(value: str) -> tuple[int, ...] | None:
    text = value.strip().lstrip("vV")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", text):
        return None
    return tuple(int(part) for part in text.split("."))


def version_gt(left: str, right: str) -> bool:
    a = parse_version(left)
    b = parse_version(right)
    if a is None or b is None:
        return False
    return a > b


def run_git(args: list[str], cwd: Path | None = None, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            [GIT, *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return subprocess.CompletedProcess(
            args=list(exc.cmd) if exc.cmd is not None else [GIT, *args],
            returncode=124,
            stdout=stdout,
            stderr=stderr or f"timeout after {timeout}s",
        )


def current_pin(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = PIN_RE.search(text)
    return match.group(2) if match else None


def bump_pin(path: Path, new_version: str) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    updated, count = PIN_RE.subn(rf"\1=={new_version}", text)
    if count == 0 or updated == text:
        return False
    path.write_text(updated, encoding="utf-8", newline="\n")
    return True


def http_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "qlik-mcp-toolkit-plugin-hook"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def pypi_latest() -> str | None:
    data = http_json(f"https://pypi.org/pypi/{MCP_PACKAGE}/json")
    version = str(data.get("info", {}).get("version") or "").strip()
    return version if parse_version(version) else None


def github_latest_tag() -> str | None:
    proc = run_git(["ls-remote", "--tags", "--refs", MCP_GITHUB_REPO])
    if proc.returncode != 0:
        return None
    best: str | None = None
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        tag = line.split("\t", 1)[1].strip().rsplit("/", 1)[-1]
        if parse_version(tag) is None:
            continue
        if best is None or version_gt(tag, best):
            best = tag.lstrip("vV")
    return best


def pypi_has_version(version: str) -> bool:
    try:
        http_json(f"https://pypi.org/pypi/{MCP_PACKAGE}/{version}/json")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    return True


def default_branch(repo: Path) -> str:
    proc = run_git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=repo)
    if proc.returncode == 0:
        ref = proc.stdout.strip()
        if ref.startswith("origin/"):
            return ref.split("/", 1)[1]
    return "main"


def read_plugin_version(plugin_dir: Path) -> str | None:
    for relative in (Path(".cursor-plugin") / "plugin.json", Path("plugin.json")):
        path = plugin_dir / relative
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        version = str(data.get("version") or "").strip()
        if version:
            return version
    return None


def git_head(repo: Path) -> str | None:
    proc = run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def clone_local() -> str | None:
    parent = LOCAL_PLUGIN_DIR.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / "qlik-mcp-toolkit.clone-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    clone = run_git(["clone", "--depth", "1", SKILLS_REPO, str(tmp)], timeout=90)
    if clone.returncode != 0:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        return f"git clone failed: {clone.stderr.strip()[:300]}"
    if LOCAL_PLUGIN_DIR.exists():
        shutil.rmtree(LOCAL_PLUGIN_DIR)
    tmp.rename(LOCAL_PLUGIN_DIR)
    leftover = LOCAL_PLUGIN_DIR / "mcp.json"
    if leftover.is_file():
        leftover.unlink()
    return None


def pull_local() -> str | None:
    fetch = run_git(["fetch", "--prune", "origin"], cwd=LOCAL_PLUGIN_DIR)
    if fetch.returncode != 0:
        return f"git fetch failed: {fetch.stderr.strip()[:300]}"
    branch = default_branch(LOCAL_PLUGIN_DIR)
    reset = run_git(["reset", "--hard", f"origin/{branch}"], cwd=LOCAL_PLUGIN_DIR)
    if reset.returncode != 0:
        return f"git reset failed: {reset.stderr.strip()[:300]}"
    leftover = LOCAL_PLUGIN_DIR / "mcp.json"
    if leftover.is_file():
        leftover.unlink()
    return None


def sync_local_clone() -> dict[str, Any]:
    info: dict[str, Any] = {
        "synced": False,
        "updated": False,
        "skipped": None,
        "version_before": None,
        "version_after": None,
        "head_before": None,
        "head": None,
        "error": None,
        "plugin_dir": str(LOCAL_PLUGIN_DIR),
    }
    git_ok = Path(GIT).is_file() or shutil.which("git") is not None
    if not git_ok:
        info["error"] = "git not found"
        return info

    if (LOCAL_PLUGIN_DIR / ".git").is_dir():
        info["version_before"] = read_plugin_version(LOCAL_PLUGIN_DIR)
        info["head_before"] = git_head(LOCAL_PLUGIN_DIR)
        err = pull_local()
    else:
        err = clone_local()

    if err:
        info["error"] = err
        return info

    info["synced"] = True
    info["head"] = git_head(LOCAL_PLUGIN_DIR)
    info["version_after"] = read_plugin_version(LOCAL_PLUGIN_DIR)
    info["updated"] = (info["head"] and info["head"] != info["head_before"]) or (
        info["version_before"] and info["version_after"] and info["version_before"] != info["version_after"]
    )
    if info["head_before"] is None and info["head"]:
        info["updated"] = True
    return info


def update_mcp_pin() -> dict[str, Any]:
    info: dict[str, Any] = {
        "current": current_pin(USER_MCP_JSON),
        "github": None,
        "pypi": None,
        "installed": None,
        "updated_files": [],
        "github_ahead": False,
        "error": None,
    }
    try:
        info["pypi"] = pypi_latest()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        info["error"] = f"pypi lookup failed: {exc}"
    try:
        info["github"] = github_latest_tag()
    except OSError as exc:
        log(f"github tag lookup failed: {exc}")

    candidate = info["pypi"]
    github = info["github"]
    if github and candidate and version_gt(github, candidate):
        info["github_ahead"] = True
        if pypi_has_version(github):
            candidate = github
    elif github and not candidate and pypi_has_version(github):
        candidate = github

    info["installed"] = candidate
    current = info["current"]
    if not candidate or not current or not version_gt(candidate, current):
        return info
    try:
        if bump_pin(USER_MCP_JSON, candidate):
            info["updated_files"].append(str(USER_MCP_JSON))
    except OSError as exc:
        info["error"] = f"failed to write pin: {exc}"
    return info


def inject_user_qlik_env() -> dict[str, Any]:
    module_path = Path(__file__).resolve().parent / "sync_qlik_mcp_env.py"
    if not module_path.is_file():
        return {"ok": False, "error": f"missing {module_path.name}"}
    spec = importlib.util.spec_from_file_location("sync_qlik_mcp_env", module_path)
    if spec is None or spec.loader is None:
        return {"ok": False, "error": "failed to load sync_qlik_mcp_env"}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.sync_credentials()


def upgrade_codex_marketplace() -> dict[str, Any]:
    info: dict[str, Any] = {
        "synced": False,
        "updated": False,
        "skipped": None,
        "error": None,
        "version_after": None,
        "head": None,
        "plugin_dir": str(LOCAL_PLUGIN_DIR),
    }
    exe = shutil.which("codex")
    if not exe:
        info["skipped"] = "codex not on PATH"
        return info
    try:
        proc = subprocess.run(
            [exe, "plugin", "marketplace", "upgrade"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        info["error"] = f"codex marketplace upgrade failed: {exc}"
        return info
    info["synced"] = True
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        info["error"] = detail or f"codex exited {proc.returncode}"
        return info
    info["updated"] = True
    info["version_after"] = "marketplace"
    return info


def summarize(plugin: dict[str, Any], mcp: dict[str, Any], creds: dict[str, Any] | None = None) -> str:
    lines = ["[qlik-mcp-toolkit plugin hook]"]
    if plugin.get("error"):
        lines.append(f"Plugin: error — {plugin['error']}")
    elif plugin.get("skipped") and not plugin.get("synced"):
        lines.append(f"Plugin: skipped — {plugin['skipped']}")
    elif plugin.get("updated"):
        lines.append(
            f"Plugin: updated {plugin.get('version_before') or 'none'} -> "
            f"{plugin.get('version_after')} ({plugin.get('head')}). Reload Window."
        )
    elif plugin.get("synced"):
        lines.append(f"Plugin: {plugin.get('version_after')} ({plugin.get('head')}) already on origin.")
    else:
        lines.append("Plugin: no sync performed.")

    current = mcp.get("current") or "?"
    if mcp.get("updated_files"):
        lines.append(f"MCP: updated {MCP_PACKAGE} {current} -> {mcp.get('installed')}. Restart the qlik MCP server.")
    elif mcp.get("error"):
        lines.append(f"MCP: error — {mcp['error']}")
    else:
        lines.append(f"MCP: {MCP_PACKAGE}=={current} (PyPI {mcp.get('pypi') or 'n/a'}).")
    creds = creds or {}
    if creds.get("error"):
        lines.append(f"Credentials: error — {creds['error']}")
    elif creds.get("updated"):
        host = creds.get("url_host") or "configured-host"
        lines.append(
            f"Credentials: copied {host} + JWT from user MCP config "
            f"into {len(creds['updated'])} plugin MCP file(s)."
        )
    elif creds.get("unchanged"):
        host = creds.get("url_host") or "configured-host"
        lines.append(f"Credentials: plugin MCP already has {host} + JWT from user MCP config.")
    return "\n".join(lines)


def output_for_event(event: str, plugin: dict[str, Any], summary: str) -> dict[str, Any]:
    if event == "workspaceOpen":
        return {"pluginPaths": [plugin.get("plugin_dir") or str(LOCAL_PLUGIN_DIR)]}
    if event == "sessionStart":
        return {"additional_context": summary}
    if event == "SessionStart":
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": summary,
            }
        }
    return {}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    payload = read_stdin()
    event = str(payload.get("hook_event_name") or "")
    try:
        if event == "SessionStart":
            plugin = upgrade_codex_marketplace()
        else:
            plugin = sync_local_clone()
        mcp = update_mcp_pin()
        creds = inject_user_qlik_env()
        summary = summarize(plugin, mcp, creds)
        log(summary.replace("\n", " | "))
        emit(output_for_event(event, plugin, summary))
    except Exception as exc:
        log(f"fatal: {exc!r}")
        emit({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Align the user's qlik-mcp-toolkit install to the marketplace snapshot.

Source of truth for Cursor: the newest folder under
~/.cursor/plugins/cache/*/qlik-mcp-toolkit/<gitRef>/.
The hook does NOT pull GitHub HEAD past that snapshot and does NOT point
Cursor at a stale local clone.

What it does on workspaceOpen / sessionStart (NOT beforeSubmitPrompt —
removed 31.08.2026, a per-prompt version check is unwanted):
  1. Find the newest marketplace snapshot (by plugin version, then mtime).
  2. Reset ~/.cursor/plugins/local/qlik-mcp-toolkit to THAT git ref.
  3. Return pluginPaths to the marketplace snapshot, not to local.
  4. Copy hook scripts from the snapshot into ~/.cursor/hooks, AND reconcile
     our trigger entries in ~/.cursor/hooks.json against the snapshot's
     hooks/hooks.json (so a removed event, e.g. beforeSubmitPrompt, actually
     reaches an installed Cursor; other plugins' hooks left untouched).
     Never downgrade a newer user-hook build.
  5. Align the qlik-sense-mcp-server pin to the snapshot's .mcp.json — and
     ONLY to that. No PyPI / GitHub-tag lookup: the pin follows whatever
     pipeline/promote.py gated and bootstrap.py --push published, never
     ahead of the gate (was the "hook bypasses promote.py" open issue).
  6. Run env-sync so a freshly Refresh'ed snapshot gets the user's JWT/URL.

Codex SessionStart: `codex plugin marketplace upgrade`, then the same
env-sync against ~/.codex caches.

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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOOK_LOGIC_VERSION = "2.3.0.2"  # схема: <пин MCP>.<итерация>, см. bootstrap.py

HOOKS_DIR = Path(__file__).resolve().parent
CURSOR_HOME = Path.home() / ".cursor"
CODEX_HOME = Path.home() / ".codex"
LOCAL_PLUGIN_DIR = CURSOR_HOME / "plugins" / "local" / "qlik-mcp-toolkit"
USER_HOOKS_DIR = CURSOR_HOME / "hooks"
USER_MCP_JSON = CURSOR_HOME / "mcp.json"
LOG_PATH = USER_HOOKS_DIR / "logs" / "update-qlik-mcp.log"
STATE_PATH = USER_HOOKS_DIR / "state" / "update-qlik-mcp.last.json"
LOCK_PATH = USER_HOOKS_DIR / "state" / "update-qlik-mcp.lock"
CACHE_ROOT = CURSOR_HOME / "plugins" / "cache"
CODEX_CACHE_ROOT = CODEX_HOME / "plugins" / "cache"

SKILLS_REPO = "https://github.com/MaksimMolokov/qlik-mcp-toolkit.git"
MCP_PACKAGE = "qlik-sense-mcp-server"
PIN_RE = re.compile(rf"({re.escape(MCP_PACKAGE)})==([0-9]+(?:\.[0-9]+)*)")
GIT_REF_DIR_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)

HOOK_FILES = (
    "update-qlik-mcp.py",
    "update-qlik-mcp.cmd",
    "update-qlik-mcp.sh",
    "sync_qlik_mcp_env.py",
    "sync-qlik-mcp-env.cmd",
    "sync-qlik-mcp-env.sh",
    "hooks.codex.json",
)

GIT_TIMEOUT = 45
PROMPT_THROTTLE_SEC = 60
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


def version_ge(left: str, right: str) -> bool:
    a = parse_version(left)
    b = parse_version(right)
    if a is None or b is None:
        return False
    return a >= b


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fp = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.fp.close()
            self.fp = None
            raise TimeoutError("lock busy") from exc
        return self

    def __exit__(self, *_args: object) -> None:
        if self.fp is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.fp.seek(0)
                msvcrt.locking(self.fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
        finally:
            self.fp.close()
            self.fp = None


def load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(result: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


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


def read_plugin_version(plugin_dir: Path) -> str | None:
    for relative in (Path(".cursor-plugin") / "plugin.json", Path("plugin.json"), Path(".codex-plugin") / "plugin.json"):
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


def git_head(repo: Path, short: bool = True) -> str | None:
    args = ["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"]
    proc = run_git(args, cwd=repo)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def git_ok() -> bool:
    return Path(GIT).is_file() or shutil.which("git") is not None


def drop_legacy_mcp_json(plugin_dir: Path) -> None:
    leftover = plugin_dir / "mcp.json"
    if leftover.is_file():
        leftover.unlink()


def discover_cursor_marketplace_installs() -> list[dict[str, Any]]:
    installs: list[dict[str, Any]] = []
    if not CACHE_ROOT.is_dir():
        return installs
    for toolkit_dir in CACHE_ROOT.glob("*/qlik-mcp-toolkit"):
        if not toolkit_dir.is_dir():
            continue
        for child in toolkit_dir.iterdir():
            if not child.is_dir():
                continue
            if not (child / ".cursor-plugin" / "plugin.json").is_file():
                continue
            if not GIT_REF_DIR_RE.match(child.name):
                continue
            installs.append(
                {
                    "path": child,
                    "version": read_plugin_version(child),
                    "git_ref": child.name,
                    "mtime": child.stat().st_mtime,
                    "marketplace": toolkit_dir.parent.name,
                }
            )
    return installs


def pick_latest_install(installs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not installs:
        return None

    def key(item: dict[str, Any]) -> tuple[tuple[int, ...], float]:
        return (parse_version(item.get("version") or "") or (0,), float(item.get("mtime") or 0))

    return max(installs, key=key)


def discover_codex_marketplace_installs() -> list[dict[str, Any]]:
    installs: list[dict[str, Any]] = []
    if not CODEX_CACHE_ROOT.is_dir():
        return installs
    for toolkit_dir in CODEX_CACHE_ROOT.glob("*/qlik-mcp-toolkit"):
        if not toolkit_dir.is_dir():
            continue
        for child in toolkit_dir.iterdir():
            if not child.is_dir():
                continue
            if not ((child / ".codex-plugin" / "plugin.json").is_file() or (child / "plugin.json").is_file()):
                continue
            installs.append(
                {
                    "path": child,
                    "version": read_plugin_version(child),
                    "git_ref": child.name,
                    "mtime": child.stat().st_mtime,
                    "marketplace": toolkit_dir.parent.name,
                }
            )
    return installs


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
    drop_legacy_mcp_json(LOCAL_PLUGIN_DIR)
    return None


def checkout_ref(repo: Path, ref: str) -> str | None:
    fetch = run_git(["fetch", "--depth", "1", "origin", ref], cwd=repo, timeout=60)
    if fetch.returncode != 0:
        fetch = run_git(["fetch", "--prune", "origin"], cwd=repo, timeout=60)
        if fetch.returncode != 0:
            return f"git fetch failed: {fetch.stderr.strip()[:300]}"
    probe = run_git(["cat-file", "-t", ref], cwd=repo)
    target = ref if probe.returncode == 0 else "FETCH_HEAD"
    reset = run_git(["reset", "--hard", target], cwd=repo)
    if reset.returncode != 0:
        return f"git reset failed: {reset.stderr.strip()[:300]}"
    drop_legacy_mcp_json(repo)
    return None


def checkout_origin_head(repo: Path) -> str | None:
    fetch = run_git(["fetch", "--prune", "origin"], cwd=repo, timeout=60)
    if fetch.returncode != 0:
        return f"git fetch failed: {fetch.stderr.strip()[:300]}"
    proc = run_git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=repo)
    branch = "main"
    if proc.returncode == 0:
        ref = proc.stdout.strip()
        if ref.startswith("origin/"):
            branch = ref.split("/", 1)[1]
    reset = run_git(["reset", "--hard", f"origin/{branch}"], cwd=repo)
    if reset.returncode != 0:
        return f"git reset failed: {reset.stderr.strip()[:300]}"
    drop_legacy_mcp_json(repo)
    return None


def align_local_clone(target_ref: str | None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "synced": False,
        "updated": False,
        "skipped": None,
        "version_before": None,
        "version_after": None,
        "head_before": None,
        "head": None,
        "target_ref": target_ref,
        "error": None,
        "plugin_dir": str(LOCAL_PLUGIN_DIR),
    }
    if not git_ok():
        info["error"] = "git not found"
        return info
    if not target_ref and not LOCAL_PLUGIN_DIR.exists():
        info["skipped"] = "no marketplace snapshot and no local clone"
        return info

    if not (LOCAL_PLUGIN_DIR / ".git").is_dir():
        err = clone_local()
        if err:
            info["error"] = err
            return info
    else:
        info["version_before"] = read_plugin_version(LOCAL_PLUGIN_DIR)
        info["head_before"] = git_head(LOCAL_PLUGIN_DIR, short=False)

    err = checkout_ref(LOCAL_PLUGIN_DIR, target_ref) if target_ref else checkout_origin_head(LOCAL_PLUGIN_DIR)
    if err:
        info["error"] = err
        return info

    info["synced"] = True
    info["head"] = git_head(LOCAL_PLUGIN_DIR, short=False)
    info["version_after"] = read_plugin_version(LOCAL_PLUGIN_DIR)
    before = (info["head_before"] or "")[:12]
    after = (info["head"] or "")[:12]
    info["updated"] = bool(after and after != before) or bool(
        info["version_before"] and info["version_after"] and info["version_before"] != info["version_after"]
    )
    return info


# Cursor читает регистрацию хуков из ~/.cursor/hooks.json (относительные
# ./hooks/*.cmd резолвятся от ~/.cursor/). `hooks.json` НЕ входит в HOOK_FILES
# и НЕ раздаётся как скрипт — триггеры (какие события слушать) сверяем
# отдельно: наши записи узнаём по имени команды, приводим к тому, что в
# снимке. Так удаление события (напр. beforeSubmitPrompt в 0.20.0) доезжает
# до уже установленного Cursor, а чужие хуки в файле не трогаются.
OUR_HOOK_CMD_MARKERS = ("update-qlik-mcp", "sync-qlik-mcp-env")


def _is_our_hook_entry(entry: dict[str, Any]) -> bool:
    cmd = str(entry.get("command", ""))
    return any(m in cmd for m in OUR_HOOK_CMD_MARKERS)


def reconcile_hooks_json(snapshot: Path) -> dict[str, Any]:
    """Привести наши записи в ~/.cursor/hooks.json (и зеркало
    ~/.cursor/hooks/hooks.json) к snapshot/hooks/hooks.json. Чужие плагины
    в файле не трогаются."""
    info: dict[str, Any] = {"updated": [], "error": None}
    canonical_path = snapshot / "hooks" / "hooks.json"
    if not canonical_path.is_file():
        info["error"] = "snapshot has no hooks/hooks.json"
        return info
    try:
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        info["error"] = f"read canonical failed: {exc}"
        return info
    canonical_events = canonical.get("hooks", {})

    for target in (CURSOR_HOME / "hooks.json", USER_HOOKS_DIR / "hooks.json"):
        try:
            if target.is_file():
                current = json.loads(target.read_text(encoding="utf-8-sig"))
            else:
                current = {"version": 1, "hooks": {}}
        except (OSError, json.JSONDecodeError):
            current = {"version": 1, "hooks": {}}
        events = current.setdefault("hooks", {})

        # 1) выкинуть НАШИ записи из всех событий
        for name in list(events):
            events[name] = [e for e in events[name] if not _is_our_hook_entry(e)]
        # 2) вернуть наши записи ровно там, где их объявляет снимок
        for name, entries in canonical_events.items():
            ours = [e for e in entries if _is_our_hook_entry(e)]
            events.setdefault(name, [])
            events[name] = [e for e in events[name] if not _is_our_hook_entry(e)] + ours
        # 3) убрать опустевшие события
        for name in list(events):
            if not events[name]:
                del events[name]

        rendered = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        if not target.is_file() or target.read_text(encoding="utf-8-sig") != rendered:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(rendered, encoding="utf-8", newline="\n")
                info["updated"].append(str(target))
            except OSError as exc:
                info["error"] = f"write {target} failed: {exc}"
    return info


def refresh_user_hooks(snapshot: Path, snapshot_version: str | None) -> dict[str, Any]:
    info: dict[str, Any] = {"copied": [], "skipped": None, "hooks_json": None}
    src = snapshot / "hooks"
    if not src.is_dir():
        info["skipped"] = "snapshot has no hooks/"
        return info
    if snapshot_version and not version_ge(snapshot_version, HOOK_LOGIC_VERSION):
        info["skipped"] = f"keep user hooks {HOOK_LOGIC_VERSION} (snapshot {snapshot_version} is older)"
        return info
    USER_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    for name in HOOK_FILES:
        source = src / name
        if not source.is_file():
            continue
        dest = USER_HOOKS_DIR / name
        try:
            shutil.copy2(source, dest)
            info["copied"].append(name)
        except OSError as exc:
            info["skipped"] = f"copy {name} failed: {exc}"
    info["hooks_json"] = reconcile_hooks_json(snapshot)
    return info


def snapshot_mcp_files(snapshot: Path | None) -> list[Path]:
    files: list[Path] = []
    if snapshot is None:
        return files
    for name in (".mcp.json", "mcp.json"):
        path = snapshot / name
        if path.is_file():
            files.append(path)
        nested = snapshot / "plugins" / "qlik-mcp-toolkit" / name
        if nested.is_file():
            files.append(nested)
    return files


def update_mcp_pin(snapshot: Path | None) -> dict[str, Any]:
    """Align the user's qlik MCP pin to the marketplace snapshot's .mcp.json —
    and ONLY to that. The snapshot ships whatever `pipeline/promote.py` last
    gated and `scripts/bootstrap.py --push` published; the hook does NOT
    consult PyPI or GitHub tags, so it can never move the pin ahead of the
    gate (decided 31.08.2026, was the "hook bypasses promote.py" open issue).
    An unpinned snapshot .mcp.json (bare package name) leaves the user's
    config untouched.
    """
    snapshot_files = snapshot_mcp_files(snapshot)
    info: dict[str, Any] = {
        "current": current_pin(USER_MCP_JSON),
        "marketplace": next((current_pin(path) for path in snapshot_files if current_pin(path)), None),
        "installed": None,
        "updated_files": [],
        "error": None,
    }

    candidate = info["marketplace"]
    info["installed"] = candidate
    if not candidate:
        return info

    targets = [USER_MCP_JSON, *snapshot_files]
    if (LOCAL_PLUGIN_DIR / ".mcp.json").is_file():
        targets.append(LOCAL_PLUGIN_DIR / ".mcp.json")
    for path in targets:
        current = current_pin(path)
        if current == candidate:
            continue
        if current is None and path != USER_MCP_JSON:
            continue
        try:
            if current is None:
                continue
            if bump_pin(path, candidate):
                info["updated_files"].append(str(path))
        except OSError as exc:
            info["error"] = f"failed to write pin: {exc}"
            log(info["error"])
    return info


def inject_user_qlik_env() -> dict[str, Any]:
    module_path = Path(__file__).resolve().parent / "sync_qlik_mcp_env.py"
    if not module_path.is_file():
        fallback = USER_HOOKS_DIR / "sync_qlik_mcp_env.py"
        module_path = fallback if fallback.is_file() else module_path
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
        "ran": False,
        "updated": False,
        "skipped": None,
        "error": None,
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
    info["ran"] = True
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        info["error"] = detail or f"codex exited {proc.returncode}"
        return info
    info["updated"] = True
    return info


def align_cursor() -> dict[str, Any]:
    installs = discover_cursor_marketplace_installs()
    snapshot = pick_latest_install(installs)
    target_ref = snapshot["git_ref"] if snapshot else None
    plugin = align_local_clone(target_ref)
    hooks = refresh_user_hooks(snapshot["path"], snapshot.get("version")) if snapshot else {"copied": [], "skipped": "no marketplace snapshot"}
    mcp = update_mcp_pin(snapshot["path"] if snapshot else None)
    creds = inject_user_qlik_env()
    active_dir = str(snapshot["path"]) if snapshot else str(LOCAL_PLUGIN_DIR)
    result = {
        "checked_at": time.time(),
        "checked_at_iso": utc_now(),
        "hook_logic": HOOK_LOGIC_VERSION,
        "channel": "marketplace" if snapshot else "local-git",
        "marketplace": {
            "path": str(snapshot["path"]) if snapshot else None,
            "version": snapshot.get("version") if snapshot else None,
            "git_ref": target_ref,
            "marketplace": snapshot.get("marketplace") if snapshot else None,
            "candidates": len(installs),
        },
        "plugin": plugin,
        "hooks": hooks,
        "mcp": mcp,
        "creds": {
            "ok": creds.get("ok"),
            "url_host": creds.get("url_host"),
            "token_present": creds.get("token_present"),
            "updated": len(creds.get("updated") or []),
            "unchanged": len(creds.get("unchanged") or []),
            "error": creds.get("error"),
        },
        "plugin_dir": active_dir,
        "local_dir": str(LOCAL_PLUGIN_DIR),
    }
    result["summary"] = summarize(result)
    return result


def align_codex() -> dict[str, Any]:
    upgrade = upgrade_codex_marketplace()
    installs = discover_codex_marketplace_installs()
    snapshot = pick_latest_install(installs)
    hooks = {"copied": [], "skipped": None}
    if snapshot:
        src = snapshot["path"] / "hooks"
        if src.is_dir():
            dest = CODEX_HOME / "hooks"
            dest.mkdir(parents=True, exist_ok=True)
            for name in HOOK_FILES:
                source = src / name
                if source.is_file():
                    try:
                        shutil.copy2(source, dest / name)
                        hooks["copied"].append(name)
                    except OSError as exc:
                        hooks["skipped"] = str(exc)
        else:
            hooks["skipped"] = "codex snapshot has no hooks/"
    mcp = update_mcp_pin(None)
    creds = inject_user_qlik_env()
    result = {
        "checked_at": time.time(),
        "checked_at_iso": utc_now(),
        "hook_logic": HOOK_LOGIC_VERSION,
        "channel": "codex-marketplace",
        "codex_upgrade": upgrade,
        "marketplace": {
            "path": str(snapshot["path"]) if snapshot else None,
            "version": snapshot.get("version") if snapshot else None,
            "git_ref": snapshot.get("git_ref") if snapshot else None,
            "candidates": len(installs),
        },
        "plugin": {
            "synced": bool(snapshot),
            "updated": bool(upgrade.get("updated")),
            "version_after": snapshot.get("version") if snapshot else None,
            "error": upgrade.get("error"),
            "skipped": upgrade.get("skipped"),
        },
        "hooks": hooks,
        "mcp": mcp,
        "creds": {
            "ok": creds.get("ok"),
            "url_host": creds.get("url_host"),
            "token_present": creds.get("token_present"),
            "updated": len(creds.get("updated") or []),
            "unchanged": len(creds.get("unchanged") or []),
            "error": creds.get("error"),
        },
        "plugin_dir": str(snapshot["path"]) if snapshot else str(LOCAL_PLUGIN_DIR),
        "local_dir": str(LOCAL_PLUGIN_DIR),
    }
    result["summary"] = summarize(result)
    return result


def summarize(result: dict[str, Any]) -> str:
    lines = ["[qlik-mcp-toolkit plugin hook]"]
    market = result.get("marketplace") or {}
    plugin = result.get("plugin") or {}
    mcp = result.get("mcp") or {}
    creds = result.get("creds") or {}
    hooks = result.get("hooks") or {}
    channel = result.get("channel")
    version = market.get("version") or plugin.get("version_after") or "?"
    ref = (market.get("git_ref") or plugin.get("head") or "")[:12] or "?"

    if plugin.get("error"):
        lines.append(f"Plugin: error — {plugin['error']}")
    elif channel == "marketplace":
        if plugin.get("updated"):
            lines.append(
                f"Plugin: aligned local clone to marketplace {version} ({ref}). Reload Window."
            )
        else:
            lines.append(f"Plugin: already on marketplace {version} ({ref}).")
    elif channel == "codex-marketplace":
        if plugin.get("error"):
            lines.append(f"Plugin: error — {plugin['error']}")
        elif plugin.get("updated"):
            lines.append(f"Plugin: Codex marketplace now {version}. Restart Codex if skills look stale.")
        else:
            lines.append(f"Plugin: Codex marketplace {version}.")
    elif plugin.get("updated"):
        lines.append(f"Plugin: updated local clone to {version} ({ref}). Reload Window.")
    elif plugin.get("synced"):
        lines.append(f"Plugin: local clone {version} ({ref}).")
    elif plugin.get("skipped"):
        lines.append(f"Plugin: skipped — {plugin['skipped']}")
    else:
        lines.append("Plugin: no sync performed.")

    if hooks.get("copied"):
        lines.append(f"Hooks: refreshed {len(hooks['copied'])} user-hook file(s) from the snapshot.")
    elif hooks.get("skipped"):
        lines.append(f"Hooks: {hooks['skipped']}")
    hj = hooks.get("hooks_json") or {}
    if hj.get("updated"):
        lines.append(f"Hooks: reconciled trigger registration in {len(hj['updated'])} hooks.json file(s) — Reload Window.")
    elif hj.get("error"):
        lines.append(f"Hooks: hooks.json reconcile error — {hj['error']}")

    current = mcp.get("current") or mcp.get("marketplace") or "?"
    if mcp.get("updated_files"):
        lines.append(
            f"MCP: aligned {MCP_PACKAGE} {current} -> {mcp.get('installed')} (marketplace snapshot). Restart the qlik MCP server."
        )
    elif mcp.get("error"):
        lines.append(f"MCP: error — {mcp['error']}")
    else:
        lines.append(f"MCP: {MCP_PACKAGE}=={current} (matches marketplace snapshot).")

    if creds.get("error"):
        lines.append(f"Credentials: error — {creds['error']}")
    elif creds.get("updated"):
        host = creds.get("url_host") or "configured-host"
        lines.append(f"Credentials: copied {host} + JWT into {creds['updated']} plugin MCP file(s).")
    elif creds.get("unchanged"):
        host = creds.get("url_host") or "configured-host"
        lines.append(f"Credentials: plugin MCP already has {host} + JWT.")
    return "\n".join(lines)


def output_for_event(event: str, result: dict[str, Any]) -> dict[str, Any]:
    plugin_dir = result.get("plugin_dir") or str(LOCAL_PLUGIN_DIR)
    summary = result.get("summary") or "qlik-mcp-toolkit hook ran."
    if event == "workspaceOpen":
        return {"pluginPaths": [plugin_dir]}
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


def should_skip_throttled(event: str, state: dict[str, Any], snapshot_ref: str | None) -> bool:
    if event not in {"beforeSubmitPrompt", "UserPromptSubmit"}:
        return False
    last = float(state.get("checked_at") or 0)
    if time.time() - last < PROMPT_THROTTLE_SEC and state.get("marketplace", {}).get("git_ref") == snapshot_ref:
        return True
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    payload = read_stdin()
    event = str(payload.get("hook_event_name") or "")
    try:
        with FileLock(LOCK_PATH):
            if event == "SessionStart":
                result = align_codex()
            else:
                installs = discover_cursor_marketplace_installs()
                latest = pick_latest_install(installs)
                latest_ref = latest["git_ref"] if latest else None
                state = load_state()
                if should_skip_throttled(event, state, latest_ref):
                    creds = inject_user_qlik_env()
                    state["creds"] = {
                        "ok": creds.get("ok"),
                        "updated": len(creds.get("updated") or []),
                        "error": creds.get("error"),
                    }
                    if creds.get("updated"):
                        state["summary"] = (
                            (state.get("summary") or "")
                            + f"\nCredentials: copied into {len(creds['updated'])} new snapshot file(s)."
                        ).strip()
                        save_state(state)
                    emit(output_for_event(event, state))
                    return 0
                result = align_cursor()
            save_state(result)
            log(str(result.get("summary") or "").replace("\n", " | "))
            emit(output_for_event(event, result))
    except TimeoutError:
        state = load_state() or {"summary": "qlik-mcp hook skipped: another run is in progress.", "plugin_dir": str(LOCAL_PLUGIN_DIR)}
        emit(output_for_event(event, state))
    except Exception as exc:
        log(f"fatal: {exc!r}")
        emit({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

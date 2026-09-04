#!/usr/bin/env python3
"""Align the user's qlik-mcp-toolkit to the newest published toolkit.

Source of truth: GitHub origin/main of this repo (what pipeline/promote
published), compared with the newest Cursor marketplace snapshot under
~/.cursor/plugins/cache/*/qlik-mcp-toolkit/<gitRef>/. If GitHub is newer
or equal, the hook pulls it — Cursor marketplace Refresh is not required
for skills or the MCP pin to move.

What it does on sessionStart — the ONLY Cursor startup event (`workspaceOpen`
is not a real Cursor event; a bad key rejects the whole hooks.json, so it
took everything down with it. Not beforeSubmitPrompt either — a per-prompt
version check is unwanted):
  1. git fetch origin/main (published toolkit). Compare with the newest
     marketplace snapshot. Winner = higher plugin version; if equal, GitHub.
     This is how a skill-only or MCP-pin-only push reaches users even when
     Cursor has not Refresh'ed the marketplace cache.
  2. Reset ~/.cursor/plugins/local/qlik-mcp-toolkit to the winner.
  3. Copy hook scripts + reconcile ~/.cursor/hooks.json from the winner.
     Never downgrade a newer user-hook build.
  4. If marketplace snapshots are older than the winner, copy skills/rules/
     hooks/manifests into them so the plugin Cursor already loaded matches
     GitHub (pluginPaths is not a real sessionStart field).
  5. Force qlik-sense-mcp-server onto the toolkit pin. Prefer `.mcp.json`;
     if unpinned, first three digits of toolkit version (2.3.0.5 → 2.3.0).
     Rewrite bare package args, then prefetch via uvx. No PyPI lookup.
  6. Run env-sync so a freshly updated snapshot gets the user's JWT/URL.

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

HOOK_LOGIC_VERSION = "2.3.0.5"  # схема: <пин MCP>.<итерация>, см. bootstrap.py

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
PREFETCH_TIMEOUT = 25
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


def version_gt(left: str, right: str) -> bool:
    a = parse_version(left)
    b = parse_version(right)
    if a is None:
        return False
    if b is None:
        return True
    return a > b


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


def mcp_pin_from_toolkit_version(version: str | None) -> str | None:
    parsed = parse_version(version or "")
    if parsed is None or len(parsed) < 3:
        return None
    return ".".join(str(part) for part in parsed[:3])


def apply_pin_to_mcp_config(data: dict[str, Any], version: str) -> bool:
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return False
    pinned = f"{MCP_PACKAGE}=={version}"
    changed = False
    for cfg in servers.values():
        if not isinstance(cfg, dict):
            continue
        args = cfg.get("args")
        if not isinstance(args, list):
            continue
        new_args: list[Any] = []
        for item in args:
            if isinstance(item, str) and (item == MCP_PACKAGE or item.startswith(f"{MCP_PACKAGE}==")):
                if item != pinned:
                    changed = True
                new_args.append(pinned)
            else:
                new_args.append(item)
        cfg["args"] = new_args
    return changed


def apply_mcp_pin(path: Path, version: str) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return bump_pin(path, version)
    if not isinstance(data, dict) or not apply_pin_to_mcp_config(data, version):
        return False
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True


def prefetch_mcp_package(version: str) -> dict[str, Any]:
    info: dict[str, Any] = {"ok": False, "version": version, "channel": None, "error": None}
    uvx = shutil.which("uvx")
    uv = shutil.which("uv")
    py_snippet = "import importlib.metadata as m; print(m.version('qlik-sense-mcp-server'))"
    if uvx:
        cmd = [uvx, "--from", f"{MCP_PACKAGE}=={version}", "python", "-c", py_snippet]
        info["channel"] = "uvx"
    elif uv:
        cmd = [uv, "tool", "run", "--from", f"{MCP_PACKAGE}=={version}", "python", "-c", py_snippet]
        info["channel"] = "uv"
    else:
        info["error"] = "uvx/uv not on PATH"
        return info
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PREFETCH_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        info["error"] = f"prefetch failed: {exc}"
        return info
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    got = lines[-1] if lines else ""
    if proc.returncode == 0 and got == version:
        info["ok"] = True
        return info
    detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:300]
    info["error"] = detail or f"expected {version}, got {got!r}"
    return info


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


PLUGIN_COPY_NAMES = (
    "skills",
    "rules",
    "hooks",
    "plugins",
    "plugin.json",
    "README.md",
    "CHANGELOG.md",
    ".cursor-plugin",
    ".claude-plugin",
    ".mcp.json",
    ".agents",
)


def origin_branch(repo: Path) -> str:
    proc = run_git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=repo)
    if proc.returncode == 0:
        ref = proc.stdout.strip()
        if ref.startswith("origin/"):
            return ref.split("/", 1)[1]
    return "main"


def fetch_origin() -> dict[str, Any]:
    info: dict[str, Any] = {"ref": None, "version": None, "branch": None, "error": None}
    if not git_ok():
        info["error"] = "git not found"
        return info
    if not (LOCAL_PLUGIN_DIR / ".git").is_dir():
        err = clone_local()
        if err:
            info["error"] = err
            return info
    branch = origin_branch(LOCAL_PLUGIN_DIR)
    fetch = run_git(["fetch", "--depth", "1", "--prune", "origin", branch], cwd=LOCAL_PLUGIN_DIR, timeout=60)
    if fetch.returncode != 0:
        fetch = run_git(["fetch", "--depth", "1", "--prune", "origin"], cwd=LOCAL_PLUGIN_DIR, timeout=60)
        if fetch.returncode != 0:
            info["error"] = f"git fetch failed: {fetch.stderr.strip()[:300]}"
            return info
        branch = origin_branch(LOCAL_PLUGIN_DIR)
    info["branch"] = branch
    rev = run_git(["rev-parse", f"origin/{branch}"], cwd=LOCAL_PLUGIN_DIR)
    info["ref"] = rev.stdout.strip() or None
    shown = run_git(["show", f"origin/{branch}:plugin.json"], cwd=LOCAL_PLUGIN_DIR)
    if shown.returncode == 0:
        try:
            info["version"] = str(json.loads(shown.stdout).get("version") or "").strip() or None
        except json.JSONDecodeError:
            info["version"] = None
    if not info["ref"]:
        info["error"] = "origin ref missing"
    return info


def pick_winner(origin: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    ov = (origin or {}).get("version")
    oref = (origin or {}).get("ref")
    sv = snapshot.get("version") if snapshot else None
    sref = snapshot.get("git_ref") if snapshot else None
    if ov and oref and sv and sref:
        if version_gt(sv, ov):
            return {"channel": "marketplace", "ref": sref, "version": sv}
        return {"channel": "origin", "ref": oref, "version": ov}
    if ov and oref:
        return {"channel": "origin", "ref": oref, "version": ov}
    if sv and sref:
        return {"channel": "marketplace", "ref": sref, "version": sv}
    return {"channel": "none", "ref": None, "version": None}


def copy_plugin_tree(src: Path, dest: Path) -> str | None:
    if not src.is_dir() or not dest.is_dir():
        return "src/dest missing"
    for name in PLUGIN_COPY_NAMES:
        source = src / name
        target = dest / name
        if not source.exists():
            continue
        try:
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".git"))
            else:
                shutil.copy2(source, target)
        except OSError as exc:
            return f"copy {name} failed: {exc}"
    return None


def sync_stale_snapshots(local: Path, installs: list[dict[str, Any]], winner_version: str | None) -> dict[str, Any]:
    info: dict[str, Any] = {"updated": [], "skipped": [], "error": None}
    if not winner_version or not local.is_dir():
        info["skipped"].append("no winner/local")
        return info
    for inst in installs:
        path = inst.get("path")
        if not isinstance(path, Path):
            continue
        current = inst.get("version") or ""
        if version_ge(current, winner_version):
            info["skipped"].append(str(path))
            continue
        err = copy_plugin_tree(local, path)
        if err:
            info["error"] = err
            log(f"cache sync {path}: {err}")
            continue
        info["updated"].append(str(path))
    return info


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
    branch = origin_branch(repo)
    fetch = run_git(["fetch", "--depth", "1", "--prune", "origin", branch], cwd=repo, timeout=60)
    if fetch.returncode != 0:
        fetch = run_git(["fetch", "--depth", "1", "--prune", "origin"], cwd=repo, timeout=60)
        if fetch.returncode != 0:
            return f"git fetch failed: {fetch.stderr.strip()[:300]}"
        branch = origin_branch(repo)
    reset = run_git(["reset", "--hard", f"origin/{branch}"], cwd=repo)
    if reset.returncode != 0:
        return f"git reset failed: {reset.stderr.strip()[:300]}"
    drop_legacy_mcp_json(repo)
    return None


def align_local_clone(target_ref: str | None, target_version: str | None = None) -> dict[str, Any]:
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
        if (
            target_version
            and info["version_before"]
            and version_gt(info["version_before"], target_version)
        ):
            info["synced"] = True
            info["skipped"] = f"keep local {info['version_before']} (target {target_version} is older)"
            info["version_after"] = info["version_before"]
            info["head"] = info["head_before"]
            return info

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


def resolve_target_pin(snapshot: Path | None) -> tuple[str | None, list[Path]]:
    snapshot_files = snapshot_mcp_files(snapshot)
    local_files = snapshot_mcp_files(LOCAL_PLUGIN_DIR)
    files = snapshot_files + [path for path in local_files if path not in snapshot_files]
    pinned = next((current_pin(path) for path in files if current_pin(path)), None)
    if pinned:
        return pinned, files
    for src in (snapshot, LOCAL_PLUGIN_DIR):
        if src is None:
            continue
        derived = mcp_pin_from_toolkit_version(read_plugin_version(src))
        if derived:
            return derived, files
    return mcp_pin_from_toolkit_version(HOOK_LOGIC_VERSION), files


def update_mcp_pin(snapshot: Path | None) -> dict[str, Any]:
    """Force the user's Qlik MCP onto the toolkit pin.

    Prefer the snapshot `.mcp.json` pin. If that file is unpinned (Codex
    used to ship a bare package name), take the first three digits of the
    toolkit version — 2.3.0.3 → 2.3.0. Never consults PyPI or GitHub tags.
    Bare `qlik-sense-mcp-server` args are rewritten to `==<pin>` so an
    old uvx cache cannot keep serving a previous release.
    """
    candidate, snapshot_files = resolve_target_pin(snapshot)
    info: dict[str, Any] = {
        "current": current_pin(USER_MCP_JSON),
        "marketplace": candidate,
        "installed": None,
        "updated_files": [],
        "prefetch": None,
        "error": None,
    }
    if not candidate:
        return info

    targets: list[Path] = []
    seen: set[str] = set()
    extra = [
        USER_MCP_JSON,
        LOCAL_PLUGIN_DIR / ".mcp.json",
        LOCAL_PLUGIN_DIR / "plugins" / "qlik-mcp-toolkit" / ".mcp.json",
    ]
    for path in [*extra, *snapshot_files]:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        targets.append(path)

    for path in targets:
        if not path.is_file():
            continue
        try:
            if apply_mcp_pin(path, candidate):
                info["updated_files"].append(str(path))
        except OSError as exc:
            info["error"] = f"failed to write pin: {exc}"
            log(info["error"])
    info["installed"] = candidate
    info["prefetch"] = prefetch_mcp_package(candidate)
    if info["prefetch"].get("error") and not info["error"]:
        log(f"MCP prefetch: {info['prefetch']['error']}")
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
    origin = fetch_origin()
    installs = discover_cursor_marketplace_installs()
    snapshot = pick_latest_install(installs)
    winner = pick_winner(origin, snapshot)
    if winner["channel"] == "marketplace" and snapshot:
        plugin = align_local_clone(snapshot.get("git_ref"), snapshot.get("version"))
        source_dir = snapshot["path"] if plugin.get("synced") else LOCAL_PLUGIN_DIR
        channel = "marketplace"
    else:
        plugin = align_local_clone(None, winner.get("version"))
        source_dir = LOCAL_PLUGIN_DIR
        channel = "origin" if winner["channel"] == "origin" else ("local-git" if plugin.get("synced") else "none")
        if origin.get("error") and not plugin.get("synced"):
            plugin["error"] = plugin.get("error") or origin["error"]

    hook_src = LOCAL_PLUGIN_DIR if plugin.get("synced") else (snapshot["path"] if snapshot else None)
    hook_ver = (read_plugin_version(hook_src) if hook_src else None) or winner.get("version")
    if hook_src and hook_src.is_dir():
        hooks = refresh_user_hooks(hook_src, hook_ver)
    else:
        hooks = {"copied": [], "skipped": "no plugin source"}

    cache = sync_stale_snapshots(LOCAL_PLUGIN_DIR, installs, hook_ver) if plugin.get("synced") else {"updated": [], "skipped": ["local clone not synced"], "error": None}
    pin_src = LOCAL_PLUGIN_DIR if plugin.get("synced") else (snapshot["path"] if snapshot else None)
    mcp = update_mcp_pin(pin_src)
    creds = inject_user_qlik_env()
    active_dir = str(source_dir) if source_dir is not None else str(LOCAL_PLUGIN_DIR)
    result = {
        "checked_at": time.time(),
        "checked_at_iso": utc_now(),
        "hook_logic": HOOK_LOGIC_VERSION,
        "channel": channel,
        "origin": {
            "ref": origin.get("ref"),
            "version": origin.get("version"),
            "error": origin.get("error"),
        },
        "marketplace": {
            "path": str(snapshot["path"]) if snapshot else None,
            "version": snapshot.get("version") if snapshot else None,
            "git_ref": snapshot.get("git_ref") if snapshot else None,
            "marketplace": snapshot.get("marketplace") if snapshot else None,
            "candidates": len(installs),
        },
        "winner": winner,
        "plugin": plugin,
        "hooks": hooks,
        "cache_sync": cache,
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
    mcp = update_mcp_pin(snapshot["path"] if snapshot else None)
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
    version = (
        (result.get("winner") or {}).get("version")
        or market.get("version")
        or plugin.get("version_after")
        or "?"
    )
    ref = (
        ((result.get("winner") or {}).get("ref") or market.get("git_ref") or plugin.get("head") or "")[:12]
        or "?"
    )

    if plugin.get("error"):
        lines.append(f"Plugin: error — {plugin['error']}")
    elif channel == "marketplace":
        if plugin.get("updated"):
            lines.append(
                f"Plugin: aligned local clone to marketplace {version} ({ref}). Reload Window."
            )
        else:
            lines.append(f"Plugin: already on marketplace {version} ({ref}).")
    elif channel == "origin":
        if plugin.get("updated"):
            lines.append(f"Plugin: pulled GitHub {version} ({ref}). Reload Window if skills look stale.")
        else:
            lines.append(f"Plugin: already on GitHub {version} ({ref}).")
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

    cache = result.get("cache_sync") or {}
    if cache.get("updated"):
        lines.append(
            f"Skills: synced {len(cache['updated'])} stale marketplace snapshot(s) to {version}."
        )
    elif cache.get("error"):
        lines.append(f"Skills: cache sync error — {cache['error']}")

    current = mcp.get("current") or "?"
    target = mcp.get("installed") or mcp.get("marketplace") or "?"
    if mcp.get("updated_files"):
        lines.append(
            f"MCP: aligned {MCP_PACKAGE} {current} -> {target} (toolkit pin). Restart the qlik MCP server."
        )
    elif mcp.get("error"):
        lines.append(f"MCP: error — {mcp['error']}")
    else:
        lines.append(f"MCP: {MCP_PACKAGE}=={target} (matches toolkit pin).")
    prefetch = mcp.get("prefetch") or {}
    if prefetch.get("ok"):
        lines.append(f"MCP: package {prefetch.get('version')} prefetched via {prefetch.get('channel')}.")
    elif prefetch.get("error"):
        lines.append(f"MCP: pin ready, package prefetch failed — {prefetch['error']}")

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
    summary = result.get("summary") or "qlik-mcp-toolkit hook ran."
    # NB: `workspaceOpen` is NOT a valid Cursor hook event (confirmed from
    # Cursor's own hooks log 31.08.2026 — one bad key rejects the WHOLE
    # hooks.json, so no hook ran at all). Cursor's startup event is
    # `sessionStart`. Skills come from marketplace cache — stale snapshots
    # are overwritten from GitHub. MCP pin is written to ~/.cursor/mcp.json.
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

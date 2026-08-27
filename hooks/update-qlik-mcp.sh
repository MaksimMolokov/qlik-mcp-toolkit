#!/bin/sh
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export GIT_TERMINAL_PROMPT=0
if command -v python >/dev/null 2>&1; then
  python "$DIR/update-qlik-mcp.py"
  exit 0
fi
if command -v python3 >/dev/null 2>&1; then
  python3 "$DIR/update-qlik-mcp.py"
  exit 0
fi
printf '%s\n' '{"additional_context":"qlik-mcp auto-update hook: python not found on PATH."}'
exit 0

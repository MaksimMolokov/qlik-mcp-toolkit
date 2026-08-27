#!/bin/sh
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python >/dev/null 2>&1; then
  python "$DIR/sync_qlik_mcp_env.py"
  exit 0
fi
if command -v python3 >/dev/null 2>&1; then
  python3 "$DIR/sync_qlik_mcp_env.py"
  exit 0
fi
printf '%s\n' '{"additional_context":"qlik-mcp env sync: python not found on PATH."}'
exit 0

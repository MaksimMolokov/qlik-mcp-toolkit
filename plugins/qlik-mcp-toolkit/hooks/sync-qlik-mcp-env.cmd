@echo off
setlocal EnableExtensions
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "%~dp0sync_qlik_mcp_env.py"
  exit /b 0
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%~dp0sync_qlik_mcp_env.py"
  exit /b 0
)

echo {"additional_context":"qlik-mcp env sync: python not found on PATH."}
exit /b 0

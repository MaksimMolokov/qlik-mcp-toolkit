@echo off
setlocal EnableExtensions
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set GIT_TERMINAL_PROMPT=0
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%LOCALAPPDATA%\Programs\Git\cmd;%USERPROFILE%\AppData\Local\Programs\Git\cmd"

where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "%~dp0update-qlik-mcp.py"
  exit /b 0
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%~dp0update-qlik-mcp.py"
  exit /b 0
)

echo {"additional_context":"qlik-mcp auto-update hook: python not found on PATH."}
exit /b 0

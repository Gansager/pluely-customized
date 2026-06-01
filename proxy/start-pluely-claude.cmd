@echo off
setlocal

set "PROXY_PORT=8765"
set "WHISPER_PORT=8766"
set "PROXY_DIR=%USERPROFILE%\pluely-proxy"
set "PLUELY_EXE=%LOCALAPPDATA%\Pluely\pluely.exe"
set "WHISPER_PY=%PROXY_DIR%\whisper-venv\Scripts\python.exe"

taskkill /F /IM pluely.exe >nul 2>&1
timeout /t 1 /nobreak >nul

node "%PROXY_DIR%\level-tools\select-provider.mjs" claude

netstat -ano | findstr /R /C:":%PROXY_PORT% .*LISTENING" >nul 2>&1
if errorlevel 1 (
    start "Pluely Proxy (Claude Code)" /D "%PROXY_DIR%" cmd /k "python proxy.py --project ""%PROXY_DIR%"" --port %PROXY_PORT%"
)

netstat -ano | findstr /R /C:":%WHISPER_PORT% .*LISTENING" >nul 2>&1
if errorlevel 1 (
    start "" /MIN "%PROXY_DIR%\start-google-stt.cmd"
)

start "" "%PLUELY_EXE%"
endlocal

@echo off
setlocal

set "WHISPER_PORT=8766"
set "PROXY_DIR=%USERPROFILE%\pluely-proxy"
set "PLUELY_EXE=%LOCALAPPDATA%\Pluely\pluely.exe"
set "WHISPER_PY=%PROXY_DIR%\whisper-venv\Scripts\python.exe"

taskkill /F /IM pluely.exe >nul 2>&1
timeout /t 1 /nobreak >nul

node "%PROXY_DIR%\level-tools\select-provider.mjs" ollama

netstat -ano | findstr /R /C:":%WHISPER_PORT% .*LISTENING" >nul 2>&1
if errorlevel 1 (
    start "" /MIN "%PROXY_DIR%\start-stt.cmd"
)

start "" "%PLUELY_EXE%"
endlocal

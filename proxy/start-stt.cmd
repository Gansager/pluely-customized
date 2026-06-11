@echo off
setlocal
set "PROXY_DIR=%USERPROFILE%\pluely-proxy"
set "STT_PY=%PROXY_DIR%\whisper-venv\Scripts\python.exe"
set "STT_PORT=8766"
title Memora STT (port %STT_PORT%)
cd /d "%PROXY_DIR%"
rem Unified STT proxy: provider via .env (STT_PROVIDER=groq|whisper|google, default groq).
"%STT_PY%" stt-server.py --port %STT_PORT%
endlocal

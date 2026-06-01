@echo off
setlocal
set "PROXY_DIR=%USERPROFILE%\pluely-proxy"
set "STT_PY=%PROXY_DIR%\whisper-venv\Scripts\python.exe"
set "STT_PORT=8766"
title Pluely Google STT (port %STT_PORT%)
cd /d "%PROXY_DIR%"
"%STT_PY%" google-stt-server.py --port %STT_PORT%
endlocal

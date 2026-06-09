@echo off
setlocal
set "PROXY_DIR=%USERPROFILE%\pluely-proxy"
set "WHISPER_PY=%PROXY_DIR%\whisper-venv\Scripts\python.exe"
set "WHISPER_PORT=8766"
title Memora Whisper STT (port %WHISPER_PORT%)
cd /d "%PROXY_DIR%"
"%WHISPER_PY%" whisper-server.py --model base --device cpu --compute int8 --port %WHISPER_PORT%
endlocal

@echo off
setlocal
set "PROXY_DIR=%USERPROFILE%\pluely-proxy"
title Memora — End meeting (summary)
cd /d "%PROXY_DIR%"
"%PROXY_DIR%\whisper-venv\Scripts\python.exe" summarize-meeting.py --open
echo.
echo (Окно закроется через 5 секунд)
timeout /t 5 /nobreak >nul
endlocal

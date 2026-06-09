@echo off
setlocal
set "PROXY_DIR=%USERPROFILE%\pluely-proxy"
title Memora — Summary from recording
cd /d "%PROXY_DIR%"
rem %~1 = path to the recorded .webm (passed by recorder.rs finish_screen_recording)
"%PROXY_DIR%\whisper-venv\Scripts\python.exe" summarize-video.py %1
echo.
echo (Окно закроется через 5 секунд)
timeout /t 5 /nobreak >nul
endlocal

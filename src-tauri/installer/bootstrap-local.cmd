@echo off
setlocal enabledelayedexpansion
title Pluely setup - Local (Ollama) mode
echo.
echo   ===================================================
echo    Pluely - finishing LOCAL setup (Ollama + Whisper)
echo   ===================================================
echo.
echo   The speech-to-text engine is bundled with the app.
echo   This step only sets up the local Ollama AI model.
echo.

REM --- locate or install Ollama ---
set "OLLAMA="
where ollama >nul 2>&1 && set "OLLAMA=ollama"
if not defined OLLAMA if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

if not defined OLLAMA (
  echo Ollama not found - installing via winget...
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
)
if not defined OLLAMA set "OLLAMA=ollama"

echo.
echo Using Ollama: !OLLAMA!
REM let the service come up after a fresh install
"!OLLAMA!" list >nul 2>&1 || timeout /t 5 /nobreak >nul

echo.
echo Pulling vision model minicpm-v (~5.5 GB first time; instant if already present)...
"!OLLAMA!" pull minicpm-v

echo.
echo   ---------------------------------------------------
echo    Local setup complete. Close this window and
echo    launch Pluely from the Start menu or desktop.
echo   ---------------------------------------------------
pause
endlocal

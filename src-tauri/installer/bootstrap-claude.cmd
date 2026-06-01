@echo off
setlocal enabledelayedexpansion
title Pluely setup - Claude mode
echo.
echo   ===================================================
echo    Pluely - finishing CLAUDE setup
echo   ===================================================
echo.
echo   The proxy and speech-to-text engine are bundled.
echo   This step installs the Claude CLI and signs you in.
echo.

REM --- ensure Node.js (required by the Claude CLI) ---
where node >nul 2>&1
if errorlevel 1 (
  echo Node.js not found - installing via winget...
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  echo.
  echo   Node.js was just installed. PATH won't update in this window.
  echo   Please CLOSE this window, open a NEW terminal, and run:
  echo       "%~f0"
  echo.
  pause
  exit /b
)

echo Installing the Claude Code CLI (npm global)...
call npm install -g @anthropic-ai/claude-code

echo.
echo Signing in to Claude (a browser window will open)...
call claude login

echo.
echo   ---------------------------------------------------
echo    Claude setup complete. Close this window and
echo    launch Pluely from the Start menu or desktop.
echo   ---------------------------------------------------
pause
endlocal

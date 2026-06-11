@echo off
rem Delegates to the hidden launcher; all server windows are invisible
rem and shut down automatically when Memora exits.
start "" wscript.exe "%USERPROFILE%\pluely-proxy\memora-claude.vbs"

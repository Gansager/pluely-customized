; Custom NSIS hooks for the Pluely fork installer.
; Wired via tauri.conf.json > bundle.windows.nsis.installerHooks.
;
; POSTINSTALL: ask the user which AI brain to use, record it in dist-mode.txt
; (read by the app on startup), and kick off a visible bootstrap window that
; installs whatever that mode still needs (Ollama+model, or Node+Claude CLI).
;
; PREUNINSTALL: stop the app and its bundled helper servers so their files can
; be removed cleanly.

!macro NSIS_HOOK_POSTINSTALL
  MessageBox MB_YESNO|MB_ICONQUESTION \
"Choose how Pluely should answer:$\r$\n$\r$\nYES  =  Local (Ollama + Whisper)$\r$\n        Fully offline. No account, no API key.$\r$\n        A one-time ~5 GB model download will start.$\r$\n$\r$\nNO  =  Claude$\r$\n        Smarter answers, but needs a one-time 'claude login'$\r$\n        and a Claude subscription.$\r$\n$\r$\nYou can switch later in Settings." \
    /SD IDYES IDNO pluely_mode_claude

  ; ---- Local (Ollama) ----
  FileOpen $0 "$INSTDIR\dist-mode.txt" w
  FileWrite $0 "ollama"
  FileClose $0
  Exec '"$SYSDIR\cmd.exe" /c start "Pluely setup" "$INSTDIR\installer\bootstrap-local.cmd"'
  Goto pluely_mode_done

  ; ---- Claude ----
  pluely_mode_claude:
  FileOpen $0 "$INSTDIR\dist-mode.txt" w
  FileWrite $0 "claude"
  FileClose $0
  Exec '"$SYSDIR\cmd.exe" /c start "Pluely setup" "$INSTDIR\installer\bootstrap-claude.cmd"'

  pluely_mode_done:
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /IM pluely.exe'
  nsExec::Exec 'taskkill /F /IM stt.exe'
  nsExec::Exec 'taskkill /F /IM proxy.exe'
!macroend

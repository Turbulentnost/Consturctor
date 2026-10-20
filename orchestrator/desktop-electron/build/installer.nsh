!macro customInstall
  StrCpy $1 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  IfFileExists "$1" runps 0
  StrCpy $1 "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe"
  runps:
  nsExec::ExecToLog '"$1" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\lan-route.ps1"'
  Pop $0
  nsExec::ExecToLog 'schtasks /Create /F /TN "OrchestratorLanRoute" /SC ONLOGON /RL HIGHEST /TR "\"$1\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"$INSTDIR\resources\lan-route.ps1\""'
  Pop $0
!macroend

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $scriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.ps1 first.' }

# A GUI process launched from the Codex tool sandbox runs in the same Windows
# session but cannot register an icon on the user's interactive taskbar. Such
# an invisible instance would still acquire the app's single-instance mutex and
# make a later Desktop-shortcut launch appear to do nothing.
if ($env:CODEX_SESSION_ID -or $env:CODEX_CI) {
    throw 'Local Dictation must be started from its Desktop shortcut, not from a Codex background session.'
}

Start-Process -FilePath $python -ArgumentList 'codex_ptt.py' -WorkingDirectory $scriptRoot -WindowStyle Hidden

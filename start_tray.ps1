$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $scriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.ps1 first.' }

Start-Process -FilePath $python -ArgumentList 'codex_ptt.py' -WorkingDirectory $scriptRoot -WindowStyle Hidden

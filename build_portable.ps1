$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $scriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.ps1 first.' }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name 'Local Dictation' `
  --icon (Join-Path $scriptRoot 'local-dictation.ico') `
  --add-data "$(Join-Path $scriptRoot 'config.json');." `
  --add-data "$(Join-Path $scriptRoot 'local-dictation.ico');." `
  --collect-all qwen_asr `
  --collect-all qwen_omni_utils `
  --collect-all PySide6 `
  --collect-all sounddevice `
  --collect-all librosa `
  --collect-all sox `
  --collect-all transformers `
  --collect-all torch `
  (Join-Path $scriptRoot 'codex_ptt.py')

Write-Host "Portable application created at: $(Join-Path $scriptRoot 'dist\Local Dictation')" -ForegroundColor Green

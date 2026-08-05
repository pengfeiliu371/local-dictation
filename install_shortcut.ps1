$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Local Dictation.lnk'
$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$runScript = Join-Path $scriptRoot 'start_tray.ps1'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`""
$shortcut.WorkingDirectory = $scriptRoot
$shortcut.Description = 'Local GPU push-to-talk dictation'
$shortcut.IconLocation = "$(Join-Path $scriptRoot 'local-dictation.ico'),0"
$shortcut.Save()

Write-Host "Created: $shortcutPath" -ForegroundColor Green

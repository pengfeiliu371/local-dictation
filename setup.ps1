$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $scriptRoot '.venv'
$configPath = Join-Path $scriptRoot 'config.json'

if (-not (Test-Path $configPath)) {
    Copy-Item (Join-Path $scriptRoot 'config.example.json') $configPath
}

$basePython = Get-Command py -ErrorAction SilentlyContinue
if ($basePython) {
    $pythonArgs = @('-3.12')
    $pythonExecutable = $basePython.Source
} else {
    throw 'Python 3.12 was not found. Install Python 3.12, then run this script again.'
}

if (-not (Test-Path $pythonExecutable)) {
    throw 'Python 3.12 was not found. Install Python 3.12, then run this script again.'
}

if (-not (Test-Path $venvDir)) {
    & $pythonExecutable @pythonArgs -m venv $venvDir
}

$python = Join-Path $venvDir 'Scripts\python.exe'
& $python -m pip install --upgrade pip

# CUDA 12.8 wheels support RTX 50-series GPUs. If PyTorch changes its wheel
# index in the future, install the current CUDA wheel before running this script.
& $python -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cu128
& $python -m pip install --upgrade -r (Join-Path $scriptRoot 'requirements.txt')

& $python -c "import torch; assert torch.cuda.is_available(), 'CUDA was not detected by PyTorch'; print('CUDA:', torch.cuda.get_device_name(0))"
& $python (Join-Path $scriptRoot 'prefetch_model.py')
Write-Host "Installation complete. Start with .\run.ps1" -ForegroundColor Green

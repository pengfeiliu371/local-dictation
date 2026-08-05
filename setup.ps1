param(
    [ValidateSet('auto', 'gpu', 'cpu')]
    [string]$Mode = 'auto'
)

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

if (-not (Test-Path $venvDir)) {
    & $pythonExecutable @pythonArgs -m venv $venvDir
}

$python = Join-Path $venvDir 'Scripts\python.exe'
& $python -m pip install --upgrade pip

# Auto mode uses the NVIDIA driver tool as a lightweight availability check.
# Use -Mode cpu to force CPU-only PyTorch even on a machine with an NVIDIA GPU.
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($Mode -eq 'auto') {
    $selectedMode = if ($nvidiaSmi) { 'gpu' } else { 'cpu' }
} else {
    $selectedMode = $Mode
}

if ($selectedMode -eq 'gpu') {
    Write-Host 'Installing CUDA-enabled PyTorch (GPU mode) ...' -ForegroundColor Cyan
    # CUDA 12.8 wheels support RTX 50-series GPUs.
    & $python -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cu128
    & $python -c "import torch; assert torch.cuda.is_available(), 'CUDA was not detected by PyTorch. Run setup.ps1 -Mode cpu for CPU-only installation.'; print('CUDA:', torch.cuda.get_device_name(0))"
} else {
    Write-Host 'Installing CPU-only PyTorch (CPU mode) ...' -ForegroundColor Yellow
    & $python -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cpu

    # CPU installations use the smaller model by default. This avoids an
    # unexpectedly slow first launch on computers without a discrete GPU.
    $config = Get-Content -Raw $configPath | ConvertFrom-Json
    $config.model_profile = 'qwen_0_6b_cpu'
    $config.model_id = 'Qwen/Qwen3-ASR-0.6B'
    $config | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $configPath
}

& $python -m pip install --upgrade -r (Join-Path $scriptRoot 'requirements.txt')
& $python (Join-Path $scriptRoot 'prefetch_model.py')

Write-Host "Installation complete ($selectedMode mode). Start with .\run.ps1" -ForegroundColor Green

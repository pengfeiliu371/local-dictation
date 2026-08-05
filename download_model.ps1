param(
    [ValidateSet('qwen_1_7b_gpu', 'qwen_0_6b_gpu', 'qwen_0_6b_cpu')]
    [string]$Profile = 'qwen_0_6b_gpu'
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $scriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Local Dictation is not installed yet. Run setup.ps1 first.'
}

switch ($Profile) {
    'qwen_1_7b_gpu' { $modelId = 'Qwen/Qwen3-ASR-1.7B' }
    'qwen_0_6b_gpu' { $modelId = 'Qwen/Qwen3-ASR-0.6B' }
    'qwen_0_6b_cpu' { $modelId = 'Qwen/Qwen3-ASR-0.6B' }
}

Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
# hf_xet is Hugging Face's official accelerated download backend. It uses
# parallel, chunked transfers from the nearest CDN edge; high-performance mode
# is appropriate for one-off multi-GB model downloads on this desktop.
Remove-Item Env:HF_HUB_DISABLE_XET -ErrorAction SilentlyContinue
$env:HF_XET_HIGH_PERFORMANCE = '1'
& $python (Join-Path $scriptRoot 'prefetch_model.py') --model-id $modelId
Write-Host 'Model downloaded. Exit and reopen Local Dictation to test it.' -ForegroundColor Green

param([switch]$DownloadModel)
$ErrorActionPreference = 'Stop'
$taskTraining = Split-Path -Parent $PSScriptRoot
$taskEnvironment = Join-Path $taskTraining '.venv'
$taskPython = Join-Path $taskEnvironment 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    py -3.12 -m venv $taskEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 virtual environment creation failed.' }
}
& $taskPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $taskPython -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed.' }
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Qwen dependency installation failed.' }
if ($DownloadModel) {
    & $taskPython (Join-Path $PSScriptRoot 'download_model.py')
    if ($LASTEXITCODE -ne 0) { throw 'Official model download failed.' }
}
Write-Output 'Local inference environment is ready. Model inference requires an NVIDIA CUDA GPU.'

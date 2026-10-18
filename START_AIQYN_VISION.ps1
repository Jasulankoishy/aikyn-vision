param(
    [ValidateSet('start', 'status', 'stop', 'preflight')]
    [string]$Action = 'start'
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskLauncher = Join-Path $PSScriptRoot 'scripts\launch_quick_local.py'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw 'Create the API environment first; see README.md.'
}
& $taskPython $taskLauncher $Action
exit $LASTEXITCODE

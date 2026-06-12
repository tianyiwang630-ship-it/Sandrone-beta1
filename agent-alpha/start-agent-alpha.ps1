$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Invoke-NativeCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$VenvDir = Join-Path $ProjectRoot ".venv"
$ScriptsDir = Join-Path $VenvDir "Scripts"
$PythonExe = Join-Path $ScriptsDir "python.exe"
$PythonVersion = "3.12"

if (-not (Test-Path $PythonExe)) {
    Write-Host "agent-alpha .venv was not found." -ForegroundColor Red
    Write-Host "Run .\setup-agent-alpha.ps1 first to create the environment." -ForegroundColor Yellow
    exit 1
}

$ActualPythonVersion = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($ActualPythonVersion -ne $PythonVersion) {
    Write-Host "agent-alpha .venv is Python $ActualPythonVersion, but Python $PythonVersion is required." -ForegroundColor Red
    Write-Host "Remove .venv and run this script again to recreate it with Python $PythonVersion." -ForegroundColor Yellow
    exit 1
}

& $PythonExe -c "import tempfile"
if ($LASTEXITCODE -ne 0) {
    Write-Host "agent-alpha .venv Python is missing the standard library module 'tempfile'." -ForegroundColor Red
    Write-Host "This usually means the uv-managed Python installation is incomplete or corrupted." -ForegroundColor Yellow
    Write-Host "Remove .venv and reinstall uv's Python 3.12 runtime, then run this script again." -ForegroundColor Yellow
    exit 1
}

$env:AGENT_ALPHA_ROOT = $ProjectRoot
$RuntimeEnvJson = & $PythonExe -c @'
import json
import os
from pathlib import Path

from agent.core.runtime_paths import build_runtime_env, ensure_runtime_directories

root = Path(os.environ['AGENT_ALPHA_ROOT'])
ensure_runtime_directories(root)
print(json.dumps(build_runtime_env(root), ensure_ascii=False))
'@
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$RuntimeEnv = $RuntimeEnvJson | ConvertFrom-Json
foreach ($Property in $RuntimeEnv.PSObject.Properties) {
    [System.Environment]::SetEnvironmentVariable($Property.Name, [string]$Property.Value, "Process")
}

Write-Host "Starting agent-alpha..." -ForegroundColor Green
Invoke-NativeCommand $PythonExe @("-m", "agent.cli.main")

$ErrorActionPreference = 'Stop'
$Frontend = Split-Path -Parent $PSScriptRoot
$Project = Split-Path -Parent $Frontend
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$Electron = Join-Path $Frontend 'node_modules\electron\dist\electron.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    throw '缺少项目 Python 环境。请先运行 setup-agent-alpha.ps1。'
}

Push-Location $Frontend
try {
    if (-not (Test-Path -LiteralPath $Electron)) {
        $env:NPM_CONFIG_OFFLINE = 'false'
        npm.cmd install
        if ($LASTEXITCODE -ne 0) { throw 'Electron 依赖安装失败。' }
        if (-not (Test-Path -LiteralPath $Electron)) {
            node.exe (Join-Path $Frontend 'node_modules\electron\install.js')
            if ($LASTEXITCODE -ne 0) { throw 'Electron 程序下载失败。' }
        }
    }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    & $Python (Join-Path $PSScriptRoot 'make-icon.py')
    if ($LASTEXITCODE -ne 0) { throw '应用图标生成失败。' }
    & (Join-Path $PSScriptRoot 'create-desktop-shortcut.ps1')
} finally {
    Pop-Location
}

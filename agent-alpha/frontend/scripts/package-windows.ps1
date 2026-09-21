param(
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$FrontendRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Split-Path -Parent $FrontendRoot
$TempRoot = Join-Path $ProjectRoot "temp"
$PackageRoot = Join-Path $TempRoot "package-stage"
$AppStage = Join-Path $PackageRoot "agent-alpha"
$BuildRoot = Join-Path $PackageRoot "build"
$CacheRoot = Join-Path $PackageRoot "cache"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$RuntimeRoot = Join-Path $AppStage "runtime"
$BackendPython = Join-Path $RuntimeRoot "backend-python"
$BrowserPython = Join-Path $RuntimeRoot "browser-python"
$McpRuntime = Join-Path $RuntimeRoot "mcp"
$PythonVersion = "3.12.12"
$BrowserHarnessVersion = "0.1.13"
$BrowserHarnessCatalogUrl = "https://pypi.org/pypi/browser-harness/$BrowserHarnessVersion/json"
$OpenWebsearchVersion = "2.1.11"
$InstallerName = "Agent-Alpha-Setup-0.1.0-win-x64.exe"
$InstallerTargetBytes = 700MB
$InstallerMaximumBytes = 900MB

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Reset-SafeDirectory([string]$Path, [string]$AllowedParent) {
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullParent = [IO.Path]::GetFullPath($AllowedParent).TrimEnd('\')
    if (-not $fullPath.StartsWith("$fullParent\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean an unexpected directory: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
}

function Copy-DirectoryContents([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing package source directory: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Destination -Recurse -Force
}

function Invoke-PythonCode([string]$Python, [string]$Code, [string[]]$Arguments = @()) {
    $oldBytecode = $env:PYTHONDONTWRITEBYTECODE
    $env:PYTHONDONTWRITEBYTECODE = "1"
    try {
        $output = & $Python -c $Code @Arguments
        Assert-LastExitCode "Read Python runtime metadata"
        return [string]$output
    }
    finally {
        $env:PYTHONDONTWRITEBYTECODE = $oldBytecode
    }
}

New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
Reset-SafeDirectory $AppStage $PackageRoot
Reset-SafeDirectory $BuildRoot $PackageRoot
New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
$env:UV_CACHE_DIR = Join-Path $CacheRoot 'uv'
$env:npm_config_cache = Join-Path $CacheRoot 'npm'
Reset-SafeDirectory $ReleaseRoot $ProjectRoot

Write-Host "[1/8] Run checks and build the frontend"
if (-not $SkipChecks) {
    $TestPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $TestPython)) {
        throw "Development environment is missing: $TestPython"
    }
    & $TestPython -m pytest (Join-Path $ProjectRoot "tests") -q --basetemp (Join-Path $PackageRoot "pytest")
    Assert-LastExitCode "Backend tests"
}
Push-Location $FrontendRoot
try {
    if (-not $SkipChecks) {
        & npm.cmd test
        Assert-LastExitCode "Frontend tests"
    }
    & npm.cmd run build
    Assert-LastExitCode "Frontend build"
}
finally {
    Pop-Location
}

Write-Host "[2/8] Stage read-only application resources"
Copy-DirectoryContents (Join-Path $FrontendRoot "dist") (Join-Path $AppStage "frontend\dist")
Copy-DirectoryContents (Join-Path $ProjectRoot "skills") (Join-Path $AppStage "skills")
New-Item -ItemType Directory -Path (Join-Path $AppStage "config") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\llm_profiles.json") -Destination (Join-Path $AppStage "config\llm_profiles.json")
New-Item -ItemType Directory -Path (Join-Path $AppStage "mcp-servers\open-websearch") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "mcp-servers\registry.json") -Destination (Join-Path $AppStage "mcp-servers\registry.json")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "mcp-servers\open-websearch\mcp.config.json") -Destination (Join-Path $AppStage "mcp-servers\open-websearch\mcp.config.json")

Write-Host "[3/8] Create two isolated Python runtimes"
$PythonInstallRoot = Join-Path $CacheRoot "python-install"
New-Item -ItemType Directory -Path $PythonInstallRoot -Force | Out-Null
& uv python install $PythonVersion --install-dir $PythonInstallRoot --no-bin --no-registry
Assert-LastExitCode "Install Python $PythonVersion"
$PythonSourceExe = Get-ChildItem -LiteralPath $PythonInstallRoot -Filter "python.exe" -Recurse |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.Directory.FullName "Lib") } |
    Select-Object -First 1
if ($null -eq $PythonSourceExe) {
    throw "Standalone Python runtime was not found"
}
Copy-DirectoryContents $PythonSourceExe.Directory.FullName $BackendPython
Copy-DirectoryContents $PythonSourceExe.Directory.FullName $BrowserPython

$RequirementsPath = Join-Path $BuildRoot "backend-requirements.txt"
Push-Location $ProjectRoot
try {
    & uv export --quiet --frozen --no-dev --no-emit-project --format requirements.txt --output-file $RequirementsPath
    Assert-LastExitCode "Export locked backend dependencies"
}
finally {
    Pop-Location
}
& uv pip install --quiet --python (Join-Path $BackendPython "python.exe") --system --break-system-packages --link-mode copy --require-hashes --requirements $RequirementsPath
Assert-LastExitCode "Install backend dependencies"

$WheelRoot = Join-Path $BuildRoot "wheel"
New-Item -ItemType Directory -Path $WheelRoot -Force | Out-Null
$SourceStage = Join-Path $BuildRoot "source"
Copy-DirectoryContents (Join-Path $ProjectRoot "agent") (Join-Path $SourceStage "agent")
foreach ($sourceFile in @("pyproject.toml", "LICENSE")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $sourceFile) -Destination (Join-Path $SourceStage $sourceFile)
}
& uv build --wheel --out-dir $WheelRoot $SourceStage
Assert-LastExitCode "Build Agent Alpha wheel"
$AgentWheel = Get-ChildItem -LiteralPath $WheelRoot -Filter "agent_alpha-*.whl" | Select-Object -First 1
if ($null -eq $AgentWheel) {
    throw "Agent Alpha wheel was not created"
}
& uv pip install --quiet --python (Join-Path $BackendPython "python.exe") --system --break-system-packages --link-mode copy --no-deps $AgentWheel.FullName
Assert-LastExitCode "Install Agent Alpha"

& uv pip install --quiet --python (Join-Path $BrowserPython "python.exe") --system --break-system-packages --link-mode copy --requirements (Join-Path $FrontendRoot "packaging\browser-harness-requirements.txt")
Assert-LastExitCode "Install Browser Harness"

Get-ChildItem -LiteralPath $BackendPython -Directory -Filter "agent_alpha-*.dist-info" -Recurse |
    ForEach-Object {
        $directUrl = Join-Path $_.FullName "direct_url.json"
        if (Test-Path -LiteralPath $directUrl) { Remove-Item -LiteralPath $directUrl -Force }
    }
foreach ($scriptsPath in @((Join-Path $BackendPython "Scripts"), (Join-Path $BrowserPython "Scripts"))) {
    if (Test-Path -LiteralPath $scriptsPath) { Remove-Item -LiteralPath $scriptsPath -Recurse -Force }
}

$BootstrapRoot = Join-Path $RuntimeRoot "bootstrap"
New-Item -ItemType Directory -Path $BootstrapRoot -Force | Out-Null
$UvSource = (Get-Command uv.exe -ErrorAction Stop).Source
$BundledUv = Join-Path $BootstrapRoot "uv.exe"
Copy-Item -LiteralPath $UvSource -Destination $BundledUv -Force
$UvVersion = (& $BundledUv --version).Trim()
Assert-LastExitCode "Verify bundled uv"
$UvSha256 = (Get-FileHash -LiteralPath $BundledUv -Algorithm SHA256).Hash.ToLowerInvariant()

$BrowserHarnessCatalog = Invoke-RestMethod -Uri $BrowserHarnessCatalogUrl
$BrowserHarnessWheelInfo = $BrowserHarnessCatalog.urls |
    Where-Object { $_.packagetype -eq "bdist_wheel" -and $_.filename -eq "browser_harness-$BrowserHarnessVersion-py3-none-any.whl" } |
    Select-Object -First 1
if ($null -eq $BrowserHarnessWheelInfo) {
    throw "Browser Harness $BrowserHarnessVersion universal wheel was not found"
}
$BrowserHarnessWheelCache = Join-Path $CacheRoot ([string]$BrowserHarnessWheelInfo.filename)
if (-not (Test-Path -LiteralPath $BrowserHarnessWheelCache)) {
    Invoke-WebRequest -Uri $BrowserHarnessWheelInfo.url -OutFile $BrowserHarnessWheelCache -UseBasicParsing
}
$BrowserHarnessWheelSha256 = (Get-FileHash -LiteralPath $BrowserHarnessWheelCache -Algorithm SHA256).Hash.ToLowerInvariant()
$ExpectedBrowserHarnessWheelSha256 = ([string]$BrowserHarnessWheelInfo.digests.sha256).ToLowerInvariant()
if ($BrowserHarnessWheelSha256 -ne $ExpectedBrowserHarnessWheelSha256) {
    throw "Browser Harness wheel SHA-256 does not match PyPI metadata"
}
$BundledBrowserHarnessWheel = Join-Path $BootstrapRoot ([string]$BrowserHarnessWheelInfo.filename)
Copy-Item -LiteralPath $BrowserHarnessWheelCache -Destination $BundledBrowserHarnessWheel -Force

Write-Host "[4/8] Bundle the pinned MCP package"
New-Item -ItemType Directory -Path $McpRuntime -Force | Out-Null
& npm.cmd install --prefix $McpRuntime --omit=dev --ignore-scripts --package-lock=false "open-websearch@$OpenWebsearchVersion"
Assert-LastExitCode "Install open-websearch MCP"
Copy-Item -LiteralPath (Join-Path $FrontendRoot "desktop\open-websearch-entry.cjs") -Destination (Join-Path $McpRuntime "open-websearch-entry.cjs")

Write-Host "[5/8] Download Chrome for Testing Stable win64"
$ChromeCatalogUrl = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
$ChromeCatalog = Invoke-RestMethod -Uri $ChromeCatalogUrl
$ChromeVersion = [string]$ChromeCatalog.channels.Stable.version
$ChromeDownload = $ChromeCatalog.channels.Stable.downloads.chrome |
    Where-Object { $_.platform -eq "win64" } |
    Select-Object -First 1
if ($null -eq $ChromeDownload) {
    throw "Chrome for Testing catalog has no Stable win64 download"
}
$ChromeZip = Join-Path $CacheRoot "chrome-$ChromeVersion-win64.zip"
if (-not (Test-Path -LiteralPath $ChromeZip)) {
    Invoke-WebRequest -Uri $ChromeDownload.url -OutFile $ChromeZip -UseBasicParsing
}
$ChromeSha256 = (Get-FileHash -LiteralPath $ChromeZip -Algorithm SHA256).Hash.ToLowerInvariant()
$ChromeExtract = Join-Path $BuildRoot "chrome-extract"
Expand-Archive -LiteralPath $ChromeZip -DestinationPath $ChromeExtract -Force
$ChromeSource = Join-Path $ChromeExtract "chrome-win64"
if (-not (Test-Path -LiteralPath (Join-Path $ChromeSource "chrome.exe"))) {
    throw "Unexpected Chrome for Testing archive layout"
}
Copy-DirectoryContents $ChromeSource (Join-Path $AppStage "tools\chrome-for-testing\chrome-win64")

Write-Host "[6/8] Verify bundled runtimes and write the manifest"
$BackendPythonExe = Join-Path $BackendPython "python.exe"
$BrowserPythonExe = Join-Path $BrowserPython "python.exe"
$BackendPythonVersion = Invoke-PythonCode $BackendPythonExe 'import sys; print(sys.version.split()[0])'
$AgentAlphaVersion = Invoke-PythonCode $BackendPythonExe 'import importlib.metadata as m, sys; print(m.version(sys.argv[1]))' @("agent-alpha")
$FastapiVersion = Invoke-PythonCode $BackendPythonExe 'import importlib.metadata as m, sys; print(m.version(sys.argv[1]))' @("fastapi")
$FastmcpVersion = Invoke-PythonCode $BackendPythonExe 'import importlib.metadata as m, sys; print(m.version(sys.argv[1]))' @("fastmcp")
$BrowserPythonVersion = Invoke-PythonCode $BrowserPythonExe 'import sys; print(sys.version.split()[0])'
$InstalledBrowserHarnessVersion = Invoke-PythonCode $BrowserPythonExe 'import importlib.metadata as m, sys; print(m.version(sys.argv[1]))' @("browser-harness")
$BrowserWebsocketsVersion = Invoke-PythonCode $BrowserPythonExe 'import importlib.metadata as m, sys; print(m.version(sys.argv[1]))' @("websockets")
& $BrowserPythonExe -m browser_harness.run --version
Assert-LastExitCode "Verify Browser Harness"

$ElectronPackage = Get-Content -LiteralPath (Join-Path $FrontendRoot "node_modules\electron\package.json") -Encoding UTF8 | ConvertFrom-Json
$OpenWebsearchPackage = Get-Content -LiteralPath (Join-Path $McpRuntime "node_modules\open-websearch\package.json") -Encoding UTF8 | ConvertFrom-Json
$Manifest = [ordered]@{
    product = "Agent Alpha"
    version = "0.1.0"
    platform = "win32-x64"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    components = [ordered]@{
        electron = [string]$ElectronPackage.version
        python = $BackendPythonVersion
        agent_alpha = $AgentAlphaVersion
        fastapi = $FastapiVersion
        fastmcp = $FastmcpVersion
        browser_python = $BrowserPythonVersion
        browser_harness = $InstalledBrowserHarnessVersion
        browser_websockets = $BrowserWebsocketsVersion
        uv = $UvVersion
        open_websearch = [string]$OpenWebsearchPackage.version
        chrome_for_testing = $ChromeVersion
    }
    sources = [ordered]@{
        chrome_catalog = $ChromeCatalogUrl
        chrome_download = [string]$ChromeDownload.url
        chrome_archive_sha256 = $ChromeSha256
        browser_harness_package = $BrowserHarnessCatalogUrl
        browser_harness_wheel = [string]$BrowserHarnessWheelInfo.url
        browser_harness_wheel_sha256 = $BrowserHarnessWheelSha256
        uv_sha256 = $UvSha256
    }
}
$StageManifest = Join-Path $AppStage "release-manifest.json"
$Manifest | ConvertTo-Json -Depth 8 | Out-File -LiteralPath $StageManifest -Encoding utf8

$ExpectedTopLevel = @("config", "frontend", "mcp-servers", "release-manifest.json", "runtime", "skills", "tools")
$ActualTopLevel = @(Get-ChildItem -LiteralPath $AppStage -Force | ForEach-Object Name | Sort-Object)
$TopLevelDifference = @(Compare-Object ($ExpectedTopLevel | Sort-Object) $ActualTopLevel)
if ($TopLevelDifference.Count -ne 0) {
    throw "Unexpected top-level package contents: $($ActualTopLevel -join ', ')"
}
$ForbiddenNames = @("runtime_env.local.json", ".env", ".env.local", "DevToolsActivePort")
$ForbiddenFiles = Get-ChildItem -LiteralPath $AppStage -File -Recurse -Force |
    Where-Object { $ForbiddenNames -contains $_.Name }
if ($ForbiddenFiles) {
    throw "Private runtime files were staged: $($ForbiddenFiles.FullName -join ', ')"
}
$BundledBrowserHarnessExecutables = Get-ChildItem -LiteralPath $AppStage -File -Recurse -Force |
    Where-Object { $_.Name -ieq "browser-harness.exe" }
if ($BundledBrowserHarnessExecutables) {
    throw "Build-machine Browser Harness launchers must not be packaged: $($BundledBrowserHarnessExecutables.FullName -join ', ')"
}
$TextExtensions = @(".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".py", ".js", ".cjs", ".pth")
$PersonalRoots = @($ProjectRoot, $env:USERPROFILE) | Where-Object { $_ }
foreach ($file in Get-ChildItem -LiteralPath $AppStage -File -Recurse -Force | Where-Object { $TextExtensions -contains $_.Extension.ToLowerInvariant() }) {
    $text = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    foreach ($personalRoot in $PersonalRoots) {
        if ($text -and $text.IndexOf($personalRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "Staged file contains a build-machine path: $($file.FullName)"
        }
    }
}

Write-Host "[7/8] Build the NSIS installer"
foreach ($bytecodeDirectory in Get-ChildItem -LiteralPath $AppStage -Directory -Recurse -Filter '__pycache__') {
    $resolvedBytecode = [IO.Path]::GetFullPath($bytecodeDirectory.FullName)
    if (-not $resolvedBytecode.StartsWith("$AppStage\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected bytecode directory: $resolvedBytecode"
    }
    Remove-Item -LiteralPath $resolvedBytecode -Recurse -Force
}
Push-Location $FrontendRoot
try {
    & (Join-Path $FrontendRoot "node_modules\.bin\electron-builder.cmd") --win nsis --x64 --config electron-builder.yml --publish never
    Assert-LastExitCode "Build Windows installer"
}
finally {
    Pop-Location
}

$InstallerPath = Join-Path $ReleaseRoot $InstallerName
if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Expected installer was not created: $InstallerPath"
}
$InstallerSize = (Get-Item -LiteralPath $InstallerPath).Length
$InstallerSizeMb = [math]::Round($InstallerSize / 1MB, 2)
if ($InstallerSize -gt $InstallerMaximumBytes) {
    throw "Installer is $InstallerSizeMb MB, exceeding the 900 MB release limit."
}
if ($InstallerSize -gt $InstallerTargetBytes) {
    Write-Warning "Installer is $InstallerSizeMb MB, above the 700 MB target but within the 900 MB release limit."
}
$InstallerHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifest.installer = [ordered]@{
    file = $InstallerName
    sha256 = $InstallerHash
    signed = $false
}
$ReleaseManifest = Join-Path $ReleaseRoot "release-manifest.json"
$Manifest | ConvertTo-Json -Depth 8 | Out-File -LiteralPath $ReleaseManifest -Encoding utf8

Write-Host "[8/8] Remove intermediate builder output"
foreach ($item in Get-ChildItem -LiteralPath $ReleaseRoot -Force) {
    if ($item.FullName -notin @($InstallerPath, $ReleaseManifest)) {
        Remove-Item -LiteralPath $item.FullName -Recurse -Force
    }
}

Write-Host "Installer created: $InstallerPath"
Write-Host "Installer size: $InstallerSizeMb MB"
Write-Host "SHA-256: $InstallerHash"

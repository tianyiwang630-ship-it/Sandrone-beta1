$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceUserData = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
$SourceLocalState = Join-Path $SourceUserData "Local State"
$SourceProfile = Join-Path $SourceUserData "Profile 5"
$TargetUserData = Join-Path $ProjectRoot "state\browser\profiles\default\user-data"
$TargetLocalState = Join-Path $TargetUserData "Local State"
$TargetDefaultProfile = Join-Path $TargetUserData "Default"

function Resolve-FullPath {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-PathInside {
    param(
        [string]$Path,
        [string]$Root
    )

    $fullPath = Resolve-FullPath $Path
    $fullRoot = Resolve-FullPath $Root
    if (-not $fullRoot.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $fullRoot = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
    }

    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside agent-alpha: $fullPath"
    }
}

function Get-BlockingBrowserProcesses {
    $names = @(
        "chrome",
        "chromium",
        "agent-browser",
        "agent-browser-win32-x64"
    )

    return Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $names -contains $_.ProcessName } |
        Select-Object Id, ProcessName, Path
}

function Set-DefaultProfileMetadata {
    param([string]$LocalStatePath)

    $localState = Get-Content -LiteralPath $LocalStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $localState.profile -or -not $localState.profile.info_cache) {
        throw "Local State does not contain profile.info_cache: $LocalStatePath"
    }

    $sourceInfo = $localState.profile.info_cache.PSObject.Properties["Profile 5"]
    if (-not $sourceInfo) {
        throw "Local State does not contain Profile 5 metadata: $LocalStatePath"
    }

    if ($localState.profile.info_cache.PSObject.Properties["Default"]) {
        $localState.profile.info_cache.Default = $sourceInfo.Value
    } else {
        $localState.profile.info_cache | Add-Member -NotePropertyName "Default" -NotePropertyValue $sourceInfo.Value
    }

    $localState.profile.last_used = "Default"
    $localState.profile.last_active_profiles = @("Default")
    $localState.profile.profiles_order = @("Default")

    $localState | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $LocalStatePath -Encoding UTF8
}

Write-Host "Sync Chrome Profile 5 to agent-alpha default profile" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Source Local State: $SourceLocalState"
Write-Host "Source Profile: $SourceProfile"
Write-Host "Target user-data: $TargetUserData"

if (-not (Test-Path -LiteralPath $SourceLocalState)) {
    throw "Source Local State not found: $SourceLocalState"
}

if (-not (Test-Path -LiteralPath $SourceProfile)) {
    throw "Source Chrome Profile 5 not found: $SourceProfile"
}

$blocking = @(Get-BlockingBrowserProcesses)
if ($blocking.Count -gt 0) {
    Write-Host ""
    Write-Host "Browser-related processes are still running. Close them before syncing:" -ForegroundColor Yellow
    $blocking | Format-Table -AutoSize
    exit 2
}

Assert-PathInside -Path $TargetUserData -Root $ProjectRoot

if (Test-Path -LiteralPath $TargetUserData) {
    Remove-Item -LiteralPath $TargetUserData -Recurse -Force
}

New-Item -ItemType Directory -Path $TargetUserData -Force | Out-Null
Copy-Item -LiteralPath $SourceLocalState -Destination $TargetLocalState -Force
Copy-Item -LiteralPath $SourceProfile -Destination $TargetDefaultProfile -Recurse -Force
Set-DefaultProfileMetadata -LocalStatePath $TargetLocalState

Write-Host ""
Write-Host "Sync complete." -ForegroundColor Green
Write-Host "Copied Local State -> $TargetLocalState"
Write-Host "Copied Profile 5   -> $TargetDefaultProfile"
Write-Host "Mapped Profile 5 metadata to Default in Local State"

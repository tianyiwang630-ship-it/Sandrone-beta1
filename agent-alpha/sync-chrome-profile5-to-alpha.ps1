$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RealUserProfile = [Environment]::GetEnvironmentVariable("USERPROFILE", "User")
if (-not $RealUserProfile) {
    $RealUserProfile = $env:USERPROFILE
}
$SourceUserData = Join-Path (Join-Path $RealUserProfile "AppData\Local") "Google\Chrome\User Data"
$SourceLocalState = Join-Path $SourceUserData "Local State"
$SourceProfile = Join-Path $SourceUserData "Profile 5"
$TargetUserData = Join-Path $ProjectRoot "state\browser\profiles\default\user-data"
$StagingUserData = Join-Path $ProjectRoot "state\browser\profiles\default\user-data.importing"
$TargetLocalState = Join-Path $TargetUserData "Local State"
$TargetDefaultProfile = Join-Path $TargetUserData "Default"
$LocksDir = Join-Path $ProjectRoot "state\browser\locks"
$ProfileCopyLock = Join-Path $LocksDir "profile-copy-default.lock"

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

function Test-ProcessAlive {
    param([int]$Pid)
    return [bool](Get-Process -Id $Pid -ErrorAction SilentlyContinue)
}

function Acquire-ProfileCopyLock {
    param(
        [string]$LockPath,
        [int]$TimeoutSeconds = 60
    )

    New-Item -ItemType Directory -Path (Split-Path -Parent $LockPath) -Force | Out-Null
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $payload = @{
        owner_pid = $PID
        owner_id = "$PID-profile5-sync"
        project_root = $ProjectRoot
        created_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json -Compress

    while ((Get-Date) -lt $deadline) {
        try {
            $stream = [System.IO.File]::Open($LockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            try {
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
                $stream.Write($bytes, 0, $bytes.Length)
            } finally {
                $stream.Close()
            }
            return
        } catch [System.IO.IOException] {
            try {
                $existing = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($existing.owner_pid -and -not (Test-ProcessAlive -Pid ([int]$existing.owner_pid))) {
                    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
                    continue
                }
            } catch {
                # Damaged or unreadable lock: keep it and wait, do not guess.
            }
            Start-Sleep -Milliseconds 100
        }
    }

    throw "Timed out waiting for profile-copy-default.lock: $LockPath"
}

function Release-ProfileCopyLock {
    param([string]$LockPath)
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

function Test-ImportedUserData {
    param([string]$UserDataPath)

    $localState = Join-Path $UserDataPath "Local State"
    $preferences = Join-Path $UserDataPath "Default\Preferences"
    if (-not (Test-Path -LiteralPath $localState)) {
        throw "Imported user-data is missing Local State: $localState"
    }
    if (-not (Test-Path -LiteralPath $preferences)) {
        throw "Imported user-data is missing Default\Preferences: $preferences"
    }
}

function Replace-Directory {
    param(
        [string]$Source,
        [string]$Target
    )

    $backup = "$Target.old-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force
    }

    if (Test-Path -LiteralPath $Target) {
        Move-Item -LiteralPath $Target -Destination $backup
    }

    try {
        Move-Item -LiteralPath $Source -Destination $Target
    } catch {
        if ((Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $Target)) {
            Move-Item -LiteralPath $backup -Destination $Target
        }
        throw
    } finally {
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $backup -Recurse -Force
        }
    }
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
Assert-PathInside -Path $StagingUserData -Root $ProjectRoot
Assert-PathInside -Path $ProfileCopyLock -Root $ProjectRoot

Acquire-ProfileCopyLock -LockPath $ProfileCopyLock

try {
    if (Test-Path -LiteralPath $StagingUserData) {
        Remove-Item -LiteralPath $StagingUserData -Recurse -Force
    }

    New-Item -ItemType Directory -Path $StagingUserData -Force | Out-Null
    Copy-Item -LiteralPath $SourceLocalState -Destination (Join-Path $StagingUserData "Local State") -Force
    Copy-Item -LiteralPath $SourceProfile -Destination (Join-Path $StagingUserData "Default") -Recurse -Force
    Set-DefaultProfileMetadata -LocalStatePath (Join-Path $StagingUserData "Local State")
    Test-ImportedUserData -UserDataPath $StagingUserData
    Replace-Directory -Source $StagingUserData -Target $TargetUserData
} finally {
    if (Test-Path -LiteralPath $StagingUserData) {
        Remove-Item -LiteralPath $StagingUserData -Recurse -Force
    }
    Release-ProfileCopyLock -LockPath $ProfileCopyLock
}

Write-Host ""
Write-Host "Sync complete." -ForegroundColor Green
Write-Host "Copied Local State -> $TargetLocalState"
Write-Host "Copied Profile 5   -> $TargetDefaultProfile"
Write-Host "Mapped Profile 5 metadata to Default in Local State"

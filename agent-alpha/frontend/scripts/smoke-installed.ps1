param([Parameter(Mandatory=$true)][string]$InstallDirectory, [switch]$Resume)
$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['Invoke-RestMethod:NoProxy'] = $true
$exe = Join-Path $InstallDirectory 'Agent Alpha.exe'
$dataRoot = Join-Path $env:LOCALAPPDATA 'AgentAlpha'
$python = Join-Path $InstallDirectory 'resources/agent-alpha/runtime/backend-python/python.exe'
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
$dataRoot = (& $python -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' $dataRoot).Trim()
$url = 'http://127.0.0.1:8787'
if (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8787 must be free before the isolated installation smoke test.'
}
if (-not $Resume -and (Test-Path (Join-Path $dataRoot 'state/web/app_state.json'))) {
    throw 'Existing release user data found; smoke test will not change it.'
}
$oldPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$desktop = $null
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class SmokeWindowClose {
    public delegate bool WindowCallback(IntPtr window, IntPtr param);
    [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback, IntPtr param);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr window, StringBuilder name, int count);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, uint message, IntPtr wparam, IntPtr lparam);
    public static bool Close(uint pid) {
        bool sent = false;
        EnumWindows((window, unused) => {
            uint owner; GetWindowThreadProcessId(window, out owner);
            var name = new StringBuilder(256); GetClassName(window, name, name.Capacity);
            if (owner == pid && name.ToString() == "Chrome_WidgetWin_1") {
                sent |= PostMessage(window, 0x0010, IntPtr.Zero, IntPtr.Zero);
            }
            return true;
        }, IntPtr.Zero);
        return sent;
    }
}
'@
function Start-TestDesktop {
    $script:desktop = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
            if ($health.ok -and $health.project_root -eq $dataRoot) { return }
        } catch { }
        Start-Sleep -Milliseconds 400
    }
    throw 'Packaged desktop did not become healthy.'
}
function Stop-TestDesktop {
    if ($script:desktop -and -not $script:desktop.HasExited) {
        $windowDeadline = (Get-Date).AddSeconds(15)
        do {
            $closed = [SmokeWindowClose]::Close($script:desktop.Id)
            if ($closed) { break }
            Start-Sleep -Milliseconds 300
        } while ((Get-Date) -lt $windowDeadline)
        if (-not $closed -or -not $script:desktop.WaitForExit(15000)) {
            throw 'Desktop did not close normally.'
        }
    }
    Start-Sleep -Seconds 2
    if (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Backend remained after desktop exit.'
    }
}
try {
    Start-TestDesktop
    $cli = Join-Path $dataRoot 'bin/browser-harness.exe'
    if ((& $cli --version).Trim() -ne '0.1.13') { throw 'Incorrect Browser Harness version.' }
    if ($Resume) {
        $projects = @(Invoke-RestMethod "$url/api/projects")
        if ($projects.Count -ne 1 -or $projects[0].name -ne 'Packaging smoke test') { throw 'Unexpected user data; refusing to resume.' }
        $sessions = Invoke-RestMethod "$url/api/projects/$($projects[0].id)/sessions"
        $session = @($sessions.sessions)[0]
        if ($session.title -ne 'Persistence smoke test') { throw 'Unexpected session.' }
    } else {
        Invoke-RestMethod "$url/api/settings" -Method Patch -ContentType 'application/json' -Body '{"theme":"dark"}' | Out-Null
        $project = Invoke-RestMethod "$url/api/projects" -Method Post -ContentType 'application/json' -Body '{"name":"Packaging smoke test"}'
        $body = @{ project_id=$project.id; title='Persistence smoke test' } | ConvertTo-Json
        $session = Invoke-RestMethod "$url/api/sessions" -Method Post -ContentType 'application/json' -Body $body
    }
    Stop-TestDesktop
    Start-TestDesktop
    $settings = Invoke-RestMethod "$url/api/settings"
    $saved = Invoke-RestMethod "$url/api/sessions/$($session.id)"
    if ($settings.theme -ne 'dark' -or $saved.id -ne $session.id) { throw 'Restart persistence failed.' }
    Stop-TestDesktop
    Write-Output 'PASS: restricted PATH, offline launcher, health, settings/project/session persistence, normal desktop exit and backend cleanup.'
    Write-Output "Test data retained at: $dataRoot"
} finally {
    $env:PATH = $oldPath
    if ($desktop -and -not $desktop.HasExited) { $desktop.Kill() }
}

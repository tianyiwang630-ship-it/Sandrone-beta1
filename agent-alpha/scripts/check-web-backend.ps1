$Root = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$Health = $null
try {
    $Request = [Net.HttpWebRequest]::Create('http://127.0.0.1:8787/api/health')
    $Request.Timeout = 2000
    $Response = $Request.GetResponse()
    try {
        $Reader = [IO.StreamReader]::new($Response.GetResponseStream(), [Text.Encoding]::UTF8)
        try { $Health = $Reader.ReadToEnd() | ConvertFrom-Json } finally { $Reader.Dispose() }
    } finally { $Response.Dispose() }
} catch {
    $Client = [Net.Sockets.TcpClient]::new()
    try {
        $Connect = $Client.BeginConnect('127.0.0.1', 8787, $null, $null)
        if ($Connect.AsyncWaitHandle.WaitOne(500)) {
            try { $Client.EndConnect($Connect); exit 2 } catch { exit 1 }
        }
        exit 1
    } finally {
        $Client.Dispose()
    }
}

if ($Health.ok -eq $true -and $Health.project_root -and [string]::Equals(
    [IO.Path]::GetFullPath([string]$Health.project_root),
    [IO.Path]::GetFullPath($Root),
    [StringComparison]::OrdinalIgnoreCase
)) { exit 0 }
exit 2

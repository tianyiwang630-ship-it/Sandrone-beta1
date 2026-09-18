$ErrorActionPreference = 'Stop'
$Frontend = Split-Path -Parent $PSScriptRoot
$Electron = Join-Path $Frontend 'node_modules\electron\dist\electron.exe'
$Icon = Join-Path $Frontend 'desktop\app.ico'
$Desktop = [Environment]::GetFolderPath('DesktopDirectory')

if (-not (Test-Path -LiteralPath $Electron)) { throw '缺少 Electron 程序。请先运行 npm run desktop:prepare。' }
if (-not (Test-Path -LiteralPath $Icon)) { throw '缺少应用图标。请先运行 npm run desktop:prepare。' }
if (-not $Desktop) { throw '无法找到 Windows 桌面目录。' }

$ShortcutPath = Join-Path $Desktop 'agent-alpha.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Electron
$Shortcut.Arguments = '"' + $Frontend + '"'
$Shortcut.WorkingDirectory = $Frontend
$Shortcut.IconLocation = $Icon + ',0'
$Shortcut.Description = '打开 agent-alpha 桌面应用'
$Shortcut.Save()
Write-Host "桌面快捷方式已创建：$ShortcutPath"

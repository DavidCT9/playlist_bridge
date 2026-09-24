# Adds PlaylistBridge to your Windows Startup folder so it launches
# (minimized to the tray) whenever you log in.
#
# Run this from PowerShell, from inside the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart_windows.ps1

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { $pythonw = (Get-Command python.exe).Source }

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "PlaylistBridge.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$projectDir\main.py`""
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "PlaylistBridge"
$shortcut.Save()

Write-Host "Installed: $shortcutPath"
Write-Host "Remove it any time by deleting that file, or from Task Manager > Startup."

<#
==============================================================================
 Windows Client Post-Format Quick Restore Script
 Maps network drives & restores background PC Agent for TX3 Companion App
 Run: powershell -ExecutionPolicy Bypass -File .\restore_pc.ps1
==============================================================================
#>

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TX3 Mini Client - Post-Format Instant Restore" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$tx3Host = "192.168.100.232"
$smbShare = "\\$tx3Host\TX3-Storage"
$user = "umarosli"
$pass = "umar24434"

# 1. Test Network Connectivity to TX3
Write-Host "[1/4] Checking connection to TX3 Mini ($tx3Host)..." -ForegroundColor Yellow
if (-not (Test-Connection -ComputerName $tx3Host -Count 1 -Quiet)) {
    Write-Warning "Cannot ping $tx3Host. Ensure TX3 is powered on and connected to LAN."
} else {
    Write-Host "  [OK] TX3 Mini is reachable." -ForegroundColor Green
}

# 2. Map Network Storage Drives
Write-Host "[2/4] Mapping Network Drives (Z: and E:)..." -ForegroundColor Yellow

# Disconnect existing mapped drives if needed
net use Z: /delete /y 2>$null | Out-Null
net use E: /delete /y 2>$null | Out-Null

# Map Z: to full TX3-Storage
net use Z: "$smbShare" /user:$user $pass /persistent:yes
Write-Host "  [OK] Drive Z: -> $smbShare" -ForegroundColor Green

# Map E: to 3TB-ext (Main workspace drive)
net use E: "$smbShare\3TB-ext" /user:$user $pass /persistent:yes
Write-Host "  [OK] Drive E: -> $smbShare\3TB-ext (Projects Root)" -ForegroundColor Green

# 3. Restore Local PC Agent
Write-Host "[3/4] Installing TX3 PC Agent to C:\Users\$env:USERNAME\.tx3-agent..." -ForegroundColor Yellow
$agentDir = "$env:USERPROFILE\.tx3-agent"
New-Item -ItemType Directory -Path $agentDir -Force | Out-Null

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item "$scriptDir\pc_agent\*" $agentDir -Force

# 4. Install Windows Startup Launcher
Write-Host "[4/4] Setting up Windows Startup shortcut..." -ForegroundColor Yellow
$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder "RemoteShutdown.lnk"

$wshShell = New-Object -ComObject WScript.Shell
$shortcut = $wshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$agentDir\launch.vbs`""
$shortcut.Description = "TX3 Companion PC Background Agent"
$shortcut.Save()

# Launch Agent silently right now
wscript.exe "$agentDir\launch.vbs"
Write-Host "  [OK] PC Agent started in background." -ForegroundColor Green

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  Restore Complete! PC is now paired with TX3 Mini." -ForegroundColor Green
Write-Host "  - Workspace: E:\Projects is ready." -ForegroundColor Green
Write-Host "  - Companion App: Remote Sleep, Shutdown & WOL active." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

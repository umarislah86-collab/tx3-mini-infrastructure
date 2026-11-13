<#
==============================================================================
 Windows Client Post-Format Quick Restore Script
 Maps network drives & restores background PC Agent for TX3 Companion App
 Features:
   - Smart Hybrid Drive Auto-Switch (Home LAN SMB <--> Cloudflare WebDAV)
   - Background Agent for Remote Shutdown / Sleep via Companion App
 Run: powershell -ExecutionPolicy Bypass -File .\restore_pc.ps1
==============================================================================
#>

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TX3 Mini Client - Post-Format Instant Restore" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$LanIp   = "192.168.100.232"
$LanSmb  = "\\$LanIp\TX3-Storage"
$WanHost = "dav.umiaq.top"
$WanUrl  = "https://$WanHost"
$user    = "umarosli"
$pass    = "umar24434"

# 1. Register Credentials
Write-Host "[1/4] Storing Windows Credentials..." -ForegroundColor Yellow
cmdkey /add:$WanHost /user:$user /pass:$pass | Out-Null
cmdkey /add:$LanIp /user:$user /pass:$pass | Out-Null
Write-Host "  [OK] Credentials saved for $LanIp and $WanHost." -ForegroundColor Green

# 2. Map Initial Drives (Probe LAN first, fallback to Cloudflare WebDAV)
Write-Host "[2/4] Detecting Network & Mapping Drives (Z: and E:)..." -ForegroundColor Yellow
net use Z: /delete /y 2>$null | Out-Null
net use E: /delete /y 2>$null | Out-Null

$isLan = $false
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($LanIp, 445, $null, $null)
    if ($iar.AsyncWaitHandle.WaitOne(1200, $false)) {
        $client.EndConnect($iar)
        $isLan = $true
    }
    $client.Close()
} catch {}

if ($isLan) {
    Write-Host "  -> Home LAN Detected! Mapping Gigabit SMB..." -ForegroundColor Cyan
    net use Z: "$LanSmb" /user:$user $pass /persistent:yes | Out-Null
    net use E: "$LanSmb\3TB-ext" /user:$user $pass /persistent:yes | Out-Null
    Write-Host "  [OK] Drive Z: -> $LanSmb (TX3-Storage)" -ForegroundColor Green
    Write-Host "  [OK] Drive E: -> $LanSmb\3TB-ext (Projects Root)" -ForegroundColor Green
} else {
    Write-Host "  -> Outside Home! Mapping Cloudflare WebDAV Tunnel..." -ForegroundColor Yellow
    net use Z: "$WanUrl" /user:$user $pass /persistent:yes | Out-Null
    net use E: "$WanUrl/3TB-ext" /user:$user $pass /persistent:yes | Out-Null
    Write-Host "  [OK] Drive Z: -> $WanUrl (WebDAV Cloud)" -ForegroundColor Green
    Write-Host "  [OK] Drive E: -> $WanUrl/3TB-ext (Projects Root Cloud)" -ForegroundColor Green
}

# 3. Restore Local PC Agent
Write-Host "[3/4] Installing TX3 PC Agent to C:\Users\$env:USERNAME\.tx3-agent..." -ForegroundColor Yellow
$agentDir = "$env:USERPROFILE\.tx3-agent"
New-Item -ItemType Directory -Path $agentDir -Force | Out-Null

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item "$scriptDir\pc_agent\*" $agentDir -Force
Write-Host "  [OK] PC Agent scripts copied to $agentDir." -ForegroundColor Green

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

# Launch Agent silently
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $agentDir\pc_agent.ps1"
} | Out-Null
Write-Host "  [OK] PC Agent running silently in background." -ForegroundColor Green

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  Restore Complete! PC is paired with TX3 Mini." -ForegroundColor Green
Write-Host "  - Smart Auto-Switch: Active (Home LAN Gigabit <-> Cloudflare WAN)" -ForegroundColor Green
Write-Host "  - Remote Companion: Sleep, Shutdown & WOL active everywhere." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

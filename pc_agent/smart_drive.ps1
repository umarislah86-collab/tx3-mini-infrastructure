<#
==============================================================================
  TX3 Mini Smart Hybrid Drive Auto-Switch (LAN SMB <--> WAN WebDAV Tunnel)
  - Home WiFi / LAN:   Maps Z: and E: to SMB Gigabit LAN (192.168.100.232)
  - Outside / Internet: Maps Z: and E: to Cloudflare WebDAV (dav.umiaq.top)
==============================================================================
#>
param (
    [switch]$Once,
    [int]$IntervalSec = 20
)

$LanIp   = "192.168.100.232"
$LanSmb  = "\\$LanIp\TX3-Storage"
$WanHost = "dav.umiaq.top"
$WanUrl  = "https://$WanHost"
$User    = "umarosli"
$Pass    = "umar24434"

function Test-PortOpen ($hostOrIp, $port, $timeoutMs = 1200) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($hostOrIp, $port, $null, $null)
        $wait = $iar.AsyncWaitHandle.WaitOne($timeoutMs, $false)
        if (-not $wait) {
            $client.Close()
            return $false
        }
        $client.EndConnect($iar)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Ensure-Credentials {
    try {
        cmdkey /add:$WanHost /user:$User /pass:$Pass | Out-Null
        cmdkey /add:$LanIp /user:$User /pass:$Pass | Out-Null
    } catch {}
}

function Sync-Drives {
    Ensure-Credentials

    $mapped = @{}
    Get-CimInstance Win32_MappedLogicalDisk -ErrorAction SilentlyContinue | ForEach-Object {
        $mapped[$_.DeviceID] = $_.ProviderName
    }

    $isLanAvailable = Test-PortOpen $LanIp 445 1200

    if ($isLanAvailable) {
        # ---------------- TARGET: LAN SMB ----------------
        $zTarget = $LanSmb
        $eTarget = "$LanSmb\3TB-ext"
        $currentZ = $mapped["Z:"]

        if ($currentZ -notlike "*$LanIp*") {
            Write-Host "[Smart-Drive] Switching to Home LAN SMB (Gigabit)..." -ForegroundColor Cyan
            net use Z: /delete /y 2>$null | Out-Null
            net use E: /delete /y 2>$null | Out-Null

            net use Z: $zTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null
            net use E: $eTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null

            $regZ = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\##$LanIp#TX3-Storage"
            if (Test-Path $regZ) { Set-ItemProperty -Path $regZ -Name "_LabelFromDesktop" -Value "TX3 Storage (Home LAN)" -ErrorAction SilentlyContinue }
            Write-Host "[Smart-Drive] [OK] Connected to Home LAN (Z: and E:)" -ForegroundColor Green
        } elseif ($Once) {
            Write-Host "[Smart-Drive] [OK] Already connected to Home LAN SMB ($LanIp) at Gigabit speed." -ForegroundColor Green
        }
    } else {
        # ---------------- TARGET: WAN WebDAV Cloudflare Tunnel ----------------
        $isWanAvailable = Test-PortOpen $WanHost 443 2000
        if ($isWanAvailable) {
            $zTarget = $WanUrl
            $eTarget = "$WanUrl/3TB-ext"
            $currentZ = $mapped["Z:"]

            if ($currentZ -notlike "*$WanHost*") {
                Write-Host "[Smart-Drive] Outside Home! Switching to Cloudflare WebDAV Tunnel..." -ForegroundColor Yellow
                net use Z: /delete /y 2>$null | Out-Null
                net use E: /delete /y 2>$null | Out-Null

                net use Z: $zTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null
                net use E: $eTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null

                $regZ = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\##$WanHost@SSL#DavWWWRoot"
                if (Test-Path $regZ) { Set-ItemProperty -Path $regZ -Name "_LabelFromDesktop" -Value "TX3 Storage (Cloud WAN)" -ErrorAction SilentlyContinue }
                Write-Host "[Smart-Drive] [OK] Connected to Cloudflare Tunnel (Z: and E:)" -ForegroundColor Green
            }
        }
    }
}

if ($Once) {
    Sync-Drives
} else {
    while ($true) {
        Sync-Drives
        Start-Sleep -Seconds $IntervalSec
    }
}

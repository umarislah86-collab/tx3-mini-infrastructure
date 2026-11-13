$lanServer = "http://192.168.100.232:3030"
$wanServer = "https://vault.umiaq.top"
$compName = $env:COMPUTERNAME

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
        $zTarget = $LanSmb
        $eTarget = "$LanSmb\3TB-ext"
        $currentZ = $mapped["Z:"]

        if ($currentZ -notlike "*$LanIp*") {
            net use Z: /delete /y 2>$null | Out-Null
            net use E: /delete /y 2>$null | Out-Null
            net use Z: $zTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null
            net use E: $eTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null

            $regZ = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\##$LanIp#TX3-Storage"
            if (Test-Path $regZ) { Set-ItemProperty -Path $regZ -Name "_LabelFromDesktop" -Value "TX3 Storage (Home LAN)" -ErrorAction SilentlyContinue }
        }
    } else {
        $isWanAvailable = Test-PortOpen $WanHost 443 2000
        if ($isWanAvailable) {
            $zTarget = $WanUrl
            $eTarget = "$WanUrl/3TB-ext"
            $currentZ = $mapped["Z:"]

            if ($currentZ -notlike "*$WanHost*") {
                net use Z: /delete /y 2>$null | Out-Null
                net use E: /delete /y 2>$null | Out-Null
                net use Z: $zTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null
                net use E: $eTarget $Pass /user:$User /persistent:yes 2>$null | Out-Null

                $regZ = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\##$WanHost@SSL#DavWWWRoot"
                if (Test-Path $regZ) { Set-ItemProperty -Path $regZ -Name "_LabelFromDesktop" -Value "TX3 Storage (Cloud WAN)" -ErrorAction SilentlyContinue }
            }
        }
    }
}

# Initial drive sync on agent startup
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] PC Agent Started. CompName: $compName" | Out-File "$PSScriptRoot\agent.log" -Append -Encoding utf8
Sync-Drives

$tick = 0
while ($true) {
    # 1. Poll Companion Remote Shutdown/Sleep (try LAN first, fallback to WAN Cloudflare Tunnel)
    $activeServer = if (Test-PortOpen $LanIp 3030 800) { $lanServer } else { $wanServer }
    try {
        $url = "$activeServer/api/pc-agent?name=$compName"
        $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 3 -ErrorAction Stop

        if ($resp.action -eq "shutdown") {
            Start-Process "shutdown.exe" -ArgumentList "/s /t 5 /c `"Remotely triggered from Phone/TX3 Mini`"" -NoNewWindow
            break
        }
        elseif ($resp.action -eq "sleep") {
            Add-Type -Assembly System.Windows.Forms
            [System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false)
        }
    } catch {
        # Offline or transient network issue, safely ignore
    }

    # 2. Check and maintain Smart Drive mapping every ~20 seconds
    $tick++
    if ($tick -ge 7) {
        $tick = 0
        Sync-Drives
    }

    Start-Sleep -Seconds 3
}

$serverUrl = "http://192.168.100.232:3030"
$compName = $env:COMPUTERNAME

while ($true) {
    try {
        $url = "$serverUrl/api/pc-agent?name=$compName"
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
        # Server temporarily offline or restarting, safely ignore
    }

    Start-Sleep -Seconds 3
}

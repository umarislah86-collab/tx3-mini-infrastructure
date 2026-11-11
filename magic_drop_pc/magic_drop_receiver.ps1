<#
    TX3 Magic Drop Receiver (Native Windows 11 Toast with Thumbnail)
    Listens for drops from pb.umiaq.top / local TX3 PocketBase
    Automatically downloads files to Desktop\Drop and copies to Windows Clipboard
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Load WinRT Toast APIs
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$DropFolder = "C:\Users\umarosli\Desktop\Drop"
if (!(Test-Path $DropFolder)) {
    New-Item -ItemType Directory -Path $DropFolder -Force | Out-Null
}

# Tray Icon Setup
$NotifyIcon = New-Object System.Windows.Forms.NotifyIcon
$NotifyIcon.Icon = [System.Drawing.SystemIcons]::Information
$NotifyIcon.Text = "⚡ TX3 Magic Drop"
$NotifyIcon.Visible = $true

# Context Menu
$ContextMenu = New-Object System.Windows.Forms.ContextMenuStrip

$itemFolder = $ContextMenu.Items.Add("📁 Buka Folder Drop")
$itemFolder.Font = New-Object System.Drawing.Font($itemFolder.Font, [System.Drawing.FontStyle]::Bold)
$itemFolder.add_Click({
    Invoke-Item $DropFolder
})

$itemStatus = $ContextMenu.Items.Add("⚡ Status: Sambung...")
$itemStatus.Enabled = $false

$ContextMenu.Items.Add("-") | Out-Null

$itemExit = $ContextMenu.Items.Add("❌ Exit Magic Drop")
$itemExit.add_Click({
    $NotifyIcon.Visible = $false
    $NotifyIcon.Dispose()
    Stop-Process -Id $PID -Force
})

$NotifyIcon.ContextMenuStrip = $ContextMenu

$NotifyIcon.add_DoubleClick({
    Invoke-Item $DropFolder
})

# Native Windows 11 Toast Notification with Thumbnail
function Show-ToastNotification($title, $body, $imagePath = $null) {
    try {
        $imgTag = ""
        if ($imagePath -and (Test-Path $imagePath)) {
            $imgTag = "<image placement=`"appLogoOverride`" src=`"$imagePath`" />"
        }
        $xmlText = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>$([System.Security.SecurityElement]::Escape($title))</text>
            <text>$([System.Security.SecurityElement]::Escape($body))</text>
            $imgTag
        </binding>
    </visual>
    <audio src="ms-winsoundevent:Notification.Default" />
</toast>
"@
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($xmlText)
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe").Show($toast)
    } catch {
        try { [System.Media.SystemSounds]::Asterisk.Play() } catch {}
    }
}

# Determine API URL
function Get-PbBaseUrl {
    try {
        $test = Invoke-RestMethod -Uri "http://192.168.100.232:8090/api/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
        return "http://192.168.100.232:8090"
    } catch {
        return "https://pb.umiaq.top"
    }
}

$baseUrl = Get-PbBaseUrl
$itemStatus.Text = "⚡ Server: $baseUrl"
Show-ToastNotification "⚡ Magic Drop Aktif" "Sedia di background! Snap screenshot kat phone bila-bila masa."

$lastProcessedId = ""
$webClient = New-Object System.Net.WebClient

# Polling Loop with DoEvents
while ($true) {
    [System.Windows.Forms.Application]::DoEvents()

    try {
        $resp = Invoke-RestMethod -Uri "$baseUrl/api/collections/drops/records?sort=-@rowid&perPage=1" -Method Get -TimeoutSec 3 -ErrorAction Stop
        if ($resp.items.Count -gt 0) {
            $record = $resp.items[0]
            if ($record.id -ne $lastProcessedId) {
                # Remember ID on first run, but if user drops a new record:
                if ($lastProcessedId -eq "") {
                    $lastProcessedId = $record.id
                } else {
                    $lastProcessedId = $record.id

                    $downloadedFiles = New-Object System.Collections.Specialized.StringCollection
                    $imageFiles = @()

                    # Process Files
                    if ($record.files -and $record.files.Count -gt 0) {
                        foreach ($fileName in $record.files) {
                            $fileUrl = "$baseUrl/api/files/drops/$($record.id)/$fileName"
                            $destFile = Join-Path $DropFolder $fileName
                            $webClient.DownloadFile($fileUrl, $destFile)
                            $downloadedFiles.Add($destFile)

                            $ext = [System.IO.Path]::GetExtension($destFile).ToLower()
                            if ($ext -in @(".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")) {
                                $imageFiles += $destFile
                            }
                        }

                        # Set Clipboard DataObject
                        $dataObj = New-Object System.Windows.Forms.DataObject
                        $dataObj.SetFileDropList($downloadedFiles)

                        # If image exists, also load bitmap into clipboard
                        if ($imageFiles.Count -gt 0) {
                            try {
                                $fs = [System.IO.File]::OpenRead($imageFiles[0])
                                $img = [System.Drawing.Image]::FromStream($fs)
                                $dataObj.SetImage($img)
                                $fs.Close()
                            } catch {}
                        }

                        [System.Windows.Forms.Clipboard]::SetDataObject($dataObj, $true) | Out-Null

                        $count = $downloadedFiles.Count
                        $firstImg = if ($imageFiles.Count -gt 0) { $imageFiles[0] } else { $null }

                        if ($count -eq 1) {
                            Show-ToastNotification "⚡ Magic Drop: 1 Fail Diterima!" "Disalin ke Clipboard (Ctrl+V) & Desktop\Drop" $firstImg
                        } else {
                            Show-ToastNotification "⚡ Magic Drop: $count Fail Diterima!" "Semua $count fail ada dalam Clipboard (Ctrl+V)" $firstImg
                        }
                    }
                    # Process Text only (if no files)
                    elseif ($record.text) {
                        [System.Windows.Forms.Clipboard]::SetText($record.text)
                        Show-ToastNotification "📋 Magic Drop: Teks Diterima!" "$($record.text)"
                    }
                }
            }
        }
    } catch {
        # Ignore transient timeouts
    }

    for ($i = 0; $i -lt 10; $i++) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
    }
}

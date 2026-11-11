Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -WindowStyle Hidden -Sta -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\umarosli\MagicDrop\magic_drop_receiver.ps1""", 0, False

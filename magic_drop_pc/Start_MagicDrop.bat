@echo off
title TX3 Magic Drop Receiver
cd /d "C:\Users\umarosli\MagicDrop"
powershell.exe -Sta -NoProfile -ExecutionPolicy Bypass -File "C:\Users\umarosli\MagicDrop\magic_drop_receiver.ps1"
pause

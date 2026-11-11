#!/usr/bin/env python3
"""
TX3 Mini Front Panel Infinite Marquee Daemon
Scrolls TX3 System Stats followed by Family Dedication:
"Abah, Umi, Aalaa', 'Aafiyah, 'Aaliyah.. <3"
"""

import time
import os
import sys
import shutil
import urllib.request
import json

DEV_TEXT = "/sys/devices/platform/spi/spi_master/spi0/spi0.0/display_text"
DEV_COLON = "/sys/class/leds/:colon/brightness"
DEV_LAN = "/sys/class/leds/:lan/brightness"
DEV_USB = "/sys/class/leds/:usb/brightness"
DEV_PLAY = "/sys/class/leds/:play/brightness"
QUEUE_FILE = "/run/display_msg"

def set_led(path, val):
    try:
        with open(path, "w") as f:
            f.write(str(val))
    except Exception:
        pass

def write_text(txt):
    try:
        with open(DEV_TEXT, "w") as f:
            f.write(txt[:4].ljust(4))
    except Exception:
        pass

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            t = int(f.read().strip()) // 1000
            return f"{t}C"
    except Exception:
        return "50C"

def get_ram_usage():
    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.readlines()
        mem = {}
        for l in lines:
            parts = l.split(":")
            if len(parts) == 2:
                mem[parts[0].strip()] = int(parts[1].split()[0])
        total = mem.get("MemTotal", 1)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        used_pct = int(((total - avail) / total) * 100)
        return f"{used_pct}%"
    except Exception:
        return "25%"

def get_pc_status():
    try:
        req = urllib.request.Request("http://127.0.0.1:3030/api/pc-status", headers={"User-Agent": "tx3-display"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("online"):
                return "PC ON"
            return "PC OFF"
    except Exception:
        return "PC --"

def get_disk_status():
    if os.path.exists("/shares/3TB-ext"):
        return "3TB ONLINE"
    return "STORAGE OK"

def scroll_string(full_text, speed=0.23, pause_end=1.2):
    # Pad so text enters smoothly from right and exits cleanly
    padded = "    " + full_text + "    "
    total_steps = len(padded) - 3

    for i in range(total_steps):
        # Check if user sent a priority override message
        if os.path.exists(QUEUE_FILE):
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as q:
                    prio_msg = q.read().strip()
                os.remove(QUEUE_FILE)
                if prio_msg:
                    # Interrupt and scroll priority message immediately
                    scroll_string(f"*** {prio_msg} ***", speed=0.20, pause_end=0.8)
            except Exception:
                try:
                    os.remove(QUEUE_FILE)
                except Exception:
                    pass

        window = padded[i:i+4]
        write_text(window)
        time.sleep(speed)

    if pause_end > 0:
        time.sleep(pause_end)

def main():
    # Turn off colon (no clock needed), ensure LAN & USB indicators are ON
    set_led(DEV_COLON, 0)
    set_led(DEV_LAN, 1)
    set_led(DEV_USB, 1)

    while True:
        # 1. Fetch Live Stats
        temp = get_cpu_temp()
        ram = get_ram_usage()
        pc = get_pc_status()
        disk = get_disk_status()

        # 2. Build the complete marquee loop string:
        # Stats section followed by family dedication
        stats_part = f"TX3 MINI -- CPU {temp} -- RAM {ram} -- {pc} -- {disk}"
        family_part = "Abah, Umi, Aalaa', 'Aafiyah, 'Aaliyah.. <3"

        full_marquee = f"{stats_part} -- {family_part}"

        # 3. Scroll entire marquee seamlessly
        scroll_string(full_marquee, speed=0.23, pause_end=1.5)

if __name__ == "__main__":
    main()

#!/bin/bash
# ==============================================================================
# TX3 Mini Home Server - Full Infrastructure Restore Script
# Tested on Armbian Linux (Kernel 6.12.x / Debian Bookworm on Amlogic S905W)
# ==============================================================================

set -e

if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run as root: sudo ./restore_tx3.sh"
  exit 1
fi

echo "[+] Starting TX3 Mini Infrastructure Restore..."
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Install Base Packages
echo "[1/7] Installing essential packages..."
apt-get update -y
apt-get install -y ntfs-3g exfat-fuse python3 python3-pip python3-pil samba udev sqlite3 curl wget jq git

# 2. Setup System User
echo "[2/7] Ensuring system user 'umarosli' exists..."
if ! id -u umarosli >/dev/null 2>&1; then
    useradd -m -s /bin/bash umarosli
    echo "umarosli:umar24434" | chpasswd
fi
usermod -aG sudo,disk umarosli

# 3. Create Storage Mount Dirs
echo "[3/7] Setting up /shares and mount directories..."
mkdir -p /shares/3TB-ext /shares/500GB-ext /shares/Pendrive-128GB /shares/SD-Card-64GB
chown -R umarosli:umarosli /shares
chmod -R 777 /shares

# 4. Restore USB Automount Scripts & Udev Rules
echo "[4/7] Restoring USB automount rules and scripts..."
cp "$BASE_DIR/scripts/tx3-usb-mount.sh" /usr/local/bin/tx3-usb-mount.sh
chmod +x /usr/local/bin/tx3-usb-mount.sh

cp "$BASE_DIR/udev/99-tx3-usb-mount.rules" /etc/udev/rules.d/99-tx3-usb-mount.rules
udevadm control --reload-rules

# 5. Restore /opt/tx3-vault (Command Center & Photos Backend)
echo "[5/7] Deploying TX3 Vault backend to /opt/tx3-vault..."
mkdir -p /opt/tx3-vault/photos_cache/thumbs
cp "$BASE_DIR/opt_tx3_vault/server.py" /opt/tx3-vault/server.py
cp "$BASE_DIR/opt_tx3_vault/photos.html" /opt/tx3-vault/photos.html
if [ -d "$BASE_DIR/opt_tx3_vault/dist" ]; then
    cp -r "$BASE_DIR/opt_tx3_vault/dist" /opt/tx3-vault/
fi
chmod +x /opt/tx3-vault/server.py

# 6. Restore PocketBase
echo "[6/7] Restoring PocketBase..."
mkdir -p /opt/pocketbase/pb_data /opt/pocketbase/pb_public
if [ ! -f /opt/pocketbase/pocketbase ]; then
    echo "    Downloading PocketBase for ARM64..."
    wget -q https://github.com/pocketbase/pocketbase/releases/download/v0.25.9/pocketbase_0.25.9_linux_arm64.zip -O /tmp/pb.zip
    unzip -q -o /tmp/pb.zip -d /opt/pocketbase/
    rm -f /tmp/pb.zip
    chmod +x /opt/pocketbase/pocketbase
fi
if [ -d "$BASE_DIR/apps/pocketboard" ]; then
    cp -r "$BASE_DIR/apps/pocketboard/"* /opt/pocketbase/pb_public/
fi

# 7. Restore Systemd Services & Samba Config
echo "[7/7] Restoring services and Samba config..."
if [ -f "$BASE_DIR/samba/smb.conf" ]; then
    cp "$BASE_DIR/samba/smb.conf" /etc/samba/smb.conf
    (echo "umar24434"; echo "umar24434") | smbpasswd -s -a umarosli
fi

cp "$BASE_DIR/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload

SERVICES=("dota-vault" "pocketbase" "filebrowser" "smbd")
for s in "${SERVICES[@]}"; do
    if systemctl list-unit-files | grep -q "$s.service"; then
        systemctl enable "$s" || true
        systemctl restart "$s" || true
        echo "    Service $s -> $(systemctl is-active $s || echo 'failed')"
    fi
done

echo "=========================================================="
echo " [+] TX3 Mini Infrastructure Restore Complete!"
echo "     Command Center Backend: http://localhost:3030"
echo "     PocketBase:             http://localhost:8090/_/"
echo "     FileBrowser:            http://localhost:8080"
echo "     Samba Share:            smb://192.168.100.232/TX3-Storage"
echo "=========================================================="

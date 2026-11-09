#!/bin/bash
ACTION=$1
DEV=$2

# Only handle sd[a-z][0-9]* partitions
if [[ ! $DEV =~ ^sd[a-z][0-9]+$ ]]; then
    exit 0
fi

DEVICE_PATH="/dev/$DEV"

if [ "$ACTION" = "add" ]; then
    # 1. Try mounting via fstab entries first
    mount -a 2>/dev/null

    # If already mounted, log and exit
    if grep -q "$DEVICE_PATH" /proc/mounts; then
        echo "$(date): Mounted $DEVICE_PATH via fstab" >> /var/log/tx3-usb-mount.log
        systemctl reload smbd 2>/dev/null || systemctl restart smbd 2>/dev/null
        exit 0
    fi

    # Skip internal/known permanent mounts
    UUID=$(blkid -o value -s UUID "$DEVICE_PATH" 2>/dev/null)
    if [[ "$UUID" == "84dddb92-a52d-4b41-add1-db2ecdc7bd14" || "$UUID" == "F71A-5FBC" ]]; then
        exit 0
    fi

    FSTYPE=$(blkid -o value -s TYPE "$DEVICE_PATH" 2>/dev/null)
    if [ -z "$FSTYPE" ]; then
        exit 0
    fi

    LABEL=$(blkid -o value -s LABEL "$DEVICE_PATH" 2>/dev/null)
    if [ -z "$LABEL" ]; then
        LABEL="HDD-$DEV"
    else
        LABEL=$(echo "$LABEL" | tr ' ' '-' | tr -cd 'A-Za-z0-9_-')
    fi

    MOUNT_DIR="/shares/$LABEL"
    mkdir -p "$MOUNT_DIR"

    case "$FSTYPE" in
        ntfs)
            ntfs-3g -o rw,uid=1000,gid=1000,umask=000,big_writes "$DEVICE_PATH" "$MOUNT_DIR"
            ;;
        vfat|fat)
            mount -t vfat -o rw,uid=1000,gid=1000,umask=000,utf8 "$DEVICE_PATH" "$MOUNT_DIR"
            ;;
        exfat)
            mount -t exfat -o rw,uid=1000,gid=1000,umask=000 "$DEVICE_PATH" "$MOUNT_DIR"
            ;;
        ext4|ext3|ext2)
            mount "$DEVICE_PATH" "$MOUNT_DIR"
            chown -R umarosli:umarosli "$MOUNT_DIR" 2>/dev/null
            ;;
        *)
            mount "$DEVICE_PATH" "$MOUNT_DIR"
            ;;
    esac

    echo "$(date): Mounted $DEVICE_PATH ($FSTYPE) to $MOUNT_DIR" >> /var/log/tx3-usb-mount.log
    systemctl reload smbd 2>/dev/null || systemctl restart smbd 2>/dev/null

elif [ "$ACTION" = "remove" ]; then
    grep "$DEVICE_PATH" /proc/mounts | while read -r line; do
        MNT=$(echo "$line" | awk '{print $2}')
        if [[ "$MNT" == /shares/* && "$MNT" != "/shares/Pendrive-128GB" && "$MNT" != "/shares/SD-Card-64GB" ]]; then
            umount -l "$MNT"
            rmdir "$MNT" 2>/dev/null
            echo "$(date): Unmounted $MNT for $DEVICE_PATH" >> /var/log/tx3-usb-mount.log
        fi
    done
fi

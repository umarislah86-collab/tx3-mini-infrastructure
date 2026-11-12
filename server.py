import sharing
import io
import os
import sys
import re
import json
import time
import socket
import shutil
import hashlib
import mimetypes
import subprocess
import urllib.parse
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from PIL import Image, ImageOps, ExifTags

try:
    import cinema
except Exception as e:
    cinema = None
    print("Cinema module load error:", e)

PC_MACS = [
    'BC:BF:2E:14:6E:8B',  # Realtek PCIe GbE (Ethernet)
    'CC:C5:30:0A:E4:6C',  # Realtek 8852BE (Wi-Fi)
]

# PC State for Remote Control
pc_state = {
    "last_seen": 0,
    "pending_action": None,
    "computer_name": "DESKTOP-S700VJ0"
}

def send_wol():
    for mac in PC_MACS:
        clean = mac.replace(':', '').replace('-', '')
        packet = bytes.fromhex('FF' * 6 + clean * 16)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                for port in [7, 9]:
                    for bcast in ['192.168.100.255', '255.255.255.255']:
                        try:
                            s.sendto(packet, (bcast, port))
                        except Exception:
                            pass
        except Exception as e:
            print("WOL error:", e)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

PORT = int(os.environ.get('PORT', 3030))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_dota_dirs():
    candidates = [
        '/shares/3TB-ext/Vids/Dota 2',
        '/shares/3TB-ext/Vids/Dota 2/Dota2 overwolf',
        '/shares/500GB-ext/Dota2 overwolf',
        '/shares/3TB-ext/Outplayed/Dota 2',
        '/shares/Pendrive-128GB/Dota 2'
    ]
    return [c for c in candidates if os.path.exists(c) and os.path.isdir(c)]

def get_primary_dota_dir():
    dirs = get_dota_dirs()
    return dirs[0] if dirs else '/shares/3TB-ext/Vids/Dota 2'

def get_notes_file():
    dota_3tb = '/shares/3TB-ext/Vids/Dota 2/_notes.json'
    if os.path.exists(dota_3tb):
        return dota_3tb
    for d in get_dota_dirs():
        nf = os.path.join(d, '_notes.json')
        if os.path.exists(nf):
            return nf
    return os.path.join(BASE_DIR, '_notes.json')

def get_cache_file():
    dota_3tb = '/shares/3TB-ext/Vids/Dota 2/_sessions_cache.json'
    if os.path.exists(dota_3tb):
        return dota_3tb
    for d in get_dota_dirs():
        cf = os.path.join(d, '_sessions_cache.json')
        if os.path.exists(cf):
            return cf
    return os.path.join(BASE_DIR, '_sessions_cache.json')

def get_settings_file():
    dota_3tb = '/shares/3TB-ext/Vids/Dota 2/_settings.json'
    if os.path.exists(dota_3tb):
        return dota_3tb
    for d in get_dota_dirs():
        sf = os.path.join(d, '_settings.json')
        if os.path.exists(sf):
            return sf
    return os.path.join(BASE_DIR, '_settings.json')

def get_thumb_dir():
    dota_3tb = '/shares/3TB-ext/Vids/Dota 2/_thumbnails'
    if os.path.exists(dota_3tb):
        return dota_3tb
    for d in get_dota_dirs():
        td = os.path.join(d, '_thumbnails')
        if os.path.exists(td):
            return td
    return os.path.join(BASE_DIR, '_thumbnails')

DOTA_DIR = get_primary_dota_dir()
NOTES_FILE = get_notes_file()
CACHE_FILE = get_cache_file()
SETTINGS_FILE = get_settings_file()
THUMB_DIR = get_thumb_dir()
DIST_DIR = os.path.join(BASE_DIR, 'dist')

# Photos Vault Paths
PHOTOS_DIR = '/shares/3TB-ext/Pictures' if os.path.exists('/shares/3TB-ext/Pictures') else BASE_DIR
PHOTO_CACHE_DIR = os.path.join(BASE_DIR, 'photos_cache')
PHOTO_THUMB_DIR = os.path.join(PHOTO_CACHE_DIR, 'thumbs')
PHOTO_CATALOG_FILE = os.path.join(PHOTO_CACHE_DIR, 'catalog.json')
PHOTOS_HTML_FILE = os.path.join(BASE_DIR, 'photos.html')

# Multi-Storage Drive Definitions
def get_available_storages():
    storages = []
    if os.path.exists('/shares'):
        try:
            root_usage = shutil.disk_usage('/')
        except Exception:
            root_usage = None

        for d in sorted(os.listdir('/shares')):
            if d.startswith('.'):
                continue
            p = os.path.join('/shares', d)
            if not os.path.isdir(p):
                continue
            try:
                usage = shutil.disk_usage(p)
                # Ignore empty unmounted mountpoints on root eMMC
                if root_usage and usage.total == root_usage.total and usage.free == root_usage.free:
                    try:
                        if len(os.listdir(p)) == 0:
                            continue
                    except Exception:
                        continue

                icon = '💽'
                d_lower = d.lower()
                if 'sd' in d_lower or 'card' in d_lower:
                    icon = '🗄️'
                elif 'pendrive' in d_lower or 'usb' in d_lower:
                    icon = '💾'

                name = d.replace('_', ' ')
                storages.append({
                    'id': d.lower().replace('-', '_'),
                    'name': name,
                    'icon': icon,
                    'path': p,
                    'total_bytes': usage.total,
                    'free_bytes': usage.free,
                    'used_bytes': usage.used,
                    'free_human': format_file_size(usage.free),
                    'total_human': format_file_size(usage.total)
                })
            except Exception:
                pass
    return storages

DRIVE_DEFAULT_STORAGE = '3tb_ext'

def get_storage_root(storage_id):
    storages = get_available_storages()
    for s in storages:
        if s['id'] == storage_id:
            return s['id'], s['path'], s['name']
    if storages:
        return storages[0]['id'], storages[0]['path'], storages[0]['name']
    return 'pendrive', BASE_DIR, 'Pendrive 128GB'

def resolve_drive_path(rel_path, storage_id=None):
    sid, root, sname = get_storage_root(storage_id)
    clean_rel = (rel_path or '').strip().lstrip('/').replace('\\', '/')
    target = os.path.abspath(os.path.join(root, clean_rel))
    if not target.startswith(os.path.abspath(root)):
        return None, None, sid, root, sname
    return target, clean_rel, sid, root, sname

def format_file_size(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"

def get_file_type_meta(ext):
    ext = (ext or '').lower()
    if ext in ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.ts'):
        return 'video', True
    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'):
        return 'image', True
    if ext in ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'):
        return 'audio', True
    if ext in ('.pdf',):
        return 'pdf', False
    if ext in ('.zip', '.tar', '.gz', '.7z', '.rar'):
        return 'archive', False
    if ext in ('.apk',):
        return 'apk', False
    if ext in ('.txt', '.md', '.json', '.js', '.py', '.html', '.css', '.sh', '.log'):
        return 'code', False
    if ext in ('.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'):
        return 'doc', False
    return 'other', False

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.mkv'}

# In-memory photo lookup map: photo_id -> photo_dict
photos_index = {}
cached_catalog = None

def get_hash(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:12]

def parse_exif(img):
    info = {}
    try:
        exif = img.getexif()
        if not exif:
            return info
        for tag_id, value in exif.items():
            tag = ExifTags.TAGS.get(tag_id, tag_id)
            if tag == 'DateTimeOriginal' or tag == 'DateTime':
                info['datetime'] = str(value)
            elif tag == 'Make':
                info['make'] = str(value).strip()
            elif tag == 'Model':
                info['model'] = str(value).strip()
            elif tag == 'FocalLength':
                try:
                    info['focal_length'] = f"{float(value):.0f}mm"
                except Exception:
                    info['focal_length'] = str(value)
            elif tag == 'FNumber':
                try:
                    info['fnumber'] = f"f/{float(value):.1f}"
                except Exception:
                    info['fnumber'] = str(value)
            elif tag == 'ExposureTime':
                try:
                    v = float(value)
                    if v < 1:
                        info['exposure'] = f"1/{int(round(1/v))}s"
                    else:
                        info['exposure'] = f"{v:.1f}s"
                except Exception:
                    info['exposure'] = str(value)
            elif tag == 'ISOSpeedRatings':
                info['iso'] = f"ISO {value}"
    except Exception:
        pass
    return info

def get_photo_sources():
    """Returns a list of directories to scan for photos across all connected storages."""
    sources = []
    # 1. Main Photos Vault folder on Pendrive
    if os.path.exists(PHOTOS_DIR):
        sources.append({'root': os.path.abspath(PHOTOS_DIR), 'name': 'Pendrive', 'dedicated': True})

    # 2. Iterate through all mounted storages
    for st in get_available_storages():
        s_path = os.path.abspath(st['path'])
        if not os.path.exists(s_path):
            continue

        try:
            entries = os.listdir(s_path)
        except Exception:
            entries = []

        # Check for dedicated photo folders
        found_dedicated = False
        for e in entries:
            if e.lower() in ('photos', 'pictures', 'dcim', 'camera', 'images', 'kamera'):
                cand = os.path.abspath(os.path.join(s_path, e))
                if os.path.isdir(cand):
                    if not any(os.path.samefile(cand, s['root']) for s in sources if os.path.exists(s['root'])):
                        sources.append({'root': cand, 'name': f"{st['name']}/{e}", 'dedicated': True})
                        found_dedicated = True

        # For SD card or removable flash media, also scan root if no dedicated folders were found
        if not found_dedicated and ('sd' in st['id'] or 'card' in st['id'] or 'pendrive' in st['id']):
            if not any(os.path.samefile(s_path, s['root']) for s in sources if os.path.exists(s['root'])):
                sources.append({'root': s_path, 'name': st['name'], 'dedicated': False})

    return sources

def scan_photos(force=False):
    global photos_index, cached_catalog
    os.makedirs(PHOTO_THUMB_DIR, exist_ok=True)

    if not force and cached_catalog and photos_index:
        return cached_catalog

    if not force and os.path.exists(PHOTO_CATALOG_FILE):
        try:
            with open(PHOTO_CATALOG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                photos_index = {p['id']: p for t in data.get('timeline', []) for p in t.get('photos', [])}
                cached_catalog = data
                return data
        except Exception as e:
            print("Failed to read cached photo catalog:", e)

    start_t = time.time()
    photos = []
    albums = set()
    seen_paths = set()

    SKIP_DIRS = {'.cache', 'lost+found', '$recycle.bin', 'system volume information', '.trash', 'node_modules', 'android', 'thumbs', '_thumbnails', 'bin', 'etc', 'usr', 'var'}

    for src in get_photo_sources():
        src_root = src['root']
        st_label = src['name']
        is_dedicated = src['dedicated']

        if not os.path.exists(src_root):
            continue

        for root, dirs, files in os.walk(src_root):
            # Prune hidden or system directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in SKIP_DIRS]

            rel_root = os.path.relpath(root, src_root)
            depth = 0 if rel_root == '.' else len(rel_root.replace('\\', '/').split('/'))

            # For non-dedicated drives, don't crawl deeper than depth 2
            if not is_dedicated and depth > 2:
                dirs[:] = []

            # Determine Album Name
            if is_dedicated:
                album_name = "All" if rel_root == "." else os.path.basename(root)
            else:
                album_name = st_label if rel_root == "." else f"{st_label} - {os.path.basename(root)}"

            if album_name and album_name != "All":
                albums.add(album_name)

            for f in files:
                if f.startswith('.'):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                    continue

                full_path = os.path.abspath(os.path.join(root, f))
                if full_path in seen_paths:
                    continue
                seen_paths.add(full_path)

                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue

                # Filter out heavy non-camera videos (> 350MB or .mkv)
                if ext == '.mkv' or (ext in VIDEO_EXTS and size > 350 * 1024 * 1024):
                    continue

                # Hash calculation: keep legacy hash for PHOTOS_DIR files so cached thumbnails match
                if os.path.exists(PHOTOS_DIR) and full_path.startswith(os.path.abspath(PHOTOS_DIR)):
                    rel_p = os.path.relpath(full_path, PHOTOS_DIR).replace('\\', '/')
                    p_id = get_hash(rel_p)
                else:
                    rel_p = os.path.relpath(full_path, src_root).replace('\\', '/')
                    p_id = get_hash(full_path)

                try:
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    mtime = time.time()

                dt = datetime.fromtimestamp(mtime)
                exif_info = {}
                width, height = 0, 0

                if ext in IMAGE_EXTS:
                    try:
                        with Image.open(full_path) as im:
                            width, height = im.size
                            exif_info = parse_exif(im)
                            if 'datetime' in exif_info:
                                try:
                                    dt = datetime.strptime(exif_info['datetime'], '%Y:%m:%d %H:%M:%S')
                                except Exception:
                                    pass
                    except Exception:
                        pass
                elif ext in VIDEO_EXTS:
                    m = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', f)
                    if m:
                        try:
                            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        except Exception:
                            pass

                month_year = dt.strftime('%B %Y')
                day_str = dt.strftime('%A, %b %d, %Y')
                time_str = dt.strftime('%I:%M %p').lstrip('0')

                item = {
                    'id': p_id,
                    'name': f,
                    'album': album_name if album_name != "All" else "Default",
                    'rel_path': rel_p,
                    'abs_path': full_path,
                    'timestamp': int(dt.timestamp()),
                    'date_str': day_str,
                    'time_str': time_str,
                    'month_year': month_year,
                    'size_mb': round(size / (1024 * 1024), 2),
                    'is_video': ext in VIDEO_EXTS,
                    'width': width,
                    'height': height,
                    'exif': exif_info
                }
                photos.append(item)
                photos_index[p_id] = item

    photos.sort(key=lambda x: x['timestamp'], reverse=True)

    timeline = []
    groups = {}
    for p in photos:
        my = p['month_year']
        if my not in groups:
            groups[my] = []
            timeline.append({'month_year': my, 'photos': groups[my]})
        groups[my].append(p)

    album_list = sorted(list(albums))
    catalog_result = {
        'albums': album_list,
        'total_count': len(photos),
        'timeline': timeline
    }
    cached_catalog = catalog_result

    try:
        with open(PHOTO_CATALOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(catalog_result, f, indent=2)
        print(f"Scanned {len(photos)} photos across {len(album_list)} albums in {time.time()-start_t:.3f}s. Saved to cache.")
    except Exception as e:
        print("Failed to save photos cache:", e)

    return catalog_result

THUMB_SEMAPHORE = threading.Semaphore(2)

def get_or_generate_thumbnail(photo_item):
    p_id = photo_item['id']
    thumb_path = os.path.join(PHOTO_THUMB_DIR, f"{p_id}.jpg")
    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
        return thumb_path

    abs_path = photo_item['abs_path']
    if not os.path.exists(abs_path):
        return None

    # Limit concurrent image decoding to 2 threads to prevent memory spikes / OOM
    with THUMB_SEMAPHORE:
        # Re-check if another thread finished it while waiting
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path

        try:
            if photo_item['is_video']:
                cmd = [
                    'ffmpeg', '-y', '-ss', '00:00:01',
                    '-i', abs_path,
                    '-vframes', '1',
                    '-vf', 'scale=450:450:force_original_aspect_ratio=decrease',
                    '-q:v', '3',
                    thumb_path
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                with Image.open(abs_path) as im:
                    try:
                        im.draft('RGB', (450, 450))
                    except Exception:
                        pass
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((450, 450))
                    if im.mode not in ('RGB', 'L'):
                        im = im.convert('RGB')
                    im.save(thumb_path, 'JPEG', quality=80, optimize=True)

            if os.path.exists(thumb_path):
                return thumb_path
        except Exception as e:
            print(f"Error generating thumbnail for {abs_path}:", e)

        return None

def parse_session_folder(folder_name, full_path):
    m = re.search(r'(\d{2})-(\d{2})-(\d{4})_(\d{2})-(\d{2})', folder_name)
    if m:
        month, day, year, hour, minute = m.groups()
        dt_str = f"{year}-{month}-{day}"
        h_int = int(hour)
        ampm = "AM" if h_int < 12 else "PM"
        h_12 = h_int % 12
        if h_12 == 0: h_12 = 12
        session_label = f"{h_12}:{minute} {ampm}"
        sort_key = f"{year}{month}{day}{hour}{minute}0000"
    else:
        try:
            mtime = os.path.getmtime(full_path)
            dt = datetime.fromtimestamp(mtime)
            dt_str = dt.strftime('%Y-%m-%d')
            session_label = dt.strftime('%I:%M %p').lstrip('0')
            sort_key = dt.strftime('%Y%m%d%H%M%S00')
        except Exception:
            dt_str = "Unknown"
            session_label = folder_name
            sort_key = folder_name

    clip_count = 0
    total_bytes = 0
    try:
        for f in os.listdir(full_path):
            if f.lower().endswith('.mp4'):
                clip_count += 1
                try:
                    total_bytes += os.path.getsize(os.path.join(full_path, f))
                except Exception:
                    pass
    except Exception:
        pass

    return {
        "folder_name": folder_name,
        "folder_path": full_path,
        "date": dt_str,
        "session_label": session_label,
        "clip_count": clip_count,
        "total_mb": round(total_bytes / (1024 * 1024), 1),
        "sort_key": sort_key,
        "thumbnail_path": os.path.join(get_thumb_dir(), f"{folder_name}.jpg")
    }

def get_sessions():
    cached = {}
    cf = get_cache_file()
    if os.path.exists(cf):
        try:
            with open(cf, 'r', encoding='utf-8') as f:
                for s in json.load(f):
                    cached[s.get('folder_name')] = s
        except Exception:
            pass

    updated = False
    current_folders = {}
    thumb_dir = get_thumb_dir()
    for d_dir in get_dota_dirs():
        try:
            for name in os.listdir(d_dir):
                if not name.startswith('Dota 2'):
                    continue
                fp = os.path.join(d_dir, name)
                if os.path.isdir(fp):
                    if name not in current_folders:
                        current_folders[name] = fp
                    if name not in cached:
                        print(f"Auto-detected new Dota 2 session: {name} in {d_dir}")
                        cached[name] = parse_session_folder(name, fp)
                        updated = True
        except Exception:
            pass

    result = []
    for name, s in list(cached.items()):
        if not name.startswith('Dota 2'):
            continue
        if name in current_folders:
            fp = current_folders[name]
            if s.get('folder_path') != fp:
                s['folder_path'] = fp
                updated = True
            # Determine thumbnail
            thumb = os.path.join(thumb_dir, f"{name}.jpg")
            if not os.path.exists(thumb):
                alt_thumb = os.path.join(os.path.dirname(fp), '_thumbnails', f"{name}.jpg")
                if os.path.exists(alt_thumb):
                    thumb = alt_thumb
            s['thumbnail_path'] = thumb
            result.append(s)
        else:
            # Still keep cached sessions if not actively missing
            result.append(s)

    if updated:
        try:
            with open(cf, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
            print("Session cache updated successfully in:", cf)
            emmc_cf = os.path.join(BASE_DIR, '_sessions_cache.json')
            if emmc_cf != cf:
                with open(emmc_cf, 'w', encoding='utf-8') as f2:
                    json.dump(result, f2, indent=2)
        except Exception as e:
            print("Failed to save cache:", e)

    result.sort(key=lambda x: str(x.get('sort_key', '')), reverse=True)
    return result

def get_system_stats():
    # 1. Temperature from thermal_zone0
    temp_c = None
    try:
        if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_c = round(float(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass

    # 2. Uptime from /proc/uptime
    uptime_str = "Unknown"
    uptime_seconds = 0
    try:
        if os.path.exists('/proc/uptime'):
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = int(float(f.read().split()[0]))
                days = uptime_seconds // 86400
                hours = (uptime_seconds % 86400) // 3600
                mins = (uptime_seconds % 3600) // 60
                uptime_str = f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"
    except Exception:
        pass

    # 3. CPU Load Averages
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        load1, load5, load15 = 0.0, 0.0, 0.0

    # 4. RAM Telemetry from /proc/meminfo
    mem = {}
    try:
        if os.path.exists('/proc/meminfo'):
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    parts = line.split(':')
                    if len(parts) == 2:
                        mem[parts[0].strip()] = int(parts[1].strip().split()[0])
    except Exception:
        pass

    total_mb = round(mem.get('MemTotal', 0) / 1024)
    avail_mb = round(mem.get('MemAvailable', 0) / 1024)
    used_mb = max(0, total_mb - avail_mb)
    ram_pct = round((used_mb / total_mb) * 100, 1) if total_mb else 0

    # 5. Storage Stats
    root_free_gb, root_total_gb, root_pct = 0, 0, 0
    try:
        d_root = shutil.disk_usage('/')
        root_free_gb = round(d_root.free / (1024**3), 1)
        root_total_gb = round(d_root.total / (1024**3), 1)
        root_pct = round((d_root.used / d_root.total) * 100, 1)
    except Exception:
        pass

    vault_free_gb, vault_total_gb, vault_pct = 0, 0, 0
    target_vault_dir = PHOTOS_DIR if os.path.exists(PHOTOS_DIR) else '/mnt/vault'
    try:
        if os.path.exists(target_vault_dir):
            d_vault = shutil.disk_usage(target_vault_dir)
            vault_free_gb = round(d_vault.free / (1024**3), 1)
            vault_total_gb = round(d_vault.total / (1024**3), 1)
            vault_pct = round((d_vault.used / d_vault.total) * 100, 1)
    except Exception:
        pass

    # 6. Service health states
    services = {
        'dota_vault': True,
        'photos_vault': True,
        'jellyfin': os.path.exists('/var/lib/jellyfin'),
        'pocketbase': os.path.exists('/opt/pocketbase/pocketbase'),
        'filebrowser': os.path.exists('/usr/local/bin/filebrowser') or os.path.exists('/mnt/vault/server.js')
    }

    return {
        'temp_c': temp_c,
        'uptime': uptime_str,
        'uptime_seconds': uptime_seconds,
        'cpu': {
            'model': 'Amlogic S905W (Quad-Core Cortex-A53)',
            'cores': 4,
            'load1': round(load1, 2),
            'load5': round(load5, 2),
            'load15': round(load15, 2),
            'est_usage_pct': min(100, round((load1 / 4.0) * 100, 1))
        },
        'ram': {
            'total_mb': total_mb,
            'used_mb': used_mb,
            'avail_mb': avail_mb,
            'pct': ram_pct
        },
        'storage_root': {
            'label': 'MicroSD (Armbian OS)',
            'free_gb': root_free_gb,
            'total_gb': root_total_gb,
            'pct': root_pct
        },
        'storage_vault': {
            'label': 'Vault Drive (Pendrive / 3TB HDD)',
            'free_gb': vault_free_gb,
            'total_gb': vault_total_gb,
            'pct': vault_pct
        },
        'services': services
    }

def read_json_body(handler):
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        if content_length <= 0:
            return {}
        raw = handler.rfile.read(content_length).decode('utf-8', errors='replace')
        return json.loads(raw)
    except Exception:
        return {}


# ---------------- PHOTOS AUTHENTICATION (UMAR24434) ----------------
import hmac
import hashlib
import time
from http import cookies

PHOTOS_PASSWORD = "umar24434"
AUTH_SECRET = "tx3_photos_auth_secret_umar24434_98234"

def generate_photos_token(days=30):
    expiry = int(time.time()) + (days * 86400)
    msg = f"tx3_auth_{expiry}"
    sig = hmac.new(AUTH_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{sig}.{expiry}"

def verify_photos_token(token_str):
    if not token_str or '.' not in token_str:
        return False
    try:
        sig, expiry_s = token_str.split('.', 1)
        expiry = int(expiry_s)
        if expiry < time.time():
            return False
        msg = f"tx3_auth_{expiry}"
        expected_sig = hmac.new(AUTH_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False

def is_photos_authenticated(handler, pathname, params):
    host = handler.headers.get('Host', '')
    cf_ip = handler.headers.get('CF-Connecting-IP')
    xf_ip = handler.headers.get('X-Forwarded-For')

    # If it is a direct local LAN request (no Cloudflare proxy headers and host is LAN IP/localhost)
    is_direct_lan = (not cf_ip) and (not xf_ip) and (
        host.startswith('192.168.') or 
        host.startswith('127.0.0.1') or 
        host.startswith('localhost') or 
        host.startswith('100.109.')
    )
    if is_direct_lan:
        return True

    # Check Cookie header
    cookie_header = handler.headers.get('Cookie')
    if cookie_header:
        try:
            c = cookies.SimpleCookie()
            c.load(cookie_header)
            if 'tx3_photos_token' in c:
                if verify_photos_token(c['tx3_photos_token'].value):
                    return True
        except Exception:
            pass

    # Check Authorization: Bearer <token>
    auth_header = handler.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
        if verify_photos_token(token):
            return True

    # Check URL param ?token=...
    if params and 'token' in params:
        token = params['token'][0]
        if verify_photos_token(token):
            return True

    return False


class VaultHandler(BaseHTTPRequestHandler):
    def send_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Range')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_GET(self, head_only=False):
        global pc_state
        parsed = urllib.parse.urlparse(self.path)
        pathname = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        host = self.headers.get('Host', '').lower()

        # Wake on LAN
        if pathname == '/api/wake-pc':
            send_wol()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(json.dumps({'status': 'Magic packet sent', 'macs': PC_MACS}).encode('utf-8'))
            return

        # Remote Shutdown PC
        if pathname == '/api/shutdown-pc':
            pc_state["pending_action"] = "shutdown"
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(json.dumps({
                    'status': 'Shutdown command queued. PC will shut down within 5 seconds.',
                    'action': 'shutdown'
                }).encode('utf-8'))
            return

        # Remote Sleep PC
        if pathname == '/api/sleep-pc':
            pc_state["pending_action"] = "sleep"
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(json.dumps({
                    'status': 'Sleep command queued. PC will enter sleep mode within 5 seconds.',
                    'action': 'sleep'
                }).encode('utf-8'))
            return

        # PC Status check
        if pathname == '/api/pc-status':
            is_online = (time.time() - pc_state["last_seen"]) < 15
            if not is_online:
                try:
                    # Quick ping to local PC
                    res = subprocess.run(['ping', '-c', '1', '-W', '1', '192.168.100.228'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if res.returncode == 0:
                        is_online = True
                except Exception:
                    pass
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(json.dumps({
                    'online': is_online,
                    'computer': pc_state.get('computer_name', 'DESKTOP-S700VJ0'),
                    'last_seen_seconds_ago': round(time.time() - pc_state["last_seen"], 1) if pc_state["last_seen"] > 0 else None
                }).encode('utf-8'))
            return

        # PC Background Agent Heartbeat & Command Retrieval
        if pathname == '/api/pc-agent':
            pc_state["last_seen"] = time.time()
            comp_name = params.get('name', [''])[0]
            if comp_name:
                pc_state["computer_name"] = comp_name

            action = pc_state["pending_action"]
            if action:
                pc_state["pending_action"] = None
                response = {"action": action}
            else:
                response = {"action": "none"}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(json.dumps(response).encode('utf-8'))
            return

        # ---------------- TX3 MINI SYSTEM TELEMETRY ----------------
        if pathname == '/api/system-stats':
            stats = get_system_stats()
            payload = json.dumps(stats).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        # ---------------- DOTA 2 SUMMARY & QUICK FEED ----------------
        if pathname == '/api/dota/summary':
            sessions = get_sessions()
            total_clips = sum(s.get('clip_count', 0) for s in sessions)
            total_mb = sum(s.get('total_mb', 0) for s in sessions)
            summary = {
                'total_matches': len(sessions),
                'total_clips': total_clips,
                'total_size_gb': round(total_mb / 1024, 2),
                'latest_match': sessions[0] if sessions else None,
                'recent_matches': sessions[:15]
            }
            payload = json.dumps(summary).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return


        # ---------------- SHARES ADMIN API ----------------
        if pathname == '/api/shares/create':
            try:
                body = read_json_body(self)
                folder_paths = body.get('folder_paths') or body.get('folder_path', '')
                title = body.get('title', '')
                password = body.get('password', '')
                expires_days = body.get('expires_days', 0)

                new_share = sharing.create_share(
                    folder_paths=folder_paths,
                    title=title,
                    password=password,
                    expires_days=expires_days
                )
                payload = json.dumps({'success': True, 'share': new_share}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(payload)
                return
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return

        if pathname == '/api/shares/delete':
            try:
                body = read_json_body(self)
                share_token = body.get('share_token', '')
                ok = sharing.delete_share(share_token)
                payload = json.dumps({'success': ok}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(payload)
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return

        # ---------------- TX3 CINEMA / PLAYBACK STATE API ----------------
        if pathname == '/api/playback/progress':
            path_param = params.get('path', [''])[0]
            pb = cinema.get_progress(path_param) if cinema else {}
            payload = json.dumps(pb or {}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/playback/continue':
            items = cinema.get_continue_watching(15) if cinema else []
            payload = json.dumps({'items': items}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/cinema/library':
            res = cinema.scan_cinema_library() if cinema else {"series": []}
            payload = json.dumps(res).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/cinema/thumb':
            path_param = params.get('path', [''])[0]
            thumb_file = cinema.get_video_thumbnail(path_param) if cinema else None
            if thumb_file and os.path.exists(thumb_file):
                f_size = os.path.getsize(thumb_file)
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(f_size))
                self.send_header('Cache-Control', 'public, max-age=604800')
                self.send_cors()
                self.end_headers()
                if not head_only:
                    with open(thumb_file, 'rb') as f:
                        shutil.copyfileobj(f, self.wfile)
                return
            else:
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                return

        if pathname == '/api/cinema/siblings':
            path_param = params.get('path', [''])[0]
            siblings = cinema.get_sibling_episodes(path_param) if cinema else []
            payload = json.dumps({'episodes': siblings}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        # ---------------- GOOGLE DRIVE FILE EXPLORER API ----------------
        if pathname == '/api/drive/storages':
            storages_data = get_available_storages()
            payload = json.dumps({'storages': storages_data}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/drive/list':
            rel = params.get('path', [''])[0]
            sid = params.get('storage', [''])[0]
            sort_by = params.get('sort', ['name'])[0]
            sort_order = params.get('order', ['asc'])[0]

            abs_target, clean_rel, storage_id, root_path, storage_name = resolve_drive_path(rel, sid)
            if not abs_target or not os.path.exists(abs_target):
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                return

            crumbs = [{'name': storage_name, 'path': ''}]
            if clean_rel:
                parts = clean_rel.split('/')
                acc = ''
                for p in parts:
                    acc = f"{acc}/{p}" if acc else p
                    crumbs.append({'name': p, 'path': acc})

            folders = []
            files = []
            progress_map = cinema.get_all_progress_map() if cinema else {}

            try:
                for item in os.listdir(abs_target):
                    if item.startswith('.'):
                        continue
                    item_abs = os.path.join(abs_target, item)
                    item_rel = f"{clean_rel}/{item}".lstrip('/') if clean_rel else item
                    try:
                        st = os.stat(item_abs)
                        mtime = int(st.st_mtime)
                        dt = datetime.fromtimestamp(mtime)
                        date_str = dt.strftime('%b %d, %Y')
                    except Exception:
                        mtime = 0
                        date_str = '--'

                    if os.path.isdir(item_abs):
                        try:
                            sub_count = len([x for x in os.listdir(item_abs) if not x.startswith('.')])
                        except Exception:
                            sub_count = 0
                        folders.append({
                            'name': item,
                            'path': item_rel,
                            'mtime': mtime,
                            'date_str': date_str,
                            'item_count': sub_count
                        })
                    else:
                        ext = os.path.splitext(item)[1]
                        ftype, is_media = get_file_type_meta(ext)
                        size_bytes = st.st_size if 'st' in locals() else 0
                        file_obj = {
                            'name': item,
                            'path': item_rel,
                            'size_bytes': size_bytes,
                            'size_str': format_file_size(size_bytes),
                            'mtime': mtime,
                            'date_str': date_str,
                            'ext': ext.lstrip('.').upper(),
                            'type': ftype,
                            'is_media': is_media
                        }
                        if ftype == 'video':
                            pb = progress_map.get(item_rel) or progress_map.get(item_abs)
                            if pb:
                                file_obj['playback'] = pb
                        files.append(file_obj)
            except Exception as e:
                print("Error listing drive dir:", e)

            rev = (sort_order == 'desc')
            if sort_by == 'date':
                folders.sort(key=lambda x: x['mtime'], reverse=rev)
                files.sort(key=lambda x: x['mtime'], reverse=rev)
            elif sort_by == 'size':
                files.sort(key=lambda x: x['size_bytes'], reverse=rev)
            else: # name
                folders.sort(key=lambda x: x['name'].lower(), reverse=rev)
                files.sort(key=lambda x: x['name'].lower(), reverse=rev)

            payload = json.dumps({
                'storage_id': storage_id,
                'storage_name': storage_name,
                'current_path': clean_rel,
                'breadcrumbs': crumbs,
                'folders': folders,
                'files': files,
                'total_folders': len(folders),
                'total_files': len(files)
            }).encode('utf-8')

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/drive/raw':
            rel = params.get('path', [''])[0]
            sid = params.get('storage', [''])[0]
            abs_target, clean_rel, storage_id, root_path, storage_name = resolve_drive_path(rel, sid)
            if not abs_target or not os.path.exists(abs_target) or os.path.isdir(abs_target):
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                return

            file_size = os.path.getsize(abs_target)
            ctype, _ = mimetypes.guess_type(abs_target)
            ctype = ctype or 'application/octet-stream'
            is_download = params.get('download', ['0'])[0] == '1'

            range_header = self.headers.get('Range')
            try:
                if range_header:
                    byte_range = range_header.replace('bytes=', '')
                    parts = byte_range.split('-')
                    start = int(parts[0]) if parts[0] else 0
                    end = int(parts[1]) if parts[1] else file_size - 1

                    if start >= file_size:
                        self.send_response(416)
                        self.send_header('Content-Range', f'bytes */{file_size}')
                        self.end_headers()
                        return

                    chunk_size = (end - start) + 1
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Length', str(chunk_size))
                    self.send_header('Content-Type', ctype)
                    if is_download:
                        self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(abs_target)}"')
                    self.send_cors()
                    self.end_headers()

                    if not head_only:
                        with open(abs_target, 'rb', buffering=2*1024*1024) as f:
                            f.seek(start)
                            bytes_to_send = chunk_size
                            while bytes_to_send > 0:
                                chunk = f.read(min(bytes_to_send, 1024 * 1024))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                bytes_to_send -= len(chunk)
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', str(file_size))
                    self.send_header('Content-Type', ctype)
                    self.send_header('Accept-Ranges', 'bytes')
                    if is_download:
                        self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(abs_target)}"')
                    self.send_cors()
                    self.end_headers()
                    if not head_only:
                        with open(abs_target, 'rb', buffering=2*1024*1024) as f:
                            while True:
                                chunk = f.read(1024 * 1024)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return


        # ---------------- TX3 SHARED FOLDERS (READ-ONLY) ----------------
        if pathname in ('/shares-manager', '/shares-manager/'):
            manager_html = '/opt/tx3-vault/shares_manager.html'
            if os.path.exists(manager_html):
                with open(manager_html, 'rb') as f:
                    payload = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_cors()
                self.end_headers()
                if not head_only:
                    self.wfile.write(payload)
                return

        if pathname.startswith('/s/'):
            token = pathname[3:].split('/')[0].strip()
            share = sharing.get_share(token)
            if not share or share.get('is_expired'):
                self.send_response(404)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_cors()
                self.end_headers()
                if not head_only:
                    self.wfile.write(b'<h1>404 - Pautan Perkongsian Tidak Dijumpai atau Telah Tamat Tempoh</h1>')
                return
            sharing.record_view(token)
            share_html = '/opt/tx3-vault/public_share.html'
            if os.path.exists(share_html):
                with open(share_html, 'rb') as f:
                    payload = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_cors()
                self.end_headers()
                if not head_only:
                    self.wfile.write(payload)
                return

        if pathname.startswith('/api/share/'):
            parts = pathname.split('/')
            # /api/share/<token>/<action>
            if len(parts) >= 4:
                token = parts[3]
                action = parts[4] if len(parts) >= 5 else 'list'
                share = sharing.get_share(token)
                if not share or share.get('is_expired'):
                    self.send_response(404)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors()
                    self.end_headers()
                    if not head_only:
                        self.wfile.write(b'{"error": "Pautan tidak dijumpai atau tamat tempoh"}')
                    return

                # Check password if protected
                pwd = params.get('pwd', [''])[0]
                if share.get('has_password'):
                    if not sharing.verify_share_password(token, pwd):
                        self.send_response(401)
                        self.send_header('Content-Type', 'application/json')
                        self.send_cors()
                        self.end_headers()
                        if not head_only:
                            self.wfile.write(b'{"error": "Kata laluan diperlukan", "auth_required": true}')
                        return

                if action == 'list':
                    subpath = params.get('subpath', [''])[0]
                    res = sharing.list_folder_contents(share, subpath)
                    if res is None:
                        self.send_response(404)
                        self.send_cors()
                        self.end_headers()
                        return
                    payload = json.dumps(res).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_cors()
                    self.end_headers()
                    if not head_only:
                        self.wfile.write(payload)
                    return

                if action == 'download':
                    req_path = params.get('path', [''])[0]
                    target_abs = sharing.resolve_shared_path(share, req_path)
                    if not target_abs or not os.path.isfile(target_abs):
                        self.send_response(404)
                        self.send_cors()
                        self.end_headers()
                        return

                    sharing.record_download(token)
                    f_size = os.path.getsize(target_abs)
                    filename = os.path.basename(target_abs)
                    mime, _ = mimetypes.guess_type(target_abs)
                    mime = mime or 'application/octet-stream'

                    range_hdr = self.headers.get('Range')
                    if range_hdr and range_hdr.startswith('bytes='):
                        try:
                            start_str, end_str = range_hdr[6:].split('-')
                            start = int(start_str)
                            end = int(end_str) if end_str else f_size - 1
                            if start >= f_size:
                                self.send_response(416)
                                self.end_headers()
                                return
                            end = min(end, f_size - 1)
                            length = end - start + 1

                            self.send_response(206)
                            self.send_header('Content-Type', mime)
                            self.send_header('Content-Range', f'bytes {start}-{end}/{f_size}')
                            self.send_header('Content-Length', str(length))
                            self.send_header('Accept-Ranges', 'bytes')
                            self.send_cors()
                            self.end_headers()

                            if not head_only:
                                with open(target_abs, 'rb') as f:
                                    f.seek(start)
                                    remaining = length
                                    while remaining > 0:
                                        chunk = f.read(min(remaining, 1024 * 512))
                                        if not chunk:
                                            break
                                        self.wfile.write(chunk)
                                        remaining -= len(chunk)
                            return
                        except Exception:
                            pass

                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(f_size))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                    self.send_cors()
                    self.end_headers()

                    if not head_only:
                        try:
                            with open(target_abs, 'rb') as f:
                                while True:
                                    chunk = f.read(1024 * 512)
                                    if not chunk:
                                        break
                                    self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    return

                if action == 'stream':
                    req_path = params.get('path', [''])[0]
                    target_abs = sharing.resolve_shared_path(share, req_path)
                    if not target_abs or not os.path.isfile(target_abs):
                        self.send_response(404)
                        self.send_cors()
                        self.end_headers()
                        return

                    status, cached_path = sharing.get_transcode_status(target_abs)
                    if status == 'ready':
                        serve_path = cached_path
                        f_size = os.path.getsize(serve_path)
                        mime = 'video/mp4'

                        range_hdr = self.headers.get('Range')
                        if range_hdr and range_hdr.startswith('bytes='):
                            try:
                                start_str, end_str = range_hdr[6:].split('-')
                                start = int(start_str)
                                end = int(end_str) if end_str else f_size - 1
                                if start >= f_size:
                                    self.send_response(416)
                                    self.end_headers()
                                    return
                                end = min(end, f_size - 1)
                                length = end - start + 1

                                self.send_response(206)
                                self.send_header('Content-Type', mime)
                                self.send_header('Content-Range', f'bytes {start}-{end}/{f_size}')
                                self.send_header('Content-Length', str(length))
                                self.send_header('Accept-Ranges', 'bytes')
                                self.send_cors()
                                self.end_headers()

                                if not head_only:
                                    with open(serve_path, 'rb') as f:
                                        f.seek(start)
                                        remaining = length
                                        while remaining > 0:
                                            chunk = f.read(min(remaining, 1024 * 512))
                                            if not chunk:
                                                break
                                            self.wfile.write(chunk)
                                            remaining -= len(chunk)
                                return
                            except Exception:
                                pass

                        self.send_response(200)
                        self.send_header('Content-Type', mime)
                        self.send_header('Content-Length', str(f_size))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.send_cors()
                        self.end_headers()

                        if not head_only:
                            try:
                                with open(serve_path, 'rb') as f:
                                    while True:
                                        chunk = f.read(1024 * 512)
                                        if not chunk:
                                            break
                                        self.wfile.write(chunk)
                            except (BrokenPipeError, ConnectionResetError):
                                pass
                        return
                    else:
                        # On-demand live stream: starts playing in ~3s!
                        self.send_response(200)
                        self.send_header('Content-Type', 'video/mp4')
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_cors()
                        self.end_headers()

                        if head_only:
                            return

                        cmd = [
                            'ffmpeg', '-i', target_abs,
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                            '-crf', '24', '-g', '25',
                            '-c:a', 'aac', '-b:a', '128k',
                            '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
                            '-f', 'mp4', 'pipe:1'
                        ]
                        proc = None
                        try:
                            import subprocess
                            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                            while True:
                                chunk = proc.stdout.read(65536)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        finally:
                            if proc:
                                try:
                                    proc.terminate()
                                    proc.wait(timeout=2)
                                except Exception:
                                    proc.kill()
                        return

                if action == 'thumb':
                    req_path = params.get('path', [''])[0]
                    target_abs = sharing.resolve_shared_path(share, req_path)
                    if not target_abs or not os.path.isfile(target_abs):
                        self.send_response(404)
                        self.send_cors()
                        self.end_headers()
                        return

                    ext = os.path.splitext(target_abs)[1].lower()
                    if ext in sharing.VIDEO_EXTS:
                        thumb_file = sharing.get_video_thumbnail(target_abs)
                        if thumb_file and os.path.exists(thumb_file):
                            f_size = os.path.getsize(thumb_file)
                            self.send_response(200)
                            self.send_header('Content-Type', 'image/jpeg')
                            self.send_header('Content-Length', str(f_size))
                            self.send_header('Cache-Control', 'public, max-age=86400')
                            self.send_cors()
                            self.end_headers()
                            if not head_only:
                                with open(thumb_file, 'rb') as f:
                                    self.wfile.write(f.read())
                            return
                        else:
                            self.send_response(404)
                            self.send_cors()
                            self.end_headers()
                            return
                    else:
                        mime, _ = mimetypes.guess_type(target_abs)
                        if not mime or not mime.startswith('image/'):
                            self.send_response(404)
                            self.send_cors()
                            self.end_headers()
                            return

                        f_size = os.path.getsize(target_abs)
                        self.send_response(200)
                        self.send_header('Content-Type', mime)
                        self.send_header('Content-Length', str(f_size))
                        self.send_header('Cache-Control', 'public, max-age=86400')
                        self.send_cors()
                        self.end_headers()
                        if not head_only:
                            with open(target_abs, 'rb') as f:
                                self.wfile.write(f.read())
                        return

                if action == 'zip':
                    subpath = params.get('subpath', [''])[0]
                    paths = share.get('folder_paths') or sharing.get_share_folder_paths(share)
                    import zipfile
                    zip_buffer = io.BytesIO()

                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        if len(paths) > 1 and not subpath.strip('/'):
                            for fp in paths:
                                f_name = os.path.basename(fp.rstrip('/' + chr(92)))
                                for root, _, files in os.walk(fp):
                                    for fn in files:
                                        if fn in sharing.IGNORED_NAMES or fn.startswith('.'):
                                            continue
                                        file_path = os.path.join(root, fn)
                                        rel_f = os.path.relpath(file_path, fp)
                                        arcname = os.path.join(f_name, rel_f)
                                        zf.write(file_path, arcname)
                            folder_name = share.get('title') or "shared_folders"
                        else:
                            target_abs = sharing.resolve_shared_path(share, subpath)
                            if not target_abs or not os.path.isdir(target_abs):
                                self.send_response(404)
                                self.send_cors()
                                self.end_headers()
                                return
                            for root, _, files in os.walk(target_abs):
                                for fn in files:
                                    if fn in sharing.IGNORED_NAMES or fn.startswith('.'):
                                        continue
                                    file_path = os.path.join(root, fn)
                                    arcname = os.path.relpath(file_path, target_abs)
                                    zf.write(file_path, arcname)
                            folder_name = os.path.basename(target_abs.rstrip('/' + chr(92))) or "shared_files"

                    zip_data = zip_buffer.getvalue()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Length', str(len(zip_data)))
                    self.send_header('Content-Disposition', f'attachment; filename="{folder_name}.zip"')
                    self.send_cors()
                    self.end_headers()
                    if not head_only:
                        self.wfile.write(zip_data)
                    return

        if pathname == '/api/shares/all':
            shares = sharing.list_all_shares()
            payload = json.dumps({'shares': shares}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/shares/browse':
            req_path = params.get('path', ['/shares/3TB-ext'])[0]
            data = sharing.browse_directory_tree(req_path)
            payload = json.dumps(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/shares/tree':
            folders = sharing.browse_storage_tree('/shares/3TB-ext')
            payload = json.dumps({'folders': folders}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        # ---------------- PHOTOS API ----------------
        if pathname == '/api/photos/auth-check':
            is_authed = is_photos_authenticated(self, pathname, params)
            payload = json.dumps({'authenticated': is_authed}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        # Enforce authentication on all /api/photos/* endpoints
        if pathname.startswith('/api/photos'):
            if not is_photos_authenticated(self, pathname, params):
                payload = json.dumps({'error': 'Unauthorized', 'auth_required': True}).encode('utf-8')
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                if not head_only:
                    self.wfile.write(payload)
                return
        if pathname in ('/api/photos', '/api/photos/catalog'):
            catalog = scan_photos()
            payload = json.dumps(catalog).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/photos/rescan':
            catalog = scan_photos(force=True)
            payload = json.dumps(catalog).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/photos/thumb-progress':
            prog_file = os.path.join(PHOTO_CACHE_DIR, 'thumb_progress.json')
            if os.path.exists(prog_file):
                try:
                    with open(prog_file, 'r', encoding='utf-8') as f:
                        payload = f.read().encode('utf-8')
                except Exception:
                    payload = b'{"status": "error"}'
            else:
                payload = b'{"status": "idle"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            return

        if pathname == '/api/photos/thumb':
            p_id = params.get('id', [''])[0]
            photo = photos_index.get(p_id)
            if not photo:
                scan_photos()
                photo = photos_index.get(p_id)

            if not photo:
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                return

            thumb_path = get_or_generate_thumbnail(photo)
            if thumb_path and os.path.exists(thumb_path):
                f_size = os.path.getsize(thumb_path)
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(f_size))
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                self.send_cors()
                self.end_headers()
                if not head_only:
                    with open(thumb_path, 'rb') as f:
                        self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.send_cors()
                self.end_headers()
            return

        if pathname == '/api/photos/raw':
            p_id = params.get('id', [''])[0]
            photo = photos_index.get(p_id)
            if not photo:
                scan_photos()
                photo = photos_index.get(p_id)

            if not photo or not os.path.exists(photo['abs_path']):
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                return

            file_path = photo['abs_path']
            file_size = os.path.getsize(file_path)
            ctype, _ = mimetypes.guess_type(file_path)
            ctype = ctype or ('video/mp4' if photo['is_video'] else 'image/jpeg')

            is_download = params.get('download', ['0'])[0] == '1'

            range_header = self.headers.get('Range')
            try:
                if range_header:
                    byte_range = range_header.replace('bytes=', '')
                    parts = byte_range.split('-')
                    start = int(parts[0]) if parts[0] else 0
                    end = int(parts[1]) if parts[1] else file_size - 1

                    if start >= file_size:
                        self.send_response(416)
                        self.send_header('Content-Range', f'bytes */{file_size}')
                        self.end_headers()
                        return

                    chunk_size = (end - start) + 1
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Length', str(chunk_size))
                    self.send_header('Content-Type', ctype)
                    if is_download:
                        self.send_header('Content-Disposition', f'attachment; filename="{photo["name"]}"')
                    self.send_cors()
                    self.end_headers()

                    if not head_only:
                        with open(file_path, 'rb', buffering=2*1024*1024) as f:
                            f.seek(start)
                            bytes_to_send = chunk_size
                            while bytes_to_send > 0:
                                chunk = f.read(min(bytes_to_send, 1024 * 1024))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                bytes_to_send -= len(chunk)
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', str(file_size))
                    self.send_header('Content-Type', ctype)
                    self.send_header('Accept-Ranges', 'bytes')
                    if is_download:
                        self.send_header('Content-Disposition', f'attachment; filename="{photo["name"]}"')
                    self.send_cors()
                    self.end_headers()
                    if not head_only:
                        with open(file_path, 'rb', buffering=2*1024*1024) as f:
                            while True:
                                chunk = f.read(1024 * 1024)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # ---------------- DOTA 2 SESSIONS & CLIPS API ----------------
        if pathname == '/api/sessions':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                sessions = get_sessions()
                self.wfile.write(json.dumps(sessions).encode('utf-8'))
            return

        if pathname == '/api/notes':
            nf = get_notes_file()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_cors()
            self.end_headers()
            if not head_only:
                if os.path.exists(nf):
                    with open(nf, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.wfile.write(b'{}')
            return

        if pathname == '/api/clips':
            folder = params.get('folder', [''])[0]
            if not os.path.exists(folder):
                folder_name = os.path.basename(folder.replace('\\', '/').rstrip('/'))
                for d_dir in get_dota_dirs():
                    cand = os.path.join(d_dir, folder_name)
                    if os.path.exists(cand):
                        folder = cand
                        break

            clips = []
            if os.path.exists(folder) and os.path.isdir(folder):
                for f in os.listdir(folder):
                    if f.lower().endswith('.mp4'):
                        fp = os.path.join(folder, f)
                        size_mb = round(os.path.getsize(fp) / (1024 * 1024), 1)
                        clips.append({'name': f, 'path': fp, 'size_mb': size_mb})
                clips.sort(key=lambda x: x['name'])

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors()
            self.end_headers()
            if not head_only:
                self.wfile.write(json.dumps(clips).encode('utf-8'))
            return

        if pathname == '/api/thumbnail':
            name = params.get('name', [''])[0]
            clean_name = os.path.splitext(os.path.basename(name))[0]
            thumb_path = None
            for d_dir in get_dota_dirs():
                cand = os.path.join(d_dir, '_thumbnails', f"{clean_name}.jpg")
                if os.path.exists(cand):
                    thumb_path = cand
                    break
            if not thumb_path or not os.path.exists(thumb_path):
                thumb_path = os.path.join(get_thumb_dir(), f"{clean_name}.jpg")

            if os.path.exists(thumb_path):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_cors()
                self.end_headers()
                if not head_only:
                    with open(thumb_path, 'rb') as f:
                        self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.send_cors()
                self.end_headers()
            return

        if pathname == '/api/video':
            video_path = params.get('path', [''])[0]
            if not os.path.exists(video_path):
                base_name = os.path.basename(video_path.replace('\\', '/'))
                parent_name = os.path.basename(os.path.dirname(video_path.replace('\\', '/')))
                for d_dir in get_dota_dirs():
                    cand = os.path.join(d_dir, parent_name, base_name)
                    if os.path.exists(cand):
                        video_path = cand
                        break

            if not os.path.exists(video_path):
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                if not head_only:
                    self.wfile.write(b'Video not found')
                return

            file_size = os.path.getsize(video_path)
            range_header = self.headers.get('Range')

            try:
                if range_header:
                    byte_range = range_header.replace('bytes=', '')
                    parts = byte_range.split('-')
                    start = int(parts[0]) if parts[0] else 0
                    end = int(parts[1]) if parts[1] else file_size - 1

                    if start >= file_size:
                        self.send_response(416)
                        self.send_header('Content-Range', f'bytes */{file_size}')
                        self.end_headers()
                        return

                    chunk_size = (end - start) + 1
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Length', str(chunk_size))
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_cors()
                    self.end_headers()

                    if not head_only:
                        with open(video_path, 'rb', buffering=2*1024*1024) as f:
                            f.seek(start)
                            bytes_to_send = chunk_size
                            while bytes_to_send > 0:
                                chunk = f.read(min(bytes_to_send, 1024 * 1024))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                bytes_to_send -= len(chunk)
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', str(file_size))
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_cors()
                    self.end_headers()
                    if not head_only:
                        with open(video_path, 'rb', buffering=2*1024*1024) as f:
                            while True:
                                chunk = f.read(1024 * 1024)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # ---------------- HTML & STATIC FILE SERVING ----------------
        # Check if requested from photos domain or /photos path
        is_photos_request = (
            host.startswith('photos.umiaq.top') or
            pathname in ('/photos', '/photos/', '/photos/index.html')
        )

        if is_photos_request and (pathname in ('/', '', '/photos', '/photos/', '/photos/index.html') or not os.path.exists(os.path.join(DIST_DIR, pathname.lstrip('/')))):
            if os.path.exists(PHOTOS_HTML_FILE):
                f_size = os.path.getsize(PHOTOS_HTML_FILE)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(f_size))
                self.send_cors()
                self.end_headers()
                if not head_only:
                    with open(PHOTOS_HTML_FILE, 'rb') as f:
                        self.wfile.write(f.read())
                return

        req_file = pathname.lstrip('/')
        if not req_file or req_file == '/':
            req_file = 'index.html'

        target_file = os.path.join(DIST_DIR, req_file)
        if not os.path.exists(target_file) or os.path.isdir(target_file):
            target_file = os.path.join(DIST_DIR, 'index.html')

        if os.path.exists(target_file):
            ctype, _ = mimetypes.guess_type(target_file)
            ctype = ctype or 'application/octet-stream'
            f_size = os.path.getsize(target_file)
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(f_size))
            self.send_cors()
            self.end_headers()
            if not head_only:
                with open(target_file, 'rb') as f:
                    self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.send_cors()
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        pathname = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # ---------------- PHOTOS AUTH LOGIN / LOGOUT ----------------
        if pathname == '/api/photos/login':
            try:
                body = read_json_body(self)
                pwd = body.get('password', '')
                if pwd == PHOTOS_PASSWORD:
                    token = generate_photos_token(days=30)
                    payload = json.dumps({'success': True, 'token': token}).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Set-Cookie', f'tx3_photos_token={token}; Path=/; Max-Age=2592000; SameSite=Lax')
                    self.send_cors()
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                else:
                    payload = json.dumps({'success': False, 'error': 'Kata laluan salah!'}).encode('utf-8')
                    self.send_response(401)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors()
                    self.end_headers()
                    self.wfile.write(payload)
                    return
            except Exception as e:
                self.send_response(500)
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return

        if pathname == '/api/photos/logout':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', 'tx3_photos_token=; Path=/; Max-Age=0; SameSite=Lax')
            self.send_cors()
            self.end_headers()
            self.wfile.write(b'{"success": true}')
            return


        # ---------------- SHARES ADMIN API ----------------
        if pathname == '/api/shares/create':
            try:
                body = read_json_body(self)
                folder_paths = body.get('folder_paths') or body.get('folder_path', '')
                title = body.get('title', '')
                password = body.get('password', '')
                expires_days = body.get('expires_days', 0)

                new_share = sharing.create_share(
                    folder_paths=folder_paths,
                    title=title,
                    password=password,
                    expires_days=expires_days
                )
                payload = json.dumps({'success': True, 'share': new_share}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(payload)
                return
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return

        if pathname == '/api/shares/delete':
            try:
                body = read_json_body(self)
                share_token = body.get('share_token', '')
                ok = sharing.delete_share(share_token)
                payload = json.dumps({'success': ok}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(payload)
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return

        # ---------------- TX3 CINEMA / PLAYBACK STATE API ----------------
        if pathname == '/api/playback/progress':
            body = read_json_body(self)
            saved = None
            if cinema:
                saved = cinema.save_progress(
                    file_path=body.get('path', ''),
                    storage_id=body.get('storage_id', ''),
                    title=body.get('title', ''),
                    folder_name=body.get('folder_name', ''),
                    position_ms=body.get('position_ms', 0),
                    duration_ms=body.get('duration_ms', 0),
                    is_completed=body.get('is_completed', None)
                )
            payload = json.dumps({'success': True, 'data': saved}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_cors()
            self.end_headers()
            self.wfile.write(payload)
            return

        if pathname == '/api/notes':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            nf = get_notes_file()
            try:
                with open(nf, 'wb') as f:
                    f.write(body)
                # Safeguard mirror copy on eMMC
                emmc_nf = os.path.join(BASE_DIR, '_notes.json')
                if emmc_nf != nf:
                    with open(emmc_nf, 'wb') as f2:
                        f2.write(body)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"success":true}')
            except Exception as e:
                self.send_response(500)
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        # ---------------- GOOGLE DRIVE FILE ACTIONS ----------------
        if pathname == '/api/drive/mkdir':
            body = read_json_body(self)
            parent_rel = body.get('path', '')
            sid = body.get('storage', '')
            folder_name = body.get('name', '').strip()

            if not folder_name or '/' in folder_name or '\\' in folder_name:
                self.send_response(400)
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid folder name"}')
                return

            parent_abs, _, storage_id, root_path, _ = resolve_drive_path(parent_rel, sid)
            if not parent_abs or not os.path.exists(parent_abs):
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Parent path not found"}')
                return

            new_dir = os.path.join(parent_abs, folder_name)
            try:
                os.makedirs(new_dir, exist_ok=False)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except Exception as e:
                self.send_response(500)
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        if pathname == '/api/drive/rename':
            body = read_json_body(self)
            rel = body.get('path', '')
            sid = body.get('storage', '')
            new_name = body.get('new_name', '').strip()

            if not new_name or '/' in new_name or '\\' in new_name:
                self.send_response(400)
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid name"}')
                return

            abs_target, _, storage_id, root_path, _ = resolve_drive_path(rel, sid)
            if not abs_target or not os.path.exists(abs_target):
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Target not found"}')
                return

            new_abs = os.path.join(os.path.dirname(abs_target), new_name)
            try:
                os.rename(abs_target, new_abs)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except Exception as e:
                self.send_response(500)
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        if pathname == '/api/drive/delete':
            body = read_json_body(self)
            rel = body.get('path', '')
            sid = body.get('storage', '')

            abs_target, _, storage_id, root_path, _ = resolve_drive_path(rel, sid)
            if not abs_target or not os.path.exists(abs_target) or abs_target == os.path.abspath(root_path):
                self.send_response(400)
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Cannot delete root or not found"}')
                return

            try:
                if os.path.isdir(abs_target):
                    shutil.rmtree(abs_target)
                else:
                    os.remove(abs_target)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except Exception as e:
                self.send_response(500)
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        if pathname == '/api/drive/upload':
            target_rel = params.get('path', [''])[0]
            sid = params.get('storage', [''])[0]
            filename = os.path.basename(params.get('filename', ['upload.bin'])[0])

            target_dir, _, storage_id, root_path, _ = resolve_drive_path(target_rel, sid)
            if not target_dir or not os.path.exists(target_dir):
                self.send_response(404)
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Destination folder not found"}')
                return

            target_file = os.path.join(target_dir, filename)
            content_length = int(self.headers.get('Content-Length', 0))

            try:
                bytes_remaining = content_length
                with open(target_file, 'wb') as f:
                    while bytes_remaining > 0:
                        chunk = self.rfile.read(min(bytes_remaining, 1024 * 1024))
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_remaining -= len(chunk)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'filename': filename,
                    'size': os.path.getsize(target_file)
                }).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

print(f"=================================================")
print(f"  TX3 Mini Vault Server (Photos + Dota 2 + Power)")
print(f"  Listening on http://0.0.0.0:{PORT}")
print(f"  Photos directory: {PHOTOS_DIR}")
print(f"  Dota directory:   {DOTA_DIR}")
print(f"=================================================")

# Pre-warm photos catalog scan in background thread so server starts listening instantly
threading.Thread(target=scan_photos, daemon=True).start()

httpd = ThreadedHTTPServer(('0.0.0.0', PORT), VaultHandler)
httpd.serve_forever()

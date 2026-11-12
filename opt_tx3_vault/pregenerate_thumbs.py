#!/usr/bin/env python3
import os
import sys
import time
import json
import gc
import subprocess
from PIL import Image, ImageOps

BASE_DIR = '/opt/tx3-vault'
CACHE_DIR = os.path.join(BASE_DIR, 'photos_cache')
THUMB_DIR = os.path.join(CACHE_DIR, 'thumbs')
CATALOG_FILE = os.path.join(CACHE_DIR, 'catalog.json')
PROGRESS_FILE = os.path.join(CACHE_DIR, 'thumb_progress.json')

os.makedirs(THUMB_DIR, exist_ok=True)

def write_progress(total, done, current_name="", status="running"):
    pct = round((done / total * 100), 1) if total > 0 else 100.0
    payload = {
        'total': total,
        'completed': done,
        'remaining': total - done,
        'percent': pct,
        'current_file': current_name,
        'status': status,
        'updated_at': int(time.time())
    }
    try:
        tmp_f = PROGRESS_FILE + '.tmp'
        with open(tmp_f, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_f, PROGRESS_FILE)
    except Exception:
        pass

def main():
    print("=" * 60)
    print("  TX3 Mini Photos Vault - Background Thumbnail Generator")
    print("=" * 60)

    if not os.path.exists(CATALOG_FILE):
        print(f"Catalog file not found: {CATALOG_FILE}")
        sys.exit(1)

    print("Loading catalog...")
    with open(CATALOG_FILE, 'r', encoding='utf-8') as f:
        catalog = json.load(f)

    # Flatten photos list
    all_photos = []
    for group in catalog.get('timeline', []):
        for p in group.get('photos', []):
            all_photos.append(p)

    total = len(all_photos)
    print(f"Total photos in catalog: {total}")

    # Count how many already exist
    existing = 0
    missing = []
    for p in all_photos:
        thumb_path = os.path.join(THUMB_DIR, f"{p['id']}.jpg")
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            existing += 1
        else:
            missing.append(p)

    print(f"Already generated: {existing} / {total} ({(existing/total*100):.1f}%)")
    print(f"Remaining to process: {len(missing)}")

    if not missing:
        print("All thumbnails are already generated! Nothing to do.")
        write_progress(total, total, status="completed")
        return

    write_progress(total, existing, status="running")

    done_count = existing
    last_update = time.time()
    t_start = time.time()

    for idx, photo in enumerate(missing, start=1):
        p_id = photo['id']
        abs_path = photo.get('abs_path', '')
        thumb_path = os.path.join(THUMB_DIR, f"{p_id}.jpg")

        if not os.path.exists(abs_path):
            continue

        try:
            if photo.get('is_video', False):
                cmd = [
                    'ffmpeg', '-y', '-ss', '00:00:01',
                    '-i', abs_path,
                    '-vframes', '1',
                    '-vf', 'scale=450:450:force_original_aspect_ratio=decrease',
                    '-q:v', '3',
                    thumb_path
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
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
                    im.save(thumb_path, 'JPEG', quality=75, optimize=True)
            done_count += 1
        except Exception as e:
            # Skip corrupted/unsupported file silently
            pass

        # Brief pause between photos so CPU remains cool and I/O is gentle
        time.sleep(0.04)

        # Update progress every 25 items or every 5 seconds
        if idx % 25 == 0 or (time.time() - last_update) >= 5:
            pct = (done_count / total * 100)
            elapsed = time.time() - t_start
            rate = idx / elapsed if elapsed > 0 else 0
            eta_mins = (len(missing) - idx) / rate / 60 if rate > 0 else 0
            print(f"[{done_count}/{total}] {pct:.1f}% | Rate: {rate:.1f} img/s | ETA: {eta_mins:.1f} mins | Current: {photo.get('name', '')}")
            write_progress(total, done_count, current_name=photo.get('name', ''), status="running")
            last_update = time.time()
            gc.collect()

    write_progress(total, total, status="completed")
    print(f"\nDone! Successfully processed all thumbnails in {(time.time()-t_start)/60:.1f} minutes.")

if __name__ == '__main__':
    main()

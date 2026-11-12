import os
import sqlite3
import time
import json
import re
import hashlib
import subprocess

DB_PATH = '/opt/tx3-vault/cinema.db'
CACHE_DIR = '/opt/tx3-vault/cinema_cache'
THUMB_DIR = os.path.join(CACHE_DIR, 'thumbs')
VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.ts', '.webm', '.m4v'}
POSTER_NAMES = {'poster.jpg', 'cover.jpg', 'folder.jpg', 'poster.png', 'cover.png', 'folder.png', 'backdrop.jpg'}

os.makedirs(THUMB_DIR, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS playback_progress (
                file_path TEXT PRIMARY KEY,
                storage_id TEXT,
                title TEXT,
                folder_name TEXT,
                position_ms INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                percentage REAL DEFAULT 0.0,
                is_completed INTEGER DEFAULT 0,
                updated_at INTEGER DEFAULT 0
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_playback_updated ON playback_progress(updated_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_playback_completed ON playback_progress(is_completed, updated_at DESC);")
    conn.close()

def save_progress(file_path, storage_id, title, folder_name, position_ms, duration_ms, is_completed=None):
    if not file_path:
        return None
    now = int(time.time())
    pos = int(position_ms or 0)
    dur = int(duration_ms or 0)
    pct = round((pos / dur * 100.0), 1) if dur > 0 else 0.0
    
    if is_completed is None:
        completed = 1 if pct >= 92.0 else 0
    else:
        completed = 1 if is_completed else 0

    conn = get_db()
    with conn:
        conn.execute("""
            INSERT INTO playback_progress (file_path, storage_id, title, folder_name, position_ms, duration_ms, percentage, is_completed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                storage_id = excluded.storage_id,
                title = excluded.title,
                folder_name = excluded.folder_name,
                position_ms = excluded.position_ms,
                duration_ms = excluded.duration_ms,
                percentage = excluded.percentage,
                is_completed = excluded.is_completed,
                updated_at = excluded.updated_at
        """, (file_path, storage_id or '', title or os.path.basename(file_path), folder_name or '', pos, dur, pct, completed, now))
    conn.close()
    return {
        'file_path': file_path,
        'position_ms': pos,
        'duration_ms': dur,
        'percentage': pct,
        'is_completed': bool(completed),
        'updated_at': now
    }

def get_progress(file_path):
    if not file_path:
        return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM playback_progress WHERE file_path = ?", (file_path,))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_continue_watching(limit=12):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM playback_progress 
        WHERE is_completed = 0 AND position_ms >= 5000 
        ORDER BY updated_at DESC 
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    items = []
    for r in rows:
        d = dict(r)
        d['is_completed'] = bool(d.get('is_completed', 0))
        # Ensure thumbnail path
        d['thumb_url'] = f"/api/cinema/thumb?path={d['file_path']}"
        items.append(d)
    return items

def get_all_progress_map():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT file_path, position_ms, duration_ms, percentage, is_completed, updated_at FROM playback_progress")
    rows = cur.fetchall()
    conn.close()
    res = {}
    for r in rows:
        res[r['file_path']] = {
            'position_ms': r['position_ms'],
            'duration_ms': r['duration_ms'],
            'percentage': r['percentage'],
            'is_completed': bool(r['is_completed']),
            'updated_at': r['updated_at']
        }
    return res

def get_sibling_episodes(file_path, storage_base="/shares/3TB-ext", storage_id="3tb_ext"):
    """
    Given a video file path (e.g. Vids/Jdrama/Pride (2004)/Season 1/Pride - S01E01.mp4),
    finds all video episodes in the same folder or series folder, naturally sorted.
    """
    abs_path = os.path.join(storage_base, file_path.lstrip('/'))
    if not os.path.exists(abs_path):
        return []
    folder = os.path.dirname(abs_path)
    progress_map = get_all_progress_map()
    episodes = _collect_episodes(folder, storage_base, storage_id, progress_map)
    return episodes

# ---------------- THUMBNAIL GENERATOR ----------------
def get_video_thumbnail(rel_path, storage_base="/shares/3TB-ext"):
    """
    Returns the absolute path to a cached thumbnail JPEG for a video file or folder.
    Generates it using ffmpeg if it doesn't already exist.
    """
    abs_path = os.path.join(storage_base, rel_path.lstrip('/'))
    if not os.path.exists(abs_path):
        return None

    # Check if a folder was requested
    if os.path.isdir(abs_path):
        # Look for existing poster/cover image in the folder
        for p_name in POSTER_NAMES:
            cand = os.path.join(abs_path, p_name)
            if os.path.exists(cand):
                return cand
        # Otherwise find first video in folder to generate thumbnail from
        first_vid = None
        for root, _, files in os.walk(abs_path):
            for f in sorted(files):
                _, ext = os.path.splitext(f)
                if ext.lower() in VIDEO_EXTS:
                    first_vid = os.path.join(root, f)
                    break
            if first_vid:
                break
        if not first_vid:
            return None
        abs_path = first_vid

    # Unique cache filename based on file path and mtime
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        mtime = 0
    h = hashlib.md5(f"{abs_path}_{mtime}".encode('utf-8')).hexdigest()
    thumb_path = os.path.join(THUMB_DIR, f"{h}.jpg")

    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
        return thumb_path

    # Extract frame at 00:00:30 (or 00:00:05 if shorter)
    try:
        cmd = [
            'ffmpeg', '-y', '-ss', '00:00:30',
            '-i', abs_path,
            '-vframes', '1',
            '-vf', 'scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2',
            '-q:v', '4',
            thumb_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
        if not os.path.exists(thumb_path) or os.path.getsize(thumb_path) == 0:
            # Fallback to 00:00:05
            cmd[3] = '00:00:05'
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)

        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception as e:
        print(f"Error generating cinema thumbnail for {abs_path}: {e}")

    return None

# ---------------- MEDIA LIBRARY SCANNER ----------------
def scan_cinema_library(storage_base="/shares/3TB-ext", storage_id="3tb_ext"):
    vids_root = os.path.join(storage_base, "Vids")
    if not os.path.exists(vids_root):
        return {"series": []}

    progress_map = get_all_progress_map()
    series_list = []

    try:
        for entry in os.scandir(vids_root):
            if not entry.is_dir() or entry.name in ('Dota 2', 'Davinci', 'Captures', '$RECYCLE.BIN'):
                continue
            
            category_name = entry.name
            sub_dirs = []
            direct_videos = []
            for sub in os.scandir(entry.path):
                if sub.is_dir():
                    sub_dirs.append(sub)
                elif sub.is_file():
                    _, ext = os.path.splitext(sub.name)
                    if ext.lower() in VIDEO_EXTS:
                        direct_videos.append(sub)

            if sub_dirs:
                for show_dir in sub_dirs:
                    show_title = show_dir.name
                    episodes = _collect_episodes(show_dir.path, storage_base, storage_id, progress_map)
                    if episodes:
                        folder_rel = os.path.relpath(show_dir.path, storage_base).replace('\\', '/')
                        series_list.append({
                            "title": show_title,
                            "category": category_name,
                            "storage_id": storage_id,
                            "folder_rel_path": folder_rel,
                            "poster_url": f"/api/cinema/thumb?path={folder_rel}",
                            "episode_count": len(episodes),
                            "episodes": episodes
                        })
            elif direct_videos:
                episodes = _collect_episodes(entry.path, storage_base, storage_id, progress_map)
                if episodes:
                    folder_rel = os.path.relpath(entry.path, storage_base).replace('\\', '/')
                    series_list.append({
                        "title": category_name,
                        "category": "Videos",
                        "storage_id": storage_id,
                        "folder_rel_path": folder_rel,
                        "poster_url": f"/api/cinema/thumb?path={folder_rel}",
                        "episode_count": len(episodes),
                        "episodes": episodes
                    })
    except Exception as e:
        print(f"Error scanning cinema library: {e}")

    return {"series": series_list}

def _collect_episodes(show_path, storage_base, storage_id, progress_map):
    episodes = []
    for root, _, files in os.walk(show_path):
        for f in files:
            _, ext = os.path.splitext(f)
            if ext.lower() in VIDEO_EXTS:
                full_p = os.path.join(root, f)
                rel_p = os.path.relpath(full_p, storage_base).replace('\\', '/')
                pb = progress_map.get(rel_p, None)

                # Clean episode title (e.g. S01E01 -> EP 01)
                clean_title = os.path.splitext(f)[0]
                ep_match = re.search(r'E(\d{1,3})', clean_title, re.IGNORECASE)
                ep_badge = f"EP {int(ep_match.group(1)):02d}" if ep_match else ""

                episodes.append({
                    "name": f,
                    "title": clean_title,
                    "ep_badge": ep_badge,
                    "path": rel_p,
                    "thumb_url": f"/api/cinema/thumb?path={rel_p}",
                    "size_bytes": os.path.getsize(full_p) if os.path.exists(full_p) else 0,
                    "playback": pb
                })
    
    def natural_keys(text):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text["name"])]
    
    episodes.sort(key=natural_keys)
    return episodes

init_db()

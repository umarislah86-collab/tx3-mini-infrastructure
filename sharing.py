"""
TX3 Shared Folders Engine (Multi-Choice & Windows Explorer Tree Browser)
Supports single or multiple selected folders, virtual root mapping,
interactive deep directory browsing, zip downloads, and password protection.
"""

import os
import sys
import json
import time
import sqlite3
import hashlib
import mimetypes
import urllib.parse
from pathlib import Path
import io
import zipfile

SHARES_DB = '/opt/tx3-vault/shares.db'
BASE_STORAGE = '/shares'
IGNORED_NAMES = {
    '$RECYCLE.BIN', 'System Volume Information', '.git', '.DS_Store', 
    'Thumbs.db', 'pagefile.sys', 'DumpStack.log.tmp', 'msdownld.tmp'
}

def get_db():
    conn = sqlite3.connect(SHARES_DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                share_token TEXT UNIQUE NOT NULL,
                folder_path TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                password_hash TEXT DEFAULT NULL,
                expires_at INTEGER DEFAULT 0,
                allow_zip INTEGER DEFAULT 1,
                views_count INTEGER DEFAULT 0,
                downloads_count INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_share_token ON shares(share_token)')
        conn.commit()

init_db()

def get_share_folder_paths(share):
    raw = share.get('folder_path', '')
    if raw.startswith('['):
        try:
            paths = json.loads(raw)
            if isinstance(paths, list):
                return [p for p in paths if os.path.exists(p)]
        except Exception:
            pass
    if os.path.exists(raw):
        return [raw]
    return []

def create_share(folder_paths, title=None, password=None, expires_days=0, allow_zip=True):
    if isinstance(folder_paths, str):
        folder_paths = [folder_paths]

    valid_paths = []
    for fp in folder_paths:
        abs_p = os.path.abspath(fp)
        # Ensure inside /shares
        try:
            if os.path.commonpath([BASE_STORAGE, abs_p]) == BASE_STORAGE and os.path.isdir(abs_p):
                valid_paths.append(abs_p)
        except Exception:
            continue

    if not valid_paths:
        raise ValueError("Tiada folder sah yang dipilih dalam /shares.")

    # Generate short unique token
    random_bytes = os.urandom(8)
    share_token = f"s_{hashlib.sha256(random_bytes + str(time.time()).encode()).hexdigest()[:10]}"

    if not title:
        if len(valid_paths) == 1:
            title = os.path.basename(valid_paths[0].rstrip('/\\')) or "Shared Folder"
        else:
            title = f"Perkongsian {len(valid_paths)} Folder"

    pwd_hash = hashlib.sha256(password.strip().encode()).hexdigest() if (password and password.strip()) else None
    expires_at = int(time.time()) + (int(expires_days) * 86400) if expires_days and int(expires_days) > 0 else 0
    stored_path = json.dumps(valid_paths) if len(valid_paths) > 1 else valid_paths[0]

    with get_db() as conn:
        conn.execute('''
            INSERT INTO shares (share_token, folder_path, title, password_hash, expires_at, allow_zip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (share_token, stored_path, title, pwd_hash, expires_at, 1 if allow_zip else 0, int(time.time())))
        conn.commit()

    return get_share(share_token)

def delete_share(share_token):
    with get_db() as conn:
        cursor = conn.execute('DELETE FROM shares WHERE share_token = ?', (share_token,))
        conn.commit()
        return cursor.rowcount > 0

def list_all_shares():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM shares ORDER BY created_at DESC').fetchall()
        result = []
        now = time.time()
        for r in rows:
            d = dict(r)
            d['is_expired'] = (d['expires_at'] > 0 and d['expires_at'] < now)
            d['has_password'] = bool(d['password_hash'])
            del d['password_hash']
            d['folder_count'] = len(get_share_folder_paths(d))
            result.append(d)
        return result

def get_share(share_token):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM shares WHERE share_token = ?', (share_token,)).fetchone()
        if not row:
            return None
        d = dict(row)
        now = time.time()
        d['is_expired'] = (d['expires_at'] > 0 and d['expires_at'] < now)
        d['has_password'] = bool(d['password_hash'])
        d['folder_paths'] = get_share_folder_paths(d)
        return d

def record_view(share_token):
    with get_db() as conn:
        conn.execute('UPDATE shares SET views_count = views_count + 1 WHERE share_token = ?', (share_token,))
        conn.commit()

def record_download(share_token):
    with get_db() as conn:
        conn.execute('UPDATE shares SET downloads_count = downloads_count + 1 WHERE share_token = ?', (share_token,))
        conn.commit()

def verify_share_password(share_token, password):
    share = get_share(share_token)
    if not share or not share['has_password']:
        return True
    if not password:
        return False
    pwd_hash = hashlib.sha256(password.strip().encode()).hexdigest()
    return hmac_compare(pwd_hash, share.get('password_hash') or '')

def hmac_compare(a, b):
    import hmac
    return hmac.compare_digest(a, b)

def resolve_shared_path(share, subpath=''):
    """
    Resolves virtual subpath into actual filesystem path.
    For single folder: subpath is relative to folder_path.
    For multi folder:
       subpath = "" -> virtual root (returns None)
       subpath = "idx" -> root of folder_paths[idx]
       subpath = "idx/rest/of/path" -> folder_paths[idx]/rest/of/path
    """
    paths = share.get('folder_paths') or get_share_folder_paths(share)
    if not paths:
        return None

    clean_sub = subpath.strip('/').replace('\\', '/')

    if len(paths) == 1:
        base_folder = os.path.abspath(paths[0])
        target_abs = os.path.abspath(os.path.join(base_folder, clean_sub))
        try:
            if os.path.commonpath([base_folder, target_abs]) != base_folder:
                return None
        except ValueError:
            return None
        return target_abs if os.path.exists(target_abs) else None
    else:
        # Multi-folder share
        if not clean_sub:
            return None  # Virtual root
        parts = clean_sub.split('/', 1)
        try:
            folder_idx = int(parts[0])
            if folder_idx < 0 or folder_idx >= len(paths):
                return None
            base_folder = os.path.abspath(paths[folder_idx])
            sub_part = parts[1] if len(parts) > 1 else ''
            target_abs = os.path.abspath(os.path.join(base_folder, sub_part))
            if os.path.commonpath([base_folder, target_abs]) != base_folder:
                return None
            return target_abs if os.path.exists(target_abs) else None
        except (ValueError, IndexError):
            return None

def list_folder_contents(share, subpath=''):
    paths = share.get('folder_paths') or get_share_folder_paths(share)
    if not paths:
        return None

    clean_sub = subpath.strip('/').replace('\\', '/')

    # Multi-folder root: display the chosen folders
    if len(paths) > 1 and not clean_sub:
        items = []
        for idx, fp in enumerate(paths):
            name = os.path.basename(fp.rstrip('/\\')) or f"Folder {idx+1}"
            items.append({
                'name': name,
                'rel_path': str(idx),
                'is_dir': True,
                'type': 'folder',
                'size': 0,
                'mtime': int(os.path.getmtime(fp)) if os.path.exists(fp) else 0,
                'mime': 'application/octet-stream'
            })
        return {
            'share_title': share['title'],
            'current_subpath': '',
            'is_virtual_root': True,
            'folder_names': [os.path.basename(p.rstrip('/' + chr(92))) for p in paths],
            'items': items,
            'allow_zip': bool(share.get('allow_zip', 1))
        }

    # Otherwise resolve directory
    target_abs = resolve_shared_path(share, subpath)
    if not target_abs or not os.path.isdir(target_abs):
        return None

    items = []
    try:
        entries = sorted(os.scandir(target_abs), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            name = entry.name
            if name in IGNORED_NAMES or name.startswith('.'):
                continue

            # Compute virtual rel_path
            if len(paths) == 1:
                rel_to_base = os.path.relpath(entry.path, paths[0]).replace('\\', '/')
            else:
                parts = clean_sub.split('/', 1)
                idx = parts[0]
                rel_to_sub = os.path.relpath(entry.path, paths[int(idx)]).replace('\\', '/')
                rel_to_base = f"{idx}/{rel_to_sub}".replace('\\', '/')

            is_dir = entry.is_dir()
            size = 0
            mtime = 0
            try:
                stat = entry.stat()
                size = stat.st_size if not is_dir else 0
                mtime = int(stat.st_mtime)
            except Exception:
                pass

            mime = 'application/octet-stream'
            file_type = 'folder' if is_dir else 'file'

            if not is_dir:
                guessed, _ = mimetypes.guess_type(entry.name)
                if guessed:
                    mime = guessed
                    if guessed.startswith('image/'):
                        file_type = 'image'
                    elif guessed.startswith('video/'):
                        file_type = 'video'
                    elif guessed.startswith('audio/'):
                        file_type = 'audio'
                    elif 'pdf' in guessed or 'document' in guessed or 'text' in guessed:
                        file_type = 'document'
                    elif 'zip' in guessed or 'tar' in guessed or 'rar' in guessed or 'compressed' in guessed:
                        file_type = 'archive'

            items.append({
                'name': name,
                'rel_path': rel_to_base,
                'is_dir': is_dir,
                'type': file_type,
                'size': size,
                'mtime': mtime,
                'mime': mime
            })
    except Exception as e:
        print(f"Error scanning shared folder {target_abs}: {e}")

    return {
        'share_title': share['title'],
        'current_subpath': clean_sub,
        'is_virtual_root': False,
        'folder_names': [os.path.basename(p.rstrip('/' + chr(92))) for p in paths],
        'items': items,
        'allow_zip': bool(share.get('allow_zip', 1))
    }

def browse_directory_tree(req_path='/shares/3TB-ext'):
    """
    Windows Explorer style backend: returns subfolders in the requested directory,
    along with clickable breadcrumb trail.
    """
    if not req_path or req_path in ('/', '\\', 'root'):
        req_path = BASE_STORAGE

    abs_target = os.path.abspath(req_path)
    # Security boundary: must stay within /shares
    try:
        if os.path.commonpath([BASE_STORAGE, abs_target]) != BASE_STORAGE:
            abs_target = BASE_STORAGE
    except ValueError:
        abs_target = BASE_STORAGE

    if not os.path.exists(abs_target) or not os.path.isdir(abs_target):
        abs_target = BASE_STORAGE

    # Build breadcrumbs
    # e.g. /shares/3TB-ext/Pictures/Japan -> [ { name: "Storage", path: "/shares" }, { name: "3TB-ext", ... } ]
    rel_from_base = os.path.relpath(abs_target, BASE_STORAGE).replace('\\', '/')
    crumbs = [{'name': 'TX3-Storage', 'path': BASE_STORAGE}]
    
    if rel_from_base != '.':
        parts = rel_from_base.split('/')
        accum = BASE_STORAGE
        for p in parts:
            accum = os.path.join(accum, p)
            crumbs.append({'name': p, 'path': accum.replace('\\', '/')})

    # List subfolders
    subfolders = []
    try:
        entries = sorted(os.scandir(abs_target), key=lambda e: e.name.lower())
        for entry in entries:
            if entry.is_dir() and entry.name not in IGNORED_NAMES and not entry.name.startswith('.'):
                # Count children subfolders
                child_count = 0
                try:
                    for _ in os.scandir(entry.path):
                        child_count += 1
                except Exception:
                    pass
                subfolders.append({
                    'name': entry.name,
                    'abs_path': entry.path.replace('\\', '/'),
                    'item_count': child_count
                })
    except Exception as e:
        print(f"Error scanning browse tree: {e}")

    # Parent path for 'Up' button
    parent_path = None
    if abs_target != BASE_STORAGE:
        parent_path = os.path.dirname(abs_target).replace('\\', '/')

    return {
        'current_path': abs_target.replace('\\', '/'),
        'display_path': 'Z:\\' + os.path.relpath(abs_target, BASE_STORAGE).replace('/', '\\').replace('.', ''),
        'parent_path': parent_path,
        'breadcrumbs': crumbs,
        'folders': subfolders
    }

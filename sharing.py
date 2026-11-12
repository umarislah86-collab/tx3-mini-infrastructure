"""
TX3 Shared Folders Engine (Read-Only Cloud Sharing)
Allows sharing any folder inside /shares with a unique token,
optional password protection, expiry, in-browser media previews,
file downloads, and zip downloads.
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

def create_share(folder_path, title=None, password=None, expires_days=0, allow_zip=True):
    abs_path = os.path.abspath(folder_path)
    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        raise ValueError(f"Folder tidak wujud: {folder_path}")

    # Generate short unique token
    random_bytes = os.urandom(8)
    share_token = f"s_{hashlib.sha256(random_bytes + str(time.time()).encode()).hexdigest()[:10]}"

    if not title:
        title = os.path.basename(abs_path.rstrip('/\\')) or "Shared Folder"

    pwd_hash = hashlib.sha256(password.strip().encode()).hexdigest() if (password and password.strip()) else None
    expires_at = int(time.time()) + (int(expires_days) * 86400) if expires_days and int(expires_days) > 0 else 0

    with get_db() as conn:
        conn.execute('''
            INSERT INTO shares (share_token, folder_path, title, password_hash, expires_at, allow_zip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (share_token, abs_path, title, pwd_hash, expires_at, 1 if allow_zip else 0, int(time.time())))
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
    base_folder = os.path.abspath(share['folder_path'])
    clean_sub = subpath.strip('/').replace('\\', '/')
    target_abs = os.path.abspath(os.path.join(base_folder, clean_sub))

    # Security check: MUST be inside base_folder!
    try:
        common = os.path.commonpath([base_folder, target_abs])
        if common != base_folder:
            return None
    except ValueError:
        return None

    if not os.path.exists(target_abs):
        return None

    return target_abs

def list_folder_contents(share, subpath=''):
    target_abs = resolve_shared_path(share, subpath)
    if not target_abs or not os.path.isdir(target_abs):
        return None

    base_folder = os.path.abspath(share['folder_path'])
    items = []

    try:
        entries = sorted(os.scandir(target_abs), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            name = entry.name
            if name in IGNORED_NAMES or name.startswith('.'):
                continue

            rel_to_base = os.path.relpath(entry.path, base_folder).replace('\\', '/')
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
        'current_subpath': subpath.strip('/'),
        'items': items,
        'allow_zip': bool(share.get('allow_zip', 1))
    }

def browse_storage_tree(root_path='/shares/3TB-ext'):
    """Used by Admin to pick a folder to share"""
    abs_root = os.path.abspath(root_path)
    if not os.path.exists(abs_root) or not os.path.isdir(abs_root):
        return []

    result = []
    try:
        for entry in sorted(os.scandir(abs_root), key=lambda e: e.name.lower()):
            if entry.is_dir() and entry.name not in IGNORED_NAMES and not entry.name.startswith('.'):
                result.append({
                    'name': entry.name,
                    'abs_path': entry.path,
                    'rel_path': os.path.relpath(entry.path, '/shares').replace('\\', '/')
                })
    except Exception:
        pass
    return result

#!/usr/bin/python3
"""Theme Studio discover: browse community Omarchy themes that are not installed yet.

  discover.py list [--refresh]   catalog + install state, one JSON object
  discover.py thumbs [--limit N] cache preview thumbnails for catalog themes
  discover.py install <id> [--apply]
                                 stream importer.py JSON lines for that theme's repo

Errors print {"ok": false, "error": "..."} and exit 1.
"""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
HERE = Path(__file__).resolve().parent
THEMES = HOME / '.config/omarchy/themes'
MANIFEST = HOME / '.local/share/omarchy-community-themes/manifest.json'
CACHE = HOME / '.cache/omarchy-theme-studio/discover'
CATALOG = CACHE / 'catalog.json'
OFFICIAL = CACHE / 'official.json'
FAILED = CACHE / 'thumb-failures.json'
THUMBS = CACHE / 'thumbs'
CATALOG_URL = 'https://raw.githubusercontent.com/limehawk/omarchy-theme-website/main/src/data/themes-data.json'
OFFICIAL_URL = 'https://omarchy.org/themes/'
UA = 'Mozilla/5.0 (X11; Linux x86_64) OmarchyThemeStudio/1.0'
TTL = 6 * 3600
FAIL_RETRY = 24 * 3600
MAX_CATALOG = 32 * 1024 * 1024
MAX_PAGE = 4 * 1024 * 1024
MAX_THUMB = 12 * 1024 * 1024
THUMB_HOSTS = {'raw.githubusercontent.com', 'user-images.githubusercontent.com', 'objects.githubusercontent.com',
               'private-user-images.githubusercontent.com'}
# github.com/user-attachments/* 302s to GitHub's signed S3 bucket; allowed only as a redirect target.
S3_ASSET = re.compile(r'^github-production-user-asset-[0-9a-f]+\.s3\.amazonaws\.com$')
REPO_RE = re.compile(r'^https?://(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$')
HEX_RE = re.compile(r'^#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$')
ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')


class Fail(Exception):
    pass


def out(obj):
    print(json.dumps(obj), flush=True)


def fail(msg):
    out({'ok': False, 'error': str(msg)[:300]})
    sys.exit(1)


# ---------------------------------------------------------------- helpers

def clean(text, limit):
    """Plain single-line text: no control/format chars, collapsed whitespace, bounded."""
    if not isinstance(text, str):
        return ''
    text = re.sub(r'<[^>]{0,200}>', ' ', text[:limit * 4])
    text = ''.join(c if unicodedata.category(c)[0] not in 'CZ' else ' ' for c in text)
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def repo_url(url):
    """Normalized https://github.com/owner/repo for a plain repo root, else None."""
    m = REPO_RE.match((url or '').strip()) if isinstance(url, str) else None
    if not m or m.group(2) in ('.', '..'):
        return None
    return f'https://github.com/{m.group(1)}/{m.group(2)}'


def repo_key(url):
    r = repo_url(url) if url and '@' not in url else None
    if not r and isinstance(url, str):  # git@github.com:o/r(.git)
        m = re.match(r'^git@github\.com:([\w.-]+)/([\w.-]+?)(?:\.git)?/?$', url.strip())
        r = m and f'https://github.com/{m.group(1)}/{m.group(2)}'
    return r.lower() if r else None


def hexcolor(v):
    m = HEX_RE.match(v.strip()) if isinstance(v, str) else None
    return '#' + m.group(1).lower() if m else ''


def luminance(hx):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hx[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def jloads(v, default):
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v) if isinstance(v, str) else default
    except ValueError:
        return default


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def thumb_name(tid):
    return (tid if ID_RE.match(tid) else hashlib.sha1(tid.encode()).hexdigest()[:20]) + '.jpg'


# ---------------------------------------------------------------- network

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow):
        self.allow = allow

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.allow(newurl, redirect=True):
            raise Fail('redirected to a disallowed host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit, timeout=30, allow=None):
    opener = urllib.request.build_opener(SafeRedirect(allow)) if allow else urllib.request.build_opener()
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    deadline = time.monotonic() + timeout
    with opener.open(req, timeout=timeout) as r:
        if int(r.headers.get('Content-Length') or 0) > limit:
            raise Fail('too large')
        buf = bytearray()
        while chunk := r.read(65536):
            buf += chunk
            if len(buf) > limit:
                raise Fail('too large')
            if time.monotonic() > deadline:
                raise Fail('timed out')
        return bytes(buf)


def parse_catalog(data):
    rows = json.loads(data)
    if not isinstance(rows, list) or not any(isinstance(r, dict) and r.get('github_url') for r in rows):
        raise Fail('catalog has an unexpected format')
    return rows


def refresh():
    data = fetch(CATALOG_URL, MAX_CATALOG, timeout=40)
    parse_catalog(data)  # only replace the cache after it parses
    atomic_write(CATALOG, data)
    try:
        page = fetch(OFFICIAL_URL, MAX_PAGE, timeout=20).decode('utf-8', 'replace')
        repos = sorted({k for u in re.findall(r'https://github\.com/[\w.-]+/[\w.-]+', page) if (k := repo_key(u))})
        if repos:
            atomic_write(OFFICIAL, json.dumps(repos))
    except Exception:
        pass  # keep the previous official list


def load_catalog(force):
    stale = False
    try:
        age = time.time() - CATALOG.stat().st_mtime
    except OSError:
        age = None
    if force or age is None or age > TTL:
        try:
            refresh()
        except Exception as e:
            if age is None:
                raise Fail(f'Could not download the theme catalog: {getattr(e, "reason", None) or e}')
            stale = True
    try:
        rows = parse_catalog(CATALOG.read_bytes())
    except (OSError, ValueError, Fail) as e:
        raise Fail(f'Theme catalog cache is unreadable: {e}')
    return rows, int(CATALOG.stat().st_mtime), stale


# ---------------------------------------------------------------- install state

def git_origin(path):
    """origin URL from .git/config without spawning git; falls back to git for odd layouts."""
    cfg = path / '.git' / 'config'
    try:
        text = cfg.read_text(errors='replace')
        m = re.search(r'\[remote "origin"\][^\[]*?^\s*url\s*=\s*(\S+)', text, re.M | re.S)
        return m.group(1) if m else ''
    except OSError:
        r = subprocess.run(['git', '-C', str(path), 'remote', 'get-url', 'origin'], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()


def installed_map():
    found = {}
    try:
        dirs = [d for d in THEMES.iterdir() if d.is_dir()]
    except OSError:
        dirs = []
    names = {d.name for d in dirs}
    try:
        for t in json.loads(MANIFEST.read_text()).get('themes', []):
            k, slug = repo_key(t.get('url')), 'gallery-' + str(t.get('slug', ''))
            if k and slug in names:
                found.setdefault(k, slug)
    except (OSError, ValueError, AttributeError):
        pass
    for d in sorted(dirs):
        try:
            k = repo_key(json.loads((d / '.theme-studio').read_text()).get('source'))
            if k:
                found[k] = d.name
        except (OSError, ValueError, AttributeError):
            pass
        if (d / '.git').exists() and (k := repo_key(git_origin(d))):
            found[k] = d.name
    return found


# ---------------------------------------------------------------- list

def themes(rows, official, installed, thumbs):
    seen, res = set(), []
    for r in rows:
        if not isinstance(r, dict) or r.get('is_builtin'):
            continue
        repo = repo_url(r.get('github_url'))
        tid = r.get('id')
        if not repo or not isinstance(tid, str) or not tid or len(tid) > 120 or tid in seen:
            continue
        seen.add(tid)
        cols = jloads(r.get('colors_json'), {})
        cols = cols if isinstance(cols, dict) else {}
        pal = [hexcolor(cols.get(k)) for k in ('background', 'foreground', 'accent', 'color1', 'color2')]
        bg = pal[0] or hexcolor(cols.get('color0'))
        warns = jloads(r.get('security_warnings'), [])
        warns = [clean(w, 160) for w in warns[:8] if isinstance(w, str)] if isinstance(warns, list) else []
        stars = r.get('stars')
        key = repo.lower()
        tn = thumb_name(tid)
        res.append({
            'id': tid,
            'name': clean(r.get('name'), 60) or repo.rsplit('/', 1)[1],
            'repo': repo,
            'owner': repo.split('/')[3],
            'stars': stars if isinstance(stars, int) and stars >= 0 else 0,
            'hue': clean(r.get('primary_hue'), 20).lower(),
            'mode': 'light' if bg and luminance(bg) > 0.35 else 'dark',
            'palette': [p for p in pal if p],
            'preview': (THUMBS / tn).as_uri() if tn in thumbs else '',
            'description': clean(r.get('description'), 200),
            'official': key in official,
            'pushed_at': clean(r.get('github_pushed_at'), 40),
            'warnings': [w for w in warns if w],
            'installed': key in installed,
            'installed_slug': installed.get(key, ''),
        })
    res.sort(key=lambda t: (-t['stars'], t['name'].lower()))
    return res


def cmd_list(force):
    rows, fetched, stale = load_catalog(force)
    try:
        official = set(json.loads(OFFICIAL.read_text()))
    except (OSError, ValueError, TypeError):
        official = set()
    try:
        thumbs = set(os.listdir(THUMBS))
    except OSError:
        thumbs = set()
    res = {'ok': True, 'fetched_at': fetched, 'themes': themes(rows, official, installed_map(), thumbs)}
    if stale:
        res['stale'] = True
    out(res)


# ---------------------------------------------------------------- thumbs

def thumb_allowed(url, redirect=False):
    u = urllib.parse.urlparse(url)
    host = (u.hostname or '').lower()
    if u.scheme != 'https':
        return False
    if host in THUMB_HOSTS:
        return True
    if host == 'github.com' and u.path.startswith('/user-attachments/'):
        return True
    return redirect and bool(S3_ASSET.match(host))


def is_image(b):
    return (b[:3] == b'\xff\xd8\xff' or b[:8] == b'\x89PNG\r\n\x1a\n' or b[:6] in (b'GIF87a', b'GIF89a')
            or (b[:4] == b'RIFF' and b[8:12] == b'WEBP') or (b[4:8] == b'ftyp' and b[8:12] in (b'avif', b'avis'))
            or b[:2] == b'BM')


def make_thumb(tid, url):
    u = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(u._replace(path=urllib.parse.quote(u.path, safe="/%@!$&'()*+,;=:~-._")))
    data = fetch(url, MAX_THUMB, timeout=15, allow=thumb_allowed)
    if not is_image(data):
        raise Fail('not an image')
    dest = THUMBS / thumb_name(tid)
    with tempfile.TemporaryDirectory(prefix='discover-', dir=CACHE) as tmp:
        src, jpg = Path(tmp) / 'src', Path(tmp) / 'out.jpg'
        src.write_bytes(data)
        subprocess.run(['magick', str(src) + '[0]', '-resize', '360x220^', '-gravity', 'center', '-extent', '360x220',
                        '-quality', '82', 'jpg:' + str(jpg)], capture_output=True, timeout=60, check=True)
        if not jpg.is_file() or jpg.stat().st_size < 100:
            raise Fail('conversion failed')
        os.replace(jpg, dest)


def cmd_thumbs(limit):
    rows, _, _ = load_catalog(False)
    THUMBS.mkdir(parents=True, exist_ok=True)
    lock = open(CACHE / '.thumbs.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        out({'ok': True, 'made': 0, 'failed': 0, 'busy': True})
        return
    try:
        failed = json.loads(FAILED.read_text())
        failed = failed if isinstance(failed, dict) else {}
    except (OSError, ValueError):
        failed = {}
    have, now, todo = set(os.listdir(THUMBS)), time.time(), []
    previews = {r.get('id'): r.get('preview_url') for r in rows if isinstance(r, dict)}
    for t in themes(rows, set(), {}, set()):
        url = previews.get(t['id'])
        if thumb_name(t['id']) in have or not isinstance(url, str) or not thumb_allowed(url.strip()):
            continue
        if now - float(failed.get(t['id'], 0) or 0) < FAIL_RETRY:
            continue
        todo.append((t['id'], url.strip()))
    if limit is not None:
        todo = todo[:max(0, limit)]
    made = bad = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(make_thumb, tid, url): tid for tid, url in todo}
        for job in concurrent.futures.as_completed(jobs):
            try:
                job.result()
                made += 1
                failed.pop(jobs[job], None)
            except Exception:
                bad += 1
                failed[jobs[job]] = now
    atomic_write(FAILED, json.dumps(failed))
    out({'ok': True, 'made': made, 'failed': bad})


# ---------------------------------------------------------------- install

def cmd_install(tid, apply):
    rows, _, _ = load_catalog(False)
    match = next((t for t in themes(rows, set(), {}, set()) if t['id'] == tid), None)
    if not match:
        raise Fail('That theme is not in the catalog')
    args = ['/usr/bin/python3', str(HERE / 'importer.py'), 'install', match['repo']] + (['--apply'] if apply else [])
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    last = None
    for line in p.stdout:
        line = line.strip()
        if line:
            print(line, flush=True)
            last = line
    code = p.wait()
    try:
        final = json.loads(last) if last else {}
    except ValueError:
        final = {}
    if 'ok' not in final:
        out({'ok': False, 'error': 'The installer stopped unexpectedly'})
        sys.exit(1)
    sys.exit(0 if final.get('ok') and code == 0 else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list').add_argument('--refresh', action='store_true')
    sub.add_parser('thumbs').add_argument('--limit', type=int)
    p = sub.add_parser('install')
    p.add_argument('id')
    p.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    try:
        if a.cmd == 'list':
            cmd_list(a.refresh)
        elif a.cmd == 'thumbs':
            cmd_thumbs(a.limit)
        else:
            cmd_install(a.id, a.apply)
    except Fail as e:
        fail(e)
    except Exception as e:
        fail(f'Discover failed: {getattr(e, "reason", None) or e}')


if __name__ == '__main__':
    main()

#!/usr/bin/python3
"""Theme Studio wallpaper catalog: openly licensed wallpapers from Openverse.

  wallpapers.py search [<query>] [--page N]
  wallpapers.py save <id> [--theme <slug>] [--apply]
  wallpapers.py suggestions

Each call prints exactly one JSON object; failures are {"ok": false, "error": ...}
with exit status 1. Search responses are cached for 24 h (stale cache is served
when Openverse rate-limits), thumbnails are cached as 360x220 JPEGs, and saved
wallpapers land in ~/.config/omarchy/backgrounds/<theme>/ with a CREDITS.md entry.
"""
import argparse
import colorsys
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
CACHE = HOME / '.cache/omarchy-theme-studio/wallpapers'
SEARCH_CACHE = CACHE / 'search'
THUMBS = CACHE / 'thumbs'
BACKGROUNDS = HOME / '.config/omarchy/backgrounds'
CURRENT = HOME / '.local/state/omarchy/current'
API = 'https://api.openverse.org/v1/images/'
UA = 'OmarchyThemeStudio/1.0 (https://omarchy.org; personal desktop wallpaper browser)'
SEARCH_TTL = 24 * 3600
FAIL_TTL = 600
THUMB_MAX = 8 * 1024 * 1024
FULL_MAX = 40 * 1024 * 1024
DEFAULT_QUERY = 'landscape'
ID_RE = re.compile(r'^[A-Za-z0-9-]{8,64}$')
THEME_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9._+-]*$')
KEEP_TYPES = {'jpg', 'jpeg', 'png', 'webp'}
FIXED = ['mountains', 'forest fog', 'space nebula', 'minimal abstract', 'desert dunes']
EXTRA = ['northern lights', 'ocean waves', 'night sky stars']


class Fail(Exception):
    pass


# ---------------------------------------------------------------- helpers

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def clean(text, limit):
    text = html.unescape(re.sub(r'<[^>]*>', ' ', str(text or '')))
    text = re.sub(r'[\x00-\x1f\x7f]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def nice_title(r):
    t = re.sub(r'^File:', '', str(r.get('title') or ''), flags=re.I)
    t = re.sub(r'\.(jpe?g|png|webp|tiff?|gif)$', '', t, flags=re.I).replace('_', ' ')
    return clean(t, 90) or 'Untitled'


def license_label(r):
    lic, ver = str(r.get('license') or '').lower(), str(r.get('license_version') or '').strip()
    if lic == 'cc0':
        return 'CC0'
    if lic == 'pdm':
        return 'Public domain'
    base = 'CC ' + lic.upper()
    return f'{base} {ver}' if ver and ver.upper() != 'N/A' else base


def image_kind(head):
    if head[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    return None


class HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != 'https':
            raise Fail('refused redirect to a non-https address')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(HttpsOnly)


def download(url, limit, timeout, deadline=None):
    """Stream an https URL into memory with a byte cap and an overall deadline."""
    if urllib.parse.urlparse(url).scheme != 'https':
        raise Fail('only https downloads are allowed')
    end = time.monotonic() + (deadline or timeout)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with OPENER.open(req, timeout=timeout) as r:
        if int(r.headers.get('Content-Length') or 0) > limit:
            raise Fail(f'image is larger than {limit // 1048576} MB')
        chunks, size = [], 0
        while True:
            if time.monotonic() > end:
                raise Fail('download timed out')
            block = r.read(65536)
            if not block:
                break
            size += len(block)
            if size > limit:
                raise Fail(f'image is larger than {limit // 1048576} MB')
            chunks.append(block)
    return b''.join(chunks)


def wikimedia_thumb(url, width):
    """upload.wikimedia.org original -> server-rendered thumbnail of a standard width."""
    u = urllib.parse.urlparse(url)
    m = re.match(r'^(/wikipedia/[^/]+)/([0-9a-f]/[0-9a-f]{2})/([^/]+)$', u.path)
    if u.netloc != 'upload.wikimedia.org' or not m:
        return None
    name = m.group(3)
    ext = name.rsplit('.', 1)[-1].lower()
    if ext in KEEP_TYPES:
        prefix, suffix = '', ''
    elif ext in ('tif', 'tiff'):
        prefix, suffix = 'lossy-page1-', '.jpg'
    else:
        return None
    return f'https://upload.wikimedia.org{m.group(1)}/thumb/{m.group(2)}/{name}/{prefix}{width}px-{name}{suffix}'


# ---------------------------------------------------------------- search

def cache_file(query, page):
    key = hashlib.sha256(f'{query}\n{page}'.encode()).hexdigest()[:24]
    return SEARCH_CACHE / f'{key}.json'


def fetch_search(query, page):
    path = cache_file(query, page)
    cached = None
    try:
        cached = json.loads(path.read_text())
        if time.time() - cached.get('fetched', 0) < SEARCH_TTL:
            return cached, False
    except Exception:
        cached = None
    params = urllib.parse.urlencode({'q': query, 'license': 'cc0,pdm,by,by-sa', 'aspect_ratio': 'wide',
                                     'size': 'large', 'page_size': 20, 'page': page, 'mature': 'false'})
    try:
        data = json.loads(download(f'{API}?{params}', 4 * 1024 * 1024, 45, 50))
    except urllib.error.HTTPError as e:
        if cached:
            return cached, True
        if e.code == 429:
            wait = e.headers.get('Retry-After')
            raise Fail('Openverse rate limit reached (anonymous: 20 searches/min, 200/day). '
                       + (f'Try again in {wait} s.' if wait else 'Try again shortly.'))
        if e.code in (400, 404) and page > 1:
            return {'query': query, 'page': page, 'page_count': page - 1, 'results': [], 'fetched': time.time()}, False
        raise Fail(f'Openverse is having trouble (HTTP {e.code}); try again in a moment')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if cached:
            return cached, True
        raise Fail(f'Openverse is unreachable ({getattr(e, "reason", e)})')
    entry = {'query': query, 'page': page, 'page_count': int(data.get('page_count') or 0),
             'results': data.get('results') or [], 'fetched': time.time()}
    atomic_write(path, json.dumps(entry))
    return entry, False


def usable(r):
    try:
        w, h = int(r.get('width') or 0), int(r.get('height') or 0)
    except (TypeError, ValueError):
        return False
    if w < 1920 or w <= h or not ID_RE.match(str(r.get('id') or '')):
        return False
    url = str(r.get('url') or '')
    if not url.startswith('https://'):
        return False
    ftype = str(r.get('filetype') or url.rsplit('.', 1)[-1]).lower()
    return ftype in KEEP_TYPES or wikimedia_thumb(url, 500) is not None


WIKI_SLOTS = threading.Semaphore(3)


def fetch_thumb(url):
    """Wikimedia throttles thumbnail renders per client: fewer parallel requests, two polite retries."""
    if urllib.parse.urlparse(url).netloc != 'upload.wikimedia.org':
        return download(url, THUMB_MAX, 12, 12)
    for attempt in range(3):
        try:
            with WIKI_SLOTS:
                return download(url, THUMB_MAX, 12, 12)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            try:
                wait = float(e.headers.get('Retry-After') or 2)
            except ValueError:
                wait = 2
            time.sleep(min(wait, 5))


def make_thumb(r):
    rid = r['id']
    out, fail = THUMBS / f'{rid}.jpg', THUMBS / f'{rid}.fail'
    if out.is_file():
        return out
    try:
        if time.time() - fail.stat().st_mtime < FAIL_TTL:
            return None
    except OSError:
        pass
    url = str(r.get('url') or '')
    candidates = []
    wm = wikimedia_thumb(url, 500)
    if wm:  # Openverse's thumb proxy 424s (often after 5-25 s) on Wikimedia files; ask Wikimedia directly
        candidates.append(wm)
    elif str(r.get('thumbnail') or '').startswith('https://'):
        candidates.append(r['thumbnail'])
    candidates.append(url)
    THUMBS.mkdir(parents=True, exist_ok=True)
    for c in dict.fromkeys(candidates):
        try:
            data = fetch_thumb(c)
            if not image_kind(data[:16]):
                continue
            with tempfile.TemporaryDirectory(dir=THUMBS, prefix='.dl-') as tmp:
                src, dst = Path(tmp) / 'src', Path(tmp) / 'thumb.jpg'
                src.write_bytes(data)
                subprocess.run(['magick', f'{src}[0]', '-resize', '360x220^', '-gravity', 'center',
                                '-extent', '360x220', '-strip', '-quality', '80', str(dst)],
                               capture_output=True, timeout=30, check=True)
                os.replace(dst, out)
            fail.unlink(missing_ok=True)
            return out
        except Exception:
            continue
    fail.touch()
    return None


def record(r, thumb):
    return {'id': r['id'], 'title': nice_title(r), 'creator': clean(r.get('creator'), 60) or 'Unknown',
            'license': license_label(r), 'license_url': str(r.get('license_url') or ''),
            'landing': str(r.get('foreign_landing_url') or ''), 'width': int(r['width']),
            'height': int(r['height']), 'thumb': thumb.as_uri() if thumb else '', 'full': r['url']}


def search(query, page):
    query = clean(query, 120).lower() or DEFAULT_QUERY
    page = max(1, min(int(page), 50))
    entry, stale = fetch_search(query, page)
    items = [r for r in entry['results'] if usable(r)]
    with ThreadPoolExecutor(6) as pool:
        thumbs = list(pool.map(make_thumb, items))
    out = {'ok': True, 'query': query, 'page': page, 'has_more': page < entry.get('page_count', 0),
           'results': [record(r, t) for r, t in zip(items, thumbs)]}
    if stale:
        out['stale'] = True
    return out


# ---------------------------------------------------------------- save

def find_cached(rid):
    for p in sorted(SEARCH_CACHE.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            for r in json.loads(p.read_text()).get('results', []):
                if r.get('id') == rid:
                    return r
        except Exception:
            continue
    return None


def slugify(text):
    s = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return s[:48].rstrip('-') or 'wallpaper'


def current_theme():
    try:
        return (CURRENT / 'theme.name').read_text().strip()
    except OSError:
        raise Fail('no current Omarchy theme found')


def credit(folder, r, filename):
    path = folder / 'CREDITS.md'
    head = '' if path.is_file() else '# Wallpaper credits\n\nOpenly licensed images saved by Theme Studio from Openverse.\n'
    lic = license_label(r)
    url = str(r.get('license_url') or '')
    entry = (f'\n## {nice_title(r)}\n\n'
             f'- File: `{filename}`\n'
             f'- Creator: {clean(r.get("creator"), 120) or "Unknown"}\n'
             f'- License: {f"[{lic}]({url})" if url else lic}\n'
             f'- Source: {r.get("foreign_landing_url") or r.get("url")}\n'
             f'- Openverse ID: {r["id"]}\n'
             f'- Saved: {time.strftime("%Y-%m-%d")}\n')
    with open(path, 'a', encoding='utf-8') as f:
        f.write(head + entry)


def apply_background(path):
    try:
        res = subprocess.run(['omarchy', 'theme', 'bg', 'set', str(path)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Fail(f'could not apply background: {e}')
    if res.returncode:
        raise Fail('could not apply background: ' + (res.stderr or res.stdout).strip()[-200:])


def save(rid, theme, apply):
    if not ID_RE.match(rid or ''):
        raise Fail('invalid wallpaper id')
    theme = theme or current_theme()
    if not THEME_RE.match(theme):
        raise Fail('invalid theme name')
    r = find_cached(rid)
    if not r:
        raise Fail('unknown wallpaper id (search for it first)')
    folder = BACKGROUNDS / theme
    existing = sorted(p for p in folder.glob(f'*-{rid[:8]}.*') if p.suffix.lower() in ('.jpg', '.png', '.webp')) if folder.is_dir() else []
    if existing:
        path = existing[0]
    else:
        url = str(r.get('url') or '')
        candidates = [url] if str(r.get('filetype') or url.rsplit('.', 1)[-1]).lower() in KEEP_TYPES else []
        wm = wikimedia_thumb(url, 3840)
        if wm:
            candidates.append(wm)
        data, kind, errors = None, None, []
        for c in candidates:
            try:
                data = download(c, FULL_MAX, 30, 60)
                kind = image_kind(data[:16])
                if kind in KEEP_TYPES:
                    break
                errors.append('not a JPEG/PNG/WebP image')
            except (Fail, urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(str(getattr(e, 'reason', e)))
            data = kind = None
        if not data:
            raise Fail('download failed: ' + ('; '.join(errors) or 'no usable source'))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{slugify(nice_title(r))}-{rid[:8]}.{kind}'
        atomic_write(path, data)
        credit(folder, r, path.name)
    if apply:
        apply_background(path)
    return {'ok': True, 'path': str(path), 'applied': bool(apply)}


# ---------------------------------------------------------------- suggestions

def suggestions():
    derived = []
    try:
        import tomllib
        c = tomllib.loads((CURRENT / 'theme/colors.toml').read_text())
        hexv = str(c.get('accent') or '').lstrip('#')
        rgb = [int(hexv[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        h, l, s = colorsys.rgb_to_hls(*rgb)
        hue = h * 360
        if s < 0.12:
            derived = ['misty monochrome', 'black and white landscape']
        elif hue < 15 or hue >= 345:
            derived = ['red canyon', 'crimson sunset']
        elif hue < 40:
            derived = ['orange sunset', 'autumn leaves']
        elif hue < 65:
            derived = ['golden hour field', 'amber dusk']
        elif hue < 160:
            derived = ['green forest', 'moss valley']
        elif hue < 195:
            derived = ['teal ocean', 'turquoise lagoon']
        elif hue < 250:
            derived = ['blue night city', 'blue mountains']
        elif hue < 290:
            derived = ['purple aurora', 'violet twilight']
        else:
            derived = ['pink blossoms', 'pastel sky']
        derived.append('snowy minimal' if str(c.get('mode', '')).lower() == 'light' or l > 0.75 else 'night sky stars')
    except Exception:
        pass
    queries = list(dict.fromkeys(derived[:3] + FIXED + EXTRA))[:8]
    return {'ok': True, 'queries': queries}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('search')
    s.add_argument('query', nargs='*')
    s.add_argument('--page', type=int, default=1)
    v = sub.add_parser('save')
    v.add_argument('id')
    v.add_argument('--theme')
    v.add_argument('--apply', action='store_true')
    sub.add_parser('suggestions')
    try:
        a = p.parse_args()
    except SystemExit as e:
        if e.code:
            print(json.dumps({'ok': False, 'error': 'invalid arguments'}))
        raise
    try:
        if a.cmd == 'search':
            out = search(' '.join(a.query), a.page)
        elif a.cmd == 'save':
            out = save(a.id, a.theme, a.apply)
        else:
            out = suggestions()
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e) or e.__class__.__name__}))
        sys.exit(1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()

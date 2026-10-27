#!/usr/bin/python3
"""Theme Studio importer: install an Omarchy theme from (almost) any link.

Accepts, one per call (images may be several, separated by spaces/newlines):
  * git repos            https://github.com/o/r, gitlab/codeberg URLs, *.git, git@host:o/r
  * theme store pages    omarchy.org/themes/#name, omarchythemes.com/themes/<slug>,
                         or any page that links a single GitHub theme repo
  * archives             .zip / .tar.gz / .tgz / .tar.xz (theme folder or images)
  * images               direct image links, GitHub blob/raw images, Wallhaven /
                         Unsplash / artist pages (og:image), local files or folders
Images become a brand-new theme: a full colors.toml palette is generated from the
artwork and the images become its backgrounds; Omarchy renders everything else
from its templates.

  importer.py inspect <input>
  importer.py install <input> [--name NAME] [--mode auto|dark|light|vivid|soft|midnight] [--apply]
  importer.py profiles <image-path>...   # six palette previews, for testing

Progress is streamed as JSON lines {"progress": "..."}; the last line is the
result {"ok": true, "slug": ..., "name": ..., "kind": ..., "applied": ...} or
{"ok": false, "error": ...}.
"""
import argparse
import colorsys
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path

HOME = Path.home()
THEMES = HOME / '.config/omarchy/themes'
STOCK = Path('/usr/share/omarchy/themes')
THUMBS = HOME / '.cache/omarchy-theme-studio/thumbs'
UA = 'Mozilla/5.0 (X11; Linux x86_64) OmarchyThemeStudio/1.0'
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif', '.heic', '.tif', '.tiff', '.jxl')
KEEP_EXT = ('.jpg', '.jpeg', '.png', '.webp')
ARCHIVE_EXT = ('.zip', '.tar.gz', '.tgz', '.tar.xz', '.txz', '.tar.bz2', '.tar')
MAX_IMAGE = 80 * 1024 * 1024
MAX_ARCHIVE = 400 * 1024 * 1024
MAX_PAGE = 3 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024  # archive contents, total
MAX_ENTRIES = 5000                 # archive members
# Files a downloaded theme may not ship because they run code. Mirrors
# omarchy-theme-set's INSTALLED_THEME_DENIED (+ every .lua), which Omarchy only
# applies to themes that still have a .git folder.
CODE_FILES = ('alacritty.toml', 'foot.ini', 'ghostty.conf', 'kitty.conf', 'vscode.json')
GIT_SAFE = ['-c', 'core.symlinks=false', '-c', 'protocol.file.allow=never', '-c', 'submodule.recurse=false']
NAME_RE = re.compile(r'^[a-z0-9_][a-z0-9._+-]*$')


class Fail(Exception):
    pass


def say(msg):
    print(json.dumps({'progress': msg}), flush=True)


def run(*args, timeout=180, cwd=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    r = subprocess.run(args, text=True, capture_output=True, timeout=timeout, cwd=cwd, env=env)
    if r.returncode:
        raise Fail((r.stderr or r.stdout or f'{args[0]} failed').strip()[-300:])
    return r.stdout.strip()


# ---------------------------------------------------------------- classify

def lower_path(url):
    return urllib.parse.urlparse(url).path.lower()


def is_image_url(url):
    return lower_path(url).endswith(IMAGE_EXT)


def is_archive_url(url):
    p = lower_path(url)
    return p.endswith(ARCHIVE_EXT) or '/archive/refs/' in p or '/zipball/' in p or '/tarball/' in p


def git_repo(url):
    """Return a clone URL when `url` names a git repository, else None."""
    if re.match(r'^[\w.-]+@[\w.-]+:[\w./-]+$', url):
        return url
    u = urllib.parse.urlparse(url)
    if u.scheme not in ('http', 'https', 'ssh', 'git'):
        return None
    parts = [p for p in u.path.split('/') if p]
    host = u.netloc.lower().removeprefix('www.')
    if host in ('github.com', 'codeberg.org', 'gitea.com') and len(parts) >= 2:
        if len(parts) > 2 and parts[2] in ('blob', 'raw', 'releases', 'archive'):
            return None
        return f'https://{host}/{parts[0]}/{parts[1].removesuffix(".git")}'
    if host == 'gitlab.com' and len(parts) >= 2:
        repo = '/'.join(parts[:parts.index('-')] if '-' in parts else parts)
        return f'https://gitlab.com/{repo.removesuffix(".git")}'
    if u.path.endswith('.git'):
        return url
    return None


def github_raw(url):
    u = urllib.parse.urlparse(url)
    parts = [p for p in u.path.split('/') if p]
    if u.netloc.lower() == 'github.com' and len(parts) > 4 and parts[2] in ('blob', 'raw'):
        return f'https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{"/".join(parts[3:])}'
    return url


def tokens(text):
    out = []
    for t in re.split(r'[\s,]+', text.strip()):
        t = t.strip('<>"\'')
        if t:
            out.append(t)
    return out


def local_path(t):
    if t.startswith('file://'):
        t = urllib.parse.unquote(urllib.parse.urlparse(t).path)
    if t.startswith('~'):
        t = os.path.expanduser(t)
    return Path(t) if t.startswith('/') else None


def classify(t):
    p = local_path(t)
    if p is not None:
        if not p.exists():
            raise Fail(f'{p} does not exist')
        if p.is_dir():
            return ('dir', str(p))
        if p.name.lower().endswith(ARCHIVE_EXT):
            return ('archive', str(p))
        if p.suffix.lower() in IMAGE_EXT:
            return ('image', str(p))
        raise Fail(f'{p.name} is not an image, archive or theme folder')
    if not re.match(r'^(https?://|git@|ssh://|git://)', t):
        if re.match(r'^[\w.-]+\.[a-z]{2,}/', t):
            t = 'https://' + t
        else:
            raise Fail('Paste a link (https://…) or a file path')
    url = github_raw(t)
    if '/wiki/' in urllib.parse.urlparse(url).path:  # e.g. commons.wikimedia.org/wiki/File:x.jpg is a page
        return ('page', url)
    if is_image_url(url) or 'raw.githubusercontent.com' in url and is_image_url(url):
        return ('image', url)
    if is_archive_url(url):
        return ('archive', url)
    repo = git_repo(url)
    if repo:
        return ('git', repo)
    return ('page', url)


def describe(kinds):
    k = [x[0] for x in kinds]
    if k == ['git']:
        repo = kinds[0][1].rstrip('/').split('/')
        return f'Theme repo · {"/".join(repo[-2:])}'
    if k == ['archive']:
        return 'Theme archive · ' + Path(urllib.parse.urlparse(kinds[0][1]).path).name
    if k == ['dir']:
        return 'Folder · ' + Path(kinds[0][1]).name
    if k == ['page']:
        return 'Web page · ' + urllib.parse.urlparse(kinds[0][1]).netloc
    n = len(k)
    return f'{n} image{"s" if n != 1 else ""} → new theme'


# ---------------------------------------------------------------- network

def fetch(url, limit, accept=None):
    if urllib.parse.urlparse(url).scheme not in ('https', 'http'):
        raise Fail('Only http(s) links can be downloaded')
    req = urllib.request.Request(url, headers={'User-Agent': UA, **({'Accept': accept} if accept else {})})
    with urllib.request.urlopen(req, timeout=40) as r:
        ctype = r.headers.get('Content-Type', '')
        size = int(r.headers.get('Content-Length') or 0)
        if size and size > limit:
            raise Fail(f'{url} is too large ({size // 1048576} MB)')
        if urllib.parse.urlparse(r.geturl()).scheme not in ('https', 'http'):
            raise Fail('That link redirects somewhere that cannot be downloaded')
        data = r.read(limit + 1)
        if len(data) > limit:
            raise Fail(f'{url} is too large')
        return data, ctype, r.geturl()


class PageScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.links, self.imgs, self.title, self._t = {}, [], [], '', False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            key = (a.get('property') or a.get('name') or '').lower()
            if key and a.get('content'):
                self.meta.setdefault(key, a['content'])
        elif tag == 'a' and a.get('href'):
            self.links.append(a['href'])
        elif tag == 'img':
            src = a.get('src') or a.get('data-src')
            if src:
                self.imgs.append((src, a.get('id', ''), a.get('width', '')))
        elif tag == 'title':
            self._t = True

    def handle_data(self, d):
        if self._t:
            self.title += d

    def handle_endtag(self, tag):
        if tag == 'title':
            self._t = False


def resolve_page(url):
    """Turn a web page into ('git', repo) or a list of image URLs + a title."""
    say('Reading ' + urllib.parse.urlparse(url).netloc + '…')
    data, ctype, final = fetch(url, MAX_PAGE, 'text/html,*/*')
    if ctype.startswith('image/'):
        return 'image-bytes', (data, final), ''
    scan = PageScan()
    scan.feed(data.decode('utf-8', 'replace'))
    title = html.unescape((scan.meta.get('og:title') or scan.title or '').strip())
    host = urllib.parse.urlparse(final).netloc.lower()
    frag = urllib.parse.urlparse(url).fragment.lower()
    repos = []
    for href in scan.links:
        full = urllib.parse.urljoin(final, href)
        r = git_repo(full)
        if r and r.startswith('https://github.com/') and r not in repos:
            owner = r.split('/')[3].lower()
            if owner in ('omacom', 'basecamp', 'sponsors', 'features', 'topics', 'login', 'about'):
                continue
            repos.append(r)
    themey = [r for r in repos if re.search(r'omarchy|theme', r, re.I)]
    if frag:
        want = re.sub(r'[^a-z0-9]', '', frag)
        hit = [r for r in repos if want and want in re.sub(r'[^a-z0-9]', '', r.lower())]
        if hit:
            return 'git', hit[0], title
    if len(themey) == 1 or (len(repos) == 1 and ('theme' in host or 'omarchy' in host or 'theme' in url.lower())):
        return 'git', (themey or repos)[0], title
    if len(themey) > 1 and ('omarchy' in host or 'theme' in host):
        raise Fail('That page lists many themes. Open one theme and paste its link.')
    images = []
    m = re.match(r'https?://(www\.)?unsplash\.com/photos/(?:[^/]*-)?([A-Za-z0-9_-]{11})', final)
    if m:
        images.append(f'https://unsplash.com/photos/{m.group(2)}/download?force=true')
    for src, ident, _ in scan.imgs:
        if ident == 'wallpaper':  # wallhaven full-size image
            images.append(urllib.parse.urljoin(final, src))
    for key in ('og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'):
        if scan.meta.get(key):
            images.append(urllib.parse.urljoin(final, html.unescape(scan.meta[key])))
            break
    images = list(dict.fromkeys(images))
    if not images:
        raise Fail('No theme repo or image found on that page')
    return 'images', images[:1], title


def download_image(url, dest_dir, index):
    say(f'Downloading image {index + 1}…')
    data, ctype, final = fetch(url, MAX_IMAGE, 'image/*')
    if not ctype.startswith('image/') and not is_image_url(final):
        raise Fail(f'{urllib.parse.urlparse(url).netloc} did not return an image')
    stem = Path(urllib.parse.urlparse(final).path).stem or f'image-{index + 1}'
    ext = Path(urllib.parse.urlparse(final).path).suffix.lower()
    if ext not in IMAGE_EXT:
        ext = '.' + (ctype.split('/')[-1].split(';')[0].replace('jpeg', 'jpg') or 'jpg')
    path = dest_dir / f'{index + 1:02d}-{clean_stem(stem)}{ext}'
    path.write_bytes(data)
    return path


def clean_stem(stem):
    s = re.sub(r'[^a-z0-9]+', '-', urllib.parse.unquote(stem).lower()).strip('-')
    return s[:40] or 'image'


# ---------------------------------------------------------------- archives

def safe_extract(archive, dest):
    dest = dest.resolve()
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if len(members) > MAX_ENTRIES or sum(m.file_size for m in members) > MAX_UNPACKED:
                raise Fail('Archive is too large to unpack')
            for m in members:
                target = (dest / m.filename).resolve()
                if not str(target).startswith(str(dest) + os.sep) and target != dest:
                    raise Fail('Archive contains unsafe paths')
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            members = t.getmembers()
            if len(members) > MAX_ENTRIES or sum(m.size for m in members if m.isfile()) > MAX_UNPACKED:
                raise Fail('Archive is too large to unpack')
            t.extractall(dest, filter='data')
    entries = [p for p in dest.iterdir() if not p.name.startswith(('.', '__MACOSX'))]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else dest


# ---------------------------------------------------------------- theme folders

def find_theme_root(root, depth=3):
    """Folder holding a theme definition (colors.toml / alacritty.toml)."""
    for d in [root] + sorted(p for p in root.rglob('*') if p.is_dir() and '.git' not in p.parts and len(p.relative_to(root).parts) <= depth):
        if (d / 'colors.toml').is_file() or (d / 'alacritty.toml').is_file():
            return d
    return None


def images_in(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXT
                  and '.git' not in p.parts and p.stat().st_size > 30_000)


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    s = re.sub(r'^omarchy-', '', s)
    s = re.sub(r'-theme$', '', s)
    return s[:48].strip('-') or 'custom-theme'


def free_slug(base):
    slug, n = base, 2
    while (THEMES / slug).exists() or (STOCK / slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug


def strip_code(folder):
    """Remove symlinks and files that run code; returns how many were removed."""
    removed = 0
    for path in sorted(folder.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink() or (path.is_file() and (path.suffix == '.lua' or path.name in CODE_FILES)):
            path.unlink()
            removed += 1
    return removed


def install_folder(src, slug, source=None):
    """Copy a theme folder that came without .git (archive, page, repo subfolder, folder).

    Omarchy trusts such folders like the user's own, so anything that could run
    code is stripped first, and links are never followed out of the source.
    """
    target = THEMES / slug
    THEMES.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target, symlinks=True, ignore=shutil.ignore_patterns('.git', '.github', '__MACOSX'))
    removed = strip_code(target)
    if removed:
        say(f'Removed {removed} file(s) that could run code')
    if source:
        (target / 'SOURCE.json').write_text(json.dumps(source, indent=2) + '\n')
    return target


# ---------------------------------------------------------------- palette

def hexc(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*(max(0, min(255, round(c * 255))) for c in rgb))


def hls(h, l, s):
    return colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s)))


def lum(rgb):
    def ch(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a, b, t):
    return tuple(x * (1 - t) + y * t for x, y in zip(a, b))


def sample_pixels(path):
    out = run('magick', '-define', 'jpeg:size=288x288', str(path) + '[0]', '-resize', '72x72!', '-colorspace', 'sRGB',
              '-depth', '8', 'txt:-', timeout=60)
    px = []
    for line in out.splitlines()[1:]:
        m = re.search(r'\((\d+),(\d+),(\d+)', line)
        if m:
            px.append(tuple(int(v) / 255 for v in m.groups()))
    return px


def kmeans(px, k=10, rounds=14):
    srt = sorted(px, key=lambda c: sum(c))
    cent = [srt[int(i * (len(srt) - 1) / (k - 1))] for i in range(k)]
    for _ in range(rounds):
        groups = [[] for _ in cent]
        for p in px:
            i = min(range(len(cent)), key=lambda j: sum((p[d] - cent[j][d]) ** 2 for d in range(3)))
            groups[i].append(p)
        cent = [tuple(sum(c[d] for c in g) / len(g) for d in range(3)) if g else cent[i] for i, g in enumerate(groups)]
    total = len(px)
    return [(c, len(g) / total) for c, g in zip(cent, groups) if g]


# Palette profiles offered in the UI (id, label). auto/dark/light are the original modes.
PROFILES = (('auto', 'Match the art'), ('dark', 'Dark'), ('light', 'Light'),
            ('vivid', 'Vivid'), ('soft', 'Soft'), ('midnight', 'Midnight'))
MODES = tuple(p for p, _ in PROFILES)
ANSI_HUES = {'red': 0.99, 'orange': 0.07, 'yellow': 0.125, 'green': 0.31, 'cyan': 0.5, 'blue': 0.6, 'magenta': 0.84}


def analyze(images):
    """Sample the artwork once: k-means clusters as (rgb, weight, h, l, s)."""
    px = []
    for img in images[:6]:
        px += sample_pixels(img)
    if not px:
        raise Fail('Could not read colors from the images')
    return [(c, w, *colorsys.rgb_to_hls(*c)) for c, w in kmeans(px)]


def hue_gap(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1 - d)


def readable(c, bg, ratio, light):
    """Move `c` away from the background's lightness until it reaches `ratio`."""
    for _ in range(40):
        if contrast(c, bg) >= ratio:
            return c
        h, l, s = colorsys.rgb_to_hls(*c)
        if (light and l <= 0) or (not light and l >= 1):
            break
        c = hls(h, l - 0.025 if light else l + 0.025, s)
    for t in range(1, 21):
        m = mix(c, (0, 0, 0) if light else (1, 1, 1), t / 20)
        if contrast(m, bg) >= ratio:
            return m
    return m


def art_hue(info, hue, pull):
    """Bend a canonical ANSI hue toward a nearby colour that is in the art."""
    near = [x for x in info if x[4] > 0.2 and hue_gap(x[2], hue) < 0.07]
    if not near:
        return hue
    n = max(near, key=lambda x: x[1])
    d = n[2] - hue
    d = d - 1 if d > 0.5 else d + 1 if d < -0.5 else d
    return hue + d * pull


def palette(images, mode):
    return palette_from(analyze(images), mode)


def palette_from(info, mode):
    avg_l = sum(w * l for _, w, _, l, _ in info)
    colorful = sum(w * s for _, w, _, l, s in info if 0.15 < l < 0.85)
    art_light = avg_l > 0.62
    light = art_light if mode in ('auto', 'soft') else mode == 'light'
    cf = min(1, colorful * 2.2)

    weighty = [x for x in info if x[1] > 0.03] or info
    base = (max if light else min)(weighty, key=lambda x: x[3])
    bh, bs = base[2], min(base[4], 0.32)
    vivid = [x for x in info if 0.22 < x[3] < 0.85 and x[4] > 0.18]
    pick = max(vivid, key=lambda x: x[4] * (x[1] ** 0.5)) if vivid else None

    if mode == 'vivid':
        # Most saturated colour in the art (weight barely matters), pushed to full chroma.
        pool = [x for x in info if 0.1 < x[3] < 0.9 and x[1] > 0.004] or info
        hot = max(pool, key=lambda x: x[4] * (x[1] ** 0.15))
        ah = hot[2] if hot[4] > 0.05 else 0.6
        th = bh if base[4] > 0.12 else ah
        bg = hls(th, 0.095, min(0.75, max(0.5, base[4] * 1.5)))
        fg = hls(th, 0.93, 0.16)
        accent = hls(ah, 0.55, max(0.9, min(1, hot[4] * 1.8)))
        sat, la, lb, pull = min(0.95, 0.74 + 0.2 * cf), 0.62, 0.71, 0.75
        brown = hls(0.07, 0.46, 0.6)
    elif mode == 'soft':
        ah = pick[2] if pick else bh
        if light:
            bg = hls(bh, 0.915, min(0.24, bs * 0.7 + 0.04))
            fg = hls(bh, 0.3, min(0.14, bs + 0.03))
        else:
            bg = hls(bh, 0.19, min(0.2, bs * 0.6 + 0.04))
            fg = hls(bh, 0.84, min(0.14, bs + 0.03))
        accent = hls(ah, 0.5 if light else 0.74, max(0.26, min(0.42, (pick[4] if pick else 0.3) * 0.7)))
        sat, la, lb, pull = 0.24 + 0.16 * cf, (0.46 if light else 0.75), (0.38 if light else 0.81), 0.6
        brown = hls(0.08, 0.42 if light else 0.6, 0.25)
    elif mode == 'midnight':
        tinted = [x for x in info if x[4] > 0.15 and 0.06 < x[3] < 0.9]
        deep = [x for x in tinted if x[3] < 0.5] or tinted  # prefer the art's deep tones
        th = max(deep, key=lambda x: x[1])[2] if tinted else bh
        ah = pick[2] if pick else th
        bg = hls(th, 0.05, 0.85 if tinted else 0.12)
        fg = hls(th, 0.95, 0.3)
        accent = hls(ah, 0.74, 1.0 if pick else 0.5)
        sat, la, lb, pull = 0.82, 0.69, 0.79, 0.5
        brown = hls(0.07, 0.48, 0.45)
    else:  # auto / dark / light: the original generator
        bg = hls(bh, 0.94 if light else 0.075, bs * (0.6 if light else 0.8))
        fg = hls(bh, 0.17 if light else 0.88, min(0.22, bs + 0.05))
        if pick:
            accent = hls(pick[2], 0.42 if light else 0.63, max(0.45, min(0.85, pick[4] * 1.15)))
        else:
            accent = hls(bh, 0.38 if light else 0.72, 0.08)
        sat, la, lb, pull = 0.38 + 0.45 * cf, (0.42 if light else 0.66), (0.34 if light else 0.74), 0.6
        brown = hls(0.08, 0.36 if light else 0.42, 0.4)

    fg = readable(fg, bg, 7.0, light)
    accent = readable(accent, bg, 3.2, light)
    ansi = {}
    for name, hue in ANSI_HUES.items():
        h = art_hue(info, hue, pull)
        ansi[name] = readable(hls(h, la, sat), bg, 4.5, light)
        ansi['bright_' + name] = readable(hls(h, lb, min(1, sat + 0.08)), bg, 4.5, light)

    col = {
        'mode': 'light' if light else 'dark',
        'accent': accent, 'selection': mix(bg, accent, 0.3),
        'muted': mix(bg, fg, 0.45),
        'background': bg,
        'dark_background': mix(bg, (1, 1, 1) if light else (0, 0, 0), 0.06),
        'darker_background': mix(bg, (1, 1, 1) if light else (0, 0, 0), 0.12),
        'lighter_background': mix(bg, fg, 0.07),
        'foreground': fg,
        'dark_foreground': mix(fg, bg, 0.35),
        'light_foreground': mix(fg, bg, 0.15),
        'bright_foreground': mix(fg, (0, 0, 0) if light else (1, 1, 1), 0.5),
        **{k: v for k, v in ansi.items() if not k.startswith('bright_')},
        'brown': readable(brown, bg, 3.0, light),
        **{k: v for k, v in ansi.items() if k.startswith('bright_') and k != 'bright_orange'},
    }
    return col


def swatch_names(info):
    """Three ANSI colours that best show the art's character (most present hues first)."""
    score = {n: sum(x[1] for x in info if x[4] > 0.2 and hue_gap(x[2], h) < 0.07) for n, h in ANSI_HUES.items()}
    names = [n for n in sorted(score, key=score.get, reverse=True) if score[n] > 0][:3]
    for n in ('red', 'green', 'blue', 'yellow', 'magenta', 'cyan'):
        if len(names) >= 3:
            break
        if n not in names and all(hue_gap(ANSI_HUES[n], ANSI_HUES[m]) > 0.1 for m in names):
            names.append(n)
    names += [n for n in ('red', 'green', 'blue') if n not in names]
    return names[:3]


def profiles_from(info):
    names = swatch_names(info)
    out = []
    for pid, label in PROFILES:
        col = palette_from(info, pid)
        out.append({'id': pid, 'label': label, 'mode': col['mode'],
                    'colors': [hexc(col[k]) for k in ('background', 'foreground', 'accent', *names)]})
    return out


def write_colors(path, col, sources):
    lines = ['# Generated by Theme Studio from the artwork in backgrounds/.']
    if sources:
        lines.append('# Sources: ' + ', '.join(sources)[:900])
    for k, v in col.items():
        lines.append(f'{k} = "{v}"' if k == 'mode' else f'{k} = "{hexc(v)}"')
    path.write_text('\n'.join(lines) + '\n')


def build_from_images(images, name, mode, sources):
    slug = free_slug(slugify(name))
    target = THEMES / slug
    (target / 'backgrounds').mkdir(parents=True)
    try:
        kept = []
        for i, img in enumerate(images):
            ok = run('magick', 'identify', '-format', '%w %h\n', str(img) + '[0]', timeout=60).split()
            w = int(ok[0]) if ok else 0
            if w < 400:
                say(f'Skipping {img.name}: too small ({w}px)')
                continue
            dst = target / 'backgrounds' / f'{i + 1:02d}-{clean_stem(img.stem.split("-", 1)[-1])}'
            if img.suffix.lower() in KEEP_EXT:
                dst = dst.with_suffix(img.suffix.lower())
                shutil.copy2(img, dst)
            else:
                dst = dst.with_suffix('.png')
                run('magick', str(img) + '[0]', str(dst), timeout=120)
            kept.append(dst)
        if not kept:
            raise Fail('None of the images were usable (need at least 400px wide)')
        say('Building a palette from the artwork…')
        col = palette(kept, mode)
        write_colors(target / 'colors.toml', col, sources)
        run('magick', str(kept[0]) + '[0]', '-resize', '1280x720^', '-gravity', 'center', '-extent', '1280x720', str(target / 'preview.png'), timeout=120)
        (target / 'SOURCE.md').write_text('# ' + name + '\n\nGenerated by Theme Studio from these images:\n\n' +
                                          '\n'.join(f'- {s}' for s in sources) + '\n\nPlease respect the artists\' licenses.\n')
        return slug, kept
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


# ---------------------------------------------------------------- install paths

def install_git(url, name_hint, mode='auto'):
    say('Checking the repository link…')
    run('omarchy-git-url-check', url, timeout=20)
    base = slugify(Path(url.rstrip('/').split(':')[-1]).name.removesuffix('.git'))
    if not NAME_RE.match(base):
        raise Fail('That repository does not give a usable theme name')
    target = THEMES / base
    if (target / '.git').is_dir():
        try:
            origin = run('git', '-C', str(target), 'config', '--get', 'remote.origin.url', timeout=10)
        except Fail:
            origin = ''
        if origin.removesuffix('.git').rstrip('/') == url.removesuffix('.git').rstrip('/'):
            say('Already installed, updating…')
            run('git', *GIT_SAFE, '-C', str(target), 'pull', '--ff-only', '--no-recurse-submodules', timeout=180)
            return base, 'git'
    tmp = Path(tempfile.mkdtemp(prefix='theme-studio-'))
    try:
        say('Downloading ' + '/'.join(url.rstrip('/').split('/')[-2:]) + '…')
        run('git', *GIT_SAFE, 'clone', '--config', 'core.symlinks=false', '--depth', '1', '--no-recurse-submodules', '--', url, str(tmp / 'repo'), timeout=300)
        repo = tmp / 'repo'
        commit = run('git', '-C', str(repo), 'rev-parse', 'HEAD', timeout=10).strip()
        say(f'Got {"/".join(url.rstrip("/").split("/")[-2:])} at {commit[:12]}')
        root = find_theme_root(repo)
        if root == repo:
            slug = free_slug(base)
            shutil.move(str(repo), str(THEMES / slug))  # keep .git so `omarchy theme update` works
            return slug, 'git'
        if root is not None:
            slug = free_slug(slugify(root.name) if root.name not in ('theme', 'src') else base)
            install_folder(root, slug, {'url': url, 'commit': commit, 'path': str(root.relative_to(repo)), 'installed_at': int(time.time())})
            return slug, 'git'
        imgs = images_in(repo)
        if imgs:
            say('No theme files in that repo, making a theme from its images…')
            slug, _ = build_from_images(imgs[:12], name_hint or base.replace('-', ' ').title(), mode, [url])
            return slug, 'images'
        raise Fail('That repository is not an Omarchy theme (no colors.toml) and has no images')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_dir(src, name_hint, mode, sources):
    root = find_theme_root(src)
    if root is not None:
        slug = free_slug(slugify(name_hint or root.name))
        say('Installing theme folder…')
        install_folder(root, slug)
        return slug, 'folder'
    imgs = images_in(src)
    if not imgs:
        raise Fail('No theme files or images found')
    slug, _ = build_from_images(imgs[:12], name_hint or src.name.replace('-', ' ').title(), mode, sources)
    return slug, 'images'


def install(text, name, mode, apply):
    items = [classify(t) for t in tokens(text)]
    if not items:
        raise Fail('Nothing to install')
    kinds = {k for k, _ in items}
    if len(items) > 1 and kinds - {'image', 'page'}:
        raise Fail('Install repos, archives and folders one link at a time')
    THEMES.mkdir(parents=True, exist_ok=True)
    kind, value = items[0]
    tmp = Path(tempfile.mkdtemp(prefix='theme-studio-'))
    try:
        if kind == 'git':
            slug, how = install_git(value, name, mode)
        elif kind == 'dir':
            slug, how = install_dir(Path(value), name, mode, [value])
        elif kind == 'archive':
            if local_path(value) or value.startswith('/'):
                arc = Path(value)
            else:
                say('Downloading archive…')
                data, _, final = fetch(value, MAX_ARCHIVE)
                arc = tmp / (Path(urllib.parse.urlparse(final).path).name or 'theme.zip')
                arc.write_bytes(data)
            say('Unpacking…')
            root = safe_extract(arc, tmp / 'x')
            hint = name or re.sub(r'\.(zip|tar|tgz|txz|gz|xz|bz2)$', '', arc.name, flags=re.I)
            slug, how = install_dir(root, hint, mode, [value])
        else:
            files, sources, title = [], [], ''
            for i, (k, v) in enumerate(items):
                if k == 'image':
                    if local_path(v) or v.startswith('/'):
                        files.append(Path(v))
                    else:
                        files.append(download_image(v, tmp, len(files)))
                    sources.append(v)
                else:
                    res = resolve_page(v)
                    if res[0] == 'git':
                        if len(items) > 1:
                            raise Fail('That page is a theme repo; install it on its own')
                        slug, how = install_git(res[1], name, mode)
                        return finish(slug, how, apply, source=res[1], profile=mode)
                    if res[0] == 'image-bytes':
                        data, final = res[1]
                        p = tmp / f'{len(files) + 1:02d}-{clean_stem(Path(urllib.parse.urlparse(final).path).stem)}.jpg'
                        p.write_bytes(data)
                        files.append(p)
                    else:
                        for u in res[1]:
                            files.append(download_image(u, tmp, len(files)))
                    title = title or res[2]
                    sources.append(v)
            hint = name or clean_title(title) or default_name(files)
            slug, _ = build_from_images(files, hint, mode, sources)
            return finish(slug, 'images', apply, hint, profile=mode)
        return finish(slug, how, apply, name, value if kind == 'git' else '', profile=mode)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def clean_title(t):
    t = re.split(r'\s[|\-–—·]\s|,', t or '')[0].strip()
    t = re.sub(r'^(File|Image):', '', t)
    t = re.sub(r'(?i)\b(wallpaper|hd|4k|free|download|photo|image)s?\b', '', t).strip(' -|')
    return t[:40]


def default_name(files):
    stem = clean_stem(files[0].stem.split('-', 1)[-1]) if files else ''
    words = [w for w in stem.split('-') if w.isalpha()][:3]
    return ' '.join(words).title() or 'Artwork ' + time.strftime('%b %d')


def thumb(slug):
    root = THEMES / slug
    bgs = images_in(root / 'backgrounds') if (root / 'backgrounds').is_dir() else []
    src = (root / 'preview.png') if (root / 'preview.png').is_file() else (bgs[0] if bgs else None)
    if src:
        THUMBS.mkdir(parents=True, exist_ok=True)
        subprocess.run(['magick', str(src) + '[0]', '-resize', '360x220^', '-gravity', 'center', '-extent', '360x220',
                        '-quality', '82', str(THUMBS / f'{slug}.jpg')], capture_output=True, timeout=60)


def finish(slug, how, apply, display='', source='', profile=''):
    target = THEMES / slug
    if not ((target / 'colors.toml').is_file() or (target / 'alacritty.toml').is_file()):
        shutil.rmtree(target, ignore_errors=True)
        raise Fail('The download did not contain a usable theme')
    name = display.strip() or slug.replace('-', ' ').title()
    marker = {'installed_at': time.time(), 'kind': how, 'name': name, **({'source': source} if source else {})}
    if profile and how == 'images':
        marker['profile'] = profile
    (target / '.theme-studio').write_text(json.dumps(marker) + '\n')
    thumb(slug)
    applied = False
    if apply:
        say('Applying ' + slug + '…')
        run('omarchy', 'theme', 'set', slug, timeout=240)
        applied = True
    return {'ok': True, 'slug': slug, 'name': name, 'kind': how, 'applied': applied}


def wide_enough(path):
    out = run('magick', 'identify', '-format', '%w\n', str(path) + '[0]', timeout=60).split()
    return bool(out) and int(out[0]) >= 400


def inspect_profiles(items, resolved=None):
    """Six palette previews for an image input, sampled once. None when they can't be computed."""
    from concurrent.futures import ThreadPoolExecutor
    tmp = Path(tempfile.mkdtemp(prefix='theme-studio-inspect-'))
    try:
        srcs = []  # ordered like install(): ('file', Path) | ('url', str)
        if resolved is not None:
            if resolved[0] == 'image-bytes':
                p = tmp / '00-page.jpg'
                p.write_bytes(resolved[1][0])
                srcs.append(('file', p))
            else:
                srcs += [('url', u) for u in resolved[1]]
        else:
            for k, v in items:
                if k == 'image':
                    lp = local_path(v)
                    srcs.append(('file', lp) if lp else ('url', v))
                elif k == 'dir':
                    if find_theme_root(Path(v)) is not None:
                        return None
                    srcs += [('file', p) for p in images_in(Path(v))[:12]]
                elif k == 'page':
                    res = resolve_page(v)
                    if res[0] == 'git':
                        return None
                    if res[0] == 'image-bytes':
                        p = tmp / f'{len(srcs):02d}-page.jpg'
                        p.write_bytes(res[1][0])
                        srcs.append(('file', p))
                    else:
                        srcs += [('url', u) for u in res[1]]
        srcs = srcs[:8]
        urls = [(i, v) for i, (k, v) in enumerate(srcs) if k == 'url']
        if urls:
            with ThreadPoolExecutor(max_workers=4) as pool:
                got = list(pool.map(lambda iu: download_image(iu[1], tmp, iu[0]), urls))
            for (i, _), path in zip(urls, got):
                srcs[i] = ('file', path)
        files = [p for _, p in srcs if wide_enough(p)][:6]
        if not files:
            return None
        return profiles_from(analyze(files))
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('inspect', 'install', 'profiles'))
    ap.add_argument('input', nargs='+')
    ap.add_argument('--name', default='')
    ap.add_argument('--mode', choices=MODES, default='auto')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    if a.action == 'profiles':
        a.input = [str(Path(os.path.expanduser(p)).resolve()) for p in a.input]
    else:
        a.input = ' '.join(a.input)
    try:
        if a.action == 'profiles':
            missing = [p for p in a.input if not Path(p).is_file()]
            if missing:
                raise Fail(f'{missing[0]} does not exist')
            t0 = time.monotonic()
            res = {'ok': True, 'profiles': profiles_from(analyze([Path(p) for p in a.input]))}
            res['ms'] = round((time.monotonic() - t0) * 1000)
            print(json.dumps(res))
        elif a.action == 'inspect':
            items = [classify(t) for t in tokens(a.input)]
            if not items:
                raise Fail('Nothing to install')
            title, resolved = '', None
            if len(items) == 1 and items[0][0] == 'page':
                res = resolve_page(items[0][1])
                if res[0] == 'git':
                    items = [('git', res[1])]
                else:
                    title = clean_title(res[2])
                    items = [('image', items[0][1])]
                    resolved = res
            makes = all(k in ('image', 'page', 'dir') for k, _ in items)
            out = {'ok': True, 'label': describe(items), 'kinds': [k for k, _ in items], 'images': makes, 'title': title}
            if makes:
                prof = inspect_profiles(items, resolved)
                if prof:
                    out['profiles'] = prof
            print(json.dumps(out))
        else:
            print(json.dumps(install(a.input, a.name.strip(), a.mode, a.apply)), flush=True)
    except Fail as e:
        print(json.dumps({'ok': False, 'error': str(e)}), flush=True)
        sys.exit(1)
    except Exception as e:  # network errors etc.
        msg = getattr(e, 'reason', None) or str(e)
        print(json.dumps({'ok': False, 'error': f'Install failed: {msg}'[:300]}), flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

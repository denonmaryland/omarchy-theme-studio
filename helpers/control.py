#!/usr/bin/python3
"""Theme Studio backend: switch, rotate, rate, remember and remove Omarchy themes."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time

HOME = Path.home()
STATE_DIR = Path(os.environ.get('THEME_STUDIO_STATE', HOME / '.local/state/omarchy-theme-studio'))
STATE_FILE = STATE_DIR / 'state.json'
LEGACY_STATE = HOME / '.local/state/omarchy-theme-rotation'  # pre-release name
PLUGIN_DIR = Path(__file__).resolve().parent.parent
HYPR_DIR = HOME / '.config/hypr'
BORDER_MODULE = 'theme_studio_border'
BORDER_LINE = f'require("hypr.{BORDER_MODULE}")  -- Theme Studio: window border colors (remove via the panel)'
GALLERY = Path(os.environ.get('THEME_STUDIO_GALLERY', HOME / '.local/share/omarchy-community-themes/manifest.json'))
LIVE_THEMES = HOME / '.config/omarchy/themes'
STOCK_THEMES = Path('/usr/share/omarchy/themes')
MINUTES = (15, 30, 60)
THUMBS = HOME / '.cache/omarchy-theme-studio/thumbs'
PALETTES = STATE_DIR / 'palettes.json'
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')


def theme_dir(name):
    for root in (LIVE_THEMES, STOCK_THEMES):
        if (root / name).is_dir():
            return root / name
    return None


def palette_mode(background, declared=None):
    """Use declared mode, otherwise infer lightness from the background."""
    if isinstance(declared, str) and declared.lower() in ('light', 'dark'):
        return declared.lower()
    value = str(background or '').removeprefix('#').removeprefix('0x')
    if len(value) == 6:
        try:
            rgb = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
            return 'light' if sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722))) > 0.179 else 'dark'
        except ValueError:
            pass
    return 'dark'


def read_palette(folder):
    """Five swatches (bg, fg, accent, red, green) plus mode for a theme folder."""
    import re
    import tomllib
    p = folder / 'colors.toml'
    try:
        if p.is_file():
            c = tomllib.loads(p.read_text())
            keys = ('background', 'foreground', 'accent', 'red', 'green', 'blue')
            return [c[k] for k in keys if isinstance(c.get(k), str)][:5], palette_mode(c.get('background'), c.get('mode'))
        a = folder / 'alacritty.toml'
        if a.is_file():
            c = tomllib.loads(a.read_text()).get('colors', {})
            prim, norm = c.get('primary', {}), c.get('normal', {})
            vals = [prim.get('background'), prim.get('foreground'), norm.get('yellow'), norm.get('red'), norm.get('green')]
            return ['#' + v[-6:] for v in vals if isinstance(v, str) and re.fullmatch(r'(#|0x)[0-9a-fA-F]{6}', v)], palette_mode(prim.get('background'))
    except Exception:
        pass
    return [], 'dark'


BORDERS = STATE_DIR / 'borders.lua'
# Themes name their palette either ANSI-style (color1..color15) or by hue
# (red, bright_blue, ...); offer both, deduplicated by value.
ANSI = ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')
BORDER_KEYS = ('accent', 'foreground',
               'red', 'orange', 'yellow', 'green', 'cyan', 'blue', 'magenta',
               'bright_red', 'bright_yellow', 'bright_green', 'bright_cyan', 'bright_blue', 'bright_magenta',
               'color1', 'color3', 'color2', 'color6', 'color4', 'color5',
               'color9', 'color11', 'color10', 'color14', 'color12', 'color13', 'color7', 'color15')


def border_label(key):
    if key.startswith('color') and key[5:].isdigit():
        n = int(key[5:])
        return ('Bright ' if n >= 8 else '') + ANSI[n % 8] if n >= 8 else ANSI[n].capitalize()
    return key.replace('_', ' ').capitalize()
BORDER_NONE = 'rgba(00000000)'


def theme_colors(slug):
    """Palette key -> #rrggbb for a theme, from colors.toml or alacritty.toml."""
    import re
    import tomllib
    folder = theme_dir(slug)
    if folder is None:
        return {}
    hexes = lambda d: {k: '#' + v[-6:].lower() for k, v in d.items()
                       if isinstance(v, str) and re.fullmatch(r'(#|0x)[0-9a-fA-F]{6}', v)}
    try:
        if (folder / 'colors.toml').is_file():
            return hexes(tomllib.loads((folder / 'colors.toml').read_text()))
        if (folder / 'alacritty.toml').is_file():
            c = tomllib.loads((folder / 'alacritty.toml').read_text()).get('colors', {})
            names = ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')
            out = {**{f'color{i}': c.get('normal', {}).get(n) for i, n in enumerate(names)},
                   **{f'color{i + 8}': c.get('bright', {}).get(n) for i, n in enumerate(names)},
                   'foreground': c.get('primary', {}).get('foreground')}
            out['accent'] = out.get('color4')
            return hexes({k: v for k, v in out.items() if v})
    except Exception:
        pass
    return {}


def border_options(slug):
    """Distinct palette colours a theme offers for its window border."""
    colors, seen, out = theme_colors(slug), set(), []
    for key in BORDER_KEYS:
        value = colors.get(key)
        if value and value not in seen:
            seen.add(value)
            out.append({'key': key, 'color': value, 'label': border_label(key)})
    return out


def live_border():
    """The applied theme's own active border colour, for the Default swatch."""
    import re
    try:
        text = (HOME / '.local/state/omarchy/current/theme/hyprland.lua').read_text()
        # First colour of `local active_border_color = ...`, plain or gradient.
        line = re.search(r'^local active_border_color\s*=\s*(.+)$', text, re.M)
        match = line and re.search(r'(?:#|rgba?\(|0x)([0-9a-fA-F]{6})', line.group(1))
        if match:
            return '#' + match.group(1).lower()
    except Exception:
        pass
    return ''


def write_borders(data):
    """Resolve saved choices to colours Hyprland reads through ~/.config/hypr/theme_border.lua.

    "*" is the default for themes without their own pick; false means "keep
    the theme's own border".
    """
    lines = ['-- Generated by Theme Studio. Theme slug -> active window border colour.',
             '-- "*" applies to every theme without its own entry; false keeps the theme\'s border.', 'return {']
    if data.get('border_default') == 'none':
        lines.append(f'  ["*"] = {json.dumps(BORDER_NONE)},')
    for slug, key in sorted((data.get('borders') or {}).items()):
        if key == 'theme':
            lines.append(f'  [{json.dumps(slug)}] = false,')
            continue
        color = BORDER_NONE if key == 'none' else theme_colors(slug).get(key)
        if color:
            lines.append(f'  [{json.dumps(slug)}] = {json.dumps(color)},')
    lines.append('}')
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = BORDERS.with_suffix('.pending')
    pending.write_text('\n'.join(lines) + '\n')
    os.replace(pending, BORDERS)
    subprocess.run(['hyprctl', 'reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def palettes(names):
    cache = {}
    try:
        cache = json.loads(PALETTES.read_text())
    except Exception:
        pass
    out, dirty = {}, False
    for name in names:
        folder = theme_dir(name)
        if folder is None:
            continue
        stamp = max((folder / f).stat().st_mtime for f in ('colors.toml', 'alacritty.toml') if (folder / f).is_file()) if any((folder / f).is_file() for f in ('colors.toml', 'alacritty.toml')) else 0
        hit = cache.get(name)
        if not hit or hit[0] != stamp or len(hit) < 4 or hit[3] != 2:
            pal, mode = read_palette(folder)
            hit = cache[name] = [stamp, pal, mode, 2]
            dirty = True
        out[name] = hit
    if dirty:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            PALETTES.write_text(json.dumps(cache))
        except Exception:
            pass
    return out


def make_thumbs(limit=400):
    """Small cached previews so the grid never decodes 4K wallpapers."""
    THUMBS.mkdir(parents=True, exist_ok=True)
    made = 0
    for item in theme_catalog(load(), with_palette=False):
        dest = THUMBS / f"{item['slug']}.jpg"
        src = item.get('source')
        if not src or (dest.is_file() and dest.stat().st_mtime >= Path(src).stat().st_mtime):
            continue
        subprocess.run(['magick', src + '[0]', '-resize', '360x220^', '-gravity', 'center', '-extent', '360x220',
                        '-quality', '82', str(dest)], capture_output=True, timeout=90)
        made += 1
        if made >= limit:
            break
    return made


def command(*args, timeout=120):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or f'{args[0]} failed').strip()[-400:])
    return result.stdout.strip()


def set_theme(selected, timeout=60, background=None):
    """Run `omarchy theme set` but return once the theme is visibly applied.

    omarchy-theme-set holds its lock only while it swaps the theme and hands the
    transition to the shell (~0.5 s); terminals, browser and other app re-tints
    keep running for a few more seconds after that. Waiting for those blocked
    the panel, so they are left to finish in the background.
    """
    log = STATE_DIR / 'theme-set.log'
    lock_path = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / 'omarchy-theme-set.lock'
    # With a remembered wallpaper, let Omarchy skip its own pick so the screen
    # does one wallpaper transition instead of two.
    env = dict(os.environ, OMARCHY_THEME_SKIP_BACKGROUND='1') if background else None
    with log.open('w') as out:
        proc = subprocess.Popen(['omarchy', 'theme', 'set', selected], stdin=subprocess.DEVNULL, env=env,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            if code:
                raise RuntimeError((log.read_text(errors='replace').strip() or 'omarchy theme set failed')[-400:])
            return restore_background(background)
        if current_theme() == selected:
            with lock_path.open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    return restore_background(background)
                except BlockingIOError:
                    pass
        time.sleep(0.02)
    raise RuntimeError(f'Timed out applying {selected}')


def background_name():
    return (HOME / '.local/state/omarchy/current/background').resolve(strict=False).name


def has_background(slug, name):
    folder = theme_dir(slug)
    return bool(name) and any((root / name).is_file() for root in
                              ([folder / 'backgrounds'] if folder else []) + [HOME / '.config/omarchy/backgrounds' / slug])


def restore_background(name):
    """Show the wallpaper a theme had when you last left it (after the theme swap)."""
    if not name:
        return
    match = next((p for p in theme_backgrounds() if p.name == name), None)
    images = theme_backgrounds()
    try:
        command('omarchy', 'theme', 'bg', 'set', str(match or images[0]), timeout=30)
    except Exception:
        pass


def current_theme():
    p = HOME / '.local/state/omarchy/current/theme.name'
    return p.read_text().strip() if p.exists() else ''


def labels():
    mapping = {}
    if LIVE_THEMES.is_dir():
        for marker in LIVE_THEMES.glob('*/.theme-studio'):
            try:
                name = json.loads(marker.read_text()).get('name')
            except Exception:
                name = None
            if name:
                mapping[marker.parent.name] = name
    if GALLERY.exists():
        for item in json.loads(GALLERY.read_text())['themes']:
            mapping['gallery-' + item['slug']] = item['name']
    return mapping


def available():
    names = {p.name for folder in (STOCK_THEMES, LIVE_THEMES) if folder.is_dir() for p in folder.iterdir() if p.is_dir()}
    return sorted(n for n in names if n and not n.startswith('.'))


def theme_catalog(data, with_palette=True):
    """Browse installed themes independently of the automatic rotation pool."""
    display = labels()
    favorites = set(data.get('favorites', []))
    extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    result = []
    for name in available():
        images = {}
        # User theme files override stock files with the same name.
        for root in (STOCK_THEMES / name / 'backgrounds', LIVE_THEMES / name / 'backgrounds'):
            if root.is_dir():
                images.update({p.name: p for p in root.iterdir() if p.is_file() and p.suffix.lower() in extensions})
        user = HOME / '.config/omarchy/backgrounds' / name
        custom = sorted(p for p in user.iterdir() if p.is_file() and p.suffix.lower() in extensions) if user.is_dir() else []
        preview = (custom + [images[key] for key in sorted(images)])[:1]
        for folder in (LIVE_THEMES / name, STOCK_THEMES / name):
            if not preview and (folder / 'preview.png').is_file():
                preview = [folder / 'preview.png']
        thumb = THUMBS / f'{name}.jpg'
        result.append({
            'slug': name,
            'name': display.get(name, name.removeprefix('gallery-').replace('-', ' ').title()),
            'url': preview[0].resolve().as_uri() if preview else '',
            'thumb': thumb.as_uri() if thumb.is_file() else (preview[0].resolve().as_uri() if preview else ''),
            'source': str(preview[0].resolve()) if preview else '',
            'favorite': name in favorites,
        })
    if with_palette:
        pals = palettes([item['slug'] for item in result])
        for item in result:
            hit = pals.get(item['slug'])
            item['palette'] = hit[1] if hit else []
            item['mode'] = hit[2] if hit else 'dark'
            item.pop('source', None)
        groups = theme_groups(result)
        sizes = {}
        for gid in groups.values():
            sizes[gid] = sizes.get(gid, 0) + 1
        for item in result:
            item['group'] = groups.get(item['slug'], item['slug'])
            item['group_size'] = sizes.get(item['group'], 1)
    return sorted(result, key=lambda item: (item['name'].casefold(), item['slug']))


# ---------------------------------------------------------------- lookalike groups
GROUPS = STATE_DIR / 'groups.json'
GROUP_CAP = 6
GROUP_DELTA = 5.0  # CIE76 limit for background, foreground and accent alike (7 merged Bauhaus/Sakura)
VARIANT_WORDS = {'light', 'dark', 'oled', 'amoled', 'dim', 'soft', 'hard', 'medium', 'mocha', 'latte',
                 'frappe', 'macchiato', 'storm', 'moon', 'day', 'v2', 'v3', 'theme', 'omarchy'}


def name_stem(slug, name):
    import re
    words = re.sub(r'[^a-z0-9]+', ' ', name.casefold().replace('é', 'e')).split()
    if not words:
        words = slug.removeprefix('gallery-').split('-')
    while len(words) > 1 and words[-1] in VARIANT_WORDS:
        words.pop()
    while len(words) > 1 and words[0] in ('omarchy', 'theme'):
        words.pop(0)
    return ' '.join(words)


def hex_lab(value):
    value = str(value).removeprefix('#').removeprefix('0x')[:6]
    rgb = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb)
    xyz = ((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b,
           (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)
    fx, fy, fz = (t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in xyz)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def compute_groups(items):
    """{slug: group id} from name stems and near-identical bg/fg/accent palettes."""
    slugs = [item['slug'] for item in items]

    def finder():
        parent = {s: s for s in slugs}

        def find(s):
            while parent[s] != s:
                parent[s] = parent[parent[s]]
                s = parent[s]
            return s

        def union(a, b):
            a, b = find(a), find(b)
            if a != b:
                parent[max(a, b)] = min(a, b)
        return find, union

    find_name, union_name = finder()
    find_all, union_all = finder()
    stems = {}
    for item in items:
        stems.setdefault(name_stem(item['slug'], item['name']), []).append(item['slug'])
    for members in stems.values():
        for other in members[1:]:
            union_name(members[0], other)
            union_all(members[0], other)
    labs = {}
    for item in items:
        try:
            if len(item.get('palette') or []) >= 3:
                labs[item['slug']] = [hex_lab(c) for c in item['palette'][:3]]
        except ValueError:
            pass
    keys = list(labs)
    limit = GROUP_DELTA ** 2
    for i, a in enumerate(keys):
        la = labs[a]
        for b in keys[i + 1:]:
            lb = labs[b]
            if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2 < limit for p, q in zip(la, lb)):
                union_all(a, b)
    sizes = {}
    for s in slugs:
        sizes[find_all(s)] = sizes.get(find_all(s), 0) + 1
    # A palette chain that snowballs into a big blob is not "lookalikes"; keep only name links there.
    return {s: (find_all(s) if sizes[find_all(s)] <= GROUP_CAP else find_name(s)) for s in slugs}


def theme_groups(items):
    import hashlib
    key = hashlib.sha1(json.dumps([GROUP_DELTA, GROUP_CAP, sorted(VARIANT_WORDS)] + [[i['slug'], i['name'], i.get('palette')] for i in items]).encode()).hexdigest()
    try:
        cached = json.loads(GROUPS.read_text())
        if cached.get('key') == key:
            return cached['groups']
    except Exception:
        pass
    groups = compute_groups(items)
    try:
        GROUPS.write_text(json.dumps({'key': key, 'groups': groups}))
    except Exception:
        pass
    return groups


# ---------------------------------------------------------------- follow the sun
def timezone_name():
    try:
        link = os.readlink('/etc/localtime')
        if 'zoneinfo/' in link:
            return link.split('zoneinfo/', 1)[1]
    except OSError:
        pass
    try:
        return command('timedatectl', 'show', '-p', 'Timezone', '--value', timeout=5)
    except Exception:
        return os.environ.get('TZ', '').lstrip(':')


def iso6709(text):
    """'+404251-0740023' -> (40.7142, -74.0064)."""
    import re
    m = re.fullmatch(r'([+-]\d+)([+-]\d+)', text)
    if not m:
        return None
    out = []
    for part, deg_len in ((m.group(1), 2), (m.group(2), 3)):
        sign, digits = (-1 if part[0] == '-' else 1), part[1:]
        value = int(digits[:deg_len]) + int(digits[deg_len:deg_len + 2]) / 60 + (int(digits[deg_len + 2:] or 0) / 3600)
        out.append(round(sign * value, 4))
    return tuple(out)


def timezone_location():
    zone = timezone_name()
    if not zone:
        return None
    names = [zone]
    try:
        for line in open('/usr/share/zoneinfo/tzdata.zi'):
            if line.startswith('L '):
                parts = line.split()
                if len(parts) == 3 and parts[2] == zone:
                    names.append(parts[1])
                    break
    except OSError:
        pass
    for table in ('/usr/share/zoneinfo/zone1970.tab', '/usr/share/zoneinfo/zone.tab'):
        try:
            for line in open(table):
                if line.startswith('#'):
                    continue
                parts = line.rstrip('\n').split('\t')
                if len(parts) >= 3 and parts[2] in names:
                    coords = iso6709(parts[1])
                    if coords:
                        city = parts[2].rsplit('/', 1)[-1].replace('_', ' ')
                        return {'lat': coords[0], 'lon': coords[1], 'label': city, 'source': 'timezone'}
        except OSError:
            pass
    return None


def sun_location(data):
    loc = data.get('sun_location')
    if isinstance(loc, dict) and isinstance(loc.get('lat'), (int, float)) and isinstance(loc.get('lon'), (int, float)):
        return loc
    return timezone_location()


def solar_terms(jd):
    """NOAA: equation of time (minutes) and declination (degrees) for a Julian day."""
    import math
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t)) + math.sin(2 * mr) * (0.019993 - 0.000101 * t) + math.sin(3 * mr) * 0.000289
    omega = 125.04 - 1934.136 * t
    lam = l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(math.radians(omega)))
    decl = math.degrees(math.asin(math.sin(eps) * math.sin(math.radians(lam))))
    y = math.tan(eps / 2) ** 2
    l0r = math.radians(l0)
    eqt = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return eqt, decl


def sun_elevation(lat, lon, when):
    import math
    eqt, decl = solar_terms(when / 86400 + 2440587.5)
    minutes = (when % 86400) / 60
    hour_angle = math.radians((minutes + eqt + 4 * lon) / 4 - 180)
    la, de = math.radians(lat), math.radians(decl)
    return math.degrees(math.asin(math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(hour_angle)))


def sun_events(lat, lon, day):
    """(sunrise, sunset) epoch seconds for a calendar date at the location; None in polar day/night."""
    import calendar
    import math
    midnight = calendar.timegm((day.year, day.month, day.day, 0, 0, 0))
    out = []
    for sign in (-1, 1):
        minutes = 720 - 4 * lon
        for _ in range(3):  # re-evaluate the sun's position at the event itself
            eqt, decl = solar_terms((midnight + minutes * 60) / 86400 + 2440587.5)
            la, de = math.radians(lat), math.radians(decl)
            cos_ha = (math.cos(math.radians(90.833)) - math.sin(la) * math.sin(de)) / (math.cos(la) * math.cos(de))
            if not -1 <= cos_ha <= 1:
                minutes = None
                break
            minutes = 720 - 4 * lon - eqt + sign * 4 * math.degrees(math.acos(cos_ha))
        out.append(None if minutes is None else midnight + minutes * 60)
    return tuple(out)


def sun_info(data, now=None):
    import datetime
    now = time.time() if now is None else now
    loc = sun_location(data)
    info = {'enabled': bool(data.get('sun_enabled')), 'phase': None, 'sunrise': None, 'sunset': None,
            'next_change': None, 'location': loc}
    if not loc:
        return info
    lat, lon = float(loc['lat']), float(loc['lon'])
    info['phase'] = 'day' if sun_elevation(lat, lon, now) > -0.833 else 'night'
    # The location's own calendar date; equals the local date for the timezone-derived default.
    offset = datetime.datetime.fromtimestamp(now).astimezone().utcoffset().total_seconds()
    if loc.get('source') == 'manual' and abs(offset - lon * 240) > 3 * 3600:
        offset = lon * 240
    today = datetime.datetime.fromtimestamp(now + offset, datetime.timezone.utc).date()
    rise, sset = sun_events(lat, lon, today)
    info['sunrise'] = int(rise) if rise else None
    info['sunset'] = int(sset) if sset else None
    for delta in range(-1, 4):
        events = [e for e in sun_events(lat, lon, today + datetime.timedelta(days=delta)) if e and e > now]
        if events:
            info['next_change'] = int(min(events))
            break
    return info


def theme_modes(names):
    return {name: hit[2] for name, hit in palettes(names).items()}


def sun_target(data, want):
    """Best installed theme of the wanted mode (light/dark) to switch to."""
    names = available()
    modes = theme_modes(names)
    current = current_theme()
    usable = [n for n in names if n not in data.get('excluded', []) and data.get('ratings', {}).get(n, {}).get('answer') != 'no']
    variant = variant_of(current)
    if variant and modes.get(variant) == want:
        return variant, True
    learned = (data.get('sun_themes') or {}).get(want)
    if learned in usable and modes.get(learned) == want:
        return learned, False
    favorites = [n for n in data.get('favorites', []) if n in usable and modes.get(n) == want]
    if favorites:
        return random.choice(favorites), False
    pool = [n for n in usable if modes.get(n) == want]
    return (random.choice(pool), False) if pool else ('', False)


def learn_theme(data, name):
    mode = theme_modes([name]).get(name)
    if mode in ('light', 'dark'):
        data.setdefault('sun_themes', {'light': None, 'dark': None})[mode] = name


def sun_tick(data, now):
    """Return True when the theme was switched for a sunrise/sunset."""
    if not data.get('sun_enabled') or now < data.get('sun_retry_at', 0):
        return False
    phase = sun_info(data, now)['phase']
    if phase is None or phase == data.get('sun_phase'):
        return False
    want = 'light' if phase == 'day' else 'dark'
    current = current_theme()
    if theme_modes([current]).get(current) == want:
        data['sun_phase'] = phase
        return True
    selected, is_variant = sun_target(data, want)
    if not selected:
        data['sun_phase'] = phase
        data['last_error'] = f'Follow the sun: no {want} theme is available'
        return True
    try:
        if is_variant:
            apply_variant(data, selected)
        else:
            change(data, selected=selected)
            data['pending_review'] = None
    except Exception as exc:
        data['sun_retry_at'] = now + 300
        data['last_error'] = f'Follow the sun: {exc}'
        return True
    data['sun_phase'] = phase
    data.pop('sun_retry_at', None)
    return True


def apply_variant(data, selected):
    background = (HOME / '.local/state/omarchy/current/background').resolve(strict=False).name
    set_theme(selected)
    if current_theme() != selected:
        raise RuntimeError(f'Omarchy did not activate {selected}')
    matching = HOME / '.local/state/omarchy/current/theme/backgrounds' / background
    if matching.is_file():
        command('omarchy', 'theme', 'bg', 'set', str(matching), timeout=30)
    data['current'] = selected
    data['last_change'] = time.time()
    data['next_at'] = data['last_change'] + data['interval_minutes'] * 60
    data['pending_review'] = None
    data['last_error'] = ''


def variant_of(name):
    """Pair any theme `x` with an installed `x-light`, and back."""
    target = name.removesuffix('-light') if name.endswith('-light') else name + '-light'
    return target if name and target in available() else ''


def atomic(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=STATE_DIR, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, STATE_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


SUN_DEFAULTS = {'sun_enabled': False, 'sun_location': None, 'sun_themes': {'light': None, 'dark': None}, 'sun_phase': None}


def load():
    now = time.time()
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        for key, value in SUN_DEFAULTS.items():
            data.setdefault(key, json.loads(json.dumps(value)))
        return data
    return {**json.loads(json.dumps(SUN_DEFAULTS)), 
        'enabled': True, 'interval_minutes': 15, 'shuffle_background': False,
        'next_at': now + 900, 'pool': [], 'ratings': {}, 'favorites': [], 'pending_review': None,
        'current': current_theme(), 'last_change': None, 'last_error': '',
        'session': os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', ''),
    }


def public(data):
    result = dict(data)
    names = available()
    result['available_count'] = sum(n not in data.get('excluded', []) and data.get('ratings', {}).get(n, {}).get('answer') != 'no' for n in names)
    result['current'] = current_theme() or data.get('current', '')
    result['current_name'] = labels().get(result['current'], result['current'].replace('-', ' ').title())
    result['favorites'] = sorted(set(data.get('favorites', [])))
    result['current_favorite'] = result['current'] in result['favorites']
    result['favorite_count'] = len(result['favorites'])
    result['themes'] = theme_catalog(data)
    result['installed_favorite_count'] = sum(item['favorite'] for item in result['themes'])
    result['seconds_remaining'] = max(0, int(data['next_at'] - time.time())) if data['enabled'] else None
    result['background'] = str((HOME / '.local/state/omarchy/current/background').resolve(strict=False))
    images = theme_backgrounds()
    result['backgrounds'] = [{'path': str(p), 'url': p.as_uri(), 'name': p.stem} for p in images]
    result['background_index'] = next((i for i, p in enumerate(images) if str(p) == result['background']), -1)
    result['variant_target'] = variant_of(result['current'])
    base = result['variant_target'].removesuffix('-light')
    result['variant_name'] = labels().get(base, base.removeprefix('gallery-').replace('-', ' ').title())
    result['can_delete_current'] = gallery_slug(result['current']) is not None or studio_theme(result['current'])
    installed = set(names)
    result['hidden_count'] = sum(n in installed for n in data.get('excluded', []))
    cur = next((t for t in result['themes'] if t['slug'] == result['current']), None)
    result['current_palette'] = cur['palette'] if cur else []
    result['recent'] = recent_themes(result['current'], installed)
    options = border_options(result['current'])
    fallback = data.get('border_default') or 'theme'
    choice = (data.get('borders') or {}).get(result['current'], fallback)
    result['border'] = {'choice': choice, 'global': fallback, 'options': options, 'default': live_border(),
                        'installed': border_installed(), 'supported': border_supported()}
    sun = sun_info(data)
    learned = data.get('sun_themes') or {}
    display = labels()
    for mode in ('light', 'dark'):
        slug = learned.get(mode) or ''
        sun[f'{mode}_theme'] = slug
        sun[f'{mode}_name'] = display.get(slug, slug.removeprefix('gallery-').replace('-', ' ').title()) if slug else ''
    result['sun'] = sun
    result.pop('sun_retry_at', None)
    return result


def gallery_slug(name):
    if not name.startswith('gallery-'):
        return None
    slug = name.removeprefix('gallery-')
    if not slug or not all(c.islower() or c.isdigit() or c == '-' for c in slug):
        return None
    if not GALLERY.exists() or slug not in {item['slug'] for item in json.loads(GALLERY.read_text())['themes']}:
        return None
    return slug


def choose(data, names):
    current = current_theme()
    names = [name for name in names if name not in data.get('excluded', []) and data.get('ratings', {}).get(name, {}).get('answer') != 'no']
    if data.get('sun_enabled'):
        phase = sun_info(data)['phase']
        if phase:
            want = 'light' if phase == 'day' else 'dark'
            modes = theme_modes(names)
            names = [n for n in names if modes.get(n) == want] or names
    pool = [x for x in data.get('pool', []) if x in names and x != current]
    if not pool:
        pool = [x for x in names if x != current]
        random.shuffle(pool)
    if not pool:
        raise RuntimeError('No second theme is available')
    selected = pool.pop()
    data['pool'] = pool
    return selected


def theme_backgrounds():
    """Mirror Omarchy's two background locations, resolving duplicate symlinks."""
    name = current_theme()
    roots = [HOME / '.config/omarchy/backgrounds' / name, HOME / '.local/state/omarchy/current/theme/backgrounds']
    images = sorted(p for folder in roots if folder.is_dir() for p in folder.iterdir()
                    if p.is_file() and p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'))
    return list(dict.fromkeys(p.resolve() for p in images))


def select_background(value, step=False):
    images = theme_backgrounds()
    if not images:
        raise ValueError('This theme has no backgrounds')
    current = (HOME / '.local/state/omarchy/current/background').resolve(strict=False)
    if step:
        direction = int(value)
        if direction not in (-1, 1):
            raise ValueError('Choose previous or next background')
        index = images.index(current) if current in images else (-1 if direction == 1 else 0)
        selected = images[(index + direction) % len(images)]
    else:
        selected = Path(value).resolve()
        if selected not in images:
            raise ValueError('That background is no longer in the current theme')
    command('omarchy', 'theme', 'bg', 'set', str(selected), timeout=30)


def shuffle_background():
    images = theme_backgrounds()
    if len(images) > 1:
        current = (HOME / '.local/state/omarchy/current/background').resolve(strict=False)
        choice = random.choice([p for p in images if p.resolve() != current] or images)
        command('omarchy', 'theme', 'bg', 'set', str(choice), timeout=30)


def change(data, selected=None):
    names = available()
    if selected is None:
        if len(names) < 2:
            raise RuntimeError('Theme gallery is not installed')
        selected = choose(data, names)
    elif selected not in names:
        raise ValueError('That theme is no longer installed')
    before = current_theme()
    remembered = data.setdefault('theme_backgrounds', {})
    if before:
        remembered[before] = background_name()
    want = remembered.get(selected)
    keep = want if want and not data.get('shuffle_background') and has_background(selected, want) else None
    set_theme(selected, background=keep)
    if current_theme() != selected:
        raise RuntimeError(f'Omarchy did not activate {selected}')
    if before and before != selected:
        data['previous_theme'] = before
    data['current'] = selected
    data['last_change'] = time.time()
    data['next_at'] = data['last_change'] + data['interval_minutes'] * 60
    data['pending_review'] = selected
    data['last_error'] = ''
    if data['shuffle_background']:
        try:
            shuffle_background()
        except Exception as exc:
            data['last_error'] = f'Background shuffle: {exc}'
    return selected


def open_review():
    for _ in range(5):
        try:
            command('omarchy-shell', 'io.github.denonmaryland.theme-studio', 'review', timeout=8)
            return
        except Exception:
            time.sleep(1)
    subprocess.run(['notify-send', 'Theme changed', 'Open the palette icon in the bar if you want to delete this theme.'], check=False, timeout=8)


RECENT_DEPTH = 10  # how far Back / Recent reach
HISTORY_KEEP = 20


def migrate_legacy():
    """One-time copy of state from the pre-release plugin name."""
    if STATE_DIR.exists() or not LEGACY_STATE.is_dir():
        return
    shutil.copytree(LEGACY_STATE, STATE_DIR, ignore=shutil.ignore_patterns('*.lock', '.pending-*'))


def note_history(theme=None):
    """Append the current theme to Recent history (newest last, no repeats)."""
    theme = theme or current_theme()
    if not theme:
        return
    path = STATE_DIR / 'history'
    try:
        names = path.read_text().split()
    except OSError:
        names = []
    if names and names[-1] == theme:
        return
    names = [n for n in names if n != theme][-(HISTORY_KEEP - 1):] + [theme]
    pending = path.with_suffix('.pending')
    pending.write_text('\n'.join(names) + '\n')
    os.replace(pending, path)


def border_installed():
    try:
        return BORDER_LINE.split('  --')[0] in (HYPR_DIR / 'hyprland.lua').read_text()
    except OSError:
        return False


def border_supported():
    return (HYPR_DIR / 'hyprland.lua').is_file()


def border_install():
    """Add the border override (one file + one marked line). Only on explicit consent."""
    if not border_supported():
        raise RuntimeError('Window borders need the Lua Hyprland config (~/.config/hypr/hyprland.lua)')
    shutil.copyfile(PLUGIN_DIR / 'extras/hypr/theme_border.lua', HYPR_DIR / f'{BORDER_MODULE}.lua')
    if not border_installed():
        main = HYPR_DIR / 'hyprland.lua'
        text = main.read_text()
        main.write_text(text + ('' if text.endswith('\n') else '\n') + '\n' + BORDER_LINE + '\n')
    subprocess.run(['hyprctl', 'reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def border_uninstall():
    """Remove exactly what border_install added."""
    main = HYPR_DIR / 'hyprland.lua'
    try:
        lines = main.read_text().splitlines(keepends=True)
    except OSError:
        lines = None
    if lines is not None:
        kept = [l for l in lines if not l.strip().startswith(BORDER_LINE.split('  --')[0])]
        while kept and kept[-1].strip() == '' and len(kept) < len(lines):
            kept.pop()
        if kept != lines:
            main.write_text(''.join(kept))
    (HYPR_DIR / f'{BORDER_MODULE}.lua').unlink(missing_ok=True)
    subprocess.run(['hyprctl', 'reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def recent_themes(current, installed):
    """Newest-first themes you were on before `current`, from the history hook."""
    try:
        history = (STATE_DIR / 'history').read_text().split()
    except OSError:
        history = []
    out = []
    for name in reversed(history):
        if name != current and name in installed and name not in out:
            out.append(name)
    return out[:RECENT_DEPTH]


def previous_theme(data, theme):
    """Most recent other installed theme, from the theme-set history hook."""
    installed = set(available())
    try:
        recent = (STATE_DIR / 'history').read_text().split()[::-1]
    except OSError:
        recent = []
    for name in recent + [data.get('previous_theme')]:
        if name and name != theme and name in installed:
            return name
    return None


def remove_unwanted(data):
    theme = current_theme()
    if not theme:
        raise RuntimeError('No current theme to remove')
    slug = gallery_slug(theme)
    installed = LIVE_THEMES / theme
    studio = studio_theme(theme)
    source = GALLERY.parent / 'repos' / slug if slug else None
    if slug and (not installed.is_dir() or installed.is_symlink() or not source.is_dir() or source.is_symlink()):
        raise RuntimeError('Gallery theme files changed; nothing was deleted')
    data.setdefault('excluded', []).append(theme)
    data['excluded'] = sorted(set(data['excluded']))
    try:
        change(data, selected=previous_theme(data, theme))
    except Exception:
        data['excluded'].remove(theme)
        raise
    data['pending_review'] = None  # a deletion is not a rotation; don't ask to keep the replacement
    if slug:
        command('omarchy', 'theme', 'remove', theme, timeout=60)
        shutil.rmtree(source)
        manifest = json.loads(GALLERY.read_text())
        for item in manifest['themes']:
            if item['slug'] == slug:
                item['status'] = 'deleted-by-user'
                item['deleted_at'] = time.time()
                break
        fd, temp = tempfile.mkstemp(prefix='.manifest-', dir=GALLERY.parent)
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(manifest, out, indent=2, ensure_ascii=False)
                out.write('\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, GALLERY)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    if studio:
        shutil.rmtree(installed)
        (THUMBS / f'{theme}.jpg').unlink(missing_ok=True)
        data['excluded'] = [n for n in data['excluded'] if n != theme]
    data['favorites'] = [name for name in data.get('favorites', []) if name != theme]
    return theme


def studio_theme(name):
    """Themes installed by the Theme Studio importer (safe to delete outright)."""
    folder = LIVE_THEMES / name
    return bool(name) and folder.is_dir() and not folder.is_symlink() and (folder / '.theme-studio').is_file() and not (STOCK_THEMES / name).exists()


def execute(action, value=None):
    migrate_legacy()
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    changed = False
    with (STATE_DIR / 'operation.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load()
        now = time.time()
        note_history()
        if action in ('state', 'note'):
            return public(data)
        if action == 'thumbs':
            return {'made': make_thumbs()}
        instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
        if action == 'tick' and data.get('session') != instance:
            # New desktop session: restart the countdown (the shell drives ticks).
            data['session'] = instance
            data['next_at'] = now + data['interval_minutes'] * 60
            atomic(data)
            return public(data)
        if action == 'tick' and sun_tick(data, now):
            atomic(data)
            return public(data)
        if action == 'tick' and (not data['enabled'] or now < data['next_at']):
            return public(data)
        if action == 'toggle':
            data['enabled'] = not data['enabled']
            if data['enabled']:
                data['next_at'] = now + data['interval_minutes'] * 60
        elif action == 'interval':
            minutes = int(value)
            if minutes not in MINUTES:
                raise ValueError('Choose 15, 30, or 60 minutes')
            data['interval_minutes'] = minutes
            data['next_at'] = now + minutes * 60
        elif action == 'background-mode':
            if value not in ('theme', 'shuffle'):
                raise ValueError('Choose theme or shuffle')
            data['shuffle_background'] = value == 'shuffle'
        elif action == 'background-next':
            command('omarchy', 'theme', 'bg', 'next', timeout=30)
        elif action == 'background-step':
            select_background(value, step=True)
        elif action == 'background-set':
            select_background(value)
        elif action == 'variant':
            selected = variant_of(current_theme())
            if not selected:
                raise ValueError('No matching light/dark theme is installed')
            apply_variant(data, selected)
            learn_theme(data, selected)
        elif action == 'favorite':
            theme = value or current_theme()
            if theme not in available():
                raise ValueError('That theme is no longer installed')
            favorites = set(data.get('favorites', []))
            if theme in favorites:
                favorites.remove(theme)
            else:
                favorites.add(theme)
            data['favorites'] = sorted(favorites)
        elif action == 'theme-select':
            if value not in available():
                raise ValueError('That theme is no longer installed')
            if value != current_theme():
                change(data, selected=value)
                data['pending_review'] = None
            learn_theme(data, value)
        elif action == 'border-install':
            border_install()
        elif action == 'cleanup':
            border_uninstall()
        elif action == 'border':
            if not border_installed():
                raise PermissionError('Allow the window border change first')
            theme = current_theme()
            borders = data.setdefault('borders', {})
            value = 'theme' if value == 'default' else value
            if value not in ('theme', 'none') and value not in {o['key'] for o in border_options(theme)}:
                raise ValueError('Pick a colour from this theme')
            if value == (data.get('border_default') or 'theme'):
                borders.pop(theme, None)  # same as the global default: just follow it
            else:
                borders[theme] = value
            write_borders(data)
        elif action == 'border-default':
            if not border_installed():
                raise PermissionError('Allow the window border change first')
            if value not in ('theme', 'none'):
                raise ValueError('Choose theme or none')
            data['border_default'] = value  # explicit per-theme picks still win
            write_borders(data)
        elif action == 'sun-toggle':
            data['sun_enabled'] = not data.get('sun_enabled')
            data['sun_phase'] = None  # apply the right mode on the next tick
            data.pop('sun_retry_at', None)
        elif action == 'sun-location':
            text = (value or '').strip().lower()
            if text in ('', 'auto'):
                data['sun_location'] = None
            else:
                try:
                    lat, lon = (float(part) for part in text.split(','))
                except ValueError:
                    raise ValueError('Use "lat,lon" (for example 38.90,-77.04) or auto') from None
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError('Latitude must be -90..90 and longitude -180..180')
                data['sun_location'] = {'lat': round(lat, 4), 'lon': round(lon, 4), 'label': f'{lat:.2f}, {lon:.2f}', 'source': 'manual'}
            if data.get('sun_enabled'):
                data['sun_phase'] = None
        elif action == 'remove-current':
            try:
                remove_unwanted(data)
            except Exception as exc:
                data['enabled'] = False
                data['last_error'] = str(exc)
                atomic(data)
                raise
        elif action == 'hide-current':
            theme = current_theme()
            data.setdefault('excluded', []).append(theme)
            data['excluded'] = sorted(set(data['excluded']))
            data['pending_review'] = None
            changed = bool(change(data))
        elif action == 'unhide-all':
            # Keep exclusions for deleted gallery themes so the collector never re-downloads them.
            installed = set(available())
            data['excluded'] = [n for n in data.get('excluded', []) if n not in installed]
        elif action == 'rate':
            if value not in ('yes', 'no', 'maybe'):
                raise ValueError('Choose yes, no, or maybe')
            theme = data.get('pending_review') or current_theme()
            if not theme:
                raise RuntimeError('No current theme to rate')
            data['ratings'][theme] = {'answer': value, 'at': now}
            data['pending_review'] = None
            if value == 'yes':
                data['enabled'] = False
            elif value == 'no':
                try:
                    changed = bool(change(data))
                except Exception as exc:
                    data['enabled'] = False
                    data['last_error'] = str(exc)
                    atomic(data)
                    raise
        elif action == 'random' or (action == 'tick' and data['enabled'] and now >= data['next_at']):
            try:
                changed = bool(change(data))
            except Exception as exc:
                data['enabled'] = False
                data['last_error'] = str(exc)
                atomic(data)
                raise
        elif action != 'tick':
            raise ValueError('Unknown action')
        atomic(data)
        response = public(data)
    if changed:
        open_review()
    return response


def daemon():
    instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    with (STATE_DIR / 'daemon.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (STATE_DIR / 'operation.lock').open('w') as op:
            fcntl.flock(op, fcntl.LOCK_EX)
            data = load()
            if data.get('session') != instance:
                data['session'] = instance
                data['next_at'] = time.time() + data['interval_minutes'] * 60
            atomic(data)
        while True:
            time.sleep(5)
            try:
                execute('tick')
            except Exception as exc:
                print('Theme rotation paused:', exc, file=sys.stderr, flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('state', 'thumbs', 'hide-current', 'unhide-all', 'variant', 'toggle', 'interval', 'background-mode', 'background-next', 'background-step', 'background-set', 'theme-select', 'favorite', 'border', 'border-default', 'border-install', 'cleanup', 'note', 'sun-toggle', 'sun-location', 'rate', 'remove-current', 'random', 'tick', 'daemon'))
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    if args.action == 'daemon':
        daemon()
    else:
        print(json.dumps(execute(args.action, args.value), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('theme-studio:', exc, file=sys.stderr)
        sys.exit(1)

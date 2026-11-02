#!/usr/bin/env python3
"""Update checks for Best Theme Plugin Ever.

Plugins added with `omarchy plugin add` are git checkouts. A check fetches the
checkout's own origin (the repository it was installed from) and compares the
manifest version there with the installed one. Installing hands off to
Omarchy's `omarchy plugin update`, which fast-forwards, validates and rolls
back on failure. Nothing here runs code from the fetched commit.

Actions print one JSON object:
  status          cached result plus the installed version (no network)
  check [auto]    fetch and compare; "auto" honors the setting and a daily limit
  install         run `omarchy plugin update <id> --yes`
  auto on|off     turn automatic daily checks on or off
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

PLUGIN_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = Path.home() / '.local/state/omarchy-theme-studio'
AUTO_INTERVAL = 20 * 3600  # roughly once a day, without drifting later each day
GIT_ENV = {'GIT_TERMINAL_PROMPT': '0', 'GIT_SSH_COMMAND': 'ssh -oBatchMode=yes', 'GIT_ASKPASS': '/bin/false'}


def state_file(state_dir):
    return Path(state_dir) / 'updates.json'


def load(state_dir):
    try:
        data = json.loads(state_file(state_dir).read_text())
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save(state_dir, data):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=state_dir, prefix='.updates-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, state_file(state_dir))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def git(plugin_dir, *args, timeout=20):
    return subprocess.run(['git', '-C', str(plugin_dir), *args], capture_output=True, text=True,
                          timeout=timeout, env={**os.environ, **GIT_ENV}, stdin=subprocess.DEVNULL)


def manifest(plugin_dir):
    return json.loads((Path(plugin_dir) / 'manifest.json').read_text())


def version_key(value):
    parts = re.findall(r'\d+', str(value or ''))
    return tuple(int(p) for p in parts[:4]) if parts else None


def newer(latest, current):
    a, b = version_key(latest), version_key(current)
    if a is None or b is None:
        return False
    return a > b


def managed(plugin_dir):
    return (Path(plugin_dir) / '.git').exists()


def status(plugin_dir=PLUGIN_DIR, state_dir=STATE_DIR):
    data = load(state_dir)
    current = str(manifest(plugin_dir).get('version', ''))
    latest = data.get('latest_version') or ''
    return {
        'ok': True,
        'auto_check': data.get('auto_check', True),
        'managed': managed(plugin_dir),
        'current_version': current,
        'latest_version': latest,
        'available': bool(latest) and newer(latest, current),
        'changes': data.get('changes', []) if latest and newer(latest, current) else [],
        'checked_at': data.get('checked_at'),
        'error': data.get('error', ''),
    }


def fetch_latest(plugin_dir):
    """Fetch origin's HEAD and read its manifest version without checking it out."""
    result = git(plugin_dir, 'fetch', '--quiet', '--no-tags', '--no-recurse-submodules', 'origin', 'HEAD', timeout=60)
    if result.returncode != 0:
        raise RuntimeError("Couldn't reach the plugin's repository.")
    commit = git(plugin_dir, 'rev-parse', 'FETCH_HEAD').stdout.strip()
    shown = git(plugin_dir, 'show', f'{commit}:manifest.json')
    if shown.returncode != 0:
        raise RuntimeError("The repository's latest version has no manifest.")
    try:
        version = str(json.loads(shown.stdout).get('version', ''))[:24]
    except ValueError:
        raise RuntimeError("The repository's latest manifest is unreadable.")
    log = git(plugin_dir, 'log', '--format=%s', '-n', '8', f'HEAD..{commit}')
    changes = [line.strip()[:120] for line in log.stdout.splitlines() if line.strip()]
    return {'latest_version': version, 'latest_commit': commit, 'changes': changes}


def check(plugin_dir=PLUGIN_DIR, state_dir=STATE_DIR, auto=False, now=None):
    now = time.time() if now is None else now
    with lock(state_dir):
        data = load(state_dir)
        if auto and (not data.get('auto_check', True) or now - float(data.get('checked_at') or 0) < AUTO_INTERVAL):
            return status(plugin_dir, state_dir)
        if not managed(plugin_dir):
            return status(plugin_dir, state_dir)
        data['checked_at'] = now
        try:
            data.update(fetch_latest(plugin_dir))
            data['error'] = ''
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            data['error'] = str(exc) if isinstance(exc, RuntimeError) else "Couldn't check for updates."
        save(state_dir, data)
    return status(plugin_dir, state_dir)


def install(plugin_dir=PLUGIN_DIR, state_dir=STATE_DIR, runner=subprocess.run):
    if not managed(plugin_dir):
        raise RuntimeError('This copy was not installed with omarchy plugin add, so it cannot update itself.')
    plugin_id = manifest(plugin_dir)['id']
    before = str(manifest(plugin_dir).get('version', ''))
    result = runner(['omarchy', 'plugin', 'update', plugin_id, '--yes'], capture_output=True, text=True,
                    timeout=300, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        lines = [l for l in (result.stderr or '').splitlines() if l.strip()]
        detail = lines[-1].removeprefix('omarchy-plugin-update: ') if lines else ''
        raise RuntimeError(f'Update failed: {detail}' if detail else 'Update failed.')
    after = status(plugin_dir, state_dir)
    after['installed'] = after['current_version'] != before
    after['previous_version'] = before
    return after


def set_auto(value, state_dir=STATE_DIR, plugin_dir=PLUGIN_DIR):
    if value not in ('on', 'off'):
        raise ValueError('Choose on or off')
    with lock(state_dir):
        data = load(state_dir)
        data['auto_check'] = value == 'on'
        save(state_dir, data)
    return status(plugin_dir, state_dir)


class lock:
    def __init__(self, state_dir):
        self.path = Path(state_dir) / 'updates.lock'

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.handle = self.path.open('w')
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        self.handle.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('status', 'check', 'install', 'auto'))
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    if args.action == 'status':
        result = status()
    elif args.action == 'check':
        result = check(auto=args.value == 'auto')
    elif args.action == 'install':
        result = install()
    else:
        result = set_auto(args.value)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('theme-studio:', exc, file=sys.stderr)
        sys.exit(1)

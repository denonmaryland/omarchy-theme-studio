"""Isolated checks of control.py actions; the live desktop is never touched."""
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
import unittest.mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('control', ROOT / 'helpers/control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class RotationReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='theme-studio-control-')
        self.addCleanup(tmp.cleanup)
        self.saved = []

        def fake_change(data, selected=None):
            # Stand-in for a successful switch; the real one asks for a review.
            data['current'] = 'picked'
            data['pending_review'] = 'picked'
            return 'picked'

        stubs = {'STATE_DIR': Path(tmp.name), 'migrate_legacy': lambda: None,
                 'note_history': lambda: None, 'change': fake_change,
                 'atomic': lambda data: self.saved.append(dict(data)), 'public': lambda data: data}
        for name, value in stubs.items():
            p = patch.object(control, name, value)
            p.start()
            self.addCleanup(p.stop)

    def run_action(self, action, **state):
        data = {'enabled': False, 'next_at': 0, 'session': '', 'pending_review': None, **state}
        with patch.object(control, 'load', lambda: data), patch.dict('os.environ', {'HYPRLAND_INSTANCE_SIGNATURE': ''}):
            return control.execute(action)

    def test_surprise_pick_does_not_ask_for_a_rotation_review(self):
        self.assertIsNone(self.run_action('random')['pending_review'])

    def test_automatic_rotation_still_asks_for_a_review(self):
        result = self.run_action('tick', enabled=True, next_at=time.time() - 1)
        self.assertEqual(result['pending_review'], 'picked')


class BackgroundUrlTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='theme-studio-control-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.live = self.root / 'themes'
        self.current = self.root / 'current/theme/backgrounds'
        for folder in (self.live / 'dusk/backgrounds', self.current):
            folder.mkdir(parents=True)
        for name, value in {'LIVE_THEMES': self.live, 'STOCK_THEMES': self.root / 'stock'}.items():
            p = patch.object(control, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_thumbnail_points_at_the_themes_own_copy(self):
        (self.live / 'dusk/backgrounds/1.png').write_bytes(b'x')
        (self.current / '1.png').write_bytes(b'x')
        url = control.background_url('dusk', self.current / '1.png')
        self.assertEqual(url, (self.live / 'dusk/backgrounds/1.png').as_uri())

    def test_falls_back_when_only_the_current_copy_exists(self):
        (self.current / 'generated.png').write_bytes(b'x')
        url = control.background_url('dusk', self.current / 'generated.png')
        self.assertEqual(url, (self.current / 'generated.png').as_uri())

    def test_does_not_follow_a_symlinked_copy(self):
        (self.root / 'elsewhere.png').write_bytes(b'x')
        (self.live / 'dusk/backgrounds/2.png').symlink_to(self.root / 'elsewhere.png')
        (self.current / '2.png').write_bytes(b'x')
        url = control.background_url('dusk', self.current / '2.png')
        self.assertEqual(url, (self.current / '2.png').as_uri())


class BorderLineTests(unittest.TestCase):
    OLD_LINE = 'require("hypr.theme_studio_border")  -- Theme Studio: window border colors (remove via the panel)'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='theme-studio-control-')
        self.addCleanup(tmp.cleanup)
        self.hypr = Path(tmp.name)
        self.main = self.hypr / 'hyprland.lua'
        for name, value in {'HYPR_DIR': self.hypr, 'subprocess': unittest.mock.MagicMock()}.items():
            p = patch.object(control, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_line_written_under_the_old_name_is_still_found_and_removed(self):
        self.main.write_text('-- user config\nlocal keep = 1\n\n' + self.OLD_LINE + '\n')
        (self.hypr / 'theme_studio_border.lua').write_text('-- module')
        self.assertTrue(control.border_installed())
        control.border_uninstall()
        self.assertEqual(self.main.read_text(), '-- user config\nlocal keep = 1\n')
        self.assertFalse((self.hypr / 'theme_studio_border.lua').exists())



class Omarchy45BackgroundTests(unittest.TestCase):
    """Video backgrounds, theme-intro friendly skipping and 4.0 fallbacks."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='theme-studio-control-')
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.live = self.home / '.config/omarchy/themes'
        self.stock = self.home / 'stock'
        self.current = self.home / '.local/state/omarchy/current'
        (self.current / 'theme/backgrounds').mkdir(parents=True)
        (self.current / 'theme.name').write_text('dusk\n')
        self.calls = []
        self.video = True
        stubs = {'HOME': self.home, 'LIVE_THEMES': self.live, 'STOCK_THEMES': self.stock,
                 'THUMBS': self.home / 'thumbs', 'VIDEO_THUMBS': self.home / 'thumbs/video',
                 'STATE_DIR': self.home / 'state', 'video_backgrounds': lambda: self.video,
                 'command': lambda *args, **kw: self.calls.append(args) or ''}
        for name, value in stubs.items():
            p = patch.object(control, name, value)
            p.start()
            self.addCleanup(p.stop)

    def backgrounds(self, theme, *names):
        folder = self.live / theme / 'backgrounds'
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / name).write_bytes(b'x')
        return folder

    def test_videos_listed_only_where_omarchy_plays_them(self):
        for name in ('a.png', 'b.mp4'):
            (self.current / 'theme/backgrounds' / name).write_bytes(b'x')
        self.assertEqual([p.name for p in control.theme_backgrounds()], ['a.png', 'b.mp4'])
        self.video = False
        self.assertEqual([p.name for p in control.theme_backgrounds()], ['a.png'])

    def test_remembered_video_is_restored(self):
        for name in ('a.png', 'clip.webm'):
            (self.current / 'theme/backgrounds' / name).write_bytes(b'x')
        control.restore_background('clip.webm')
        self.assertEqual(self.calls[-1][-1], str((self.current / 'theme/backgrounds/clip.webm').resolve()))

    def test_video_tile_without_thumbnailer_gets_a_placeholder(self):
        (self.current / 'theme/backgrounds/clip.mp4').write_bytes(b'x')
        with patch.object(control.shutil, 'which', lambda name: None):
            self.assertEqual(control.video_thumb(self.current / 'theme/backgrounds/clip.mp4'), '')

    def test_skip_on_40_when_restoring_a_remembered_wallpaper(self):
        self.video = False
        self.assertTrue(control.skip_background('dawn', '2.png', own_background=False))
        self.assertFalse(control.skip_background('dawn', None, own_background=False))

    def test_no_skip_on_45_when_omarchy_remembers_the_same_wallpaper(self):
        folder = self.backgrounds('dawn', '2.png')
        memory = self.home / '.local/state/omarchy/theme-backgrounds'
        memory.mkdir(parents=True)
        (memory / 'dawn').write_text(f'{folder / "2.png"}\n')
        self.assertFalse(control.skip_background('dawn', '2.png', own_background=False))
        # Its memory disagrees with ours: still skip, then restore ours (one transition).
        self.assertTrue(control.skip_background('dawn', '3.png', own_background=False))

    def test_no_skip_on_45_when_memory_points_into_the_current_theme(self):
        # Omarchy writes readlink -f of the background link: a path under
        # current/theme/backgrounds/ that belongs to the theme being left.
        self.backgrounds('dawn', '2.png')
        memory = self.home / '.local/state/omarchy/theme-backgrounds'
        memory.mkdir(parents=True, exist_ok=True)
        (memory / 'dawn').write_text(f'{self.current / "theme/backgrounds/2.png"}\n')
        self.assertFalse(control.skip_background('dawn', '2.png', own_background=False))

    def test_own_wallpaper_always_skips(self):
        for video in (False, True):
            self.video = video
            self.assertTrue(control.skip_background('dawn', '2.png', own_background=True))
            self.assertFalse(control.skip_background('dawn', None, own_background=True))

    def test_restore_leaves_omarchys_matching_pick_alone(self):
        target = self.current / 'theme/backgrounds/2.png'
        target.write_bytes(b'x')
        (self.current / 'background').symlink_to(target)
        control.restore_background('2.png', force=False)
        self.assertEqual(self.calls, [])
        control.restore_background('2.png')
        self.assertEqual(len(self.calls), 1)

    def test_shuffle_switch_skips_omarchys_pick(self):
        self.backgrounds('dawn', '1.png', '2.mp4')
        seen = []

        def fake_set(selected, timeout=60, background=None, own_background=False):
            seen.append((background, own_background))
            (self.current / 'theme.name').write_text(selected + '\n')

        data = {'shuffle_background': True, 'interval_minutes': 15}
        with patch.object(control, 'set_theme', fake_set), patch.object(control, 'background_name', lambda: 'x.png'):
            control.change(data, selected='dawn')
        background, own = seen[-1]
        self.assertIn(background, ('1.png', '2.mp4'))
        self.assertTrue(own)

    def test_follow_the_sun_variant_skips_only_with_a_matching_wallpaper(self):
        self.backgrounds('dusk-light', '1.png')
        seen = []

        def fake_set(selected, timeout=60, background=None, own_background=False):
            seen.append(background)
            (self.current / 'theme.name').write_text(selected + '\n')

        data = {'interval_minutes': 15}
        with patch.object(control, 'set_theme', fake_set):
            with patch.object(control, 'background_name', lambda: '1.png'):
                control.apply_variant(data, 'dusk-light')
            with patch.object(control, 'background_name', lambda: 'other.png'):
                control.apply_variant(data, 'dusk-light')
        self.assertEqual(seen, ['1.png', None])


if __name__ == '__main__':
    unittest.main()

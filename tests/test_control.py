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


if __name__ == '__main__':
    unittest.main()

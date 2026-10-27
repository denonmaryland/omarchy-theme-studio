"""Isolated checks of control.py actions; the live desktop is never touched."""
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
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


if __name__ == '__main__':
    unittest.main()

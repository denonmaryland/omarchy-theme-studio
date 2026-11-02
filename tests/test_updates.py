"""Isolated update-check regressions: local repositories, no network, no omarchy."""
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('updates', ROOT / 'helpers/updates.py')
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                   env={'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                        'GIT_COMMITTER_EMAIL': 't@t', 'HOME': str(cwd), 'PATH': '/usr/bin:/bin'})


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='theme-studio-updates-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.upstream, self.plugin, self.state = root / 'upstream', root / 'plugin', root / 'state'
        self.upstream.mkdir()
        run('git', 'init', '-q', '-b', 'main', cwd=self.upstream)
        self.release('0.1.0', 'Release 0.1.0')
        run('git', 'clone', '-q', str(self.upstream), str(self.plugin), cwd=root)

    def release(self, version, subject):
        (self.upstream / 'manifest.json').write_text(json.dumps({'id': 'io.example.studio', 'version': version}))
        run('git', 'add', '.', cwd=self.upstream)
        run('git', 'commit', '-q', '--allow-empty', '-m', subject, cwd=self.upstream)

    def check(self, **kw):
        return updates.check(self.plugin, self.state, **kw)

    def test_up_to_date(self):
        result = self.check()
        self.assertFalse(result['available'])
        self.assertEqual(result['current_version'], '0.1.0')
        self.assertEqual(result['error'], '')

    def test_newer_version_is_offered_with_its_changes(self):
        self.release('0.2.0', 'Add update checks')
        result = self.check()
        self.assertTrue(result['available'])
        self.assertEqual(result['latest_version'], '0.2.0')
        self.assertEqual(result['changes'], ['Add update checks'])
        # The check only fetches; the installed files are untouched.
        self.assertEqual(json.loads((self.plugin / 'manifest.json').read_text())['version'], '0.1.0')

    def test_commits_without_a_version_bump_do_not_nag(self):
        (self.upstream / 'README.md').write_text('docs')
        run('git', 'add', '.', cwd=self.upstream)
        run('git', 'commit', '-q', '-m', 'README tweak', cwd=self.upstream)
        self.assertFalse(self.check()['available'])

    def test_versions_compare_numerically(self):
        self.assertTrue(updates.newer('0.10.0', '0.9.3'))
        self.assertFalse(updates.newer('0.1.0', '0.1.0'))
        self.assertFalse(updates.newer('0.0.9', '0.1.0'))
        self.assertFalse(updates.newer('', '0.1.0'))

    def test_automatic_checks_run_at_most_daily_and_respect_the_setting(self):
        self.check(now=1000)
        self.release('0.2.0', 'Newer')
        self.assertFalse(self.check(auto=True, now=2000)['available'])  # too soon
        self.assertTrue(self.check(auto=True, now=1000 + updates.AUTO_INTERVAL)['available'])
        updates.set_auto('off', self.state, self.plugin)
        self.release('0.3.0', 'Newest')
        result = self.check(auto=True, now=10 ** 9)
        self.assertFalse(result['auto_check'])
        self.assertEqual(result['latest_version'], '0.2.0')
        # A manual check still works with automatic checks off.
        self.assertEqual(self.check(now=10 ** 9)['latest_version'], '0.3.0')

    def test_unreachable_repository_reports_an_error_without_an_update(self):
        run('git', 'remote', 'set-url', 'origin', str(self.plugin.parent / 'missing'), cwd=self.plugin)
        result = self.check()
        self.assertFalse(result['available'])
        self.assertIn("Couldn't reach", result['error'])

    def test_non_git_copy_is_reported_as_unmanaged(self):
        copy = self.plugin.parent / 'copy'
        copy.mkdir()
        (copy / 'manifest.json').write_text(json.dumps({'id': 'io.example.studio', 'version': '0.1.0'}))
        result = updates.check(copy, self.state)
        self.assertFalse(result['managed'])
        self.assertFalse(result['available'])
        with self.assertRaises(RuntimeError):
            updates.install(copy, self.state, runner=lambda *a, **k: None)

    def test_install_hands_off_to_omarchy_plugin_update(self):
        self.release('0.2.0', 'Newer')
        self.check()
        calls = []

        def fake_update(args, **kw):
            calls.append(args)
            run('git', 'merge', '-q', '--ff-only', 'FETCH_HEAD', cwd=self.plugin)
            return types.SimpleNamespace(returncode=0, stderr='')

        result = updates.install(self.plugin, self.state, runner=fake_update)
        self.assertEqual(calls, [['omarchy', 'plugin', 'update', 'io.example.studio', '--yes']])
        self.assertTrue(result['installed'])
        self.assertFalse(result['available'])
        self.assertEqual(result['current_version'], '0.2.0')

    def test_failed_install_surfaces_omarchys_reason(self):
        failed = types.SimpleNamespace(returncode=1, stderr="omarchy-plugin-update: cannot fast-forward 'x'; you have local changes\n")
        with self.assertRaisesRegex(RuntimeError, 'cannot fast-forward'):
            updates.install(self.plugin, self.state, runner=lambda *a, **k: failed)


class ReleaseVersionTests(unittest.TestCase):
    def test_panel_built_version_matches_the_manifest(self):
        # A mismatch would make every install look like it needs a restart.
        built = re.search(r'property string builtVersion: "([^"]+)"', (ROOT / 'ThemeStudio.qml').read_text())
        self.assertIsNotNone(built)
        self.assertEqual(built.group(1), json.loads((ROOT / 'manifest.json').read_text())['version'])


if __name__ == '__main__':
    unittest.main()

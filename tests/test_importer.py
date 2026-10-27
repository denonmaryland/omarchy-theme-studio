"""Importer regressions, using temporary themes and local Git repositories."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('importer', ROOT / 'helpers/importer.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def git(folder, *args):
    return subprocess.run(['git', '-C', str(folder), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='theme-studio-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.themes = self.root / 'themes'
        self.themes.mkdir()
        # File transport is allowed only inside these offline test fixtures.
        for name, value in {'THEMES': self.themes, 'STOCK': self.root / 'stock',
                            'THUMBS': self.root / 'thumbs',
                            'GIT_SAFE': importer.GIT_SAFE + ['-c', 'protocol.file.allow=always']}.items():
            p = patch.object(importer, name, value)
            p.start()
            self.addCleanup(p.stop)

    def repository(self):
        repo = self.root / 'upstream.git'
        repo.mkdir()
        git(repo, 'init')
        git(repo, 'config', 'user.name', 'Review Fixture')
        git(repo, 'config', 'user.email', 'review@example.invalid')
        (repo / 'colors.toml').write_text('background = "#123456"\n')
        self.commit(repo)
        slug, how = importer.install_git(repo.as_uri(), '')
        importer.finish(slug, how, False)
        target = self.themes / slug
        (target / 'personal-notes.txt').write_text('keep me')
        return repo, target

    def commit(self, repo):
        git(repo, 'add', '.')
        git(repo, 'commit', '-m', 'fixture')

    def test_invalid_update_keeps_installed_commit_palette_and_local_files(self):
        repo, target = self.repository()
        before = git(target, 'rev-parse', 'HEAD')
        (repo / 'colors.toml').unlink()
        (repo / 'README.md').write_text('Theme moved elsewhere')
        self.commit(repo)
        with self.assertRaisesRegex(importer.Fail, 'installed theme was kept'):
            importer.install_git(repo.as_uri(), '')
        self.assertEqual(git(target, 'rev-parse', 'HEAD'), before)
        self.assertTrue((target / 'colors.toml').is_file())
        self.assertEqual((target / 'personal-notes.txt').read_text(), 'keep me')

    def test_valid_update_preserves_untracked_files(self):
        repo, target = self.repository()
        (repo / 'colors.toml').write_text('background = "#abcdef"\n')
        self.commit(repo)
        slug, how = importer.install_git(repo.as_uri(), '')
        self.assertTrue(importer.finish(slug, how, False)['ok'])
        self.assertEqual(git(target, 'rev-parse', 'HEAD'), git(repo, 'rev-parse', 'HEAD'))
        self.assertIn('#abcdef', (target / 'colors.toml').read_text())
        self.assertEqual((target / 'personal-notes.txt').read_text(), 'keep me')

    def test_update_stages_outside_the_themes_folder(self):
        repo, target = self.repository()
        (repo / 'colors.toml').write_text('background = "#abcdef"\n')
        self.commit(repo)
        seen, real_run = [], importer.run

        def watch(*args, **kwargs):
            if 'pull' in args:
                seen.append(sorted(p.name for p in self.themes.iterdir()))
            return real_run(*args, **kwargs)

        with patch.object(importer, 'run', watch):
            importer.install_git(repo.as_uri(), '')
        self.assertEqual(seen, [[target.name]])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()
                                if p.name.startswith('.theme-studio-update-')), [])

    def test_conflicting_update_preserves_local_changes(self):
        repo, target = self.repository()
        (target / 'colors.toml').write_text('background = "#ffffff"\n')
        (repo / 'colors.toml').write_text('background = "#abcdef"\n')
        self.commit(repo)
        with self.assertRaisesRegex(importer.Fail, r"can't be updated automatically; the installed theme was kept$"):
            importer.install_git(repo.as_uri(), '')
        self.assertIn('#ffffff', (target / 'colors.toml').read_text())
        self.assertEqual((target / 'personal-notes.txt').read_text(), 'keep me')

    def test_diverged_update_keeps_the_installed_commit(self):
        repo, target = self.repository()
        git(target, '-c', 'user.name=Local', '-c', 'user.email=local@example.invalid',
            'commit', '--amend', '--allow-empty', '-m', 'local change')
        before = git(target, 'rev-parse', 'HEAD')
        (repo / 'colors.toml').write_text('background = "#abcdef"\n')
        self.commit(repo)
        with self.assertRaisesRegex(importer.Fail, r"can't be updated automatically; the installed theme was kept$"):
            importer.install_git(repo.as_uri(), '')
        self.assertEqual(git(target, 'rev-parse', 'HEAD'), before)
        self.assertEqual((target / 'personal-notes.txt').read_text(), 'keep me')

    def test_failed_directory_swap_restores_the_previous_installation(self):
        repo, target = self.repository()
        before = git(target, 'rev-parse', 'HEAD')
        (repo / 'colors.toml').write_text('background = "#abcdef"\n')
        self.commit(repo)
        rename = Path.rename

        def fail_stage_move(path, destination):
            if path.name == 'repo' and path.parent.name.startswith('.theme-studio-update-'):
                raise OSError('simulated directory swap failure')
            return rename(path, destination)

        with patch.object(Path, 'rename', fail_stage_move):
            with self.assertRaisesRegex(OSError, 'directory swap failure'):
                importer.install_git(repo.as_uri(), '')
        self.assertEqual(git(target, 'rev-parse', 'HEAD'), before)
        self.assertIn('#123456', (target / 'colors.toml').read_text())
        self.assertEqual((target / 'personal-notes.txt').read_text(), 'keep me')

    def test_finish_does_not_delete_an_invalid_existing_directory(self):
        target = self.themes / 'existing'
        target.mkdir()
        (target / 'notes').write_text('keep me')
        with self.assertRaises(importer.Fail):
            importer.finish('existing', 'git', False)
        self.assertEqual((target / 'notes').read_text(), 'keep me')

    def legacy_theme(self):
        src = self.root / 'legacy'
        src.mkdir()
        (src / 'alacritty.toml').write_text(
            '[terminal.shell]\nprogram = "do-not-execute"\n[colors.normal]\n' +
            ''.join(f'{name} = "#123456"\n' for name in
                    ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')))
        (src / 'hyprland.lua').write_text('error("do not execute")')
        return src

    @unittest.skipUnless(shutil.which('omarchy-theme-colors-from-alacritty'), 'needs Omarchy palette converter')
    def test_legacy_folder_archive_and_repo_subfolder_extract_palette(self):
        src = self.legacy_theme()
        archive = self.root / 'legacy.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(src, arcname='legacy')
        repo = self.root / 'nested.git'
        repo.mkdir()
        git(repo, 'init')
        git(repo, 'config', 'user.name', 'Review Fixture')
        git(repo, 'config', 'user.email', 'review@example.invalid')
        shutil.copytree(src, repo / 'theme')
        self.commit(repo)
        results = [importer.install(str(src), '', 'auto', False),
                   importer.install(str(archive), '', 'auto', False)]
        slug, how = importer.install_git(repo.as_uri(), '')
        results.append(importer.finish(slug, how, False))
        for result in results:
            target = self.themes / result['slug']
            self.assertTrue(result['ok'])
            self.assertIn('#123456', (target / 'colors.toml').read_text())
            self.assertNotIn('do-not-execute', (target / 'colors.toml').read_text())
            self.assertFalse((target / 'alacritty.toml').exists())
            self.assertFalse((target / 'hyprland.lua').exists())

    def test_legacy_symlink_is_not_used_as_a_palette(self):
        src = self.legacy_theme()
        original = self.root / 'outside.toml'
        (src / 'alacritty.toml').rename(original)
        (src / 'alacritty.toml').symlink_to(original)
        with self.assertRaises(importer.Fail):
            importer.install(str(src), '', 'auto', False)
        self.assertTrue(original.is_file())
        self.assertFalse((self.themes / 'legacy').exists())


if __name__ == '__main__':
    unittest.main()

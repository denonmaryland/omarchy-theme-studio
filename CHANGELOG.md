# Changelog

## 0.1.0 (unreleased)

First standalone version, prepared for the Omarchy plugin marketplace.

- Self-contained plugin folder: helpers live in `helpers/`. The panel uses
  Omarchy's stock popup, or the denon.bar glass host when that's installed.
- Rotation and Follow the sun run from the shell; no systemd service.
- Recent/Back history is recorded in-plugin; no theme-set hook.
- The window border override needs explicit consent and can be removed from the
  panel.
- Hardened installs: code files and symlinks are stripped from themes without
  `.git`; safe git clones; archive and download limits.
- Git updates are staged and validated before replacing installed themes,
  preserving local files and retaining the previous installation on failure.
  The staging copy sits outside the themes folder, so theme menus never list it.
- Legacy folder, archive and repository-subfolder themes retain their palette
  by converting `alacritty.toml` before removing executable settings.
- Failed theme switches preserve newer queued selections, including a repeated
  random pick.
- Surprise me no longer asks to review the pick as if it had rotated in.
- The rotation review card no longer appears or disappears under the pointer:
  it waits while picks are landing or the pointer is over a grid.
- The hero label stays readable on themes with dark accent colors.
- Regression checks cover importer failures, legacy palette extraction and
  queued switching behavior.

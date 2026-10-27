# Changelog

## 0.1.0 (unreleased)

First standalone version, prepared for the Omarchy plugin marketplace, under the
name Best Theme Plugin Ever (plugin ID `io.github.denonmaryland.theme-studio`).

- Self-contained plugin folder: helpers live in `helpers/`. The panel uses
  Omarchy's stock popup, or the denon.bar glass host when that's installed.
- Rotation and Follow the sun run from the shell; no systemd service.
  Rotation starts paused.
- Recent/Back history is recorded in-plugin; no theme-set hook.
- The window border override needs explicit consent and can be removed from the
  panel.
- Hardened installs: code files and symlinks are stripped from themes without
  `.git`; safe git clones; archive and download limits.
- Git updates are staged outside the themes folder and validated before they
  replace an installed theme; local files are kept, and a failed update leaves
  the installed theme untouched.
- Older themes that only ship `alacritty.toml` keep their palette: it is
  converted to `colors.toml` before the terminal config is removed.
- Latest-click-wins switching: a failed switch never drops a newer pick,
  including repeated Surprise me picks.
- The "Keep it in the rotation?" review appears only after an automatic
  rotation, and never moves the grid under the pointer.
- Readable on light and dark themes, including themes with dark accent colors.
- Regression checks cover importer failures, legacy palette extraction,
  rotation review and queued switching.

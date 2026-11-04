# Changelog

## 0.2.1 (2026-11-04)

- Backgrounds › This theme now scrolls. Themes with many backgrounds used to
  overflow the panel with no way to reach the rest (or the Shuffle toggle).

## 0.2.0 (2026-11-02)

- Update checks: about once a day (and on demand from ⋯) the plugin checks the
  repository it was installed from. A newer manifest version puts a dot on the
  bar icon and ⋯; one click runs `omarchy plugin update`, then a restart
  loads it. Daily checks can be turned off. Git installs only.
- Faster gallery scrolling: trackpad pixel movement is scaled by three, and
  angle-only wheel input moves one row per notch. Applies to installed themes,
  Discover and wallpaper search in both compact and wide layouts.

## 0.1.0 (2026-10-27)

First standalone version, prepared for the Omarchy plugin marketplace, under the
name Best Theme Plugin Ever (plugin ID `io.github.denonmaryland.theme-studio`).

- Self-contained plugin folder: helpers live in `helpers/`. The panel uses
  Omarchy's stock popup.
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

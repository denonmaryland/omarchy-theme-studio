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

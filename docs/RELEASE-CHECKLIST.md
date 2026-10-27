# Release checklist (marketplace)

Status of each item needed before submitting to
https://github.com/omacom/omarchy-plugin-marketplace (rules: SUBMISSION.md, SECURITY.md).

## Repository basics
- [x] Own repository, `manifest.json` at the root
- [x] Permanent ID `io.github.denonmaryland.theme-studio`, category Appearance
- [x] `preview.png` at the root (panel-only screenshot; retake once the UI is final)
- [ ] LICENSE file (owner to choose; MIT is the common choice)
- [ ] README with install, removal, external dependencies (draft present)
- [ ] Public GitHub repository (owner approval needed before publishing)

## Make it self-contained (blocking)
- [ ] Helpers: QML points at `~/.local/share/omarchy-theme-rotation/*.py`. Load them
      from the plugin folder instead (`helpers/`), resolved relative to the QML file.
- [ ] Remove the dependency on the author's custom bar (`../denon.bar/panels`:
      `PopupPanel`, `PanelMotion`, `GlassTile`). Ship a fallback or use Omarchy's
      stock panel host so it works on a default Omarchy install.
- [ ] Internal names: IPC target / module name `denon.theme-rotation`, and the
      `omarchy-shell denon.theme-rotation review` call in control.py.
- [ ] State/cache dirs: `~/.local/state|cache/omarchy-theme-rotation` → `theme-studio`
      (with a one-time migration for the author's existing data).
- [ ] Community gallery: control.py reads `~/.local/share/omarchy-community-themes`
      (a collector script the author ran separately). Make it optional, or drop it.

## Things that touch the system (need explicit in-panel consent)
- [ ] Rotation timer: today a systemd user service (`extras/systemd`). Prefer an
      in-shell Timer so no service is needed; otherwise install it only on opt-in.
      (systemd use triggers manual review.)
- [ ] Theme history hook (`extras/hooks/theme-history` → `theme-set.d/`): install on
      opt-in, or track history in-plugin from the theme-name file.
- [ ] Window border override needs a line in the user's `hyprland.lua`: ask first,
      add/remove cleanly, never edit other lines.
- [ ] Uninstall path that removes everything above.

## Security hardening (reviewers rejected a similar plugin for this)
- [ ] Repo installs (importer / Discover): pin to a full commit SHA, not HEAD.
- [ ] Cap download sizes; safe archive extraction (no path traversal, size/file limits).
- [ ] Image-link imports: restrict hosts or document; no execution of downloaded content.
- [ ] Runtime files only in `$XDG_RUNTIME_DIR` / owner-only dirs.

## Compatibility and polish
- [ ] Works on stock Omarchy with the default bar; test on a clean user account.
- [ ] Tolerate missing optional tools (ImageMagick `magick`, `notify-send`, `git`).
- [ ] `omarchy plugin validate .` clean; version bump; CHANGELOG.
- [ ] Submit with `gh issue create` (owner reviews the issue text first).

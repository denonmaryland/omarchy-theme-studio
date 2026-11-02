# Release checklist (marketplace)

Release evidence and remaining checks for
https://github.com/omacom/omarchy-plugin-marketplace (rules: SUBMISSION.md, SECURITY.md).

## Marketplace outcome (checked 2026-11-01)

- Repository is public. Version 0.1.0 was submitted as
  [issue #12994](https://github.com/omacom/omarchy-plugin-marketplace/issues/12994).
- Compatibility validation and the automated security baseline passed at
  `0b604c2ffab73341411f96859fe9f30dded7618f`. That evidence does not cover later commits.
- The maintainer closed the submission on 2026-10-27: plugins primarily
  providing or installing themes are outside the marketplace's scope.
  This is not an approved marketplace listing.
- The owner's 2026-10-28 follow-up asks whether an installed-themes-only version
  would qualify. No reply was present on 2026-11-01. Product scope is unchanged;
  any reduced-scope release or new submission needs a separate decision.

## 0.2.0 (prepared 2026-11-02)

- Contents: update checks and the gallery scrolling fix below.
- `manifest.json` and `builtVersion` are both 0.2.0; CHANGELOG dated.
- Checks before the release commit: listed in the commit's verification note.
- Not part of a marketplace listing: the submission was closed (see above).

## Local scrolling fix (2026-10-28, released in 0.2.0)

- Shared wheel handler for installed themes, Discover and wallpaper search:
  phased trackpad pixel movement is scaled by three; physical wheels and events
  without a gesture phase move a row per notch. Bounds include view margins.
- Verified: 15 Python tests, 12 Node tests (`node --test tests/*.cjs`), plugin
  validation and diff checks. No skips. Isolated Qt input checks passed for
  compact/wide wheel delivery, pixel input, boundaries, horizontal scrolling
  and clicks. Native Qt touchpad events verified updates, momentum and gesture
  end, plus physical and phase-free wheel events.
- Deployed only the changed QML locally after backing up the previous file to
  `~/.local/state/omarchy-theme-studio-backups/20261028T071052Z-trackpad-scroll/`.
  A shell restart was required to load it. Live injected wheel input moved
  122 logical pixels in compact mode and 169 in wide mode in both hosts;
  Discover also scrolled. Inspected panel renders and found no new QML errors.
  Restored the compact glass host and Installed view.
- Physical trackpad feel and a live wallpaper-search flow remain unverified;
  the latter uses the same handler. Automated checks were rerun on 2026-11-01:
  15 Python and 12 Node tests passed without skips, plus plugin validation and
  diff checks. No new live verification was performed. This local commit does
  not publish a release or update the marketplace.

## Repository basics
- [x] Own repository, `manifest.json` at the root
- [x] Permanent ID `io.github.denonmaryland.theme-studio`, category Appearance
- [x] Display name "Best Theme Plugin Ever" (2026-10-27): "Theme Studio" is already
      listed by io.github.ofa14-prog.theme-studio (a theme designer). Internal
      names (ID, IPC target, state/cache dirs, `.theme-studio` markers, the
      `theme_studio_border` module) are unchanged; old border lines still match.
- [x] Tags: bar, hyprland, quickshell.
- [x] `preview.png` at the root (panel-only screenshot of the final UI)
- [x] MIT LICENSE file
- [x] README with install, removal and external dependencies
- [x] Public GitHub repository: https://github.com/denonmaryland/omarchy-theme-studio
- [x] Published history uses the GitHub noreply identity (2026-10-27).

## Make it self-contained (blocking)
- [x] Helpers: QML points at `~/.local/share/omarchy-theme-rotation/*.py`. Load them
      from the plugin folder instead (`helpers/`), resolved relative to the QML file.
- [x] Remove the dependency on the author's custom bar (`../denon.bar/panels`:
      `PopupPanel`, `PanelMotion`, `GlassTile`). Ship a fallback or use Omarchy's
      stock panel host so it works on a default Omarchy install.
- [x] Internal names: IPC target / module name `denon.theme-rotation`, and the
      `omarchy-shell denon.theme-rotation review` call in control.py.
- [x] State/cache dirs: `~/.local/state|cache/omarchy-theme-rotation` → `theme-studio`
      (with a one-time migration for the author's existing data).
- [x] Community gallery: control.py reads `~/.local/share/omarchy-community-themes`
      (a collector script the author ran separately). Make it optional, or drop it.

## Things that touch the system (need explicit in-panel consent)
- [x] Rotation timer: today a systemd user service (`extras/systemd`). Prefer an
      in-shell Timer so no service is needed; otherwise install it only on opt-in.
      (systemd use triggers manual review.)
- [x] Theme history hook (`extras/hooks/theme-history` → `theme-set.d/`): install on
      opt-in, or track history in-plugin from the theme-name file.
- [x] Window border override needs a line in the user's `hyprland.lua`: ask first,
      add/remove cleanly, never edit other lines.
- [x] Uninstall path that removes everything above.

## Security hardening (reviewers rejected a similar plugin for this)
- [x] Repo installs: record the installed commit; clones are shallow, symlink-free, no submodules.
      (User-chosen theme repos have no reviewed commit to pin to; README says so.)
- [x] Cap download sizes; safe archive extraction (no path traversal, size/file limits).
- [x] No execution of downloaded content: code files + symlinks stripped from non-.git installs;
      http(s) only. (Hosts not restricted: the user pastes the link.)
- [x] Runtime files only in `$XDG_RUNTIME_DIR` / owner-only dirs.

## Compatibility and polish
- [x] Works on stock Omarchy with the default bar; tested on a clean user account.
- [x] Tolerate missing optional tools (ImageMagick `magick`, `notify-send`, `git`).
- [x] `omarchy plugin validate .` clean on the reviewed local source (2026-10-26).
- [x] Version 0.1.0 and CHANGELOG released; marketplace checks passed at the
      exact snapshot recorded above. The scrolling fix remains unreleased.
- [x] Submitted as issue #12994; closed as out of scope (see outcome above).

## Verification history and remaining checks
- [x] Clean user account, stock Omarchy config (/etc/skel) and stock bar, nested Hyprland
      (2026-10-26): `omarchy plugin add file://… --enable --yes` validated, installed and
      placed the widget; `omarchy plugin update` worked; panel opens in the stock popup
      with the 22 stock themes, Discover (373), Recent (0). Found + fixed: rotation was on
      by default; compact gallery overflowed a 960 px-tall screen; filter cramped in the
      monospace font (Add label now hides). Verified after fix: rotation paused on first
      run, filter roomy.
- [x] Clean account, stock bar, 1366x700 screen (2026-10-27, 60e954d): installed
      from a local clone with `omarchy plugin add`, widget placed on the stock
      bar, panel opens in the stock popup, compact gallery fits (two rows, footer
      visible). Note: after a live resize of the nested display the shell kept
      the old screen height until restarted (Omarchy shell behavior).
- [x] Targeted helper/install review (2026-10-26): three findings fixed locally;
      Git updates stage before replacement, legacy palettes are extracted before
      stripping terminal configs, failed switches keep newer queued selections.
      Seven Python and four Node regression tests passed. Subsequently committed
      in 3284db2 and deployed; this was not an exhaustive whole-repo review.
- [x] Second-model review of those fixes (2026-10-26): two follow-ups fixed —
      update staging moved out of the themes folder (it showed in Omarchy's theme
      list), and a repeated random pick now survives a failed one. Eight Python
      and five Node tests passed; each new test failed on the old code. These fixes
      were subsequently committed in 3284db2 and deployed.
- [x] Live regression check of those fixes on the release candidate.
      2026-10-26, glass bar host. Python helper changes take effect at once:
      live Git update of `futurism` staged only in `~/.config/omarchy/`, nothing
      in the themes folder, cleaned up after; live legacy folder import produced
      `colors.toml`, stripped `alacritty.toml` and its launch command (not run).
      QML changes did NOT load via hot reload or `rescanPlugins` for this
      widget; the first pointer walkthrough therefore ran pre-fix QML (success
      paths only). After `omarchy restart shell` (23:40) the working-tree QML
      was verified with real clicks: the review card held still through three
      picks 1.2 s apart (each landed on its target), buttons disabled while
      stale, collapse once the pointer left the grid; Surprise me shows no
      review; hero label readable on Hinterlands; Surprise me clicked twice
      150 ms apart applied two random themes in order (de2b245).
      2026-10-27 failure paths, live: a theme deleted 5 ms after its click
      failed and showed "That theme didn't apply…"; with a newer pick queued
      the newer pick still applied. A diverged Git update of `futurism` was
      refused, kept its commit and a local file, left no staging folder, and
      now reports a plain sentence instead of git's hints.
- [x] Polish from the walkthrough fixed: review card no longer shifts the grid
      under the pointer; Surprise me no longer asks for a rotation review; hero
      label readable with dark accents.
- [x] Background thumbnails load from the theme's own folder, so a switch no
      longer leaves them pointing at the replaced `current/theme/backgrounds`.
- [x] Retake preview.png from the final UI (2026-10-27, wide panel, live QML of 3a477cd).
- [x] README media (2026-10-27): banner, demo GIF recorded live on an empty
      workspace (Follow-the-sun times blurred), compact/Discover/wide screenshots
      over the wallpaper; preview.png is the compact panel on a full desktop.
      Social carousel and MP4 kept outside the repo.
- [x] Made public and submitted on 2026-10-27; see marketplace outcome above.
- [ ] Bump `manifest.json` `version` and `builtVersion` in `ThemeStudio.qml`
      together for every release users should be told about (a test checks
      they match). Update checks compare manifest versions, so commits
      without a bump (docs, README) don't notify anyone.
- [x] Update checks (unreleased), verified live 2026-11-02 on the glass host,
      compact layout: a temporary git install of this source pointed at a local
      upstream with a fake 0.2.0. The automatic check fired about 90 s after
      startup and found 0.2.0. The dot appeared on the bar glyph and ⋯, and
      ⋯ → Update installed it through `omarchy plugin update`. The plugin
      rescan re-created the panel from old QML and lost the in-memory restart
      flag; fixed with `builtVersion`, then reverified: Restart shell to
      finish update appeared, the restart loaded the new QML (IPC marker),
      and the prompt cleared. Up to date, the daily-check toggle (saved off and
      on) and the unreachable-repository error were also checked. The original
      live plugin was restored afterwards. Not checked live: the stock host,
      the wide layout, and the final ⋯ tooltip wording change.
- [ ] Verify physical trackpad feel and the live wallpaper-search scrolling flow.
- [ ] Decide whether to pursue the proposed installed-themes-only marketplace version
      after eligibility feedback; no scope change is authorized by this checklist.

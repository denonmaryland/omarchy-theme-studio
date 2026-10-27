# Best Theme Plugin Ever for Omarchy

A bar panel for everything themes. Browse and apply your installed themes
instantly, discover community themes, install a theme from a pasted link, rotate
themes on a timer or with the sun, pick wallpapers, color your window borders per
theme, and step back through the themes you used recently.

![Best Theme Plugin Ever](preview.png)

## Features

- **Instant switching.** Click any theme; the panel updates immediately and the
  last click always wins, so rapid clicking never gets stuck.
- **Installed · Recent · Discover.** Light/dark filters, favorites, search, and
  lookalike grouping (near-identical themes stack into one tile).
- **Back button.** Step back through your last 10 themes, including ones the
  rotation timer or Surprise me picked. Each theme comes back with the wallpaper
  you last used with it.
- **Install from a link.** Paste a GitHub repo, a theme page, a zip/tar archive,
  an image, or a local folder. Images become a full generated theme, with six
  palette styles to choose from.
- **Rotation.** Change theme every 15/30/60 minutes and rate each new one with
  Keep / Maybe / Not for me. **Follow the sun** switches to light themes at
  sunrise and dark at sunset, computed locally from your time zone.
- **Wallpapers.** Pick between a theme's wallpapers, shuffle them, or find more
  openly licensed images (Openverse). Credits are saved next to each download.
- **Window borders.** Pick a border color from the theme's palette, or turn the
  border off for every theme.
- **Compact panel or wide window** (button or `E`).

Keyboard: `/` search · arrows browse · `Enter` apply · `B` back · `E` expand ·
`1` `2` `3` tabs · `F` favorite · `Esc` close.

## Install

```bash
omarchy plugin add https://github.com/denonmaryland/omarchy-theme-studio --enable
```

Then click the palette icon in the bar.

## Remove

1. If you turned on window border colors, first open Best Theme Plugin Ever and choose
   **⋯ → Remove system changes**. That removes the one line and file it added
   (see below).
2. Remove the plugin:

   ```bash
   omarchy plugin remove io.github.denonmaryland.theme-studio
   ```

3. Optional: delete its saved settings and caches.

   ```bash
   rm -rf ~/.local/state/omarchy-theme-studio ~/.cache/omarchy-theme-studio
   ```

Themes and wallpapers you installed through Best Theme Plugin Ever are normal Omarchy
themes and stay installed. Remove them in the panel (⋯ → Delete theme) or with
`omarchy theme remove`.

## What it changes on your system

Best Theme Plugin Ever runs inside the Omarchy shell. It doesn't install services or
hooks, and it doesn't need root.

| What | When |
|---|---|
| Applies themes and wallpapers with `omarchy theme set` / `omarchy theme bg set` | When you pick one, or when rotation / Follow the sun is on |
| Installs themes into `~/.config/omarchy/themes/` | Only when you install one |
| Saves wallpapers into the current theme's background folder, with `CREDITS.md` | Only when you save one |
| Adds `~/.config/hypr/theme_studio_border.lua` and one marked `require` line at the end of `~/.config/hypr/hyprland.lua` | Only after you press **Allow** in the window border picker. **⋯ → Remove system changes** removes both. |
| Settings and history in `~/.local/state/omarchy-theme-studio/`; thumbnails and downloads in `~/.cache/omarchy-theme-studio/` | Always |

## Network use

- **Discover** reads a community theme catalog and fetches preview images.
- **Find more** (wallpapers) searches the Openverse API.
- Installs from a link download from the address you paste.

There's no telemetry and no account.

## Security notes

Themes you install are code-adjacent: Omarchy can load a theme's `hyprland.lua`,
`neovim.lua` and terminal configs. Omarchy itself refuses those files from themes
that keep their `.git` folder. Best Theme Plugin Ever applies the same rule to every theme
it installs without `.git` (archives, web pages, repository subfolders, folders):

- `*.lua`, `alacritty.toml`, `foot.ini`, `ghostty.conf`, `kitty.conf` and
  `vscode.json` are removed, along with any symlinks.
- Git installs are shallow clones with symlinks disabled (also for later
  updates) and no submodules. The installed commit is recorded.
- Updates are pulled and checked in a temporary copy before replacing an
  installed theme. Failed pulls or updates missing a theme definition leave
  the existing installation intact; successful updates preserve local files.
- Older themes that only provide `alacritty.toml` have their palette converted
  to `colors.toml` before the terminal config is removed.
- Downloads are http(s) only, with size limits. Archives are checked for unsafe
  paths, total unpacked size (1 GiB) and file count (5000).

Repository installs fetch the repository's current version, which is whatever
its author has published. Only install themes you trust.

## Requirements

Omarchy with the shell bar, which includes Python 3 and ImageMagick. `git`
is needed for repository installs. Window border colors need Omarchy's Lua
Hyprland config (`~/.config/hypr/hyprland.lua`).

If the `denon.bar` glass bar plugin is installed, Best Theme Plugin Ever uses its
animated panel host (hover to preview, click to keep). Otherwise it uses
Omarchy's standard popup.

## Development checks

```bash
python3 -m unittest discover -s tests -v
node --test tests/theme_queue.cjs
omarchy plugin validate .
```

The importer checks use temporary folders and local Git repositories. Legacy
palette coverage needs Omarchy's `omarchy-theme-colors-from-alacritty` command.
The Node.js checks exercise the QML switching functions without a desktop;
they do not replace a live mouse walkthrough or short-screen layout checks.

Release preparation and outstanding live checks are tracked in
[the marketplace checklist](docs/RELEASE-CHECKLIST.md).

## License

MIT

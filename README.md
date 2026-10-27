# Theme Studio for Omarchy

> Work in progress: being prepared for the Omarchy plugin marketplace. See
> `docs/RELEASE-CHECKLIST.md`. Not yet installable on other machines.

A bar panel for everything themes: browse and apply installed themes instantly,
discover community themes, install any theme or image from a pasted link, rotate
themes on a timer or follow the sun, pick wallpapers, set per-theme window border
colors, and step back through recently used themes.

![Theme Studio](preview.png)

## Features
- Instant theme switching with last-click-wins and live previews
- Installed · Recent · Discover views, light/dark filters, favorites, lookalike grouping
- Paste a GitHub repo, theme page, archive or image to install or generate a theme
- Rotation timer with Keep / Maybe / Not for me ratings; Follow the sun
- Wallpaper catalog (Openverse, openly licensed, credits saved)
- Window border color per theme, or no border on every theme
- Back button through your last 10 themes; each theme remembers its wallpaper
- Compact panel or wide window

## Install / remove
Coming with the first release:

```bash
omarchy plugin add https://github.com/denonmaryland/omarchy-theme-studio --enable
omarchy plugin remove io.github.denonmaryland.theme-studio
```

## Requirements
Omarchy with the shell bar, Python 3.11+. Optional: ImageMagick (`magick`) for
generated themes and thumbnails, `git` for repo installs.

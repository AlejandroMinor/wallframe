# wallframe

Drag, zoom, mirror and rotate your wallpaper inside each monitor's frame. A GTK4 editor for awww and swww on Wayland.

Wallpaper daemons scale the image to fill the screen and cut off the parts that do not fit. They always keep the center. On a portrait monitor, a landscape image can lose more than half of its width, and often the part you wanted to see. wallframe shows the frame of each monitor over the image, so you can choose which part to keep.

**Before:** the daemon keeps the center, so the portrait monitors cut off the characters.

![The same wallpaper cropped around the center on every monitor](docs/before.webp)

**After:** each monitor framed by hand with wallframe.

![Each portrait monitor framed by hand with wallframe](docs/after.webp)

## Requirements

`gtk4`, `python-gobject`, `python-cairo`, `python-pillow`, and `awww` or `swww`. On Arch Linux:

```bash
sudo pacman -S gtk4 python-gobject python-cairo python-pillow awww
```

Optional:

- Hyprland or sway: wallframe opens on the focused monitor and shows the model of each monitor.
- `libnotify`: errors appear as notifications, which helps when you start wallframe without a terminal. On Hyprland, errors appear as Hyprland notifications even without it.

## Install

Clone the repository and run it. There is nothing to build:

```bash
git clone https://github.com/AlejandroMinor/wallframe.git
cd wallframe
./wallframe
```

To run it from anywhere as `wallframe`, link it into a folder in your `PATH`:

```bash
ln -s "$PWD/wallframe" ~/.local/bin/wallframe
```

### Open as a floating window

wallframe works best as a floating window, centered on the screen. Add a rule for its app ID, `io.github.AlejandroMinor.wallframe`.

Hyprland:

```lua
hl.window_rule({
    name   = "wallframe",
    match  = { class = "^(io.github.AlejandroMinor.wallframe)$" },
    float  = true,
    center = true,
})
```

sway:

```
for_window [app_id="io.github.AlejandroMinor.wallframe"] floating enable
```

## Usage

![wallframe editing a portrait monitor: the frame is bright, the rest of the image is dimmed](docs/interface.webp)

| Action | Mouse / button | Key |
|--------|----------------|-----|
| Move | Drag | Arrows (`Shift` for bigger steps) |
| Zoom | Scroll, slider or `−` / `+` buttons | `+` / `-` |
| Center, keeping the zoom | | `C` |
| Move the background instead of the image | Fill panel | `B` |
| Mirror / flip / rotate 90° | Toolbar | `H` / `V` / `R` |
| Reset to the original image, centered | Toolbar | `0` |
| Rule-of-thirds grid | Toolbar | `G` |
| Next monitor | Monitor buttons | `Tab` |
| Apply to the marked monitors | Apply | `Enter` |
| Close | | `Esc` |

Zoom below 100% to see more of the image, or to make it smaller than the monitor. The empty space around it is filled with a copy of the image, blurred as much as you like, or with a color. Both are in the **Fill** panel of the bottom bar. Check **Move background** there (or press `B`) to drag and zoom that copy instead of the image.

A dot on a monitor button means that the monitor does not show your changes yet. Apply crops the image to the exact size of the monitor and sets it with awww (or swww) on that monitor only. The window stays open.

wallframe saves the crops in `~/.local/share/wallframe/`. It does not use the cache folder, because the daemon loads the crops from there again at login. When you open wallframe again, each monitor starts from the original image with your last framing, so the image does not lose quality. Animated and video wallpapers are not supported.

wallframe opens on the focused monitor. To start on a different monitor, give its output name: `wallframe DP-1`.

## Development

The tests cover everything except the window: framing, cropping, saved state and reading the daemon and compositor output. They do not need a display or a wallpaper daemon:

```bash
python -m venv --system-site-packages .venv
.venv/bin/pip install pytest
PYTHONPATH=src .venv/bin/pytest
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

# Close All Apps (Ubuntu)

One-click closer for open desktop apps — VS Code, gedit/Text Editor, Files, browsers, snaps, flatpaks.

## Install

```bash
chmod +x install.sh closeall.py
./install.sh
```

Then search **Close All Apps** in Activities and drag it to the dock.

## Use

| Action | Result |
|---|---|
| Click the icon | Closes everything right away, no prompt |
| Right-click dock icon → *Choose what to close…* | Opens the window with tick boxes |
| `closeall --list` | Prints what it detects, closes nothing |
| `closeall --gui` | Same as the right-click action |

## How it works

GNOME puts every launched app in its own systemd user scope (`app-*.scope`,
`snap.*.scope`), so that list is the source of truth on both X11 and Wayland.
On X11 it also maps windows via `wmctrl` and sends a real window-close request,
which lets apps show their "save changes?" prompt. On Wayland there is no such
API, so apps get `SIGTERM` — VS Code restores unsaved buffers on next launch,
but a plain text editor may lose them. Anything still alive after the timeout
gets `systemctl --user stop` then `SIGKILL`.

Your shell, GNOME Shell itself, and the app's own process are never touched.

## Config

`~/.config/closeall/config.json`, created on first run:

```json
{
  "exclude": ["gnome-terminal-server", "org.gnome.Terminal", "ptyxis", "closeall"],
  "force_kill_after": 8,
  "confirm_on_now": false
}
```

Add anything you want kept open — e.g. `"firefox"` or `"org.gnome.Music"`.

## Uninstall

```bash
rm ~/.local/bin/closeall ~/.local/share/applications/close-all-apps.desktop
```

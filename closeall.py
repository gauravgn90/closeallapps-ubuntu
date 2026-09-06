#!/usr/bin/env python3
"""
Close All Apps — one-click app closer for Ubuntu (GNOME, X11 or Wayland).

Usage:
    closeall            # close everything immediately, no prompt
    closeall --gui      # open the window and pick what to close
    closeall --list     # print what it detects and exit
"""

import json
import os
import re
import signal
import subprocess
import sys
import time

CONFIG_DIR = os.path.expanduser("~/.config/closeall")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    # Anything whose process name or app id matches one of these is never closed.
    "exclude": [
        "gnome-terminal-server",
        "org.gnome.Terminal",
        "org.gnome.Console",
        "ptyxis",
        "closeall",
    ],
    # Seconds to wait after a polite close request before force-killing.
    "force_kill_after": 8,
    # Ask for confirmation in --now mode too.
    "confirm_on_now": False,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except OSError:
            pass
    return cfg


def run(cmd, timeout=5):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- discovery

def proc_name(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return ""


def alive(pid):
    return os.path.exists("/proc/%d" % pid)


def unit_appid(unit):
    """app-gnome-org.gnome.Nautilus-1234.scope -> org.gnome.Nautilus"""
    m = re.match(r"app-(?:[a-z0-9]+-)?(.+?)-\d+\.scope$", unit)
    if m:
        return m.group(1).replace("\\x2d", "-")
    m = re.match(r"snap\.([^.]+)\.", unit)
    if m:
        return m.group(1)
    return unit


def cgroup_pids(unit):
    cg = run(["systemctl", "--user", "show", "-p", "ControlGroup", "--value", unit]).strip()
    if not cg:
        return []
    try:
        with open("/sys/fs/cgroup" + cg + "/cgroup.procs") as f:
            return [int(x) for x in f.read().split()]
    except (OSError, ValueError):
        return []


def systemd_apps():
    """Every GUI app GNOME launched lives in its own systemd --user scope."""
    out = run(["systemctl", "--user", "list-units", "--type=scope",
               "--plain", "--no-legend", "--all"])
    apps = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0].lstrip("\u25cf* ")
        if not unit.endswith(".scope"):
            continue
        if not (unit.startswith("app-") or unit.startswith("snap.")):
            continue
        pids = [p for p in cgroup_pids(unit) if alive(p)]
        if not pids:
            continue
        appid = unit_appid(unit)
        apps.append({
            "unit": unit,
            "appid": appid,
            "pids": pids,
            "comm": proc_name(pids[0]),
            "windows": [],
        })
    return apps


def x11_windows():
    """Window ids per pid, so we can send a real 'close' request on X11."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return {}
    out = run(["wmctrl", "-lpx"])
    by_pid = {}
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 5:
            continue
        winid, _desktop, pid, wmclass = parts[0], parts[1], parts[2], parts[3]
        title = parts[5] if len(parts) > 5 else wmclass
        try:
            pid = int(pid)
        except ValueError:
            continue
        if pid == 0:
            continue
        by_pid.setdefault(pid, []).append({"id": winid, "title": title,
                                           "wmclass": wmclass})
    return by_pid


def pretty(app):
    appid = app["appid"]
    if appid.count(".") >= 2:              # org.gnome.Nautilus -> Nautilus
        label = appid.rsplit(".", 1)[-1]
    else:
        label = appid
    label = label.replace("-", " ").replace("_", " ").strip()
    if not label or label.endswith(".scope"):
        label = app["comm"] or appid
    return label[:1].upper() + label[1:]


def discover(cfg):
    apps = systemd_apps()
    wins = x11_windows()

    for a in apps:
        for pid in a["pids"]:
            a["windows"].extend(wins.get(pid, []))

    # Fallback for setups without app scopes (older GNOME, other DEs on X11).
    if not apps and wins:
        for pid, w in wins.items():
            apps.append({"unit": None, "appid": proc_name(pid), "pids": [pid],
                         "comm": proc_name(pid), "windows": w})

    excl = [e.lower() for e in cfg["exclude"]]
    mine = {os.getpid(), os.getppid()}
    out = []
    for a in apps:
        hay = (a["appid"] + " " + a["comm"]).lower()
        if any(e in hay for e in excl):
            continue
        if mine & set(a["pids"]):
            continue
        a["label"] = pretty(a)
        out.append(a)
    out.sort(key=lambda a: a["label"].lower())
    return out


# ------------------------------------------------------------------ closing

def close_app(app):
    """Polite close: WM close request on X11, otherwise SIGTERM."""
    if app["windows"]:
        for w in app["windows"]:
            run(["wmctrl", "-ic", w["id"]])
        return
    for pid in app["pids"]:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def force_close(app):
    if app["unit"]:
        run(["systemctl", "--user", "stop", app["unit"]], timeout=10)
    for pid in app["pids"]:
        if alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def still_running(app):
    return any(alive(p) for p in app["pids"])


def notify(body):
    run(["notify-send", "-a", "Close All Apps", "-i", "application-exit",
         "Close All Apps", body])


def close_all_cli(cfg):
    apps = discover(cfg)
    if not apps:
        print("Nothing to close.")
        notify("Nothing was open.")
        return
    notify("Closing %d app%s\u2026" % (len(apps), "" if len(apps) == 1 else "s"))
    for a in apps:
        print("closing", a["label"])
        close_app(a)
    deadline = time.time() + cfg["force_kill_after"]
    while time.time() < deadline:
        if not any(still_running(a) for a in apps):
            return
        time.sleep(0.5)
    for a in apps:
        if still_running(a):
            print("force closing", a["label"])
            force_close(a)


# ---------------------------------------------------------------------- GUI

def gui(cfg):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    class App(Gtk.Window):
        def __init__(self):
            super().__init__(title="Close All Apps")
            self.set_default_size(420, 480)
            self.set_border_width(0)
            self.cfg = cfg
            self.rows = []

            hb = Gtk.HeaderBar(title="Close All Apps", show_close_button=True)
            self.set_titlebar(hb)
            refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic",
                                                    Gtk.IconSize.BUTTON)
            refresh.connect("clicked", lambda *_: self.reload())
            hb.pack_start(refresh)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_border_width(12)
            self.add(box)

            self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(self.listbox)
            box.pack_start(scroll, True, True, 0)

            self.force = Gtk.CheckButton(
                label="Force close anything still open after %d s"
                      % cfg["force_kill_after"])
            self.force.set_active(True)
            box.pack_start(self.force, False, False, 0)

            self.status = Gtk.Label(xalign=0)
            box.pack_start(self.status, False, False, 0)

            btn = Gtk.Button(label="Close All")
            btn.get_style_context().add_class("destructive-action")
            btn.connect("clicked", self.on_close_all)
            box.pack_start(btn, False, False, 0)

            self.reload()

        def reload(self):
            for child in self.listbox.get_children():
                self.listbox.remove(child)
            self.rows = []
            apps = discover(self.cfg)
            for a in apps:
                row = Gtk.ListBoxRow()
                cb = Gtk.CheckButton()
                cb.set_active(True)
                hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                hb.set_border_width(6)
                hb.pack_start(cb, False, False, 0)
                lbl = Gtk.Label(xalign=0)
                sub = ", ".join(str(p) for p in a["pids"][:3])
                lbl.set_markup("<b>%s</b>\n<small>pid %s</small>"
                               % (GLib.markup_escape_text(a["label"]), sub))
                hb.pack_start(lbl, True, True, 0)
                row.add(hb)
                self.listbox.add(row)
                self.rows.append((cb, a))
            self.listbox.show_all()
            self.status.set_text("%d app%s open" % (len(apps),
                                                    "" if len(apps) == 1 else "s"))

        def on_close_all(self, _btn):
            targets = [a for cb, a in self.rows if cb.get_active()]
            if not targets:
                self.status.set_text("Nothing selected.")
                return
            for a in targets:
                close_app(a)
            self.status.set_text("Asked %d app%s to close\u2026"
                                 % (len(targets), "" if len(targets) == 1 else "s"))
            if self.force.get_active():
                GLib.timeout_add_seconds(self.cfg["force_kill_after"],
                                         self.sweep, targets)
            else:
                GLib.timeout_add_seconds(2, lambda: (self.reload(), False)[1])

        def sweep(self, targets):
            left = [a for a in targets if still_running(a)]
            for a in left:
                force_close(a)
            self.reload()
            return False

    win = App()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


def main():
    cfg = load_config()
    args = sys.argv[1:]
    if "--list" in args:
        for a in discover(cfg):
            print("%-28s pids=%s unit=%s" % (a["label"], a["pids"], a["unit"]))
    elif "--gui" in args:
        gui(cfg)
    else:
        close_all_cli(cfg)


if __name__ == "__main__":
    main()

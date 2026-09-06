#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo ">> installing dependencies"
sudo apt-get update -qq
sudo apt-get install -y python3-gi gir1.2-gtk-3.0 wmctrl libnotify-bin

echo ">> installing closeall"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
install -m 755 closeall.py "$HOME/.local/bin/closeall"

sed "s|Exec=closeall|Exec=$HOME/.local/bin/closeall|g" close-all-apps.desktop \
  > "$HOME/.local/share/applications/close-all-apps.desktop"
chmod 644 "$HOME/.local/share/applications/close-all-apps.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "NOTE: add \$HOME/.local/bin to your PATH" ;;
esac

echo ">> done. Search 'Close All Apps' in Activities, then drag it to the dock."

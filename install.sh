#!/usr/bin/env bash
# Installs or updates agent-usage from the latest GitHub release into ~/.local.
set -euo pipefail

REPO="Changroro/agent-usage"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/agent-usage"
BIN="$HOME/.local/bin"
PACKAGES=(python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1 gnome-shell-extension-appindicator gir1.2-notify-0.7)

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$DEST" "$BIN/agent-usage" "$HOME/.local/share/applications/agent-usage.desktop" "$HOME/.config/autostart/agent-usage.desktop"
    echo "Removed agent-usage. Settings and accounts stay in ~/.config/agent-usage."
    exit 0
fi

if ! dpkg -s "${PACKAGES[@]}" >/dev/null 2>&1; then
    command -v apt-get >/dev/null || { echo "Install these packages first: ${PACKAGES[*]}" >&2; exit 1; }
    sudo apt-get install -y "${PACKAGES[@]}"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://github.com/$REPO/releases/latest/download/agent-usage.tar.gz" | tar -xz -C "$tmp"
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")" "$BIN" "$HOME/.local/share/applications"
mv "$tmp/agent-usage" "$DEST"
ln -sf "$DEST/bin/agent-usage" "$BIN/agent-usage"
printf '[Desktop Entry]\nType=Application\nName=agent-usage\nExec=%s\nIcon=%s\n' \
    "$DEST/bin/agent-usage" "$DEST/assets/orb.png" > "$HOME/.local/share/applications/agent-usage.desktop"

echo "Installed agent-usage $(sed -n 's/^version = "\(.*\)"/\1/p' "$DEST/pyproject.toml") to $DEST"
echo "Run: agent-usage  (or $BIN/agent-usage if ~/.local/bin is not on PATH yet)"

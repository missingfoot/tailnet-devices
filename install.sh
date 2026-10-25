#!/usr/bin/env bash
# Install (or update) the Tailscale Devices tray app, and start it at login.
set -euo pipefail

src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="$HOME/.local/bin"
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
autostart_dir="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

mkdir -p "$bin_dir" "$app_dir" "$autostart_dir"
install -m 0755 "$src_dir/tailnet-devices.py"      "$bin_dir/tailnet-devices"
install -m 0644 "$src_dir/tailnet-devices.desktop" "$app_dir/tailnet-devices.desktop"
sed 's|^Exec=tailnet-devices$|Exec=tailnet-devices --hidden|' \
    "$src_dir/tailnet-devices.desktop" > "$autostart_dir/tailnet-devices.desktop"
update-desktop-database "$app_dir" 2>/dev/null || true

echo "Installed $bin_dir/tailnet-devices"
echo "  launcher:  $app_dir/tailnet-devices.desktop"
echo "  autostart: $autostart_dir/tailnet-devices.desktop (starts in tray)"

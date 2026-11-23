#!/bin/sh
# labwc does not activate graphical-session.target on this Raspberry Pi image.
# Import the actual desktop environment, then let systemd own the application.
set -eu
for name in DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP; do
    if printenv "$name" >/dev/null 2>&1; then
        systemctl --user import-environment "$name"
    fi
done
exec systemctl --user start pimex.service

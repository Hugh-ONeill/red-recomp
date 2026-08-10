#!/usr/bin/env bash
# Launch gen1recomp with the red-recomp shim. Usage: run.sh [--headed] [SPEED]
set -euo pipefail
HEADED=0
[ "${1:-}" = "--headed" ] && { HEADED=1; shift; }
SPEED="${1:-20}"
export RED_BRIDGE_DIR="${RED_BRIDGE_DIR:-$HOME/Developer/red-recomp/run}"
mkdir -p "$RED_BRIDGE_DIR"
rm -f "$RED_BRIDGE_DIR"/obs.json "$RED_BRIDGE_DIR"/cmd.lua
cd "$HOME/Developer/gen1recomp"
COMMON=(POKEPORT_DRIVER="$HOME/Developer/red-recomp/harness/shim.lua" POKEPORT_SPEED="$SPEED")
if [ "$HEADED" = 1 ]; then
  exec env "${COMMON[@]}" love .
else
  # True headless on a Wayland session (Hyprland): SDL/LOVE defaults to the
  # Wayland backend and would open a real window even under xvfb-run, so force
  # the X11 backend and clear WAYLAND_DISPLAY so love binds the Xvfb X server
  # instead. Xvfb supplies software GL (llvmpipe). NOTE: `env -u` must precede
  # the NAME=VALUE assignments or env treats -u as the command.
  exec xvfb-run -a env -u WAYLAND_DISPLAY SDL_VIDEODRIVER=x11 "${COMMON[@]}" love .
fi

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
# THE PORT'S OWN SETTINGS ARE RIG CONFIG (TODO (a), 2026-08-25). The shim
# refuses the presses that change them, but a value already changed lives
# in options.lua and the dying game rewrites that file on exit — a restart
# raced it once and came up green-and-negative. Assert the rig's values at
# every boot, from here, the one place every game starts (fresh_run.sh and
# the exclusive tests both go through run.sh).
OPTS="$HOME/.local/share/love/pokemon-love2d/options.lua"
if [ -f "$OPTS" ]; then
  sed -i -E 's/(gbcfx[[:space:]]*=[[:space:]]*)[0-9]+/\10/;
             s/(spanish_ui[[:space:]]*=[[:space:]]*)true/\1false/;
             s/(colors[[:space:]]*=[[:space:]]*)"[a-z]+"/\1"gbc"/' "$OPTS"
fi
# Headless runs still open an audio device — the repeated bump/interact
# sounds are an accidental but genuinely useful progress channel (a loop
# SOUNDS like a loop). RED_MUTE=1 silences it for unattended runs.
[ "${RED_MUTE:-0}" = "1" ] && export SDL_AUDIODRIVER=dummy
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

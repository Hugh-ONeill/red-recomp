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
CMD=(env POKEPORT_DRIVER="$HOME/Developer/red-recomp/harness/shim.lua" POKEPORT_SPEED="$SPEED" love .)
if [ "$HEADED" = 1 ]; then exec "${CMD[@]}"; else exec xvfb-run -a "${CMD[@]}"; fi

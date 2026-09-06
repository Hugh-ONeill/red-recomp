#!/usr/bin/env python3
"""A way back to a Pokemon Center is in the party or the bag, and the
harness now says so and drives it.

2026-09-05 (user): "add a shim operation for DIG so if its ever trying to
get to the pokecenter and cant but it has dig or escape rope it can use
either of those, but while i think it currently can use escape rope it
cant currently use dig ... teleport is included sorta in that as well".

The game runs DIG, TELEPORT and the ESCAPE_ROPE through one escape warp:
the party menu's "escape" action and the bag's escape_rope both call
beginTeleportOut, a 48-frame spin, a fade, and the party set down OUTSIDE
the door of the last Pokemon Center it used (warpToHealPoint). field_move
already picked party-submenu rows by label, so DIG was one row away — but
the op returned "used DIG" the instant the menu popped, said nothing about
where the party landed, and had no idea why the row might be missing
(DIG and the rope are offered only in the dungeon tilesets of
escape_rope_tilesets.asm, never in Agatha's room; TELEPORT only outdoors).
The rope had never been used in this run at all, and a refused rope would
have been reported as "a field item acts on what you are standing next to".

Now: one gate function reads the game's own tileset rule; the three ops
refuse in words BEFORE opening a menu when the game would; DIG, TELEPORT
and the rope ride the warp out and report the landing map and cell; and
heal, when there is no Center to walk to, names whichever of the three is
in hand, with its op and its cost. Which to use, or whether to walk, stays
the model's.
"""
from __future__ import annotations
import re, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SHIM = (ROOT / "harness/shim.lua").read_text()
EXEC = (ROOT / "planner/executor.py").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

# --- one gate, the game's own rule ------------------------------------
ck("the escape tilesets are the game's list",
   "local ESCAPE_TILESETS = { FOREST = true, CEMETERY = true, CAVERN = true,\n"
   "                          FACILITY = true, INTERIOR = true }" in SHIM)
ck("...and Agatha's room is excluded by id", 'mid ~= "AGATHAS_ROOM"' in SHIM)
ck("TELEPORT's gate is the engine's isOutside, not a guess",
   "pcall(MapM.isOutside, md," in SHIM)
ck("the ride-out waits for the spin, the fade and a new map",
   "not ow.teleportOut" in SHIM and "not ow.transitioning" in SHIM
   and '(ow.map or {}).id ~= from_map' in SHIM)
ck("...and reports the landing map and cell",
   "took you out of %s and set you down on %s at (%d,%d)" in SHIM)
ck("...and a save with no Center to return to is said, not guessed",
   "This save has never used a Pokemon Center" in SHIM)

# --- field_move --------------------------------------------------------
fm = SHIM[SHIM.index("function OPS.field_move"):SHIM.index("function OPS.field_move") + 20000]
ck("DIG is refused in words before any menu opens",
   '"DIG is not offered here — " .. tostring(_dwhy)' in fm)
ck("TELEPORT likewise, naming DIG as the indoor twin",
   "TELEPORT is offered only while you are OUTSIDE" in fm
   and "it is DIG that does this" in fm)
ck("after the row is chosen the warp is ridden out, not A-mashed",
   'if mv == "DIG" or mv == "TELEPORT" then\n    return ride_escape(G, _fromMap0, mv)' in fm)
ck("the not-offered fallback names DIG's gate too",
   'if _extra == "" and mv == "DIG" then' in fm)

# --- use_item / the rope -----------------------------------------------
ui = SHIM[SHIM.index("function OPS.use_item"):SHIM.index("function OPS.field_move")]
ck("the rope is gated before the bag opens, quoting the game's refusal",
   'if c.item == "ESCAPE_ROPE" then' in ui
   and "OAK: This isn't the time to use that!" in ui and "Nothing was spent" in ui)
ck("...and after the USE it rides the warp out and counts the rope spent",
   'ride_escape(G, _from0, "ESCAPE_ROPE")' in ui
   and "one ESCAPE_ROPE was spent (%d left)" in ui)

# --- heal names the ways back ---------------------------------------------
ck("heal's no-Center refusal carries the ways back",
   '.. "this map" .. escape_ways(G)' in SHIM)
ew = SHIM[SHIM.index("local function escape_ways"):SHIM.index("local function ride_escape")]
ck("...each with its op", '\\"op\\":\\"use_item\\"' in ew.replace('\\"', '\\"') or '"op\\":\\"use_item' in ew or 'op\\":\\"field_move' in ew)
ck("...and its cost", "is spent by the use" in ew and "which spends nothing" in ew)
ck("...and where they land, without saying to use any",
   "set you down OUTSIDE the door " in ew
   and "of the last Pokemon Center you used" in ew
   and "you should" not in ew.lower())
ck("...only when the game would actually offer it",
   'if bag_count(G, "ESCAPE_ROPE") > 0 and dig_ok then' in ew
   and "if ds and dig_ok then" in ew and "if tsl and tele_ok then" in ew)

# --- the model is told -------------------------------------------------
ck("the vocabulary states DIG, TELEPORT and the rope as ways out",
   "DIG AND TELEPORT ARE\nWAYS OUT" in EXEC and "is used up. None of\nthem brings you back" in EXEC)
ck("...and heal's doc says it names them on failure",
   "names any way back to\none you are holding" in EXEC)

# --- the gate itself, in luajit ------------------------------------------
if shutil.which("luajit"):
    m = re.search(r"local ESCAPE_TILESETS = \{.*?\nlocal function escape_gate\(G\).*?\nend\n", SHIM, re.S)
    ck("the gate extracts", bool(m))
    lua = m.group(0) + r'''
local os = require("os")
local ok = true
local function ck(name, got, want)
  if got ~= want then ok = false; print("FAIL " .. name .. " got=" .. tostring(got))
  else print("ok   " .. name) end
end
local function G_of(id, ts) return { overworld = { map = { id = id, def = { tileset = ts } } }, data = {} } end
local d, t, why = escape_gate(G_of("POKEMON_MANSION_B1F", "FACILITY"))
ck("a FACILITY floor offers DIG", d, true)
ck("...with no reason to give", why, nil)
d, t, why = escape_gate(G_of("CINNABAR_POKECENTER", "INTERIOR"))
ck("a Center is INTERIOR and offers DIG too (gen 1's rule)", d, true)
d, t, why = escape_gate(G_of("CINNABAR_ISLAND", "OVERWORLD"))
ck("a town does not", d, false)
ck("...and the reason names the kind and the outdoor twin",
   (why:find("OVERWORLD", 1, true) ~= nil and why:find("TELEPORT", 1, true) ~= nil), true)
d, t, why = escape_gate(G_of("AGATHAS_ROOM", "CEMETERY"))
ck("Agatha's room is refused by id", d, false)
ck("...and says so", why:find("Agatha", 1, true) ~= nil, true)
os.exit(ok and 0 or 1)
'''
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
        f.write(lua); path = f.name
    r = subprocess.run(["luajit", path], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        ck("luajit: " + line[5:], line.startswith("ok"))
    ck("luajit gate run exits clean", r.returncode == 0)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

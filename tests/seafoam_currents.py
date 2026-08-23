"""Water that moves you is said so, and never called reachable.

Seafoam's currents are a scripted sweep -- the same class of mechanic as
the arrow tiles the harness already models -- and it modelled them not at
all.  Worse, B4F's forcedExit coords ARE the two doors (20,17)/(21,17):
while the party rides and the B3F plug boulders are not down, the engine
bumps it two cells north (OverworldState:checkSeafoamCurrent), so it can
never stand there.  Every list said "reachable: true", use_warp answered
"no path", and one subgoal aimed at those doors sixteen times.
Read from the engine's own field.seafoam table, so the cells stop being
listed the moment the boulders go down.
"""
import json
import subprocess
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

# --- the engine's data is what we claim it is ---------------------------
LUA = r'''
package.path = "./?.lua;./?/init.lua;" .. package.path
local field = dofile("data/generated/field.lua")
local sf = field.seafoam.SEAFOAM_ISLANDS_B4F
local out = { forced = {}, currents = {}, until_ = {}, disabled = {} }
for _, c in ipairs(sf.forcedExit.coords) do
  out.forced[#out.forced + 1] = c.x .. "," .. c.y
end
for _, c in ipairs(sf.currents or {}) do
  out.currents[#out.currents + 1] = c.x .. "," .. c.y
end
for _, e in ipairs(sf.forcedExit.activeUntilEvents) do
  out.until_[#out.until_ + 1] = e
end
for _, e in ipairs(sf.currentsDisabledByEvents or {}) do
  out.disabled[#out.disabled + 1] = e
end
local parts = {}
for k, v in pairs(out) do
  parts[#parts + 1] = '"' .. k .. '":["' .. table.concat(v, '","') .. '"]'
end
print("{" .. table.concat(parts, ",") .. "}")
'''
d = json.loads(subprocess.run(
    ["lua5.4", "-e", LUA], cwd="/home/wiz/Developer/gen1recomp",
    capture_output=True, text=True).stdout.strip())

ck("B4F forcedExit covers both door tiles",
   {"20,17", "21,17"} <= set(d["forced"]))
ck("B4F forcedExit covers the two cells above them",
   {"20,16", "21,16"} <= set(d["forced"]))
ck("forcedExit is released by the B3F boulders",
   all("SEAFOAM3_BOULDER" in e for e in d["until_"]) and len(d["until_"]) == 2)
ck("B4F carries you at its two current cells", set(d["currents"]) == {"4,14", "5,14"})
ck("currents are released by the B4F boulders",
   all("SEAFOAM4_BOULDER" in e for e in d["disabled"]) and len(d["disabled"]) == 2)

# --- the ledger says it, in words ---------------------------------------
import ledger
obs = {
    "party": [{"moves": ["SURF", "STRENGTH"]}],
    "map": {
        "id": "SEAFOAM_ISLANDS_B4F",
        "water": {"cells": 300, "x": 20, "y": 15,
                  "mount_x": 20, "mount_y": 14},
        "currents": {
            "pushed": [{"x": 20, "y": 16}, {"x": 21, "y": 16},
                       {"x": 20, "y": 17}, {"x": 21, "y": 17}],
            "carried": [{"x": 4, "y": 14}, {"x": 5, "y": 14}],
        },
    },
}
class _Ex:
    """The least a ledger needs to render a page."""
    visits: dict = {}
    frontier: dict = {}
    explored: dict = {}
    sightings: dict = {}
    shut_doors: dict = {}
    dead_ends: dict = {}
    map_doors: dict = {}
    def _where(self, _obs): return "SEAFOAM_ISLANDS_B4F|15,0"
    def __getattr__(self, _n): return {}

try:
    head = ledger.render([], _Ex(), obs).splitlines()[0]
except Exception as e:                           # pragma: no cover
    head = "RENDER FAILED: %r" % (e,)
ck("header names the water as moving you", "WATER MOVES YOU" in head)
ck("header names a pushed door", "(20,17)" in head)
ck("header names a carried cell", "(4,14)" in head)
ck("header says you cannot stand there", "cannot stand there" in head)
ck("header does not tell it what to do about it",
   "boulder" not in head.lower() and "push the" not in head.lower())

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("HEAD WAS:", head)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

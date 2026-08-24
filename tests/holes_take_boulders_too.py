"""A hole takes a boulder, not just the player.

Victory Road 3F's (23,15) is in NO warp table — 3F's warps are (23,7),
(26,8), (27,15), (2,0) — and it is BOTH: the player falls through it, and a
boulder shoved onto it drops to 2F beside that floor's second switch, which
is the only way a boulder reaches that switch at all (user, 2026-08-24:
"does it know it can push boulders down holes? ... the last puzzle requires
this i think").

Seafoam is the same shape and larger: EIGHT player holes across four floors
in HOLE_FALLS, and a boulder cascade whose cells were sitting in
field.seafoam[map].holes — one field over from the currents the harness
already reads — with nothing ever reading them (user: "is that the same for
the seafoam holes?").
"""
import subprocess, sys, pathlib
GAME = pathlib.Path("/home/wiz/Developer/gen1recomp")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from planner import ledger

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


def lua(script, expr):
    return subprocess.run(
        ["lua5.4", "-e", f'local M = dofile("data/scripts/{script}") ' + expr],
        cwd=GAME, capture_output=True, text=True).stdout.strip()


def cells(script, mapid, field):
    return lua(script, f'local l = (M.{mapid} or {{}}).{field} '
                       'local t = {} for _, c in ipairs(l or {}) do '
                       't[#t+1] = c[1]..","..c[2] end print(table.concat(t," "))')


ck("Victory Road 3F exports its hole for the player",
   cells("story.lua", "VICTORY_ROAD_3F", "holes") == "23,15")
ck("...and for a boulder",
   cells("story.lua", "VICTORY_ROAD_3F", "boulder_holes") == "23,15")
ck("a floor with no hole exports none",
   cells("story.lua", "VICTORY_ROAD_1F", "holes") == "")

for mid, want in (("SEAFOAM_ISLANDS_1F", "17,6 24,6"),
                  ("SEAFOAM_ISLANDS_B1F", "18,6 23,6"),
                  ("SEAFOAM_ISLANDS_B2F", "19,6 22,6"),
                  ("SEAFOAM_ISLANDS_B3F", "3,16 6,16")):
    ck(f"{mid} exports its player holes",
       cells("seafoam.lua", mid, "holes") == want)

# the boulder side of Seafoam is generated data the shim reads directly
shim = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim reads field.seafoam's own hole list",
   "_sf.holes" in shim)
ck("...into the same boulder_holes the script feeds",
   "o.map.boulder_holes" in shim)


class Ex:
    def _where(self, o):
        return f"{o['map']['id']}|{o['player']['x']},{o['player']['y']}"

    def __getattr__(self, k):
        return {}


obs = {"map": {"id": "VICTORY_ROAD_3F", "warps": [],
               "boulder_holes": [{"x": 23, "y": 15, "reachable": True}]},
       "player": {"x": 20, "y": 15}, "party": [], "bag": {}}
page = str(ledger.render([], Ex(), obs))
ck("the page says a boulder can be sent down", "A BOULDER CAN BE SENT DOWN" in page)
ck("...naming the cell", "(23,15)" in page)
ck("...and that it is the same hole you fall through",
   "fall through yourself" in page)
ck("...without claiming what the landing is worth",
   "not recorded here" in page)
ck("no boulder holes, no line",
   "A BOULDER CAN BE SENT DOWN" not in str(ledger.render(
       [], Ex(), {"map": {"id": "X", "warps": []},
                  "player": {"x": 1, "y": 1}, "party": [], "bag": {}})))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

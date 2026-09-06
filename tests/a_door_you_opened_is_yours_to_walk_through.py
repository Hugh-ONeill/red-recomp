#!/usr/bin/env python3
"""A door the model opened is the model's to walk through.

2026-09-05, live in the Pokemon Mansion. The model pressed the 2F switch
at (2,11), then sent use_warp(25,14) for the stairs that switch opens, and
the harness answered:

  couldn't reach the warp tile (no path — the ground you have SEEN and can
  walk from here is 236 cell(s) ... 2 cell(s) that were WALLS the last time
  they were on screen were not routed into — if one has opened since,
  seeing it again is what lifts that)

The footprint rule is right for every walk the harness picks for itself:
open NOW proves nothing until it has been SEEN open, or explore threads
walls it has only guessed about. It was wrong here, because the model
picked the destination. It had pressed the switch and remembered what the
switch does; the refusal was the harness overruling that memory (user:
"if the model chooses to try to route to a warp that IS open as the result
of flicking the switch but hasnt yet been seen to, it should route, because
thats the model remembering a fact about when the stairs are open based on
switch state, not the harness telling the model where to go").

So the ops whose destination the MODEL names — walk_to, use_warp, interact
— now go out with "thaw":true, and the route gate lets a cell that was a
wall at last view and is open now be walked into. What is still true:

  a cell that is STILL a wall stops the walk, as live collision always did
  ground never on screen is still refused ("unseen" is not thawed)
  explore, sweep and go are the harness's own picks and keep the freeze
  the result names the cell the way went through, so the model reads that
  its switch did what it thought

The flag rides the COPY of the op that is sent: the strike key and the
trace line the model reads are unchanged.
"""
from __future__ import annotations
import re, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import executor as EX                                # noqa: E402
import ledger                                        # noqa: E402
import candidates as C                               # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SHIM = (ROOT / "harness/shim.lua").read_text()
EXEC = (ROOT / "planner/executor.py").read_text()
LED = (ROOT / "planner/ledger.py").read_text()

# --- the gate takes the flag and lifts ONLY the frozen rule ------------
ck("route_gate takes thaw", "local function route_gate(G, thaw)" in SHIM)
ck("...and skips the frozen rule under it, not the unseen one",
   'if not mask[nk] then return "unseen" end\n'
   "    if not thaw and seen_wall_since_view(map, WT, rpx, rpy, nx, ny, nk,"
   in SHIM)
ck("bfs_dir threads it",
   "local function bfs_dir(G, tx, ty, blind, thaw)" in SHIM
   and "and route_gate(G, thaw) or nil" in SHIM)
ck("the seam finder does not (cross is the harness's gap-finding)",
   "local gate = (not (blind or BLIND_ROUTING)) and route_gate(G) or nil"
   in SHIM)
ck("sweep's own router keeps the freeze",
   "bfs_dir_pass(G, target.x, target.y, avoid,\n"
   "                               route_gate(G))" in SHIM)

# --- walk_to reads it, passes it, and names what it went through -------
ck("walk_to reads the flag", "local thaw = c.thaw and true or false" in SHIM)
ck("...snapshots the frozen cells before it moves",
   "thawed0[k] = true" in SHIM and "if thaw and not blind then" in SHIM)
ck("...routes with it, on foot and on the water",
   SHIM.count("bfs_dir(G, c.x, c.y, blind, thaw)") == 2)
ck("...hands it to the walk that mounts the water",
   "blind = c.blind, thaw = c.thaw })" in SHIM)
ck("...records each such cell as it is stepped onto",
   'crossed[#crossed + 1] = "(" .. _ck .. ")"' in SHIM)
ck("...and says so on arrival, in the game's own terms",
   "a WALL the " in SHIM and "last time on screen; open now, and you have now seen it so"
   in SHIM)
ck("use_warp hands the flag to both its walks",
   SHIM.count("blind = c.blind, thaw = c.thaw })") == 3)
ck("...and its warped-returns carry the note",
   SHIM.count(".. THAW_LAST") >= 3)
ck("interact's approach walk carries it",
   "p, a[1], a[2]), thaw = c.thaw })" in SHIM)
ck("the refusal words no longer claim the wall is never routed into",
   "a walk_to or use_warp YOU send goes through it" in SHIM
   and SHIM.count("you send yourself") == 2
   and "is not \"\n      .. \"routed into until it is SEEN again" not in SHIM)

# --- the executor sets it only where the MODEL named the place ---------
ck("the executor has the rule", "def _named(self, op, step):" in EXEC)
ck("...and both senders use it",
   EXEC.count("self.b.send(op, **self._named(op, step))") == 2)
ck("...and no sender still sends the bare step",
   "self.b.send(op, **step)" not in EXEC)

class _E:                       # any object: _named reads one attribute
    pass
e = _E()
st = {"x": 25, "y": 14}
out = EX.Executor._named(e, "use_warp", st)
ck("a use_warp the model wrote goes out thawed", out.get("thaw") is True)
ck("...without touching the step itself", "thaw" not in st)
ck("walk_to and interact too",
   EX.Executor._named(e, "walk_to", {"x": 1, "y": 1}).get("thaw") is True
   and EX.Executor._named(e, "interact", {"x": 1, "y": 1}).get("thaw") is True)
ck("cross, go, sweep are not (the harness finds those ways)",
   all("thaw" not in EX.Executor._named(e, op, {"dir": "north"})
       for op in ("cross", "sweep", "grind", "heal")))
e2 = _E(); e2._explore_params = {}
ck("inside explore the same walk_to keeps the freeze",
   "thaw" not in EX.Executor._named(e2, "walk_to", {"x": 1, "y": 1}))
e3 = _E()
ck("a step that already says thaw:false is left alone",
   EX.Executor._named(e3, "walk_to", {"x": 1, "y": 1, "thaw": False})
   .get("thaw") is False)

# --- the model is told the contract ------------------------------------
ck("the op vocabulary says it",
   "IS walked through by a walk_to, use_warp or interact YOU send" in EXEC
   and "explore's own walks do not cross one until you" in EXEC)

def head(m_extra):
    ex = C.make()
    ex._where = lambda o: "POKEMON_MANSION_2F|6,1"
    ex._explore_trips = {}
    obs = {"map": dict({"id": "POKEMON_MANSION_2F", "region": "6,1",
                        "warps": []}, **m_extra),
           "player": {"x": 10, "y": 1}, "party": [], "bag": {}}
    return ledger.render([], ex, obs, "map:POKEMON_MANSION_3F")

t = head({"frontier_stale": [{"x": 10, "y": 1, "d": 3, "wx": 9, "wy": 1}]})
ck("the page's stale-wall note says the model may go through one",
   "a walk_to or use_warp you send goes through it if it is open now" in t
   and "explore's own walks will not" in t)
ck("...while still claiming nothing about whether it has",
   "Whether any of them has opened is not known here" in t)

# --- the gate itself, in luajit: frozen without the flag, open with it --
if shutil.which("luajit"):
    m1 = re.search(r"seen_wall_since_view = function.*?\nend\n", SHIM, re.S)
    m2 = re.search(r"local function route_gate\(G, thaw\).*?\nend\n", SHIM, re.S)
    ck("both decision functions extract", bool(m1 and m2))
    lua = r'''
local os = require("os")
VIEW_L, VIEW_R, VIEW_U, VIEW_D = 4, 5, 4, 4
SEEN = { M = { ["40,40"] = true, ["41,41"] = true, ["20,21"] = true } }
WALK = { M = { ["40,40"] = false, ["41,41"] = true, ["20,21"] = false } }
''' + m1.group(0) + m2.group(0) + r'''
local G = { overworld = {
  map = { id = "M", isWalkableCell = function(self, x, y) return true end },
  player = { cellX = 20, cellY = 20 } } }
local ok = true
local function ck(name, got, want)
  if got ~= want then ok = false; print("FAIL " .. name .. " got=" .. tostring(got))
  else print("ok   " .. name) end
end
local g0, g1 = route_gate(G, false), route_gate(G, true)
ck("off-screen was-wall-now-open is frozen for a harness walk", g0(40, 40, "40,40"), "frozen")
ck("...and open for a walk the model named",                    g1(40, 40, "40,40"), nil)
ck("never-seen ground stays unseen without the flag",           g0(50, 50, "50,50"), "unseen")
ck("...and with it",                                            g1(50, 50, "50,50"), "unseen")
ck("a cell last seen open is open either way",                  g0(41, 41, "41,41"), nil)
ck("an on-screen was-wall cell is live, never frozen",          g0(20, 21, "20,21"), nil)
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

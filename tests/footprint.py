"""The footprint: the model knows what has been on screen, and no more.

The shim paints a seen-mask from the engine's own viewport and cuts every
positioned list in the observation down to it; the executor reads the
result. These are the executor's obligations: say where seen ground ends
(never what is past it), sweep unseen ground before pressing things, count
newly seen ground as progress, and never call a floor with unseen ground
finished. Designed 2026-08-24 (TODO "AREA-FOOTPRINT", the user's).
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

def fresh():
    ex = E.Executor.__new__(E.Executor)
    ex.explored, ex.visits, ex.map_doors, ex.map_seen = {}, {}, {}, {}
    ex.searched = {"*": {}}
    ex._mark_now = [1, 2, 3]
    ex.logged = []
    ex.log = lambda kind, **kw: ex.logged.append((kind, kw))
    return ex

OBS = {"mode": "overworld", "player": {"x": 10, "y": 10},
       "map": {"id": "ROUTE_10", "region": "3,3",
               "seen": {"n": 90, "frontier_n": 8},
               "frontier": [{"x": 10, "y": 6, "d": 4}, {"x": 15, "y": 10, "d": 5},
                            {"x": 4, "y": 11, "d": 7}, {"x": 11, "y": 14, "d": 8},
                            {"x": 16, "y": 6, "d": 9}, {"x": 3, "y": 3, "d": 12},
                            {"x": 18, "y": 12, "d": 13}, {"x": 2, "y": 18, "d": 15}],
               "warps": [{"x": 12, "y": 9, "reachable": True}]}}

# ---- the coverage line ---------------------------------------------------
ex = fresh()
t = ex.coverage_text(OBS)
ck("unseen ground is announced", "HAS NOT ALL BEEN ON SCREEN" in t)
ck("the nearest spot comes first, with its side", "(10,6) north" in t and t.index("(10,6)") < t.index("(15,10)"))
ck("east/west/south sides are computed from the player", "(15,10) east" in t and "(4,11) west" in t and "(11,14) south" in t)
ck("the overflow is counted, not listed", "2 more such spot(s)" in t)
ck("it never says what is past the edge", "past any of them is not known" in t)
ck("no percentage of the map is stated", "%" not in t)
ck("explore is named as the way to look", '{"op":"explore"}' in t)

done = {"mode": "overworld", "player": {"x": 1, "y": 1},
        "map": {"id": "X", "seen": {"n": 40, "frontier_n": 0}, "frontier": []}}
ck("a fully seen floor says so", "has been on screen" in ex.coverage_text(done))
ck("an old shim (no seen block) says nothing", ex.coverage_text({"map": {"id": "X"}}) == "")
dark = {"mode": "overworld", "player": {"x": 1, "y": 1},
        "map": {"id": "ROCK_TUNNEL_1F", "dark": True, "seen": {"n": 40, "frontier_n": 0}, "frontier": []}}
ck("darkness is said, and what it hides", "IT IS DARK" in ex.coverage_text(dark) and "FLASH" in ex.coverage_text(dark))

# ---- unseen ground keeps a floor unfinished --------------------------------
ex = fresh()
# note_frontier reads a dozen ledgers this fake does not carry; give it
# empty ones as it asks, since the one thing under test is map_seen
for _ in range(40):
    try:
        ex.note_frontier(OBS)
        break
    except AttributeError as e:
        setattr(ex, str(e).split("'")[-2], {})
ck("note_frontier records the frontier count", ex.map_seen.get("ROUTE_10") == 8)
ck("a map with unseen ground has 'unopened doors' even with none", ex._map_has_unopened_doors("ROUTE_10"))
ex.searched["*"] = {"ROUTE_10|3,3": {"n": 3}}
ck("...and is not 'fully worked'", "ROUTE_10|3,3" not in ex._worked_for("map:CERULEAN_CITY"))
ex.map_seen["ROUTE_10"] = 0
ck("once seen from all reachable ground, the door arithmetic decides again: an unwalked door still counts",
   ex._map_has_unopened_doors("ROUTE_10"))
ex.map_doors["ROUTE_10"] = set()
ck("...and with no unwalked door and no unseen ground the floor is finished",
   not ex._map_has_unopened_doors("ROUTE_10"))

# ---- newly seen ground is progress -----------------------------------------
a = dict(OBS); b = {**OBS, "map": {**OBS["map"], "seen": {"n": 120, "frontier_n": 5}}}
ck("a sweep that ends where it began still changes the snapshot",
   E.Executor._snapshot(a) != E.Executor._snapshot(b))
ck("...trailing, so the circling indices are untouched",
   E.Executor._snapshot(a)[:6] == E.Executor._snapshot(b)[:6])

# ---- explore sweeps before it presses -------------------------------------
ex = fresh()
sent = []
def fake_run_traced(sg, macro, ignore_done=False):
    sent.append(macro)
    return True, ["sweep: swept 9 step(s)"], list(macro)
ex._run_traced = fake_run_traced
ex._cur_target = "map:LAVENDER_TOWN"
ex._outcomes_here = lambda obs: {}
ex._explore_params = {"until": "door", "steps": 40}
ok, tr, cl = ex._explore_step({"id": "s"}, OBS)
ck("explore on a floor with a frontier is a sweep", sent and sent[0][0]["op"] == "sweep")
ck("the model's until/steps ride along", sent and sent[0][0].get("until") == "door" and sent[0][0].get("steps") == 40)
ck("the trace says it swept", any("sweeping unseen ground" in t for t in tr))
ck("the step is logged as a sweep", any(k == "explore_step" and kw.get("step") == "sweep" for k, kw in ex.logged))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

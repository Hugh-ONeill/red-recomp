"""A seam is double-edged. Crossing Viridian's north edge onto Route 2
records Route 2's south edge as the way back, at that moment, with its
destination known and its count 0 (user, 2026-08-25: "south rt2 seam
should be viridian automatically since its coming from there")."""
import sys
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E, ledger

def fresh():
    ex = E.Executor.__new__(E.Executor)
    ex.explored, ex.visits, ex.map_doors, ex.map_seen = {}, {}, {}, {}
    ex._bad_seam, ex._no_cross, ex._faint_at = set(), {}, None
    ex._cur_target = "map:PEWTER_CITY"
    ex._mark_now = [0, 3, 2]
    ex.logged = []
    ex.log = lambda kind, **kw: ex.logged.append((kind, kw))
    ex._save_memory = lambda: None
    ex._where = lambda o: f"{(o or {}).get('map', {}).get('id')}|{(o or {}).get('map', {}).get('region')}"
    return ex

before = {"mode": "overworld", "player": {"x": 10, "y": 0},
          "map": {"id": "VIRIDIAN_CITY", "region": "4,4", "connections": {"north": "ROUTE_2"}}}
after = {"mode": "overworld", "player": {"x": 10, "y": 35},
         "map": {"id": "ROUTE_2", "region": "2,30", "connections": {"south": "VIRIDIAN_CITY"}},
         "result": {"detail": "crossed"}}
ex = fresh()
for _ in range(60):
    try:
        ex.note_transition(before, {"dir": "north"}, after)
        break
    except AttributeError as e:
        setattr(ex, str(e).split("'")[-2], {})
fwd = (ex.explored.get("VIRIDIAN_CITY|4,4") or {}).get("north") or {}
back = (ex.explored.get("ROUTE_2|2,30") or {}).get("south") or {}
ck("the crossing is recorded forward", fwd.get("to") == "ROUTE_2|2,30" and int(fwd.get("n") or 0) >= 1)
ck("...and its reverse at the same moment", back.get("to") == "VIRIDIAN_CITY|4,4")
ck("the reverse counts 0 crossings and says it was inferred", back.get("n") == 0 and back.get("inferred"))
ck("it is logged", any(k == "reverse_seam" for k, _ in ex.logged))

# walking it back later makes it a real crossing, not a second inferred one
ex.note_transition(after, {"dir": "south"}, before)
back = (ex.explored.get("ROUTE_2|2,30") or {}).get("south") or {}
ck("walking it back counts on the same edge", back.get("n") == 1 and back.get("to") == "VIRIDIAN_CITY|4,4")

# a refuted seam is not re-inferred
ex2 = fresh()
ex2._bad_seam = {("ROUTE_2|2,30", "south", "VIRIDIAN_CITY|4,4")}
for _ in range(60):
    try:
        ex2.note_transition(before, {"dir": "north"}, after); break
    except AttributeError as e:
        setattr(ex2, str(e).split("'")[-2], {})
ck("a seam the walk refuted gets no reverse", "south" not in (ex2.explored.get("ROUTE_2|2,30") or {}))

# graphs from before the rule get it at load
ex3 = fresh()
ex3.explored = {"PALLET_TOWN|1,1": {"north": {"n": 4, "to": "ROUTE_1|3,3"}},
                "ROUTE_1|3,3": {"north": {"n": 2, "to": "VIRIDIAN_CITY|4,4"}}}
n = ex3._backfill_reverse_seams()
ck("backfill adds one reverse per walked seam", n == 2)
ck("...pointing home", ex3.explored["ROUTE_1|3,3"]["south"]["to"] == "PALLET_TOWN|1,1"
   and ex3.explored["VIRIDIAN_CITY|4,4"]["south"]["to"] == "ROUTE_1|3,3")
ck("backfill is idempotent", ex3._backfill_reverse_seams() == 0)

# the ledger says what it is
ex4 = fresh()
ex4.explored = {"ROUTE_2|2,30": {"south": {"n": 0, "to": "VIRIDIAN_CITY|4,4", "inferred": True}}}
ex4._taken_here = lambda here: dict(ex4.explored.get(here) or {})
ex4._spent_exits = lambda here: {}
ex4._sealed = lambda here: set()
ex4._walked_dest = lambda mid, key: "VIRIDIAN_CITY|4,4"
ex4.dead_for = lambda t, r: 0
obs = {"mode": "overworld", "player": {"x": 10, "y": 35},
       "map": {"id": "ROUTE_2", "region": "2,30", "connections": {"south": "VIRIDIAN_CITY"}, "warps": [], "objects": []}}
cands = None
for _ in range(80):
    try:
        cands = ledger.build(ex4, obs, "map:PEWTER_CITY"); break
    except AttributeError as e:
        setattr(ex4, str(e).split("'")[-2], {} if "sightings" not in str(e) else {})
seam = next((c for c in (cands or []) if c.kind == "seam" and c.key == "south"), None)
ck("the ledger lists the reverse seam", seam is not None)
ck("...as the way back, not as taken 0x", seam is not None and seam.status == "back")
ck("...with its destination known", seam is not None and "VIRIDIAN" in str(seam.dest))
ck("the words say it has not been crossed from this side",
   "not crossed it from this side" in ledger._STATUS_WORDS["back"])

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

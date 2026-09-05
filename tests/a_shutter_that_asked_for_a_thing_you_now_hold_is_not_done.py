#!/usr/bin/env python3
"""A shutter that asked for a thing you now hold is not done (2026-09-05).

Silph 9F read "EVERYTHING YOU CAN REACH HERE IS DONE" with three card-key
shutters marked "pressed", CARD_KEY in the bag, and half the floor drawn behind
them as ground "you cannot walk to"; the run rode the lift away (user: "the
shutters were not touched so half the room is unexplored ... its now reachable
if it actually interacts with the shutters now that it has the key card"). The
door's own words, the engine's item list and the bag are put together: the door
goes back to unworked, its row says why, and the unreachable-ground line names
the shutters as what stands between. Which door leads where stays unsaid.

Synthetic: a bare executor and an observation, no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import executor as E                                   # noqa: E402
import ledger as L                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
HERE = "SILPH_CO_9F|14,0"
def bare(bag):
    ex = object.__new__(E.Executor)
    for name, val in dict(explored={}, frontier={HERE: ["9,0"]}, _no_cross={}, _no_cross_at={}, _exit_tries={},
                          visits={HERE: 9}, hints={HERE: ['DOOR_SILPH_CO_9F_11_12: Darn! It needs a CARD KEY!']},
                          touched={HERE: ["DOOR_SILPH_CO_9F_11_12", "DOOR_SILPH_CO_9F_18_4"]}, _inert_objs={}, sightings={}, searched={},
                          dead_ends={}, _gone={}, seen_far={}, blockers={}, _cut_bushes={}, map_forced={}, map_holes={}, door_dests={},
                          _shelves={}, _shelf_machine=set(), _shelf_reads={}, _offered={}, _wild_lv={}, _wild_seen={}, region_seen={},
                          frontier_here={}, _retalked=set(), _cur_target="flag:EVENT_X", _outcomes={}, hints_at={}, _touch_mark={},
                          _dead_ops={}, _dead_at={}, _dead_why={}, _unreached_at={}, _region_mark={}, _plan_hist={},
                          _world_visits={}, _stuck_in={}, _parts_by_map={}, region_anchors={}, _bad_seam=set(), _shut_settings={},
                          _reach_settings={}, _flag_sites={}, contested={}, _dry_walks={}, _ghost_said="").items():
        setattr(ex, name, val)
    ex._mark_now = [4, 191, len(bag)]
    ex._where = lambda o: HERE
    ex._route = lambda a, b: None
    ex.log = lambda *a, **k: None
    return ex
def obs(bag):
    return {"mode": "overworld", "player": {"x": 14, "y": 0}, "badges": ["A"] * 4, "flags": ["f"] * 191, "bag": bag,
            "map": {"id": "SILPH_CO_9F", "region": "14,0", "warps": [{"x": 9, "y": 0, "dest": "SILPH_CO_10F", "reachable": True}],
                    "connections": {}, "seen_unreached": {"n": 61, "near": [{"x": 10, "y": 1}], "from": []},
                    "objects": [{"name": "DOOR_SILPH_CO_9F_11_12", "kind": "shut_door", "x": 11, "y": 12, "reachable": True, "twins": [{"x": 11, "y": 13}]},
                                {"name": "DOOR_SILPH_CO_9F_18_4", "kind": "shut_door", "x": 18, "y": 4, "reachable": True}]}}
OUT = {"DOOR_SILPH_CO_9F_11_12": {"n": 1, "last": 'the world did not change, but it SPOKE — it said: "Darn! It needs a CARD KEY!"'},
       "DOOR_SILPH_CO_9F_18_4": {"n": 1, "last": 'the world did not change, but it SPOKE — it said: "Darn! It needs a CARD KEY!"'}}
err = None
try:
    ex = bare({"CARD_KEY": 1, "LIFT_KEY": 1}); o = obs({"CARD_KEY": 1, "LIFT_KEY": 1})
    cands = L.build(ex, o, "flag:EVENT_X", outcomes=OUT)
    page = L.render(cands, ex, o, "flag:EVENT_X")
except Exception as e:
    import traceback; err = traceback.format_exc(); cands, page = [], ""
ck("build and render run on the bare rig", err is None, err)
doors = [c for c in cands if c.kind == "shut_door"]
ck("a shutter that asked for the key you now hold is back to unworked", doors and all(c.status == "reopened" and c.now_held == "CARD_KEY" for c in doors), [(c.key, c.status) for c in doors])
ck("...and its row says so in the door's words", 'pressed 1x when you held no CARD_KEY (it said: "Darn! It needs a CARD KEY!") — you hold CARD_KEY NOW' in page, page[:1500])
ck("...so the floor is not called done", "EVERYTHING YOU CAN REACH HERE IS DONE" not in page and "FULLY WORKED" not in page, page[:600])
ck("the unreachable ground names the shutters as what stands between", "CLOSED DOOR(s) stand on this floor (DOOR_SILPH_CO_9F_11_12, DOOR_SILPH_CO_9F_18_4) — ground past a shut door is reached by opening it" in page, page[:900])
ck("which door leads where is not said", "10F" not in page.split("CLOSED DOOR(s)")[1][:200] if "CLOSED DOOR(s)" in page else False)
try:
    ex2 = bare({"LIFT_KEY": 1}); o2 = obs({"LIFT_KEY": 1})
    c2 = L.build(ex2, o2, "flag:EVENT_X", outcomes=OUT); p2 = L.render(c2, ex2, o2, "flag:EVENT_X")
    ck("without the key, the shutters stay as they were", all(getattr(c, "now_held", None) is None for c in c2 if c.kind == "shut_door") and "you hold CARD_KEY NOW" not in p2)
except Exception as e:
    import traceback; ck("without the key, the shutters stay as they were", False, traceback.format_exc())
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:900]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)

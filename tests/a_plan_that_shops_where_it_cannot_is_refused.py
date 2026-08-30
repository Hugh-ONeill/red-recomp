"""A plan cannot end on buying what that counter does not sell.

Leg 19 was authored TEN times as "go to the mart, buy FRESH_WATER". By the
tenth, CERULEAN_MART had been read four times and VERMILION_MART three — the
same seven and six items every time, no water on either — and both shelves
were printed on the page the plan was written from (2026-08-30). Showing the
evidence had stopped being enough.

Same class as the already-fired flag, the has_item count of 0, and the
species the party lacks: not a judgement about where the water IS, which
nothing in this harness knows, but a plan the run's OWN evidence says cannot
finish. Handing it back is how the model finds out.

A shelf that has come back DIFFERENT is exempt: Viridian's changes once,
after the parcel, and a counter this run has watched move is not one we may
call settled.
"""
import sys, json, tempfile, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

def plan(*subs):
    return {"goal": "g", "subgoals": list(subs)}
GO = {"id": "enter_mart", "goal_text": "Enter the mart",
      "done_when": {"map": "VERMILION_MART"}}
BUY = {"id": "buy_fresh_water", "goal_text": "Buy Fresh Water",
       "done_when": {"has_item": {"FRESH_WATER": 1}}}
OK = {"id": "buy_a_ball", "goal_text": "Buy a Poke Ball",
      "done_when": {"has_item": {"POKE_BALL": 5}}}

with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    Path("run").mkdir()
    def world(moved=False, shelves=True):
        Path("run/explored.json").write_text(json.dumps({
            "explored": {"VERMILION_CITY|18,0": {}},
            "shelves": ({"VERMILION_MART": ["POKE_BALL", "SUPER_POTION",
                                            "REPEL"]} if shelves else {}),
            "shelf_reads": {"VERMILION_MART": {"n": 3, "moved": moved}}}))
    world()
    p = A.validate(plan(GO, BUY))
    ck("a buy at a counter that does not sell it is refused", bool(p), p)
    ck("...naming the counter and what it does sell",
       p and "VERMILION_MART" in p[0] and "SUPER_POTION" in p[0], p)
    ck("...and claiming nothing about where the item is",
       p and "Nothing here says where FRESH_WATER IS" in p[0], p)
    ck("something the counter DOES sell is fine", not A.validate(plan(GO, OK)))
    ck("a buy with no shop step before it is not second-guessed",
       not A.validate(plan(BUY)))
    world(moved=True)
    ck("a shelf that has come back different is exempt",
       not A.validate(plan(GO, BUY)))
    world(shelves=False)
    ck("a counter the run never stood at says nothing",
       not A.validate(plan(GO, BUY)))
    ck("the reader returns the run's own play, nothing more",
       A.walked_shelves() == {})

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:220])
sys.exit(1 if bad else 0)

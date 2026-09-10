"""How a sealed part of a floor is entered has THREE answers, not two.

"THIS FLOOR IS NOT FINISHED" is the only sentence on the page that asks
how ground no walk reaches is got onto, and it offered two answers: more
walking here, or a doorway somewhere else.  A hole is neither.  The
Pokemon Mansion's three holes are the ONLY way into 1F's sealed
basement-stairs room; they were on the page a screen further down, under
a heading that reads as recall, and run 16 spent twelve rounds of
descend_to_mansion_b1f on statues, stairs and warps without once
stepping on one (2026-09-10).

WHERE a hole lands stays unsaid.  The shim reads the destination out of
the engine's own table and drops it on purpose -- "unwalked ground is not
ours to name, and the same is true of every untried door" -- and this
does not touch that.  It names a KIND of way in, not a way into this
room, and whether any of them helps is the model's.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

MANSION = {
    "POKEMON_MANSION_1F|1,1": {"5,10": {"to": "POKEMON_MANSION_2F|6,1", "n": 4}},
    "POKEMON_MANSION_2F|6,1": {"7,10": {"to": "POKEMON_MANSION_3F|5,8", "n": 2},
                               "5,10": {"to": "POKEMON_MANSION_1F|1,1", "n": 4}},
    "POKEMON_MANSION_3F|5,8": {"7,10": {"to": "POKEMON_MANSION_2F|6,1", "n": 2}},
}
OBS = {"mode": "overworld", "player": {"x": 5, "y": 11}, "party": [],
       "map": {"id": "POKEMON_MANSION_1F", "region": "1,1", "objects": [],
               "connections": {},
               "warps": [{"x": 5, "y": 10}, {"x": 5, "y": 27},
                         {"x": 21, "y": 23}, {"x": 26, "y": 27}]}}


def page(holes):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = dict(MANSION)
    ex.map_holes = dict(holes)
    for _ in range(300):
        try:
            return ex.exploration_text(OBS)
        except AttributeError as e:
            setattr(ex, str(e).split("'")[-2], {})
    raise AssertionError("exploration_text never settled")


def note(txt):
    return next((ln for ln in txt.splitlines()
                 if "THIS FLOOR IS NOT FINISHED" in ln), "")


# ---- a walked floor of this building has holes --------------------------
t = page({"POKEMON_MANSION_3F": ["16,14", "17,14", "19,14"]})
n = note(t)

ck("the sealed-floor sentence still asks the question",
   "How to get there is not known" in n)
ck("...and a hole is now one of the answers",
   "A HOLE IS A THIRD WAY" in n)
ck("...naming the floor it was seen on and how many",
   "POKEMON_MANSION_3F has 3 hole(s)" in n)
ck("...and that the run has walked that floor", "you have walked it" in n)
ck("it says a hole is in no doorway list", "IN NO DOORWAY LIST" in n)
ck("it says stepping on one drops you through",
   "drops you through to the floor below" in n)
ck("it does NOT say where a hole lands",
   "16,14" not in n and "lands on" not in n and "sealed" not in n.lower())
ck("...and does not say this is the way in",
   "is not known" in n.split("A HOLE IS A THIRD WAY")[1])

# ---- nothing to say when no walked floor here has one -------------------
ck("no holes anywhere, no sentence", "A HOLE IS A THIRD WAY" not in note(page({})))

ck("a hole on THIS floor is not a way INTO this floor",
   "A HOLE IS A THIRD WAY" not in
   note(page({"POKEMON_MANSION_1F": ["16,14"]})))

ck("a hole in another building says nothing here",
   "A HOLE IS A THIRD WAY" not in
   note(page({"SEAFOAM_ISLANDS_1F": ["17,6"]})))

# a floor of this building whose holes were seen but never walked in
ex = E.Executor.__new__(E.Executor)
ex.explored = {k: v for k, v in MANSION.items()
               if not k.startswith("POKEMON_MANSION_3F")}
ex.map_holes = {"POKEMON_MANSION_3F": ["16,14"]}
for _ in range(300):
    try:
        t2 = ex.exploration_text(OBS)
        break
    except AttributeError as e:
        setattr(ex, str(e).split("'")[-2], {})
ck("a floor never walked in is not offered as walked",
   "A HOLE IS A THIRD WAY" not in note(t2))

bad = [n2 for n2, ok in checks if not ok]
for n2, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n2)
if bad:
    print("\nNOTE:", n[:900])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

#!/usr/bin/env python3
"""Two things a sweep in the grass could not know, and both were ours.

Run 17 worked out for itself that Charmeleon and Nidorino lose to Misty
and that a GRASS or ELECTRIC type would answer her. It walked to Route 25,
which is grass. Then it swept the map pressing signs (user, 2026-09-13:
"it should know it can try to grind with the intent to catch for this").

Nothing was wrong with its reasoning and nothing was missing from the op
vocabulary: {"op":"grind"} with "intent":"catch" and "want":"GRASS" is
documented, in those words. What the PAGE never said was that the ground
it stood on produces wild Pokemon at all — the note that lists wild ground
skips here_map by design, so the one floor never described is the one
underfoot — and, worse, that under a BADGE goal a wild met there is FLED.
That default follows the step's condition, the run cannot observe it, and
it would otherwise be learned by losing an encounter to it.

Both facts are about the harness, not the game. What lives in the grass,
and whether any of it is worth a ball, stays the model's.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                       # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))


def note(seen, done_when, here="ROUTE_25"):
    ex = E.Executor.__new__(E.Executor)
    ex._wild_seen = seen
    ex._cur_sg = {"done_when": done_when}
    return ex._wild_here_note(here, {})


GRASS = {"ROUTE_25": {"grass": 48, "cave": 0}}
n = note(GRASS, {"badge": "CASCADEBADGE"})
ck("standing in grass is said, with the run's own count",
   "WILD GROUND YOU ARE STANDING ON" in n and "48 cell(s) of tall grass" in n)
ck("...and that walking is what produces an encounter",
   "from WALKING on it and never from standing still" in n)
ck("under a badge goal, the default is FLEE and it says so",
   "it is FLED" in n and "nothing is thrown and nothing is fought" in n)
ck("...and names the op that changes it",
   '{"op":"grind"}' in n and '"intent"' in n and '"want"' in n)
ck("...without telling it to catch anything",
   "yours to judge" in n
   and not any(w in n.lower() for w in ("you should", "you need to catch",
                                        "go and catch")))

ck("under a catch goal the default is a ball, and says which",
   "a ball is thrown at what this step is looking for"
   in note(GRASS, {"has_species": "ODDISH"}))
ck("under a level goal the default is a fight",
   "it is FOUGHT" in note(GRASS, {"party_min_level": 20}))

CAVE = {"MT_MOON_1F": {"grass": 0, "cave": 90}}
ck("a cave floor is wild ground too, and is named as such",
   "90 cell(s) of cave floor" in note(CAVE, {"badge": "X"}, "MT_MOON_1F"))
BOTH = {"ROUTE_25": {"grass": 10, "cave": 4}}
ck("both kinds read as one sentence",
   "10 cell(s) of tall grass and 4 cell(s) of cave floor"
   in note(BOTH, {"badge": "X"}))

ck("a map with no wild ground says nothing at all",
   note({}, {"badge": "X"}, "CERULEAN_CITY") == "")
ck("...and neither does one whose count is zero",
   note({"CERULEAN_CITY": {"grass": 0, "cave": 0}}, {"badge": "X"},
        "CERULEAN_CITY") == "")

# it must never cost a page
ex = E.Executor.__new__(E.Executor)
ck("a broken record is silent, not fatal", ex._wild_here_note("X", {}) == "")

SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the note rides the page beside its elsewhere sibling",
   "+ self._wild_here_note(here_map, obs)" in SRC)
ck("...which still skips here_map, which is why this exists",
   "if _m == here_map or not isinstance(_c, dict):" in SRC)
ck("the vocabulary that was never the problem is untouched",
   '"intent":"catch" with "want":"ODDISH"' in E.Executor.MACRO_AUTHOR_SYS)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

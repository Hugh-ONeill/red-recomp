#!/usr/bin/env python3
"""A refusal the run has since walked through is not the last word.

The row for Cinnabar's gym door read "-> CINNABAR_GYM|16,7 — the door you
came in by; taken 1x" and then, in the same sentence, "trying it said:
'The door is locked...' — FAILED — you reached the door and it refused to
open ... walking somewhere else and coming back will not change the
answer".  The run had disproved that clause an hour earlier by doing
exactly that.  It read its own page and went back to the fossil scientist
to unlock a gym it had already been inside (2026-09-10, user: "and now it
thinks the door is locked still oof").

Two records fed it.  The outcomes book keeps the last outcome written for
a tile, and the op that SATISFIES a subgoal ends the subgoal before its
outcome is written, so the last thing on file stayed the failure.  The
quoted words came from the hint ledger, which has no idea the door later
opened.

The words are kept, because a door can shut again and what it said is the
run's own record.  They move to the past tense, where the destination and
the count already are.  The stale VERDICT goes.  Synthetic: no game.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger                                          # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HERE = "CINNABAR_ISLAND|10,0"
KEY = "18,3"
SAID = "The door is locked..."
FAILED = ('FAILED — you reached the door and it refused to open — the game '
          'said: "The door is locked...". You stood on the mat; walking '
          'somewhere else and coming back will not change the answer.')


class _Ex:
    frontier = {}
    _inert_objs = {}
    def __init__(self, walked):
        self._walked = walked
        self.explored = {HERE: {}}
        self.visits = {HERE: 9}
        self.hints = {HERE: [f"use_warp ({KEY}): {SAID}"]}
        self.hints_at = {}
    def _where(self, _o): return HERE
    def _taken_here(self, h): return {KEY: {"n": 1, "to": "CINNABAR_GYM|16,7"}} if self._walked else {}
    def _spent_exits(self, h): return {}
    def _sealed(self, h): return set()
    def _untaken(self, m, t): return set()
    def _worth_another_word(self, h, o, backfill=True): return []
    def _door_groups(self, w): return {}
    def _frontage(self, d): return ""
    def _seen_cells_words(self, h): return ""
    def _walked_dest(self, mid, key):
        return "CINNABAR_GYM|16,7" if (self._walked and key == KEY) else None
    def _snapshot_anywhere(self, o): return None
    def _frontier_left(self, r): return set()
    def dead_for(self, t, r): return 0
    def __getattr__(self, _n): return {}


OBS = {"party": [], "mode": "overworld", "player": {"x": 18, "y": 4},
       "map": {"id": "CINNABAR_ISLAND", "region": "10,0", "objects": [],
               "connections": {},
               "warps": [{"x": 18, "y": 3, "reachable": True}]}}


def row(walked):
    ex = _Ex(walked)
    ex._outcomes = {KEY: {"n": 1, "last": FAILED}}
    cands = ledger.build(ex, OBS)
    for c in cands:
        if c.key == KEY:
            c.spoke = SAID
            if walked:
                c.dest = "CINNABAR_GYM|16,7"
    return next(ln for ln in ledger.render(cands, ex, OBS).splitlines()
                if KEY in ln and "->" in ln)


shut, opened = row(False), row(True)

# ---- before it ever opened, the refusal stands as it is ----------------
ck("a door that refused still quotes it plainly",
   'trying it said: "The door is locked' in shut, shut[:200])
ck("...and does not talk about getting through",
   "before you got through" not in shut)

# ---- once walked, the same words are put in the past -------------------
ck("a door walked through says the refusal came first",
   'before you got through, trying it said: "The door is locked' in opened,
   opened[:260])
ck("...and keeps the words rather than hiding them", SAID in opened)
ck("...and still names where it goes", "CINNABAR_GYM|16,7" in opened)
ck("the clause the run disproved is gone",
   "will not change the answer" not in opened, opened[:400])
ck("...and so is the stale FAILED verdict",
   "refused to open" not in opened, opened[:400])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:200] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

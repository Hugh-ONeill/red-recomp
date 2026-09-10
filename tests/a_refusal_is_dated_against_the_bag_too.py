#!/usr/bin/env python3
"""A locked door's refusal is dated in events, and a key fires none.

This game explains itself when it refuses, and the harness keeps what was
said with a stamp so the row can add "said before N event(s) that have
fired since".  The stamp was a flag count and nothing else.  Picking up a
key item fires no flag, so the one change that most obviously lifts a
locked door could not move it.

Cinnabar's gym door said "The door is locked..." at 12:33.  The run held
the SECRET KEY by 16:50 and never went back to try it, planning instead to
re-explore the Mansion "as the Gym's unlock condition is likely tied to
the Mansion's completion" (2026-09-10, user: "wait a sec did it try the
lock? because it has the key now").

WHICH key items are new is a fact about the bag, not a claim that any of
them opens anything.  The row goes on saying "nothing named yet as what
lifts it".  Synthetic: no game, no model.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

REG = "CINNABAR_ISLAND|10,0"
LINE = 'use_warp (18,3): The door is locked...'


SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the dating method is where the test expects it",
   "def _dated(self, region: str, line: str, obs) -> str:" in SRC)


def dated(stamp, flags, keys):
    ex = E.Executor.__new__(E.Executor)
    ex.hints_at = {REG: {LINE: stamp}}
    ex._gone = {}
    return ex._dated(REG, LINE,
                     {"flags": ["f"] * flags, "key_items": list(keys)})


OLD = {"flags": 6, "keys": ["BICYCLE", "CARD_KEY"]}

# ---- the bag moved and the flags did not --------------------------------
out = dated(OLD, 6, ["BICYCLE", "CARD_KEY", "SECRET_KEY"])
ck("a key picked up since dates the refusal", "you picked up SECRET_KEY" in out, out)
ck("...and no event is invented", "event(s)" not in out, out)
ck("...and the refusal itself is kept whole", LINE in out)

# ---- events still count, as before --------------------------------------
out2 = dated(OLD, 9, ["BICYCLE", "CARD_KEY"])
ck("events fired since still date it", "3 event(s) that have fired since" in out2)
ck("...without claiming a pickup", "picked up" not in out2)

# ---- both ---------------------------------------------------------------
out3 = dated(OLD, 9, ["BICYCLE", "CARD_KEY", "SECRET_KEY"])
ck("both are said, in one clause",
   "3 event(s)" in out3 and "you picked up SECRET_KEY" in out3
   and out3.count("said before") == 1, out3)

# ---- nothing has moved --------------------------------------------------
out4 = dated(OLD, 6, ["BICYCLE", "CARD_KEY"])
ck("a world that has not moved says nothing extra", out4 == LINE, out4)

# ---- an item LOST is not a change worth claiming ------------------------
out5 = dated(OLD, 6, ["BICYCLE"])
ck("dropping a key item does not date the refusal", out5 == LINE, out5)

# ---- stamps written before this rule are bare counts --------------------
out6 = dated(6, 9, ["BICYCLE", "CARD_KEY", "SECRET_KEY"])
ck("an old stamp still dates by events", "3 event(s)" in out6)
ck("...and claims nothing about a bag it never recorded",
   "picked up" not in out6, out6)

# ---- and the stamp being written now carries both -----------------------
blk = SRC.split("self.hints_at.setdefault(reg, {})[line]", 1)[1][:400]
ck("the stamp records the flags", '"flags"' in blk)
ck("...and the key items", '"keys"' in blk and 'key_items' in blk)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:120] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

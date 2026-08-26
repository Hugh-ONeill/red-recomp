"""The bag is on every page, and events reach has_item goals (2026-08-26).

The bag reached the prompt only when a round changed NOTHING (_stale_rounds)
or after two blackouts, so a run that is BUSY was never told what it holds.
The staleness gate's own comment already describes this bug in its earlier
form: "Route 12's leg is literally named for the POKE FLUTE, the flute was in
the bag, and across eleven escalations the word POKE_FLUTE did not appear in
the prompt once."

It happened again while moving. Chasing has_item SECRET_KEY the run wrote "To
get the Secret Key, I must first find the Warden's Gold Teeth" and planned an
expedition across the Safari Zone — for teeth it had already handed over. The
trade is in the ledger twice: the op's own delta
[GOLD_TEETH -1 (now 0); HM_STRENGTH +1 (now 1)] and EVENT_GAVE_GOLD_TEETH
fired in WARDENS_HOUSE|0,1. Neither reached the page: the bag was gated on
staleness, and the fired-events block was gated on the goal naming a FLAG."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

# --- the bag, unconditionally ---
i = src.find("WHAT YOU ARE CARRYING, ON EVERY PAGE")
ck("the bag is on the general page", i > 0)
blk = src[i:i + 1900]
ck("...beside the storage line, not inside a stuck note",
   "_rs_line = (" in blk and "_bagall = (obs or {}).get(\"bag\")" in blk)
ck("...only gated on the bag existing", "if _bagall:" in blk)
ck("...naming the count against the cap", "self.BAG_SLOTS" in blk)
ck("...and the op that uses one", "use_item" in blk)
ck("it judges nothing", "yours to read" in blk)

ck("the staleness-gated copy no longer fires",
   "NOW SUBSUMED" in src and "if False:" in src)
ck("the wipe note keeps the WALLET",
   "the wipe note keeps" in src and 'stuck_note += f"\\nMONEY: {_money}."' in src)
ck("...and no longer repeats the bag",
   src.count('stuck_note += ("\\nWHAT YOU ARE CARRYING: ') == 1)

# --- fired events reach has_item goals ---
j = src.find("A has_item GOAL IS WAITING ON EVENTS TOO")
ck("the fired-events gate is widened", j > 0)
fblk = src[j:j + 1400]
ck("...to has_item as well as flag",
   '"flag" not in _pk and "has_item" not in _pk' in fblk)
ck("...and no further: other goal kinds still get nothing",
   "_pk = pred_keys(sg.get(\"done_when\") or {})" in fblk)
ck("the live-flags authority check is untouched",
   'live = set((obs or {}).get("flags") or [])' in src
   and "if f in live]" in src)

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

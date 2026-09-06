"""Two objectives that share nothing but a place are two objectives.

The dedupe's rule is two names in common (its docstring says why one is
too few).  Across the five outlines drawn on 2026-09-06 that rule ate
"Retrieve the HM04 from the Safari Zone" as a repeat of "Navigate the
Safari Zone" in two passes -- STRENGTH gone from the outline before play,
on {safari, zone} -- and "Obtain the Master Ball from Silph Co." as a
repeat of "Clear the Silph Co. building", and "Retrieve the HM01 from the
S.S. Anne" as a repeat of "Explore the S.S. Anne" (planner/outline_trends.py
tallied them).  A fetch inside a place and the visit to the place share the
place's name and nothing else.

The place words come from the game's own map list (engine_maps.txt); the
Town Map labels them.  Same rule in the dedupe and in the era checklist's
repeat guard, from one function.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import author as A

ck("the map list is loaded", len(A.ENGINE_MAPS) >= 200)
pw = A._place_words()
ck("safari, zone, tunnel, tower, anne are place words",
   {"safari", "zone", "tunnel", "tower", "anne"} <= pw)
ck("ticket, flute, key are not (bill is: Bill's house is a map)",
   not ({"ticket", "flute", "key"} & pw) and "bill" in pw)

def same(a, b):
    return A._same_objective(A._objective_key(a), A._objective_key(b))

ck("the HM04 fetch is not the Safari visit",
   not same("Retrieve the HM04 from the Safari Zone", "Navigate the Safari Zone"))
ck("the Master Ball is not the Silph clear",
   not same("Obtain the Master Ball from Silph Co.", "Clear the Silph Co. building"))
ck("HM01 is not a tour of the ship",
   not same("Retrieve the HM01 from the S.S. Anne", "Explore the S.S. Anne"))
ck("the Gold Teeth are not the Safari visit",
   not same("Obtain the Gold Teeth from the Safari Zone", "Navigate the Safari Zone"))
ck("two tickets from Bill are still one thing",
   same("Retrieve the S.S. Ticket from Bill", "Obtain the S.S. Ticket from Bill"))
ck("two SURF fetches from the Safari Zone are still one thing",
   same("Retrieve the HM03 from the Safari Zone", "Obtain the SURF HM from the Safari Zone"))
ck("the same names outright are still the same",
   same("a party Pokemon knows HM01", "a party Pokemon knows CUT"))
ck("Giovanni's two fights are still two", not same(
    "Defeat Giovanni in the Rocket Hideout", "Defeat Giovanni for the Earth Badge"))

A.OUTLINE_NOTES.clear()
kept = A._dedupe_outline(["Reach Fuchsia City", "Navigate the Safari Zone",
                          "Retrieve the HM04 from the Safari Zone",
                          "Obtain the Gold Teeth from the Safari Zone",
                          "Retrieve the S.S. Ticket from Bill",
                          "Obtain the S.S. Ticket from Bill"])
ck("the dedupe keeps STRENGTH and the teeth beside the Safari visit",
   "Retrieve the HM04 from the Safari Zone" in kept
   and "Obtain the Gold Teeth from the Safari Zone" in kept)
ck("...and still folds the two tickets", len(kept) == 5)

src = Path("planner/author.py").read_text()
ck("the era repeat guard uses the same rule",
   "if k and any(_same_objective(k, s) for s in seen):" in src)
ck("the era prose is written to the log",
   'print(f"[era:{era}]   {_ln.rstrip()}", file=sys.stderr)' in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

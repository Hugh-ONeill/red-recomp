#!/usr/bin/env python3
"""A prerequisite that names only what the leg names, for the same kind of
deed, is the leg said shorter.

Run 16, 2026-09-07: after "Defeat Lt. Surge for the Thunder Badge" failed an
attempt, the missing rung answered "Battle Lt. Surge", and the insert guard
let it through at similarity 0.62 — a shorter sentence about the same
person with the verb swapped. The chain then authored and ran the same leg
twice under two names. The names in a sentence (its capitalised words, minus
the opening verb) are what it is about: when the proposal's names are all in
the leg's line AND its verb is of the same kind, it restates the leg. A
different deed on the same name — "Catch a SPEAROW" before "Trade the
SPEAROW" — is a real prerequisite and still passes.
"""
import subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import insert_guard as G   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ol = Path(tempfile.mkdtemp()) / "outline.txt"
ol.write_text("Defeat Lt. Surge for the Thunder Badge\nTravel through Rock Tunnel\n")
def guard(prop, leg):
    r = subprocess.run([sys.executable, str(ROOT / "planner" / "insert_guard.py"), prop, leg, str(ol)],
                       capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode, r.stdout.strip()
rc, out = guard("Battle Lt. Surge", "Defeat Lt. Surge for the Thunder Badge")
ck("'Battle Lt. Surge' before 'Defeat Lt. Surge ...' is refused", rc == 3 and "names only what" in out, out)
rc, out = guard("Fight Brock", "Defeat Brock for the Boulder Badge")
ck("...and so is 'Fight Brock' before 'Defeat Brock'", rc == 3, out)
rc, out = guard("Catch a SPEAROW", "Trade the SPEAROW for a FARFETCH'D at the Vermilion City trade house")
ck("a different deed on the same name passes (catch before trade)", rc == 0, out)
rc, out = guard("Reach Vermilion Gym", "Defeat Lt. Surge for the Thunder Badge")
ck("a step with names of its own passes", rc == 0, out)
ck("the names are the capitalised words minus the opening verb",
   G._names("Battle Lt. Surge") == {"lt", "surge"} and G._names("Catch a SPEAROW") == {"spearow"}
   and G._names("a party Pokemon knows CUT") == {"cut"})   # a move name is a name
ck("verbs of one kind are one deed", G._same_deed("Battle X", "Defeat X") and not G._same_deed("Catch X", "Trade X"))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)

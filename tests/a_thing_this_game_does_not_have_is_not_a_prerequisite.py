#!/usr/bin/env python3
"""A prerequisite about a thing this game does not define is refused, at the
rung and at the outline's door.

Run 16, 2026-09-07: after Erika's first attempt, the missing rung answered
"Obtain the Tea from the Celadon Mansion" with the reason "In FireRed/
LeafGreen, the player must first obtain the Tea ...". The Tea is another
game's item; in Red the Saffron guards want a drink from the roof vending
machine, and neither has anything to do with Erika. The insert guard scored
it novel and the chain inserted it, then authored it. Two gates now: the
rung turns down a fetch whose object is not an item, Pokemon, machine,
badge or place of this game (fuzzy on the engine's ids, so "S.S. Ticket"
and "Poke Flute" pass), and the hedge regex reads "In FireRed/LeafGreen"
as the inference it is. The insert guard applies the same object check.
"""
import subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the Tea is not a thing this game has", A._thing_unknown("Obtain the Tea from the Celadon Mansion") == "TEA")
ck("...nor the Rainbow Pass", A._thing_unknown("Obtain the Rainbow Pass") == "RAINBOW_PASS")
for t in ("Retrieve the S.S. Ticket from Bill", "Obtain the Poke Flute from Mr. Fuji", "Buy a Water Stone at the Celadon Department Store",
          "Catch a SPEAROW", "Obtain the Gold Teeth", "Retrieve the HM03 from the Secret House",
          "Give a FRESH WATER from the Celadon Department Store roof to the thirsty guard", "Catch a WATER type"):
    ck(f"a real thing passes: {t[:45]}", A._thing_unknown(t) is None, A._thing_unknown(t))
ck("a non-fetch sentence is not judged", A._thing_unknown("Defeat Erika for the Rainbow Badge") is None)
ck("another game's rule is an inference",
   A._inferred("In FireRed/LeafGreen, the player must first obtain the Tea from the Celadon Mansion")
   and A._inferred("in Gold and Silver the gym is elsewhere") and not A._inferred("the old lady said she has no tea"))
src = (ROOT / "planner" / "author.py").read_text()
ck("the missing rung turns such a proposal down and quotes it back",
   "_unknown = _thing_unknown(ins)" in src and "is not an item, Pokemon, machine, " in src)
ol = Path(tempfile.mkdtemp()) / "outline.txt"; ol.write_text("Defeat Erika for the Rainbow Badge\n")
r = subprocess.run([sys.executable, str(ROOT / "planner" / "insert_guard.py"), "Obtain the Tea from the Celadon Mansion",
                    "Defeat Erika for the Rainbow Badge", str(ol)], capture_output=True, text=True, cwd=str(ROOT))
ck("the insert guard refuses it at the outline's door", r.returncode == 3 and "names TEA" in r.stdout, r.stdout + r.stderr)
r2 = subprocess.run([sys.executable, str(ROOT / "planner" / "insert_guard.py"), "Buy a FRESH WATER from the roof vending machine",
                     "Defeat Erika for the Rainbow Badge", str(ol)], capture_output=True, text=True, cwd=str(ROOT))
ck("...and lets a real fetch through", r2.returncode == 0, r2.stdout + r2.stderr)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)

#!/usr/bin/env python3
"""A lift door looks like one (2026-09-04).

The page said "door (24,19) -> UNKNOWN — never taken from here" for the
Hideout B2F lift while the run's step was "use the elevator", and it took the
stairs beside it to hunt an elevator on another floor. The tile drawn on a warp
into an *_ELEVATOR map is the lift-door graphic, distinct on screen from a
stair or a doorway, so the shim now calls its look "lift" and the page says
"lift door". Where the lift goes stays unknown until it is ridden.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

c = L.Candidate.__new__(L.Candidate)
c.kind = "door"; c.key = "24,19"; c.look = "lift"; c.twins = ["25,19"]
try:
    lab = c.label() if hasattr(c, "label") else None
except Exception as ex:
    lab = f"RAISED {ex!r}"
if lab is None:
    # find the method that renders the key words
    for name in dir(c):
        if name.startswith("_") or name in ("kind", "key", "look", "twins"):
            continue
        try:
            v = getattr(c, name)
            if callable(v):
                out = v()
                if isinstance(out, str) and "24,19" in out:
                    lab = out; break
        except Exception:
            continue
ck("a warp whose look is lift renders as a lift door", isinstance(lab, str) and lab.startswith("lift door (24,19)"), lab)
ck("...as one door two tiles wide", isinstance(lab, str) and "(25,19) is" in lab and "the SAME door" in lab, lab)
lua = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim marks the look from the tile drawn on an elevator warp",
   'if _look == "door" and type(dest) == "string"\n             and dest:match("_ELEVATOR$") then\n            _look = "lift"' in lua)
src = (ROOT / "planner" / "ledger.py").read_text()
ck("...and the page has a word for it", 'if _l == "lift":\n                return f"lift door ({self.key}){_tw}"' in src)
ck("the destination is not said by the look", "ELEVATOR" not in (lab or ""))
bad = [x for x in checks if not x[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)

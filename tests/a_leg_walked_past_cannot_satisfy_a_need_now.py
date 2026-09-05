#!/usr/bin/env python3
"""A leg already walked past cannot satisfy a need now (2026-09-05).

"Clear space in the bag" was inserted at 27, counted without ever being
confirmed, and walked past. Ten legs later the bag was full again in the Safari
Zone — the blocker rung said so and the missing rung asked for the step three
times — and every one was refused as "already on your own list", pointing at
that dead leg. Some needs recur: a bag slot, money, a heal. A line behind the
run is history, not a plan, so the guard now compares against the leg the
insertion would precede and everything still AHEAD of it.

Synthetic: an outline and a progress index in a temp dir, no model."""
import os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
LINES = ["Reach Cerulean City", "Clear space in the bag", "Reach Celadon City",
         "Reach the Secret House in the Safari Zone", "Defeat Koga for the Soul Badge"]
def guard(proposed, leg, done):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d); (d / "run").mkdir(); (d / "plans").mkdir()
        (d / "plans/outline.txt").write_text("\n".join(LINES) + "\n")
        (d / "run/outline_leg").write_text(str(done))
        cwd = os.getcwd()
        try:
            os.chdir(d)
            r = subprocess.run([sys.executable, str(ROOT / "planner" / "insert_guard.py"),
                                proposed, leg, "plans/outline.txt"], capture_output=True, text=True)
            return r.returncode, r.stdout.strip()
        finally:
            os.chdir(cwd)
rc, out = guard("Clear space in the bag", LINES[3], done=3)
ck("a recurring need behind the run is allowed again", rc == 0, out)
rc, out = guard("Clear space in the bag", LINES[3], done=1)
ck("...but while it is still ahead it is a duplicate", rc == 3 and "still ahead of you" in out, out)
rc, out = guard("Defeat Koga for the Soul Badge", LINES[3], done=3)
ck("a leg still ahead is refused", rc == 3, out)
rc, out = guard("Enter the Secret House of the Safari Zone", LINES[3], done=3)
ck("restating the leg it would precede is still refused", rc == 3, out)
rc, out = guard("Teach SURF to a party member", LINES[3], done=3)
ck("a genuinely new step is allowed", rc == 0, out)
rc, out = guard("Clear space in the bag", LINES[3], done=0)
ck("with no progress recorded, nothing is treated as behind", rc == 3, out)
src = (ROOT / "planner" / "insert_guard.py").read_text()
ck("the boundary is the run's own progress index", 'Path("run/outline_leg").read_text()' in src and "ahead = lines[max(0, _done):]" in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)

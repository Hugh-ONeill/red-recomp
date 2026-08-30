"""The unconfirmed list was written and never read.

A leg whose SECOND plan also ends with check-done saying NOT DONE is counted
and walked past. That escape is deliberate — a run cannot stop for ever on
one objective — and the chain writes each such leg to run/leg_unconfirmed
"so that 'known-bad in the world' is a list and not a memory". Nothing in the
planner ever opened that file.

So "Clear Rock Tunnel" went into the page as plainly finished:

    THE OBJECTIVES YOU HAVE ALREADY FINISHED, in the order you finished
    them: ...; Clear Rock Tunnel.

and the model planned around a tunnel it believed it had come out the far
side of, hunting the Poke Flute in Vermilion and Cerulean for an hour (user,
2026-08-30: "its still trying the same things over and over instead of going
through the rock tunnel"). The escape may walk PAST a leg. It may not tell
the model the leg is DONE.

Marked, not hidden: whether it is worth going back for is the model's, and
the honest reason it was counted is that the chain could not tell either way.
"""
import sys, os, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the chain still records what it could not confirm",
   "printf '%s\\n' \"$leg\" >> run/leg_unconfirmed" in sh)

cwd = os.getcwd()
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    Path("plans").mkdir(); Path("run").mkdir()
    Path("plans/outline.txt").write_text(
        "Reach Pewter City\nClear Rock Tunnel\nReach Lavender Town\n"
        "Cleanse the Pokemon Tower\nReach Celadon City\n")
    Path("run/outline_leg").write_text("2")
    t = A.outline_so_far()
    ck("with no list, the sentence is as it was",
       "Clear Rock Tunnel" in t and "COUNTED BUT NEVER CONFIRMED" not in t, t)
    Path("run/leg_unconfirmed").write_text("Clear Rock Tunnel\n")
    t = A.outline_so_far()
    ck("a counted leg is marked in the finished list",
       "Clear Rock Tunnel (COUNTED BUT NEVER CONFIRMED" in t, t)
    ck("...saying what actually happened to it",
       "its plans ran and the deed could not be seen afterwards" in t, t)
    ck("...and leaving the choice",
       "treat it as open if what you are doing needs it" in t, t)
    ck("a confirmed leg beside it is untouched",
       "Reach Pewter City" in t
       and "Reach Pewter City (COUNTED" not in t, t)
    # the list of what comes next starts AFTER the current leg, which is
    # legs[n] — "Reach Lavender Town" here — so it begins one past it
    ck("the legs still ahead are unaffected",
       "WHAT YOU PLANNED TO DO AFTER THIS ONE" in t
       and "Cleanse the Pokemon Tower" in t
       and "COUNTED" not in t.split("AFTER THIS ONE")[1], t)
os.chdir(cwd)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:240])
sys.exit(1 if bad else 0)

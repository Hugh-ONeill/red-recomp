"""A leg you struck out is not a leg you did (2026-09-02).

A VOID leaves the objective sitting in the outline and steps past it, so it
reaches THE OBJECTIVES YOU HAVE ALREADY FINISHED in exactly the words a walked
leg does. The model then read its own struck-out "Reach Celadon City via the
Underground Path" back as an achievement and voided the live "Reach Celadon
City" for being redundant with it — cancelling both ways into the city, with
the run having never once stood in Celadon and the Fresh Water it needs sold
only there.

The reason it gave when it struck the first one out was sitting in
run/outline_void the whole time and this sentence never read it. Handing its
own words back is enough: a leg it dismissed can no longer come back as
evidence for the thing it dismissed.

Struck out beats counted-but-unconfirmed when a leg is somehow both. They say
different things — one is "we could not tell whether you did it", the other is
"you said it was never a thing to do" — and the second is the stronger claim."""
import sys, tempfile, os
from pathlib import Path
sys.path.insert(0, "planner")
import author

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

LEGS = ["Reach Cerulean City",
        "Reach Celadon City via the Underground Path",
        "Clear Rock Tunnel",
        "Reach Vermilion City"]
WHY = ("The Underground Path connects Route 5 and Route 6, but it does not "
       "lead to Celadon City")


def sentence(void=(), unconf=(), n=4):
    d = Path(tempfile.mkdtemp())
    (d / "run").mkdir(); (d / "plans").mkdir()
    (d / "plans/outline.txt").write_text("\n".join(LEGS) + "\n")
    (d / "run/outline_leg").write_text(str(n))
    (d / "run/outline_void").write_text(
        "".join(f"{t}\t{w}\n" for t, w in void))
    (d / "run/leg_unconfirmed").write_text("".join(f"{t}\n" for t in unconf))
    cwd = os.getcwd()
    try:
        os.chdir(d)
        return author.outline_so_far()
    finally:
        os.chdir(cwd)


plain = sentence()
ck("an ordinary finished leg is listed plainly",
   "Reach Cerulean City;" in plain or "Reach Cerulean City," in plain)
ck("...and carries no marking", "STRUCK OUT" not in plain)

struck = sentence(void=[("Reach Celadon City via the Underground Path", WHY)])
ck("a struck-out leg is marked as not done",
   "STRUCK OUT BY YOU, NOT DONE" in struck)
ck("...and says nothing was achieved by it",
   "nothing was achieved by it" in struck)
ck("...and hands back the reason the model itself gave", WHY in struck)
ck("...only to the leg it was recorded against",
   struck.count("STRUCK OUT") == 1)
ck("a leg that was never voided is untouched",
   "Reach Vermilion City (" not in struck)

unc = sentence(unconf=["Clear Rock Tunnel"])
ck("the unconfirmed marking still works",
   "COUNTED BUT NEVER CONFIRMED" in unc)

both = sentence(void=[("Clear Rock Tunnel", "not a real objective")],
                unconf=["Clear Rock Tunnel"])
ck("struck out wins over unconfirmed when a leg is both",
   "STRUCK OUT BY YOU" in both and "COUNTED BUT NEVER CONFIRMED" not in both)

none = sentence(void=[("Clear Rock Tunnel", "")])
ck("a void with no recorded reason still says it was struck out",
   "STRUCK OUT BY YOU, NOT DONE" in none and "your reason" not in none)

d = Path(tempfile.mkdtemp())
(d / "run").mkdir(); (d / "plans").mkdir()
(d / "plans/outline.txt").write_text("\n".join(LEGS) + "\n")
(d / "run/outline_leg").write_text("4")
cwd = os.getcwd(); os.chdir(d)
try:
    ck("no ledgers on disk is not an error",
       "Reach Cerulean City" in author.outline_so_far())
finally:
    os.chdir(cwd)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)

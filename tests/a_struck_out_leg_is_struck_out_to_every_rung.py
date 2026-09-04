#!/usr/bin/env python3
"""A leg the model struck out is struck out on every rung's list, not only
the plan-author's sentence (2026-09-04).

outline_so_far() has marked VOID legs "(STRUCK OUT BY YOU, NOT DONE ...)" since
2026-09-02. The missing, wording and later rungs list the same legs through
_leg_line — numbered, bare. So with objectives 26 and 27 (both Silph Scope
legs, both VOID) listed under OBJECTIVES YOU HAVE ALREADY FINISHED, the missing
rung proposed "Defeat the Team Rocket administrator" on "the player has the
Silph Scope (Objective 27)" three times, and the wording rung stood on "the
player has already obtained the Silph Scope (Objective 27)" — with no
SILPH_SCOPE in the bag. The bag check turned the proposals down; the premise
was the harness's. Now the marks ride the line wherever it is read.

Synthetic: a temp run/ directory, no game, no model."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

VOID_T = "Obtain the Silph Scope from Celadon City"
VOID_W = "The Silph Scope is obtained from Mr. Fuji in Lavender Town, not from Celadon City."
UNC_T = "Clear Rock Tunnel"
BOTH_T = "Reach Celadon City via the Underground Path"

d = Path(tempfile.mkdtemp())
(d / "run").mkdir()
(d / "run/outline_void").write_text(f"{VOID_T}\t{VOID_W}\n{BOTH_T}\tnot a way in\n")
(d / "run/leg_unconfirmed").write_text(f"{UNC_T}\n{BOTH_T}\n")
cwd = os.getcwd()
try:
    os.chdir(d)
    void_line = A._leg_line(27, VOID_T)
    unc_line = A._leg_line(21, UNC_T)
    both_line = A._leg_line(19, BOTH_T)
    plain = A._leg_line(24, "Reach Lavender Town")
    marks_missing_files = None
    os.chdir(cwd)
    e = Path(tempfile.mkdtemp()); os.chdir(e)
    marks_missing_files = A._leg_line(27, VOID_T)
finally:
    os.chdir(cwd)

ck("a struck-out leg says so on the rung's numbered line",
   void_line.startswith(f"  27. {VOID_T} (STRUCK OUT BY YOU, NOT DONE"), void_line)
ck("...with the model's own reason", VOID_W in void_line, void_line)
ck("a counted-but-unconfirmed leg says so", "COUNTED BUT NEVER CONFIRMED" in unc_line and "treat it as open" in unc_line, unc_line)
ck("struck out beats unconfirmed", "STRUCK OUT" in both_line and "NEVER CONFIRMED" not in both_line, both_line)
ck("a walked leg carries no mark", plain == "  24. Reach Lavender Town", plain)
ck("no ledgers on disk = no marks, no error", marks_missing_files == f"  27. {VOID_T}", marks_missing_files)

src = (ROOT / "planner" / "author.py").read_text()
ck("every rung list reads through _leg_line, which carries the marks",
   'return (f"  {n}. {t}" + _leg_marks(t)' in src)
ck("the plan-author's sentence uses the same marks", "_mark = [t + _leg_marks(t) for t in show]" in src)

bad = [c for c in checks if not c[1]]
for n, ok, dd in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(dd)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)

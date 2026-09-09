#!/usr/bin/env python3
"""A rewrite is not evidence for itself, and a wording taken back off an
objective is not put back.

Run 16, 2026-09-08: "Retrieve the Card Key inside Silph Co." was rewritten
to "Obtain the Card Key from the Team Rocket executive inside Silph Co." —
false in this game, where the key is a Poke Ball on 5F at (21,16). The
wording was restored by hand and the rewording row dropped with it; the rung
was asked again an hour later and put the executive straight back, its whole
stated reason being "a previous rewrite already established that the Card
Key is obtained from the Team Rocket executive". A rewrite is its own
earlier guess, not something the run proved. Now the prompt says so, and a
sentence recorded in run/outline_wordings_reverted is refused outright.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


ck("the prompt says a rewrite is not evidence for itself", "A REWRITE IS NOT EVIDENCE FOR ITSELF." in A.WORDING_SYS)
ck("...and that only what was walked, seen or told counts", "Only what the run WALKED, SAW, or was TOLD counts." in A.WORDING_SYS)
ck("...naming the reason that is never a reason", '"a previous rewrite already established it" is\nnever a reason' in A.WORDING_SYS)

cwd = os.getcwd()
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    try:
        Path("run").mkdir()
        ck("no file means nothing is refused", A._reverted_wordings() == set())
        Path("run/outline_wordings_reverted").write_text(
            "Obtain the Card Key from the Team Rocket executive inside Silph Co.\n")
        rev = A._reverted_wordings()
        ck("a recorded wording is read back", A._norm_obj(
            "Obtain the Card Key from the Team Rocket executive inside Silph Co.") in rev)
        ck("...and matched however it is spelled", A._norm_obj(
            "obtain the card key from the team rocket executive inside silph co.") in rev)
        ck("an unrelated wording is not in it", A._norm_obj("Retrieve the Card Key inside Silph Co.") not in rev)
    finally:
        os.chdir(cwd)

src = (ROOT / "planner" / "author.py").read_text()
ck("check_wording refuses a taken-back sentence", 'if _norm_obj(new) in _reverted_wordings():' in src)
ck("...saying it was taken back, and standing pat", "was tried on this objective and " in src and "TAKEN BACK" in src and src.count('a rewrite is not evidence for itself; the ') == 1)
ck("the refusal comes after the same-sentence check, so ordinary rewrites still work", src.index("_reverted_wordings()", src.index("def check_wording")) > src.index("that is the same sentence"))
sys.exit(1 if fails else 0)

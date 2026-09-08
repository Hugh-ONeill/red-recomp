#!/usr/bin/env python3
"""The plan author is told the legs after this one are their own.

Run 16, leg 32 "Defeat Koga for the Soul Badge" (2026-09-08, after the
outline put Koga ahead of the Safari HM legs): the author's page listed the
Gold Teeth, SURF and STRENGTH legs as "what you planned to do after this
one", and all three drafts opened with a Safari trip, the Warden and a
STRENGTH lesson before the gym — the picker's own reason was "the necessity
of Strength to navigate Koga's gym", a false fact. Ten older Koga drafts from
runs where Koga came after those legs are heal, gym, Koga. The list stays
(it places the leg in the arc); the rule now says what it is for, and the
one game fact the harness can vouch for — no gym needs a field move to reach
its leader — is on the page. User: "make that fix please".
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


ck("the system prompt scopes the plan to its own goal", "THIS PLAN IS FOR THIS GOAL." in A.SYS)
ck("...and names the one case a later leg is folded in", "fold one into this plan only when THIS goal cannot be reached\nwithout it" in A.SYS)
ck("...and says no gym needs a field move to reach its leader", "no gym in this game needs a field move\nto reach its leader" in A.SYS)
src = (ROOT / "planner" / "author.py").read_text()
ck("the after-this-one list says what it is for, where it is shown", "WHAT YOU PLANNED TO DO AFTER THIS ONE (their own legs, " in src and "not steps of this plan unless " in src)
sys.exit(1 if fails else 0)

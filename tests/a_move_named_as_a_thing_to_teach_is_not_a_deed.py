#!/usr/bin/env python3
"""A field move the plan names as a thing to TEACH is not a deed left undone.

Words are not ops: when a plan says "use CUT on the bush" and no field_move
ran, the round is told so. On the Fly leg every plan said "teach FLY to ..."
and every round was told "Your words named FLY and no FLY happened: nobody
flew" (run 16, 2026-09-08). A mention within a few words of teach, learn,
know, compatible, forget or the machine's own name is about the move as a
thing, not the deed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


ex = E.Executor.__new__(E.Executor)
ck("teaching FLY is not flying", ex._deeds_named_not_done([], "I will teach FLY to Eevee using HM_FLY from the bag.", []) == [])
ck("knowing FLY is not flying", ex._deeds_named_not_done([], "Nobody in the party knows FLY, so I must catch one that can learn it.", []) == [])
ck("being ABLE to learn FLY is not flying", ex._deeds_named_not_done([], "Charizard is not able to learn FLY.", []) == [])
r = ex._deeds_named_not_done([], "I will use FLY to return to Pallet Town.", [])
ck("flying somewhere with no fly op is still the deed left undone", r == [("FLY", False)], r)
r = ex._deeds_named_not_done([], "I will use CUT on the bush at (34,9) and walk north.", [])
ck("CUT on a bush with no field_move is still named", r == [("CUT", False)], r)
r = ex._deeds_named_not_done([], "Teach CUT to Gloom, then use CUT on the bush.", [])
ck("one mention as a thing and one as a deed: the deed counts", r == [("CUT", False)], r)
sys.exit(1 if fails else 0)

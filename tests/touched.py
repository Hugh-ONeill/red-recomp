#!/usr/bin/env python3
"""A touch is recorded ONLY for an interaction that completed.

WHY THIS LEDGER AND NOT ANOTHER. `_tried_objs` is monotone and every
consumer trusts it without question — the untouched list, the fully-worked
proof, the escort's ranking, the sweep's own "everything reachable here has
now been tried". Every other ledger in this harness can be wrong in a way
the run recovers from: a hidden destination is learned by walking, a lost
sentence is heard again, an uncounted attempt is retried. A false entry
HERE is a wrong FACT that nothing downstream can disagree with, and it is
unrecoverable by design.

It cost the Mt Moon fossils in a live run. The blind sweep pressed both,
was asked "You want the DOME FOSSIL?", declined — `interact` with no
`answer` IS a decline — and wrote both in as touched. The room read fully
worked, both fossils sat there untaken, and no signal anywhere could
notice, because every internal check agreed the room was finished. It took
a human watching the screen to see the bag had no fossil in it.

WHAT THIS DOES NOT TEST, and why. The obvious audit — "an item recorded as
touched that never reached the bag" — cannot see this case. A fossil has no
`item` field in the engine's map data and no POKE_BALL in its name, so the
shim classifies it `npc`, not `item`; and a bag check misfires on
consumables anyway, since a POTION legitimately leaves the bag. The rule
itself is the checkable thing, so the rule is what is checked.

Synthetic only: no game, no model, no ledger on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

REGION = "MT_MOON_B2F|20,5"
THING = "MTMOONB2F_DOME_FOSSIL"


def make():
    ex = object.__new__(E.Executor)
    ex._tried_objs = {}
    ex._touch_bag = {}
    ex._touch_mark = {}
    ex._last_key_items = []
    ex._mark_now = [0, 0, 0]
    return ex


def result(ok, detail=""):
    return {"result": {"ok": ok, "detail": detail},
            "badges": [], "flags": [], "bag": {}}


ASKED = "is ASKING something and the box is STILL OPEN"

CASES = [
    ("an interaction that completed is recorded",
     result(True, "ok (moved)"), True),
    ("one that only ASKED something is not — nothing answered it",
     result(True, f"interact: {ASKED}"), False),
    ("one that never happened is not",
     result(False, "no reachable tile adjacent to target"), False),
    ("one the harness refused is not",
     result(False, "REFUSED — you already interacted with it here"), False),
    ("a missing result is not a completed interaction",
     {}, False),
]


def main():
    fails = []
    for name, res, want in CASES:
        ex = make()
        got = ex._record_touch(REGION, THING, res)
        in_ledger = THING in (ex._tried_objs.get(REGION) or set())
        ok = (got is want) and (in_ledger is want)
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          returned {got}, ledger says {in_ledger}, "
                  f"want {want}")
            fails.append(name)

    # the retraction direction, which _run_traced uses instead
    ex = make()
    ex._record_touch(REGION, THING, result(True, "ok (moved)"))
    ex._retract_touch(REGION, THING)
    left = THING in (ex._tried_objs.get(REGION) or set())
    ok = not left
    print(f"  {'ok  ' if ok else 'FAIL'}  a retracted touch leaves the ledger")
    if not ok:
        fails.append("retract")

    # THE SWEEP AS IT ACTUALLY RAN IN MT MOON: five things pressed blind,
    # two of them asking a question it cannot answer. Exactly three should
    # be recorded, and the fossils must survive to be offered again.
    ex = make()
    room = [("MTMOONB2F_SUPER_NERD", result(True, "ok (moved)")),
            ("MTMOONB2F_ROCKET1", result(True, "ok (moved)")),
            ("MTMOONB2F_ROCKET4", result(True, "ok (moved)")),
            ("MTMOONB2F_DOME_FOSSIL", result(True, f"interact: {ASKED}")),
            ("MTMOONB2F_HELIX_FOSSIL", result(True, f"interact: {ASKED}"))]
    asked = [n for n, r in room if not ex._record_touch(REGION, n, r)]
    got = sorted(ex._tried_objs.get(REGION) or [])
    want = ["MTMOONB2F_ROCKET1", "MTMOONB2F_ROCKET4",
            "MTMOONB2F_SUPER_NERD"]
    ok = got == want and asked == ["MTMOONB2F_DOME_FOSSIL",
                                   "MTMOONB2F_HELIX_FOSSIL"]
    print(f"  {'ok  ' if ok else 'FAIL'}  the Mt Moon sweep records three of "
          f"five and leaves both fossils open")
    if not ok:
        print(f"          recorded {got}")
        print(f"          still open {asked}")
        fails.append("mt moon sweep")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"THE TOUCH RULE IS BROKEN: {len(fails)} case(s)")
        return 1
    print(f"a touch is recorded only for an interaction that completed "
          f"({len(CASES) + 2} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

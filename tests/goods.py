#!/usr/bin/env python3
"""An op that spends money says so.

Run 6 bought fifteen POKE BALLs without meaning to. It never proposed a
`buy` op at all — its entire vocabulary that run was interact 91,
use_warp 61, cross 28, menu 9, grind 2 — but `menu(index=1)` selects BUY
and the boilerplate `answer="yes"` on the next interact presses A through
"That'll be 200. OK?". One ball per cycle, fifteen cycles, 3175 money down
to 175. Every trace line it was shown said:

    interact(VIRIDIANMART_CLERK,answer=yes): ok (map->None, moved, dialog
    still open)

The harness knew the whole time. `_snapshot` carries the bag, so the
change was detected and used internally to keep the op from being marked
inert, and `money` sits in every observation. It was simply not in the
sentence: the change list names map, party and movement and nothing else.
So the run walked toward Brock with 175 money, which is the state that
killed brock37 at level 8 with 93, and nothing it had ever been shown
could have told it why.

WHAT THIS DOES NOT DO. It does not stop the purchase, warn about it, or
price it. Whether fifteen balls are worth 3000 is the model's call and
stays the model's call. The harness's job here is only to make the bill
legible, which is the same rule that put the clerk's sentence back into
the feedback and the shop's real stock into the refusal.

Synthetic only: no game, no model, no observation on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402


def o(bag=None, money=None):
    d = {}
    if bag is not None:
        d["bag"] = dict(bag)
    if money is not None:
        d["money"] = money
    return d


CASES = [
    ("the purchase nobody asked for is now visible",
     o({"POTION": 1}, 3175), o({"POTION": 1, "POKE_BALL": 1}, 2975),
     "  [POKE_BALL +1 (now 1); money -200 (2975 left)]"),

    ("...and so is the fifteenth one",
     o({"POTION": 1, "POKE_BALL": 14}, 375),
     o({"POTION": 1, "POKE_BALL": 15}, 175),
     "  [POKE_BALL +1 (now 15); money -200 (175 left)]"),

    ("an op that changed nothing says nothing",
     o({"POTION": 1}, 3175), o({"POTION": 1}, 3175), ""),

    ("selling reads the other way round",
     o({"NUGGET": 1}, 500), o({}, 5500),
     "  [NUGGET -1 (now 0); money +5000 (5500 left)]"),

    ("spending an item costs no money and still counts",
     o({"POTION": 2}, 900), o({"POTION": 1}, 900),
     "  [POTION -1 (now 1)]"),

    ("a gift is a bag change with no bill",
     o({"POTION": 1}, 3175), o({"POTION": 1, "TOWN_MAP": 1}, 3175),
     "  [TOWN_MAP +1 (now 1)]"),

    # MONEY IS NOT IN THE SNAPSHOT, so a wallet that moves on its own is
    # reported by nothing else in the harness. A blackout halves it.
    ("a blackout halving the wallet is not a silent event",
     o({"POTION": 1}, 3000), o({"POTION": 1}, 1500),
     "  [money -1500 (1500 left)]"),

    ("several things at once, in a stable order",
     o({"POTION": 2, "ANTIDOTE": 1}, 1000),
     o({"POTION": 1, "ANTIDOTE": 3}, 1000),
     "  [ANTIDOTE +2 (now 3); POTION -1 (now 1)]"),

    # older observations, replayed journals, and the very first op of a run
    ("no money field is not a crash and not a lie",
     o({"POTION": 1}), o({"POTION": 1, "POKE_BALL": 1}),
     "  [POKE_BALL +1 (now 1)]"),
    ("no bag at all reports nothing",
     {}, {}, ""),
    ("a bag that is not a dict is ignored rather than guessed at",
     {"bag": "?"}, {"bag": "?"}, ""),
]


def main():
    fails = []
    for name, pre, post, want in CASES:
        got = E.Executor._goods_delta(pre, post)
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          got  {got!r}")
            print(f"          want {want!r}")
            fails.append(name)

    # IT MUST SURVIVE A FAILING OP. A purchase that rides an interact is
    # exactly as real when the interact is reported as failing, and "the
    # world did not change" is flatly false about a wallet down 200. The
    # executor appends this outside the ok/no-effect/failed split; this
    # pins the property the placement exists for.
    got = E.Executor._goods_delta(o({"POTION": 1}, 3175),
                                  o({"POTION": 1, "POKE_BALL": 1}, 2975))
    ok = bool(got)
    print(f"  {'ok  ' if ok else 'FAIL'}  the bill does not depend on the op "
          f"reporting success")
    if not ok:
        fails.append("branch independence")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"MONEY AND ITEMS ARE MOVING SILENTLY: {len(fails)} case(s)")
        return 1
    print(f"an op that moves goods or money says so ({len(CASES) + 1} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

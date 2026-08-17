#!/usr/bin/env python3
"""Somebody who repeats themselves is still speaking.

`last_text` outlives the box that printed it, so an op that said nothing
of its own inherits whatever was said last — a warp out of the gym once
reported "Nope, there's only trash here." That smear was fixed by
requiring the text to have CHANGED, which created the exact opposite
fault: ANYONE WHO REPEATS THEMSELVES GOES SILENT. A repeated line and a
stale line are the same string and completely different facts.

It cost a run the Viridian mart. The clerk says

    "Okay! Say hi to PROF.OAK for me!"

every single time she is pressed, and that sentence names the next
objective outright. The run was shown it on the first press and never
again. It then pressed her round after round waiting for a Pokemon she
does not have, told only `ok (moved, dialog still open)`, until four
attempts were exhausted and a leg rewrite eventually changed tack. A
human watching could read the answer on screen the whole time.

The fix is a counter, not a cleverer string test: shim.note_text bumps
`text_seq` whenever the game PRINTS anything, so "did this op make
somebody speak" is answered without looking at the words. The cases below
pin both faults at once — the smear must stay fixed, and the repeat must
now be heard.

Synthetic only: no game, no model, no shim.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

CLERK = "Okay! Say hi to PROF.OAK for me!"
TRASH = "Nope, there's only trash here."


def ex(last_said=""):
    e = object.__new__(E.Executor)
    e._last_said = last_said
    return e


def obs(text=None, seq=None):
    o = {}
    if text is not None:
        o["last_text"] = text
    if seq is not None:
        o["text_seq"] = seq
    return o


# (name, pre, post, want)
CASES = [
    # WITH A COUNTER — the live path
    ("a first line is heard",
     obs(None, 4), obs(CLERK, 5), True),
    ("THE SAME LINE SAID AGAIN IS HEARD AGAIN",
     obs(CLERK, 5), obs(CLERK, 6), True),
    ("...and again, and again — she never stops being worth quoting",
     obs(CLERK, 6), obs(CLERK, 7), True),
    ("a stale line nobody just printed is NOT attributed to this op",
     obs(TRASH, 9), obs(TRASH, 9), False),
    ("a different stale line is still stale",
     obs(CLERK, 9), obs(CLERK, 9), False),
    ("several lines in one op still count as speech",
     obs(None, 2), obs(CLERK, 5), True),

    # WITHOUT A COUNTER — an old fixture or a replayed journal, which must
    # behave exactly as it did when it was recorded rather than going quiet
    # or suddenly shouting
    ("no counter: a new line is heard, as before",
     obs(TRASH), obs(CLERK), True),
    ("no counter: an inherited line is not, as before",
     obs(CLERK), obs(CLERK), False),
]


def main():
    fails = []
    for name, pre, post, want in CASES:
        e = ex()
        said = (post.get("last_text") or "").strip()
        got = bool(e._op_spoke(pre, post, said))
        ok = got is want
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          got {got}, want {want}")
            fails.append(name)

    # THE GLOBAL SLOT WAS THE OTHER HALF OF THE BUG. `_last_said` held the
    # last line reported ANYWHERE, so a second press was silenced even
    # when the counter would have said she spoke. With a counter present
    # it must have no say at all.
    e = ex(last_said=CLERK)
    got = bool(e._op_spoke(obs(CLERK, 5), obs(CLERK, 6), CLERK))
    ok = got is True
    print(f"  {'ok  ' if ok else 'FAIL'}  the run-global last-said slot "
          f"cannot silence a counted line")
    if not ok:
        fails.append("global slot")

    # ...but it still guards the counter-less path, where it is the only
    # thing standing between a replay and eight copies of one sentence
    e = ex(last_said=CLERK)
    got = bool(e._op_spoke(obs(TRASH), obs(CLERK), CLERK))
    ok = got is False
    print(f"  {'ok  ' if ok else 'FAIL'}  ...and still guards the "
          f"counter-less path")
    if not ok:
        fails.append("global slot fallback")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"SPEECH IS BEING ATTRIBUTED WRONG: {len(fails)} case(s)")
        return 1
    print(f"a line is attributed to the op that printed it "
          f"({len(CASES) + 2} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

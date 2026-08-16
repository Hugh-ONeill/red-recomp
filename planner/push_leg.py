#!/usr/bin/env python3
"""Move an outline leg LATER, when it is right but not yet.

The inverse of pull_leg, and the commoner case. An outline's ordering
errors are overwhelmingly TOO EARLY — a model writing a playthrough puts
down what it knows about when it thinks of it — and until now the ladder
had four ways to say "something else first" and no way to say "this, but
later". Watched live: "the party holds a WATER or GRASS type" placed
before Vermilion, where wild water Pokemon need a rod nobody has yet; the
Master Ball at position 3; "Defeat Giovanni for the Earth Badge" at 19.
The first of those was dropped for good by the upkeep rule, which saved
the chain and lost the objective. Deferring it is the better answer.

Recorded by TEXT as well as position (run/outline_pushes,
"from<TAB>after<TAB>text"), same as pull_leg and for the same reason:
positions shift under the sweep and the insert rung, and the text is what
survives.

Usage: push_leg.py <from> <after>     # move leg <from> to sit after <after>
"""
import sys
from pathlib import Path

OUT = Path("plans/outline.txt")
PUSHES = Path("run/outline_pushes")


def read_outline() -> list:
    return [l for l in OUT.read_text().splitlines() if l.strip()]


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: push_leg.py <from> <after>")
    try:
        frm, after = int(argv[0]), int(argv[1])
    except ValueError:
        sys.exit("push_leg: both arguments are outline positions")
    lines = read_outline()
    n = len(lines)
    if not 1 <= frm <= n:
        sys.exit(f"push_leg: {frm} is off the list of {n}")
    # LATER MEANS LATER. A push that lands at or before where the leg
    # already sits is not a deferral, it is a no-op or a pull wearing the
    # wrong name, and the chain would re-run the same leg immediately.
    if after <= frm:
        sys.exit(f"push_leg: {after} is not after {frm}")
    after = min(after, n)
    text = lines.pop(frm - 1)
    # popping shifted everything above frm down one
    lines.insert(after - 1, text)
    OUT.write_text("\n".join(lines) + "\n")
    with PUSHES.open("a") as f:
        f.write(f"{frm}\t{after}\t{text}\n")
    print(f"pushed {text!r} from {frm} to {after}")


if __name__ == "__main__":
    main(sys.argv[1:])

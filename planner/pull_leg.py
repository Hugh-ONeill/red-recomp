#!/usr/bin/env python3
"""Move an outline leg forward, and put it back when that was wrong.

Its own file rather than an inline heredoc: the chain script already
nests one, and a second sharing the terminator silently truncated the
block it was written into.

A pull is recorded by TEXT as well as by position (run/outline_pulls,
"to<TAB>from<TAB>text"). Positions shift — the sweep crosses finished
objectives off, the insert rung adds one — so the number that named a leg
when it moved may name a different leg by the time the move turns out to
have been a mistake. The text is what survives.

Usage: pull_leg.py pull <to> <from>
       pull_leg.py undo <at>
"""
import sys
from pathlib import Path

OUT = Path("plans/outline.txt")
PULLS = Path("run/outline_pulls")
FAILED = Path("run/outline_pulls_failed")


def read_outline() -> list:
    return [l for l in OUT.read_text().splitlines() if l.strip()]


def write_outline(lines: list):
    OUT.write_text("\n".join(lines) + "\n")


def records() -> list:
    try:
        return [l.split("\t") for l in PULLS.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []


def do_pull(to: int, frm: int):
    lines = read_outline()
    if not (1 <= to <= len(lines)) or not (1 <= frm <= len(lines)):
        sys.exit(f"pull_leg: {to} or {frm} is off the list of {len(lines)}")
    text = lines.pop(frm - 1)
    lines.insert(to - 1, text)
    write_outline(lines)
    with PULLS.open("a") as fh:
        fh.write(f"{to}\t{frm}\t{text}\n")
    print(f"pulled forward: {text}")


def do_undo(at: int):
    """Put back the leg pulled to this position, if one was.

    A pulled-forward leg that then exhausts its own attempts did not
    unstick anything, and leaving it where it is costs the run twice: the
    leg it displaced never comes up, and the reorder budget is spent
    defending the mistake. It goes home, and it is written down as a pull
    that failed so the blocker rung will not make the same move again.
    """
    lines = read_outline()
    recs = records()
    for k in range(len(recs) - 1, -1, -1):
        r = recs[k]
        if len(r) < 3 or int(r[0]) != at:
            continue
        text = r[2]
        if text not in lines:
            break
        frm = max(1, min(int(r[1]), len(lines)))
        lines.remove(text)
        lines.insert(frm - 1, text)
        write_outline(lines)
        del recs[k]
        PULLS.write_text("".join("\t".join(x) + "\n" for x in recs))
        with FAILED.open("a") as fh:
            fh.write(f"{at}\t{text}\n")
        print(f"put back at {frm}: {text}")
        return
    sys.exit(3)


if len(sys.argv) < 3:
    sys.exit(__doc__)
if sys.argv[1] == "pull":
    do_pull(int(sys.argv[2]), int(sys.argv[3]))
elif sys.argv[1] == "undo":
    do_undo(int(sys.argv[2]))
else:
    sys.exit(__doc__)

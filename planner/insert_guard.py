#!/usr/bin/env python3
"""Refuse an outline insertion that restates a line already there.

The "needs something first" rung asked what leg 19 was missing and the
model answered with leg 19's own objective in other words ("Retrieve the
Gold Teeth FROM the Pokemon Tower" for "... FOR the Pokemon Tower"), and the
chain inserted it as a new leg in front of the old one (2026-08-25). A
prerequisite that is the objective itself is not a prerequisite.

Usage: insert_guard.py "<proposed>" "<the leg it would precede>" <outline>
Exit 0 when the proposal is novel; 3 (with a reason on stdout) when it is a
near-restatement of the leg or of any outline line.
"""
import difflib
import re
import sys
from pathlib import Path

_STOP = {"the", "a", "an", "to", "for", "from", "of", "in", "at", "on", "and"}


def _norm(s: str) -> str:
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split()
             if w not in _STOP]
    return " ".join(words)


def main():
    if len(sys.argv) < 4:
        sys.exit("usage: insert_guard.py PROPOSED LEG OUTLINE")
    proposed, leg, outline = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    lines = [l.strip() for l in outline.read_text().splitlines() if l.strip()]
    p = _norm(proposed)
    for other in [leg] + lines:
        o = _norm(other)
        if not o:
            continue
        ratio = difflib.SequenceMatcher(None, p, o).ratio()
        if p == o or ratio >= 0.85:
            print(f"insertion refused: '{proposed}' restates '{other}' "
                  f"(similarity {ratio:.2f})")
            sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()

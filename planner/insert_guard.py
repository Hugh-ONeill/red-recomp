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


def _names(s: str) -> set:
    """The capitalised words of a sentence, minus its first word (a verb
    in this list's imperative voice) and the game's scaffolding words."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9'.]*", s or "")
    out = set()
    for w in words[1:]:
        if w[:1].isupper() and w.lower().rstrip(".") not in _STOP | {"pokemon", "pok\u00e9mon", "hm", "tm"}:
            out.add(w.lower().rstrip("."))
    return out


_VERB_CLASSES = ({"defeat", "beat", "battle", "fight", "challenge", "win"},
                 {"retrieve", "obtain", "get", "collect", "receive", "take", "fetch"},
                 {"reach", "enter", "go", "travel", "visit", "arrive"},
                 {"catch", "capture"}, {"buy", "purchase"}, {"deliver", "bring", "return"})


def _same_deed(a: str, b: str) -> bool:
    """Do two imperative lines open with the same kind of verb? "Battle"
    and "Defeat" are one deed on the same names; "Catch a SPEAROW" before
    "Trade the SPEAROW" is a different deed on the same name, and a real
    prerequisite."""
    va = (re.findall(r"[A-Za-z]+", a or "") or [""])[0].lower()
    vb = (re.findall(r"[A-Za-z]+", b or "") or [""])[0].lower()
    if va == vb:
        return True
    return any(va in c and vb in c for c in _VERB_CLASSES)


def main():
    if len(sys.argv) < 4:
        sys.exit("usage: insert_guard.py PROPOSED LEG OUTLINE")
    proposed, leg, outline = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    lines = [l.strip() for l in outline.read_text().splitlines() if l.strip()]
    # A LEG ALREADY WALKED PAST CANNOT SATISFY A NEED NOW. "Clear space in
    # the bag" was inserted at 27, counted without ever being confirmed, and
    # walked past; ten legs later the bag was full again in the Safari Zone
    # and the missing rung asked for it three times, each refused as
    # "already on your own list" (2026-09-05). Some needs recur — a bag
    # slot, money, a heal — and a line behind the run is history, not a
    # plan. Compare against the leg this would precede and everything still
    # AHEAD of the run; what is done is done.
    try:
        _done = int(Path("run/outline_leg").read_text().strip() or 0)
    except (OSError, ValueError):
        _done = 0
    ahead = lines[max(0, _done):]
    p = _norm(proposed)
    # A PREREQUISITE THAT NAMES ONLY WHAT THE LEG NAMES IS THE LEG. "Battle
    # Lt. Surge" was inserted in front of "Defeat Lt. Surge for the Thunder
    # Badge" at similarity 0.62 (run 16, 2026-09-07): a shorter sentence
    # about the same person, verb swapped. The names in a sentence — its
    # capitalised words — are what it is about; when every name the
    # proposal carries is in the leg's own line, it restates the leg.
    _pn = _names(proposed)
    for other in [leg] + ahead:
        o = _norm(other)
        if not o:
            continue
        ratio = difflib.SequenceMatcher(None, p, o).ratio()
        if (_pn and _pn <= _names(other) and _names(other)
                and _same_deed(proposed, other)):
            print(f"insertion refused: '{proposed}' names only what '{other}' "
                  f"names ({', '.join(sorted(_pn))}), which is still ahead of you")
            sys.exit(3)
        if p == o or ratio >= 0.85:
            print(f"insertion refused: '{proposed}' restates '{other}' "
                  f"(similarity {ratio:.2f}), which is still ahead of you")
            sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()

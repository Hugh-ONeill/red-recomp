#!/usr/bin/env python3
"""Has this run finished the game?

Exit 0 and say why when the executor's last snapshot records a Hall of
Fame induction (the save's own count, or the executor having watched the
credits roll); exit 3 otherwise. Reads run/last_state.json only — the
snapshot THIS chain's executor wrote — never the save on disk, so a
chain started fresh beside an old champion save is not told it has won
before it has played (RED_LAST_STATE overrides the path for tests).

Until 2026-08-28 nothing in the chain knew a finished game: the Hall of
Fame soft-resets to the title, the last step "failed", and the ladder
rewrote the Elite Four leg from an unknown location.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ.get("RED_LAST_STATE", "run/last_state.json"))


def verdict(path: Path = STATE) -> str:
    try:
        o = json.loads(path.read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(o, dict):
        return ""
    try:
        n = int(o.get("hall_of_fame") or 0)
    except (TypeError, ValueError):
        n = 0
    fin = bool(o.get("finished"))
    if n <= 0 and not fin:
        return ""
    return (f"the party has been entered into the Hall of Fame "
            f"{max(n, 1)} time(s)"
            + (" — the executor watched the credits roll" if fin else ""))


def main() -> int:
    v = verdict()
    if v:
        print(v)
        return 0
    return 3


if __name__ == "__main__":
    sys.exit(main())

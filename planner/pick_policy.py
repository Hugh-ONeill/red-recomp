#!/usr/bin/env python3
"""Which battle policy plays: the one that SCORED best, not the newest file.

fresh_run.sh picked the active spec with `ls plans/policy_model_v*.json |
sort -V | tail -1` — the highest version number, which is a filename and
not a result. Run 16 therefore fought its entire game on v6, whose own
provenance records three gauntlet trials that cleared ZERO rooms and
blacked out three times out of three, while v1 (6/6 on the rival, three
badges, no blackouts) and v3 (eight Elite Four rooms, no blackouts) sat
beside it in the same directory (2026-09-12).

Every spec carries the trial that judged it in `provenance.eval`, written
by policy_author.py at the moment it was scored. That is the ranking, and
it was already there.

TWO ARENAS, NOT ONE SCALE. policy_author runs either the Brock arena (the
level-five rival, then the forest and Pewter Gym) or the Elite Four
gauntlet, and they measure different things: `rooms` only exists for the
gauntlet, `badge` and `rival_wins` only for Brock. Ranking them on one
tuple would mean any gauntlet spec beats any Brock spec by default. So
they are ranked SEPARATELY and the stage chooses between them — which is
also why the specs read the way they do: v1 heals with POTION and cures
with ANTIDOTE, things a Kanto mart stocks, and v6 reaches for HYPER_POTION
and MAX_REVIVE, which no early party has ever seen.

  pick_policy.py                 the best sound spec, any arena
  pick_policy.py --badges 3      the best for a run wearing three badges
  pick_policy.py --why           say what was rejected and why
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Where the stage line falls. The gauntlet arena is the last fight in the
# game and the Brock arena is the first; a run is on the endgame side of
# that once it holds the badges that open the league. Nothing subtler is
# claimed — a midgame tier, when one is authored, adds a row here.
E4_FROM_BADGES = 8


def _eval(p: Path) -> dict:
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    return (d.get("provenance") or {}).get("eval") or {}


def arena_of(ev: dict) -> str:
    """Which arena judged this spec. Recorded by policy_author since
    2026-09-12; inferred from the shape of the score for older files —
    the Brock arena is the only one that fights the rival or wins badges."""
    a = str(ev.get("arena") or "")
    if a:
        return a
    if (ev.get("rival_trials") or 0) or (ev.get("badge") or 0):
        return "brock"
    return "e4"


def failed_its_own_trial(ev: dict) -> str:
    """Why this spec should never be chosen, or "" if it is sound.

    A spec that blacked out in EVERY trial it was given did not survive
    the only test it has, and no version number changes that."""
    if not ev:
        return "no recorded trial at all"
    trials = (ev.get("gauntlet_trials") or 0) + (ev.get("rival_trials") or 0)
    if trials and (ev.get("blackouts") or 0) >= trials:
        return f"blacked out in all {trials} of its own trials"
    if not trials:
        return "its trial ran no fights"
    return ""


def score(ev: dict) -> tuple:
    """Higher is better, within one arena. The same terms policy_author
    ranks its own candidates on, minus `rooms` for the Brock arena where
    it does not exist."""
    return (int(ev.get("rooms") or 0),
            int(ev.get("badge") or 0),
            int(ev.get("pewter") or 0),
            (ev.get("rival_wins") or 0) / max(1, ev.get("rival_trials") or 0),
            -int(ev.get("blackouts") or 0),
            -float(ev.get("dmg_gap") or 0.0))


def rank(paths, badges: int | None = None):
    """(winner, rows) — rows are (path, arena, sound?, why, score)."""
    rows = []
    for p in sorted(paths):
        ev = _eval(p)
        why = failed_its_own_trial(ev)
        rows.append((p, arena_of(ev), not why, why, score(ev)))
    sound = [r for r in rows if r[2]]
    if not sound:
        return None, rows
    want = None
    if badges is not None:
        want = "e4" if badges >= E4_FROM_BADGES else "brock"
        tier = [r for r in sound if r[1] == want]
        if tier:
            return max(tier, key=lambda r: r[4])[0], rows
    # no stage asked, or no spec scored on that stage's arena: the best
    # sound one anywhere, which at least beat something
    return max(sound, key=lambda r: r[4])[0], rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=REPO / "plans")
    ap.add_argument("--glob", default="policy_model_v*.json")
    ap.add_argument("--badges", type=int, default=None,
                    help="how many badges the run holds, to pick the tier")
    ap.add_argument("--why", action="store_true",
                    help="print every spec and why it did or did not win")
    a = ap.parse_args()
    paths = list(Path(a.dir).glob(a.glob))
    if not paths:
        return 1
    win, rows = rank(paths, a.badges)
    if a.why:
        for p, arena, ok, why, sc in sorted(rows, key=lambda r: -r[4][0]):
            mark = "WINNER" if p == win else ("  ok  " if ok else "REJECT")
            print(f"{mark} {p.name:28s} arena={arena:6s} "
                  + (why or f"score={sc}"), file=sys.stderr)
    if not win:
        return 1
    print(win)
    return 0


if __name__ == "__main__":
    sys.exit(main())

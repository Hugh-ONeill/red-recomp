#!/usr/bin/env python3
"""A warp onto the same floor is a move, not nothing (2026-09-05).

Silph Co's pads often land elsewhere on the floor you left. The no-change
verdict blanks the party's position on purpose, so use_warp(3,11) came back
"ran but had NO visible effect (nothing changed) — warped — same map, you are
now at 11,9": a denial and its own refutation in one line (user: "the visible
effect was the move, it just didnt have a map change"). The line now says the
move.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
pre = {"map": {"id": "SILPH_CO_5F"}, "player": {"x": 3, "y": 11}}
post = {"map": {"id": "SILPH_CO_5F"}, "player": {"x": 11, "y": 9}}
w = E.Executor._same_floor_move_words(pre, post, "use_warp", "warped — same map, you are now at 11,9")
ck("a same-map warp is said as a move with both cells", "moved you on the SAME floor, to (11,9) from (3,11)" in w, w)
ck("...and named as a pad or door of the floor", "a pad or door of SILPH_CO_5F" in w and "not nothing" in w, w)
ck("a map change is left to the ordinary verdict", E.Executor._same_floor_move_words(pre, {"map": {"id": "SILPH_CO_7F"}, "player": {"x": 1, "y": 1}}, "use_warp", "") == "")
ck("no move and no same-map detail: nothing", E.Executor._same_floor_move_words(pre, pre, "use_warp", "") == "")
ck("only use_warp qualifies", E.Executor._same_floor_move_words(pre, post, "interact", "") == "")
ck("a missing player position says nothing", E.Executor._same_floor_move_words(pre, {"map": {"id": "SILPH_CO_5F"}}, "use_warp", "same map") == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("the no-change verdict asks it first", "_mv0 = self._same_floor_move_words(pre_obs, obs, op, det0)" in src and 'note += (_mv0 if _mv0 else' in src)
ck("...and does not re-append the shim's line under it", 'and det0[:60] not in note and not _mv0:' in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)

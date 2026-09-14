#!/usr/bin/env python3
"""A pure place step is not re-opened by the backtrack when the party is
still inside that place's building.

reach_captain (map SS_ANNE_CAPTAINS_ROOM) spent its rounds on B1F and
failed; the backtrack looked back for the last step no longer true, found
enter_ss_anne (map SS_ANNE_1F) false from SS_ANNE_B1F_ROOMS, re-opened it,
and the party walked back to 1F to board a ship it was already on, then
started reach_captain over (2026-09-14, user: "dragging it back even
though it was making progress"). Boarding is done once; floors of one
building are one place, the departure rule's own lesson. Two changes:
map_family recognises a floor token wherever it sits (SS_ANNE_B1F_ROOMS
is the S.S. Anne), and the backtrack's "does not hold" mode stands down
for a pure place step whose map is the building the party stands in. The
relocate mode, for a step that still holds with rooms unsearched, is
untouched.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the ship's rooms are the ship", E.map_family("SS_ANNE_B1F_ROOMS") == "SS_ANNE" == E.map_family("SS_ANNE_2F_ROOMS") == E.map_family("SS_ANNE_1F"))
ck("floors still share a family", E.map_family("POKEMON_TOWER_6F") == "POKEMON_TOWER" and E.map_family("MT_MOON_B2F") == "MT_MOON")
ck("a trailing token still works alone", E.map_family("ROCKET_HIDEOUT_B4F") == "ROCKET_HIDEOUT" and E.map_family("SILPH_CO_11F") == "SILPH_CO")
ck("a map with no floor token is its own family",
   E.map_family("LAVENDER_TOWN") == "LAVENDER_TOWN" and E.map_family("CERULEAN_GYM") == "CERULEAN_GYM"
   and E.map_family("SS_ANNE_BOW") == "SS_ANNE_BOW")
ck("None is safe", E.map_family(None) == "")

src = (ROOT / "planner" / "executor.py").read_text()
i = src.index("for back in range(idx - 1, max(-1, idx - 5), -1):")
loop = src[i:i + 2600]
ck("the backtrack scan leaves a pure place step alone when the party is in its building",
   "map_family(_want_pl) == map_family(_here_map)" in loop and "continue" in loop.split("map_family(_want_pl)", 1)[1][:400])
ck("...only for a PURE place step (map, area, not_area), never one with a deed in it",
   'set(_dw) <= {"map", "area", "not_area"}' in loop)
ck("...and says so in the journal", '"backtrack_place_held"' in loop)
ck("the relocate mode for a step that still holds is untouched",
   "cand, holds, elsewhere = c, True, elw" in loop)
ck("a step that does not hold and is not a place step is still re-opened",
   "cand, holds = c, False\n                        break" in loop)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

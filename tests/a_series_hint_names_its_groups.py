#!/usr/bin/env python3
"""A guessed flag in a named series is answered with every member, grouped
by the place its trainers stand in.

"Defeat all trainers on the S.S. Anne" (run 16, 2026-09-07) was authored
with four floor subgoals whose done_when flags were ALL of the
EVENT_BEAT_SS_ANNE_10_TRAINER_* series — the B1F cabins — because the hint
for the placeholder EVENT_BEAT_SS_ANNE_N_TRAINER_N listed the first six of
sixteen ids in sort order ("10" sorts before "5") and said "(and more)".
Every member is now printed verbatim, grouped by the map its trainers are
on, with how many of each group are already beaten.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

mem = [f"EVENT_BEAT_SS_ANNE_{s}_TRAINER_{i}" for s, n in ((10, 6), (5, 2), (8, 4), (9, 4)) for i in range(n)]
fired = {"EVENT_BEAT_SS_ANNE_10_TRAINER_3", "EVENT_BEAT_SS_ANNE_5_TRAINER_0", "EVENT_BEAT_SS_ANNE_5_TRAINER_1",
         "EVENT_BEAT_SS_ANNE_8_TRAINER_1", "EVENT_BEAT_SS_ANNE_8_TRAINER_2", "EVENT_BEAT_SS_ANNE_8_TRAINER_3"}
h = A._series_hint(mem, fired)
ck("every member is printed verbatim", all(m in h for m in mem))
ck("the count and the groups are said", "16 events" in h and "4 group(s)" in h)
ck("each group is tied to its place",
   all(w in h for w in ("SS_ANNE_B1F_ROOMS", "SS_ANNE_BOW", "SS_ANNE_1F_ROOMS", "SS_ANNE_2F_ROOMS")))
ck("what is already beaten is said per group",
   "the 2 trainer(s) of SS_ANNE_BOW (all already beaten)" in h
   and "the 4 trainer(s) of SS_ANNE_1F_ROOMS (3 of them already beaten)" in h
   and "the 6 trainer(s) of SS_ANNE_B1F_ROOMS (1 of them already beaten)" in h)
ck("...and no group is cut off", "(and more)" not in h)
ck("a single member keeps the 'ONLY event' wording",
   "ONLY event of that series" in A._series_hint(["EVENT_BEAT_ROUTE_4_TRAINER_0"]))
ck("a short single series keeps the plain list",
   A._series_hint(["EVENT_BEAT_ROUTE_3_TRAINER_0", "EVENT_BEAT_ROUTE_3_TRAINER_1"]).startswith(
       " Did you mean one of EVENT_BEAT_ROUTE_3_TRAINER_0, EVENT_BEAT_ROUTE_3_TRAINER_1?"))
ck("the table covers the engine's trainer events and only real maps",
   len(A.TRAINER_EVENT_MAP) >= 300 and set(A.TRAINER_EVENT_MAP.values()) <= set(A.ENGINE_MAPS))
ck("the validator uses the helper with the flags fired so far",
   "_hint = _series_hint(" in (ROOT / "planner" / "author.py").read_text())

# the matcher itself (_series_members): what a guessed id is read as
def maps_of(v):
    return sorted({A.TRAINER_EVENT_MAP.get(x, "?") for x in A._series_members(v)})
ck("a blank beside an impossible number still yields the named series",
   len(A._series_members("EVENT_BEAT_SS_ANNE_N_TRAINER_14")) == 16)
ck("a number that completes no map name is an index guess and widens (SS_ANNE_1, SS_ANNE_B1)",
   len(A._series_members("EVENT_BEAT_SS_ANNE_1_TRAINER_0")) == 16
   and len(A._series_members("EVENT_BEAT_SS_ANNE_B1_TRAINER_0")) == 16
   and maps_of("EVENT_BEAT_SS_ANNE_1_TRAINER_0") == ["SS_ANNE_1F_ROOMS", "SS_ANNE_2F_ROOMS", "SS_ANNE_B1F_ROOMS", "SS_ANNE_BOW"])
ck("a number that IS a map's name stays literal (Route 4 never suggests Route 10)",
   maps_of("EVENT_BEAT_ROUTE_4_TRAINER_N") == ["ROUTE_4"] and maps_of("EVENT_BEAT_ROUTE_4_TRAINER_7") == ["ROUTE_4"])
ck("a place with no trainers gets no other place's trainers",
   A._series_members("EVENT_BEAT_ROUTE_5_TRAINER_0") == [])
ck("a floor index inside a dungeon widens to the dungeon's floors only",
   maps_of("EVENT_BEAT_ROCK_TUNNEL_1_TRAINER_9") == ["ROCK_TUNNEL_1F", "ROCK_TUNNEL_B1F"])
ck("a bare prefix is not a series: EVENT_GOT_TEA offers no other event's name",
   A._series_members("EVENT_GOT_TEA") == [] and A._series_members("EVENT_GOT_SECRET_CLUB_CARD") == [])
ck("...while a numbered tail still finds its series", len(A._series_members("EVENT_BEAT_ROUTE_4_TRAINER_7")) >= 1)
src = (ROOT / "planner" / "author.py").read_text()
ck("the validator reads guesses through that one function", "_mem = _series_members(str(v))" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

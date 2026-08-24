"""A switch in the floor, and the barrier it opens.

Third of the family with the Mansion's statues and the Cinnabar gym's quiz
machines: a coordinate a map script tests, in no list the observation
carries. Victory Road showed three boulders it could push and no reason to
push any of them anywhere, so the run reached for SURF on a floor with no
water (user, 2026-08-24: "it thinks it needs to surf but it needs to use
strength"). The barrier is owed with it — a player watches that wall go
(user: "the block it removes is also visible to the player so it should be
visible to us as well").

Positions only. WHICH boulder, and by what route, is the puzzle.
"""
import re
import subprocess, sys, pathlib

GAME = pathlib.Path("/home/wiz/Developer/gen1recomp")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from planner import ledger

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


def lua(expr):
    return subprocess.run(
        ["lua5.4", "-e", 'local M = dofile("data/scripts/story.lua") ' + expr],
        cwd=GAME, capture_output=True, text=True).stdout.strip()


def sw(mapid):
    return lua(f'local l = M.{mapid} and M.{mapid}.boulder_switches '
               'local t = {} for _, c in ipairs(l or {}) do '
               't[#t+1] = c[1]..","..c[2]..">"..c[3]..","..c[4] end '
               'print(table.concat(t, " "))')


ck("1F exports its switch and barrier", sw("VICTORY_ROAD_1F") == "17,13>4,6")
ck("2F exports both of its switches",
   sw("VICTORY_ROAD_2F") == "1,16>3,4 9,16>11,7")
ck("3F exports its switch", sw("VICTORY_ROAD_3F") == "3,5>3,5")
ck("a floor with no such puzzle exports none",
   sw("POKEMON_MANSION_1F") == "")


class Ex:
    def _where(self, o):
        return f"{o['map']['id']}|{o['player']['x']},{o['player']['y']}"

    def __getattr__(self, k):
        return {}


def page(sws):
    obs = {"map": {"id": "VICTORY_ROAD_1F", "warps": [],
                   "boulder_switches": sws},
           "player": {"x": 8, "y": 15}, "party": [], "bag": {}}
    return str(ledger.render([], Ex(), obs))


free = page([{"x": 17, "y": 13, "held": False, "reachable": True,
              "opens_x": 8, "opens_y": 12}])
ck("the page names the switch cell", "(17,13)" in free)
ck("...and the barrier it opens", "opens the way at (8,12)" in free)
ck("...and that a boulder is what works it", "a BOULDER has to be shoved onto" in free)
# THE OPPOSITE, ACTUALLY. Measured on VICTORY_ROAD_1F: the boulder landed,
# the barrier opened, the floor reloaded with the boulders back at their
# start cells, and the way was STILL open — the landing sets something that
# outlives the boulder. The old wording claimed the reverse.
ck("...and does not claim it closes when the boulder leaves",
   "only while the boulder stays" not in free)
ck("...and says the way outlives the boulder",
   "stays open after the boulder has gone" in free)
ck("...without inventing what unsets it",
   "not recorded here" in free)
ck("it does not say which boulder to use",
   "WHICH boulder, and where, is yours" in free)

# ...AND IT TEACHES THE DESTINATION FORM, NOT THE ONE-CELL ONE. The first
# version of this line said "Boulders move one cell at a time with
# {"op":"push",...,"dir":...}" — written before push learned to solve a
# route, and left standing next to the switch it describes, which is the
# nearest instruction to the decision. The run went on spelling out single
# shoves (user, 2026-08-24: "its trying to solve it push by push still").
ck("the switch line names the destination form", '"to_x"' in free)
ck("...and does not teach the one-cell form beside it",
   '"dir":"..."' not in free)

held = page([{"x": 17, "y": 13, "held": True, "reachable": True,
              "opens_x": 8, "opens_y": 12}])
ck("a switch already held says so", "a BOULDER IS ON IT NOW" in held)

far = page([{"x": 17, "y": 13, "held": False, "reachable": False,
             "opens_x": 8, "opens_y": 12}])
ck("an unreachable switch says so", "no walk from here reaches that cell" in far)
# ...AND SAYS IT DOES NOT MATTER. Player-reachability is the wrong test for
# a switch a BOULDER has to arrive on; the bare clause reads as "this one is
# out of play" and sends the run looking elsewhere.
ck("...and that it is the boulder that must get there, not the player",
   "it is the BOULDER that has to end up on it, not you" in far)

ck("no switches, no line", "SWITCH(ES) IN THE FLOOR" not in page([]))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

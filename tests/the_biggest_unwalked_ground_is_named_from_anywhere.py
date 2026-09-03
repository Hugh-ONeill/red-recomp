"""The biggest unwalked ground is named wherever the party is standing.

THE FRONTIER WAS ADVERTISED LOCALLY ONLY. The candidate list is built around
where you stand, and the remote list beside it is built from regions with
untried EXITS — so a floor whose every door has been taken is skipped however
much unwalked ground lies behind it. Rock Tunnel B1F is exactly that: both
ladders taken, eleven spots where the ground it looked at ends, and not a line
about it anywhere on the page.

Measured 2026-09-02 over thirty escalation pages. While the run circled
Vermilion, Cerulean, Route 6, Route 11 and Route 12, the tunnel's unexplored
ground was named on 0 of 21 pages; once the party was within a map or two it
was named on 9 of 9. Standing in Cerulean on its 191st visit the entire menu
was a bush and three houses it had already been inside, so exploring the bike
shop WAS the best exploration on offer. Exploring the tunnel was never a
choice it declined. It was a choice it was never shown.

Ranked by SIZE and not by distance, which is the point of it: the list above
already covers what is near, and what this exists to surface is the big
unwalked space several maps away. Walked route only, first leg named the same
way the remote list already names one. No route is drawn; whether a hundred
unseen cells are worth six legs stays the model's call."""
import sys
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

GRAPH = {
    "CERULEAN_CITY|26,7": {"east": {"to": "ROUTE_9|0,8", "n": 3},
                          "13,25": {"to": "BIKE_SHOP|4,1", "n": 3}},
    "ROUTE_9|0,8": {"east": {"to": "ROUTE_10|0,4", "n": 3}},
    "ROUTE_10|0,4": {"8,17": {"to": "ROCK_TUNNEL_1F|14,2", "n": 3}},
    "ROCK_TUNNEL_1F|14,2": {"37,3": {"to": "ROCK_TUNNEL_B1F|26,2", "n": 3}},
    "ROCK_TUNNEL_B1F|26,2": {},
    "BIKE_SHOP|4,1": {},
}


def fake(seen):
    ex = object.__new__(E.Executor)
    ex.region_seen = seen
    ex.explored = GRAPH
    ex._bad_seam = set()
    ex._route = E.Executor._route.__get__(ex)
    return ex


line = fake({"ROCK_TUNNEL_B1F|26,2": 11, "BIKE_SHOP|4,1": 1}
            )._unwalked_ground_line("CERULEAN_CITY|26,7")
ck("a floor whose every door is taken is still named", "ROCK_TUNNEL_B1F" in line)
ck("...with how much ground is unwalked there", "11 spot(s)" in line)
ck("...how far off it is", "leg(s) away" in line)
ck("...and the first leg to start on", "first:" in line)
ck("size wins over distance: the big far one leads",
   line.index("ROCK_TUNNEL_B1F") < line.index("BIKE_SHOP"))
ck("it says what a spot IS, not that it is worth going to",
   "the ground you looked at ends" in line and "should" not in line)

ck("where you already stand is not offered",
   "ROCK_TUNNEL_B1F" not in
   fake({"ROCK_TUNNEL_B1F|26,2": 11})._unwalked_ground_line(
       "ROCK_TUNNEL_B1F|26,2"))
ck("a region with nothing unwalked is not offered",
   fake({"BIKE_SHOP|4,1": 0})._unwalked_ground_line("CERULEAN_CITY|26,7") == "")
ck("nothing unwalked anywhere says nothing at all",
   fake({})._unwalked_ground_line("CERULEAN_CITY|26,7") == "")
ck("a place no walk reaches is not offered as a place to go",
   "NOWHERE" not in fake({"NOWHERE|1,1": 99})._unwalked_ground_line(
       "CERULEAN_CITY|26,7"))
ck("a junk count is skipped rather than crashing",
   fake({"BIKE_SHOP|4,1": None, "ROCK_TUNNEL_B1F|26,2": "x"}
        )._unwalked_ground_line("CERULEAN_CITY|26,7") == "")

many = fake({f"R{i}|0,0": 50 - i for i in range(9)}
            | {"ROCK_TUNNEL_B1F|26,2": 11})._unwalked_ground_line(
    "CERULEAN_CITY|26,7")
ck("the line is capped so it cannot eat the page",
   many == "" or many.count("spot(s)") <= 4)

src = Path("planner/executor.py").read_text()
ck("it hangs off the remote list, not a block of its own",
   "_elsewhere_str += self._unwalked_ground_line(here)" in src)
ck("...and is reached even when that list was empty",
   src.index("_elsewhere_str += self._unwalked_ground_line")
   > src.index('_elsewhere_str = ""'))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)

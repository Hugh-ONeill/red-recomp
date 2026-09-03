"""The one who is standing at the door is told which roads never opened.

The author's brief has carried ROADS YOU HAVE STOOD BESIDE AND NEVER CROSSED
for weeks, and its preamble names Route 10 as the worked example: a road may
leave from a part of a map the run has never stood on, and Route 10's south
end is past Rock Tunnel. Measured across sixty escalation pages on 2026-09-02,
the walking model saw that block ZERO times. The author was told; the walker,
who is the one standing in the tunnel deciding whether to go deeper, was not.

So it went in, read truthfully that the chamber it could reach was finished,
and walked back out to look for a road south along a Route 10 it had only ever
stood on the northern half of. Forty-two times, saying so plainly each time:
"Since Route 10 has no eastern edge, the 'eastern exit' of the Rock Tunnel must
be the south exit of Route 10."

Nothing here draws a route. The counts are the run's own visits, the roads are
the Town Map it is holding, and the caveat is the same sentence the author gets.
It says a road has been leaned on and never opened, and what the run itself has
already heard at one."""
import sys
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
i = src.find("ROADS THE MAP DRAWS THAT YOU HAVE NEVER")
ck("the block reaches the player's page at all", i > 0)
blk = src[max(0, i - 3000):i + 1600]

ck("it is built from the run's OWN visit counts",
   "for _r, _n in (self.visits or {}).items()" in blk)
ck("...and from the printed map it is holding", "MAP_EDGES.items()" in blk)
ck("only roads well leaned on are listed",
   '_vis_m.get(_m0, 0) < 8' in blk)
ck("...and only ones whose far side was never reached",
   "if _vis_m.get(_nb):" in blk and "continue" in blk)
ck("the split caveat travels with it, in capitals",
   "THE ROAD MAY LEAVE FROM A PART OF THAT MAP YOU" in blk
   and "HAVE NEVER STOOD ON" in blk)
ck("...and says a map can be split", "a map can be split" in blk)
ck("it never claims to know WHY",
   "WHY is not " in blk and "recorded and is not always the same" in blk)
ck("it is capped so it cannot eat the page", "[:8]" in blk)
ck("it rides the TOWN MAP gate, like every printed-map block",
   src.find("_holding_town_map(obs)", max(0, i - 3000)) < i
   or "_holding_town_map" in blk)
ck("no route is drawn — the itinerary stays deleted",
   "TOWN-MAP ITINERARY" in src and "walk the model's finger" in src)

# the pressed-thing join, same rule the author's brief uses
ex = object.__new__(E.Executor)
SNOR = 'ok (moved) — it said: "A sleeping POKeMON blocks the way!"'
ex._outcomes = {"map:LAVENDER_TOWN|ROUTE_12|0,61":
                {"ROUTE12_SNORLAX": {"last": SNOR}}}
said = ex._road_words("ROUTE_12", "LAVENDER_TOWN")
ck("a road carries what the run pressed toward it",
   "ROUTE12_SNORLAX" in said and "blocks the way" in said)
ck("...and says the press was aimed at that place",
   "while aiming at LAVENDER_TOWN" in said)
ck("a press aimed somewhere else is not that road's answer",
   not object.__new__(E.Executor).__class__._road_words(
       type("X", (), {"_outcomes": {"map:CELADON_CITY|ROUTE_12|0,61":
                                    {"ROUTE12_SNORLAX": {"last": SNOR}}}})(),
       "ROUTE_12", "LAVENDER_TOWN"))
ex2 = object.__new__(E.Executor)
ex2._outcomes = {"map:SAFFRON_CITY|ROUTE_5|6,0":
                 {"TEXT_ROUTE5_SIGN": {"last": 'ok — it said: "UNDERGROUND"'}}}
ck("a signpost is never what shut a road",
   not ex2._road_words("ROUTE_5", "SAFFRON_CITY"))
ex3 = object.__new__(E.Executor); ex3._outcomes = {}
ck("nothing pressed toward it adds nothing",
   ex3._road_words("PALLET_TOWN", "ROUTE_21") == "")

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)

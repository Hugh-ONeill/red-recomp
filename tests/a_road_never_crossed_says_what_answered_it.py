"""A road the run keeps not taking says what answered it there (2026-09-02).

ROADS YOU HAVE STOOD BESIDE AND NEVER CROSSED is derived from visit counts,
and its own preamble says WHY IS NOT RECORDED. That was false of the one
road that mattered. The run pressed the ROUTE12_SNORLAX while aiming at
LAVENDER_TOWN and wrote down what it said — "A sleeping POKeMON blocks the
way!" — and then the road appeared in this list with a bare count, while the
sentence sat in WHAT PEOPLE HAVE SAID, which the budget trimmer drops by
distance from the party. Standing in Vermilion, the model was never shown it.

So it re-derived "I am blocked by Snorlax on Route 12" from its own prose
every round for forty rounds, and spent them walking back to Cerulean to
look for a Poke Flute in shops (user, watching: "its mostly just getting
stuck at borders").

The join is scoped to keep it evidence rather than chatter: a thing pressed
ON THAT MAP while AIMING AT the place the road leads to. Pallet Town's four
recorded sentences are signs and a fisherman, none of them pressed on the
way to Route 21, so nothing attaches to that road. And a signpost is never
the answer: it is read, not met."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "planner")
import author

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SNOR = 'ok (moved) — it said: "A sleeping POKeMON blocks the way!"'
SIGN = 'ok — it said: "UNDERGROUND PATH CERULEAN CITY - VERMILION CITY"'


def render(outcomes):
    d = {"visits": {"ROUTE_12|0,61": 67, "ROUTE_5|6,0": 215,
                    "PALLET_TOWN|10,0": 30},
         "explored": {"ROUTE_12|0,61": {}, "ROUTE_5|6,0": {},
                      "PALLET_TOWN|10,0": {}},
         "outcomes": outcomes}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(d, f)
        p = f.name
    return author.observed_text(Path(p))


def road(text, m, nb):
    return next((l for l in text.splitlines()
                 if f"{m} --" in l and f"--> {nb}" in l and "stood in" in l),
                "")


t = render({"map:LAVENDER_TOWN|ROUTE_12|0,61":
            {"ROUTE12_SNORLAX": {"n": 1, "last": SNOR}}})
line = road(t, "ROUTE_12", "LAVENDER_TOWN")
ck("the Route 12 road is listed at all", line)
ck("...and names what was pressed", "ROUTE12_SNORLAX" in line)
ck("...and quotes what it said", "A sleeping POKeMON blocks the way!" in line)
ck("...and says the press was made aiming at that place",
   "while aiming at LAVENDER_TOWN" in line)
ck("the bare count survives beside it", "never once reached" in line)

ck("a road with nothing pressed toward it stays a bare count",
   road(t, "PALLET_TOWN", "ROUTE_21")
   and "it said" not in road(t, "PALLET_TOWN", "ROUTE_21"))

# THE SCOPING GUARDS
t2 = render({"map:CELADON_CITY|ROUTE_12|0,61":
             {"ROUTE12_SNORLAX": {"n": 1, "last": SNOR}}})
ck("a press made while aiming SOMEWHERE ELSE is not that road's answer",
   "it said" not in road(t2, "ROUTE_12", "LAVENDER_TOWN"))

t3 = render({"map:LAVENDER_TOWN|ROUTE_5|6,0":
             {"ROUTE12_SNORLAX": {"n": 1, "last": SNOR}}})
ck("a press made on ANOTHER MAP is not that road's answer",
   "it said" not in road(t3, "ROUTE_12", "LAVENDER_TOWN"))

t4 = render({"map:SAFFRON_CITY|ROUTE_5|6,0":
             {"TEXT_ROUTE5_UNDERGROUND_PATH_SIGN": {"n": 9, "last": SIGN}}})
ck("a signpost is never offered as what shut a road",
   "it said" not in road(t4, "ROUTE_5", "SAFFRON_CITY"))

t5 = render({"map:LAVENDER_TOWN|ROUTE_12|0,61":
             {"ROUTE12_SNORLAX": {"n": 1, "last": "ok (moved)"}}})
ck("a press that said nothing adds nothing",
   "it said" not in road(t5, "ROUTE_12", "LAVENDER_TOWN"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)

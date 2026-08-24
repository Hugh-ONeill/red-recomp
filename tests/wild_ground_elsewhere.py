"""What the wild ground on OTHER maps has paid.

Every note about fighting described the map underfoot and nothing else, so a
party grinding L2-L5 wilds for 481 exp a grind had no way to know that
ground it has already walked pays several times that per battle (user,
2026-08-24: "it doesnt have a comparison with an actually good place to
train like the mansion where each battle earns as much as a full grind
here").

Ordered by how far away they are, NOT by how good they look — which is
worth the walk stays the model's read.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "planner"))
import executor as E

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


class S:
    _wild_lv = {"ROUTE_22": {"lo": 2, "hi": 5, "n": 579},
                "POKEMON_MANSION_B1F": {"lo": 34, "hi": 39, "n": 22},
                "VICTORY_ROAD_2F": {"lo": 40, "hi": 46, "n": 8},
                "EMPTY": {"lo": 3, "hi": 3, "n": 0}}
    _grind_exp = {"ROUTE_22": {"exp": 16097, "n": 37},
                  "POKEMON_MANSION_B1F": {"exp": 9100, "n": 3}}
    explored = {"POKEMON_MANSION_B1F|20,1": {}, "VICTORY_ROAD_2F|1,1": {}}

    def _where(self, o):
        return "ROUTE_22|30,11"

    def _route(self, a, b):
        return [1, 1, 1] if "MANSION" in b else [1] * 7


S._wild_elsewhere_note = E.Executor._wild_elsewhere_note
note = S()._wild_elsewhere_note("ROUTE_22", {"map": {"id": "ROUTE_22"}})

ck("names another map's wild levels", "POKEMON_MANSION_B1F L34-L39" in note)
ck("names what it paid per grind", "3033 exp per grind" in note)
ck("names the walk cost", "3 walked leg(s) away" in note)
ck("the map underfoot is excluded", "ROUTE_22 L2-L5" not in note)
ck("a map with no battles is excluded", "EMPTY" not in note)
ck("a map with levels but no grinds still appears",
   "VICTORY_ROAD_2F L40-L46 in 8 battle(s)" in note)
ck("...without inventing an exp figure for it",
   "VICTORY_ROAD_2F L40-L46 in 8 battle(s), 7 walked" in note)
ck("nearest first, not best first",
   note.index("POKEMON_MANSION_B1F") < note.index("VICTORY_ROAD_2F"))
ck("draws no conclusion", not any(w in note.lower() for w in
   ("better", "should", "worth it", "instead", "waste")))

S2 = type("S2", (S,), {"_wild_lv": {"ROUTE_22": {"lo": 2, "hi": 5, "n": 9}}})
ck("nothing to compare against says nothing",
   S2()._wild_elsewhere_note("ROUTE_22", {"map": {"id": "ROUTE_22"}}) == "")

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

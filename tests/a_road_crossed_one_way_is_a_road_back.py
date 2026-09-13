#!/usr/bin/env python3
"""`go` exists to backtrack, and a suffixed crossing gave it no way home.

The router already infers the reverse of a compass seam: a road crossed
east can be crossed back west unless a walk refuted it, and a refutation
goes in _bad_seam. That rule matched the BARE direction only — and a
crossing made at a different cell of the same edge is deliberately filed
under "north#skip1" so _walk_route can reproduce it.

Run 17 walked Pallet Town to Route 1 to Viridian City, then could not `go`
back to Pallet. Walking north out of Pallet the first time triggered Oak's
scripted pull into his lab, so the bare "north" key was taken by a false
edge to OAKS_LAB, and the real crossing landed under "north#skip1". No
reverse was inferred from it, the router found Viridian to Route 1 and
stopped, and said "no walked way" (2026-09-13, user: "that kind of defeats
the purpose of go for any long journey, the whole point of it is to be
able to quickly backtrack").

Across run 16 that refusal hit 164 of 1,285 `go` ops, about one in eight.

A walk INSIDE a map is still never reversed — a ledge hopped down is not
hopped up — and that is the whole reason the rule is narrow.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                       # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))


def ex_with(explored, bad=()):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = explored
    ex._bad_seam = set(bad)
    return ex


def dests(ex, region):
    return {k: (v or {}).get("to") for k, v in ex._edges_of(region).items()}


# ---- run 17's own graph, exactly as it stood --------------------------
G = {"PALLET_TOWN|10,0": {"north": {"to": "OAKS_LAB|4,1"},
                          "north#skip1": {"to": "ROUTE_1|10,0"}},
     "ROUTE_1|10,0": {"north": {"to": "VIRIDIAN_CITY|17,0"}},
     "VIRIDIAN_CITY|17,0": {}}
ex = ex_with(G)
ck("a bare crossing still offers its way back",
   dests(ex, "VIRIDIAN_CITY|17,0").get("south") == "ROUTE_1|10,0")
ck("a SUFFIXED crossing now offers one too",
   dests(ex, "ROUTE_1|10,0").get("south") == "PALLET_TOWN|10,0")
ck("...and the forward edge is untouched",
   dests(ex, "ROUTE_1|10,0").get("north") == "VIRIDIAN_CITY|17,0")
ck("the whole way home exists again",
   "south" in dests(ex, "VIRIDIAN_CITY|17,0")
   and "south" in dests(ex, "ROUTE_1|10,0"))

# ---- and it is an INFERENCE, marked as one and refutable ---------------
ck("the inferred leg says it was inferred",
   (ex._edges_of("ROUTE_1|10,0").get("south") or {}).get("inferred") is True)
ck("...and carries no traversal count", 
   (ex._edges_of("ROUTE_1|10,0").get("south") or {}).get("n") == 0)
ck("a walk that refuted it takes it away",
   "south" not in dests(
       ex_with(G, bad={("ROUTE_1|10,0", "south", "PALLET_TOWN|10,0")}),
       "ROUTE_1|10,0"))

# ---- a walk inside a map is STILL never reversed -----------------------
W = {"ROUTE_9|1,1": {"walk:20,4": {"to": "ROUTE_9|30,4"}}}
ck("a ledge hopped down is not hopped up",
   dests(ex_with(W), "ROUTE_9|30,4") == {})
L = {"SILPH_CO_1F|1,1": {"lift:5F": {"to": "SILPH_CO_5F|2,2"}}}
ck("...and a lift ride is not a corridor either",
   dests(ex_with(L), "SILPH_CO_5F|2,2") == {})
D = {"PALLET_TOWN|10,0": {"12,11": {"to": "OAKS_LAB|4,1"}}}
ck("a DOOR is not reversed here — its own writer does that",
   dests(ex_with(D), "OAKS_LAB|4,1") == {})

# ---- two crossings of one seam landing apart keep both ----------------
T = {"A|1,1": {"west": {"to": "B|5,5"}},
     "A|9,9": {"west#skip2": {"to": "B|7,7"}}}
back = dests(ex_with(T), "B|5,5")
ck("the seam that landed here is the one offered back",
   back.get("east") == "A|1,1")
two = dests(ex_with({"A|1,1": {"west": {"to": "B|5,5"}},
                     "A|9,9": {"west#skip2": {"to": "B|5,5"}}}), "B|5,5")
ck("...and two crossings into ONE part keep both ways back, not one",
   sorted(two.values()) == ["A|1,1", "A|9,9"])

# ---- the rule reads the base of the key, whatever the suffix ----------
for suffix in ("#skip1", "#skip12", "#alt", "#altx"):
    g = {"X|1,1": {"north" + suffix: {"to": "Y|2,2"}}}
    ck(f"'north{suffix}' reverses",
       dests(ex_with(g), "Y|2,2").get("south") == "X|1,1")
ck("something that merely starts with a direction does not",
   dests(ex_with({"X|1,1": {"northern_door": {"to": "Y|2,2"}}}),
         "Y|2,2") == {})

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

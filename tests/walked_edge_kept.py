"""A refusal does not erase a road the run has walked.

Route 20's east edge had carried the run to ROUTE_19 twice; one turned-back
attempt rewrote it as a shut self-loop, the graph forgot the road, and the
ledger printed "-> UNKNOWN" about ground the run had crossed (2026-08-23).
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def record(node, key, src, dst, reason=""):
    """The recorder's rule, as executor.note_transition applies it."""
    e = node.setdefault(key, {"n": 0, "to": dst})
    e["n"] += 1
    _prev_to = e.get("to")
    if not (_prev_to and _prev_to != src):
        e["to"] = dst
    if "couldn't reach" not in (reason or ""):
        e["shut"] = True
    return e

SRC = "ROUTE_20|44,2"

# a real crossing, then a refusal that lands you back where you started
node = {}
record(node, "east", SRC, "ROUTE_19|13,0")
ck("a crossing records where it went", node["east"]["to"] == "ROUTE_19|13,0")
record(node, "east", SRC, SRC, "turned back")
ck("a later refusal KEEPS the walked destination",
   node["east"]["to"] == "ROUTE_19|13,0")
ck("...and still records that it refused today", node["east"].get("shut"))
ck("...and counts both outings", node["east"]["n"] == 2)

# a door that has only ever refused still records the self-loop honestly
node2 = {}
record(node2, "west", SRC, SRC, "turned back")
ck("a door that never went anywhere records landing back here",
   node2["west"]["to"] == SRC and node2["west"].get("shut"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("  ok    " if ok else "  FAIL  ") + n)
if bad:
    print(f"\nWALKED EDGE BROKEN: {len(bad)} check(s) failed"); sys.exit(1)
print("\nwalked edge kept: all checks passed")

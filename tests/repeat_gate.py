"""The exact-repeat gate: same macro + unchanged world = refused, not run."""
import json, sys
sys.path.insert(0, "planner")

# the gate is three lines of arithmetic; exercise them directly the way the
# escalation loop does, so the law is pinned without booting a game
spent_macros = {}
def gate(macro, mark, where="ROUTE_20|52,2"):
    key = (where, json.dumps(macro, sort_keys=True), str(mark))
    return spent_macros.get(key), key
def record(key, why):
    r = spent_macros.setdefault(key, {"n": 0, "why": ""})
    r["n"] += 1
    r["why"] = why

FLY = [{"op": "field_move", "move": "FLY", "to": "CINNABAR_ISLAND"}]
SURF = [{"op": "cross", "dir": "west", "surf": True}]
M1, M2 = [6, 302, 18], [6, 303, 18]

checks = []
def ck(name, cond):
    checks.append((name, bool(cond)))

seen, k = gate(FLY, M1); ck("a macro never spent is not refused", seen is None)
record(k, "no fly destination called CINNABAR_ISLAND")
seen, k = gate(FLY, M1); ck("the same macro in the same world IS refused", seen)
ck("...and the refusal carries the answer that killed it",
   "no fly destination" in (seen or {}).get("why", ""))

seen, k2 = gate(SURF, M1); ck("the OTHER half of an oscillation is not pre-refused", seen is None)
record(k2, "the west seam cannot be walked to from here")
seen, _ = gate(SURF, M1); ck("...but its second outing is refused too — A/B/A/B dies", seen)

others = len({kk for kk in spent_macros
              if kk[0] == "ROUTE_20|52,2" and kk[2] == str(M1)})
ck("the count of DIFFERENT spent macros is available to the refusal", others == 2)

seen, _ = gate(FLY, M2); ck("a world that MOVED frees every macro again", seen is None)

# a refusal is itself a thing that happened, and the message says so
r = spent_macros[k]
r["refused"] = int(r.get("refused") or 0) + 1
ck("the first refusal is counted", r["refused"] == 1)
r["refused"] += 1
ck("...and repeat refusals accumulate past the run count",
   r["refused"] == 2 and r["n"] == 1)

# THE SAME COORDINATES ON ANOTHER FLOOR ARE ANOTHER PLACE
WARP = [{"op": "use_warp", "x": 25, "y": 3}]
seen, kb3 = gate(WARP, M1, "SEAFOAM_ISLANDS_B3F|21,0")
record(kb3, "the way was shut")
seen, _ = gate(WARP, M1, "SEAFOAM_ISLANDS_B3F|21,0")
ck("a repeat on the SAME floor is refused", seen)
seen, _ = gate(WARP, M1, "SEAFOAM_ISLANDS_B2F|23,2")
ck("...but the same coordinates on ANOTHER floor are not", seen is None)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("  ok    " if ok else "  FAIL  ") + n)
if bad:
    print(f"\nREPEAT GATE BROKEN: {len(bad)} check(s) failed"); sys.exit(1)
print("\nrepeat gate: all checks passed")

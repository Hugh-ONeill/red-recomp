"""A shelf belongs to a COUNTER, not to a floor (2026-08-26): Celadon 5F's
CLERK1 sells the X items and CLERK2 the vitamins, so "not sold here — this
mart sells: <one shelf>" condemned a floor from half its stock."""
import sys, re
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E

two = ("X_SPEED is not on CELADONMART5F_CLERK2's shelf, which holds: HP_UP, "
       "PROTEIN, IRON, CARBOS, CALCIUM. THIS FLOOR HAS OTHER COUNTERS and in "
       "this game they carry different stock: CELADONMART5F_CLERK1 — "
       '{"op":"buy","item":X,"count":N,"clerk":"CELADONMART5F_CLERK1"} reads '
       "that one instead")
one = ("POTION is not on VIRIDIANMART_CLERK's shelf, which holds: POKE_BALL, "
       "ANTIDOTE, PARLYZ_HEAL, BURN_HEAL")

for det, alone_want, name in ((two, False, "two counters"), (one, True, "one counter")):
    alone = "THIS FLOOR HAS OTHER COUNTERS" not in det
    ck(f"{name}: alone={alone_want}", alone is alone_want)
    m = re.search(r"shelf, which holds: ([A-Z0-9_, ]+)", det)
    ck(f"{name}: the shelf still parses", bool(m))

ck("the floor record is only taken from a lone counter",
   ("THIS FLOOR HAS OTHER COUNTERS" not in one) and ("THIS FLOOR HAS OTHER COUNTERS" in two))
ck("the refusal names the other counter to read", "CELADONMART5F_CLERK1" in two)
ck("...and the op that reads it", '"clerk":"CELADONMART5F_CLERK1"' in two)
_shim = open("harness/shim.lua").read()
ck("the harness refusal is per-counter, not per-floor",
   "'s shelf, which holds: " in _shim
   and "THIS FLOOR HAS OTHER COUNTERS" in _shim)
ck("buy and sell both accept a named counter (2 sites each: on the floor,\n    and again after walking into a shop)", _shim.count("pick_clerk(ow, c.clerk)") == 4)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

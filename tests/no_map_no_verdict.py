"""No map, no verdict. A box on screen means the observation has no map;
the ledger page then called Oak's lab FULLY WORKED with three starter
balls untouched (2026-08-25, leg 1). What is on screen is the only fact."""
import sys
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E, ledger
ex = E.Executor.__new__(E.Executor)
ex.visits, ex.explored = {}, {}
ex._where = lambda o: "None|None"
obs = {"mode": "ui", "last_text": "So! You want the fire POKéMON, CHARMANDER?",
       "recent_text": "So! You want the fire POKéMON, CHARMANDER?"}
t = ledger.render([], ex, obs, "party_size:1")
ck("no map: the page says the screen is not the overworld", "NOT THE OVERWORLD" in t)
ck("it quotes what the box says", "CHARMANDER" in t)
ck("it never says fully worked", "FULLY WORKED" not in t)
ck("it never prints a None address", "None|None" not in t)
ck("it names the op that closes a box", '"op":"tap"' in t)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

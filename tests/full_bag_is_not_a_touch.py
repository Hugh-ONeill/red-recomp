"""A ball you could not carry is still lying there.

Pressing an item ball with a full bag answers "No more room for items!" and
LEAVES THE BALL WHERE IT IS. Recorded as a touch anyway, POKEMON_MANSION_
B1F's (5,13) and (5,4) — one of them the Secret Key — sat in the author's
evidence with no * on them, reading exactly like the ten balls the run had
actually collected, and the leg was replanned as a tour of the floors
upstairs (user, 2026-08-23: "items that arent taken shouldnt be done").

The touch rule at the top of executor.py says a touch is an interaction
that COMPLETED, and asks that any fourth condition be added in BOTH places
that implement it: _record_touch (the sweep) and _run_traced (the walker).
"""
import re
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


NEEDLE = "No more room for items"

# 1. the sweep side refuses to write the touch
i = src.find("def _record_touch")
body = src[i:src.find("\n    def ", i + 10)]
ck("_record_touch refuses a full-bag press", NEEDLE in body)
ck("...by returning False, not by recording it",
   re.search(NEEDLE + r'[^\n]*\n\s*return False', body) is not None)

# 2. the walker side retracts it
ck("_run_traced retracts a full-bag press",
   re.search(NEEDLE + r'[\s\S]{0,200}?_retract_touch', src) is not None)

# 3. the other three conditions are still there
for cond, label in ((r"blackout and op == \"interact\"", "a wipe"),
                    (r"ASKING in str\(r\.get\(\"detail\"", "an unanswered question"),
                    (r"asked WHICH POKEMON", "a backed-out picker")):
    ck(f"the existing condition for {label} survives",
       re.search(cond, src) is not None)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

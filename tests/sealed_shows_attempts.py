"""The most-repeated action on the page carried no count.

Every other entry says how worn it is -- "taken 14x", "pressed 7x" -- but a
sealed seam said only "proven uncrossable from this area", because n counts
times TAKEN and a way that never once worked has n=0.  So the page numbered
everything the run had managed and went silent on everything it had failed
at: `walk west` looked no more worn than an untried door while the outcomes
ledger held 184 attempts from that very spot against that very goal.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import ledger

def words(status, n):
    st = "sealed_untried" if (status == "sealed" and not n) else status
    return ledger._STATUS_WORDS.get(st, st).format(n=n)

ck("a sealed seam reached for 184x says so", "184" in words("sealed", 184))
ck("it still says it is proven uncrossable",
   "proven uncrossable" in words("sealed", 184))
ck("it says it never once got through",
   "never once got through" in words("sealed", 184))
ck("a sealed seam never tried reads plainly",
   words("sealed", 0) == "proven uncrossable from this area")
ck("no entry ever reads 'reached for 0x'", "0x" not in words("sealed", 0))

# the neighbouring statuses are untouched
ck("taken still counts", words("taken", 14) == "taken 14x")
ck("pressed still counts", words("touched", 7) == "pressed 7x")
ck("spent still says it", "never once got through" in words("spent", 9))
ck("untried is still untried", words("untried", 0) == "never taken from here")

# and the real page renders the number
HERE = "ROUTE_20|44,2"
class _Ex:
    explored = {HERE: {}}
    visits = {HERE: 218}
    frontier = {HERE: ["west", "east"]}
    def _where(self, _o): return HERE
    def _walked_dest(self, *_a): return None
    def dead_for(self, *_a, **_k): return 0
    def __getattr__(self, _n): return {}

c = ledger.Candidate(key="west", kind="seam", status="sealed", n=184)
obs = {"party": [], "map": {"id": "ROUTE_20", "region": "44,2"}}
page = ledger.render([c], _Ex(), obs)
ck("the rendered page shows the count", "184x" in page)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("PAGE:", page[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

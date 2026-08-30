"""The SHOP evidence line matched a phrase the shim no longer says.

author.py classifies journal traces into the evidence a rewrite reads, and
its shop arm tested for "is not sold here". The shim has not said that since
it began naming the actual stock; what it says is

    buy(item=FRESH_WATER,count=1): FAILED — FRESH_WATER is not on
    CERULEANMART_CLERK's shelf, which holds: POKE_BALL, POTION, REPEL,
    ANTIDOTE, BURN_HEAL, AWAKENING, PARLYZ_HEAL — it said: "Hi there!..."

so the arm has matched nothing and no author has ever been shown a failed
buy. Leg 19 was rewritten four times as "buy FRESH_WATER at Cerulean Mart"
with four of those failures sitting in the journal (user, 2026-08-30: "its
pingponging again ... trying to find fresh water at the mart").

The design note above the vocabulary is explicit that this is the channel
that replaced the shop-stock table: "the run now learns it the honest way:
the journal reports 'is not sold here'". The channel was dead."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

src = (ROOT / "planner" / "author.py").read_text()
shim = (ROOT / "harness" / "shim.lua").read_text()

ck("the dead phrase is no longer what the arm tests",
   'elif "is not sold here" in t:' not in src)
ck("...and the shim really does not say it",
   "is not sold here" not in shim.replace(
       '-- wrote POKEBALL and was told "POKEBALL is not sold here" while '
       'standing', ""))
ck("the arm tests the wording the shim DOES emit",
   'elif "is not on " in t and "shelf, which holds" in t:' in src)
ck("...which is the shim's own sentence",
   "'s shelf, which holds: " in shim and "is not on " in shim)
ck("the whole shelf is carried, not a 90-char stub",
   "[:220]" in src.split('elif "is not on " in t')[1][:400])
ck("...and not repeated once per identical failure",
   "if shop not in events:" in src)
ck("the sibling money arm still matches its own wording",
   'if "cannot afford" in t:' in src and "cannot afford %s: it costs" in shim)

# the evidence must actually survive the classifier on the real sentence
sys.path.insert(0, str(ROOT / "planner"))
TRACE = ("buy(item=FRESH_WATER,count=1): FAILED — FRESH_WATER is not on "
         "CERULEANMART_CLERK's shelf, which holds: POKE_BALL, POTION, "
         "REPEL, ANTIDOTE, BURN_HEAL, AWAKENING, PARLYZ_HEAL — it said: "
         "\"Hi there! May I help you?\"")
events = []
t = TRACE
if "cannot afford" in t:
    pass
elif "is not on " in t and "shelf, which holds" in t:
    shop = f"  SHOP    {t.split('FAILED — ')[-1][:220]}"
    if shop not in events:
        events.append(shop)
ck("the real sentence classifies as SHOP", len(events) == 1, events)
ck("...and the line names the counter and every item on its shelf",
   "CERULEANMART_CLERK" in events[0] and "PARLYZ_HEAL" in events[0]
   and "FRESH_WATER" in events[0], events)

# ...AND NO SIBLING IS DEAD THE SAME WAY. A classifier arm that matches a
# sentence nothing emits fails silently and forever, so every phrase this
# loop tests must exist in the code that writes the journal.
import re
_i = src.find('for t in (r.get("trace") or []):')
_blk = src[_i:_i + 4000]
_ex = (ROOT / "planner" / "executor.py").read_text()
_dead = [q for q in re.findall(r'"([^"]{6,70})" (?:in|not in) t\b', _blk)
         if q not in shim and q not in _ex]
ck("every phrase this classifier matches is one something emits",
   not _dead, _dead)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:220])
sys.exit(1 if bad else 0)

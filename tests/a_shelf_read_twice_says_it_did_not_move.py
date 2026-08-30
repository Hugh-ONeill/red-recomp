"""A shop's shelf is dated by the run's own readings (2026-08-30).

"SHOPS YOU HAVE WALKED INTO AND WHAT THEY WERE SELLING" is past tense about
a list, which reads as an open question — and the run answered it by walking
seven legs back to CERULEAN_MART "specifically thinking 'maybe there are new
items'" (user), on a leg that needs FRESH_WATER, which no mart it has walked
into sells.

Whether a shelf restocks is NOT the harness's to rule on: Viridian's does
change, once. What is the harness's to say is what this run has actually
seen — how many times it has read that shelf, and whether the list ever came
back different. Evidence, not a rule; the inference stays the model's."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ex = E.Executor.__new__(E.Executor)
ex.log = lambda *a, **k: None
ex._save_memory = lambda *a, **k: None
ex._shelves, ex._shelf_reads, ex._shelf_machine = {}, {}, set()

DET = ("pressed the clerk and opened a menu of things for sale: "
       "1=POKE BALL ¥200, 2=POTION ¥300. Nothing was chosen")
ex._record_machine_stock("CERULEAN_MART|0,2", DET)
ck("a first reading is recorded", ex._shelves["CERULEAN_MART"]
   == ["POKE_BALL", "POTION"] and ex._shelf_reads["CERULEAN_MART"]["n"] == 1)
ex._record_machine_stock("CERULEAN_MART|0,2", DET)
ex._record_machine_stock("CERULEAN_MART|0,2", DET)
ck("...and so is every reading after it, unchanged or not",
   ex._shelf_reads["CERULEAN_MART"]["n"] == 3, ex._shelf_reads)
ck("...an unmoved shelf is not marked moved",
   ex._shelf_reads["CERULEAN_MART"]["moved"] is False)
ex._record_machine_stock(
    "CERULEAN_MART|0,2",
    "opened a menu of things for sale: 1=POKE BALL ¥200, 2=REPEL ¥350. "
    "Nothing was chosen")
ck("a shelf that comes back different is marked moved",
   ex._shelf_reads["CERULEAN_MART"]["moved"] is True
   and ex._shelves["CERULEAN_MART"] == ["POKE_BALL", "REPEL"])

src = (ROOT / "planner" / "executor.py").read_text()
ck("the reading history is persisted with the shelves",
   '"shelf_reads": getattr(self, "_shelf_reads", {})' in src
   and 'self._shelf_reads = data.get("shelf_reads") or {}' in src)
ck("the counter site counts its readings too",
   "_h5 = self._shelf_reads.setdefault(" in src)
i = src.find("def _seen_note(_sm):")
ck("the page says how many times a shelf was read", i > 0)
blk = src[i:i + 1400]
ck("...only once there is more than one reading to compare",
   "if _n < 2:" in blk)
ck("...saying plainly that it did not move",
   "the same list every time" in blk)
ck("...and plainly when it did",
   "come back " in blk and "DIFFERENT at least once" in blk)
# THE RULE IS NOT OURS TO STATE. Viridian's mart restocks after the parcel,
# so "shops do not restock" would be a fabricated absolute of exactly the
# kind the shelf record was split per-counter to avoid.
ck("no claim about restocking in general",
   "never restock" not in src and "do not restock" not in src
   and "always the same" not in blk)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)

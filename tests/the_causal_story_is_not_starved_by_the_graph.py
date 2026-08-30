"""The journal never survived the evidence budget (2026-08-30).

`_fit` trims the LARGEST block. The walked graph arrives as a dozen middling
blocks and the journal as two big ones — "WHAT HAPPENED ON THE LAST RUN"
(5644 chars) and "WHAT EACH STEP OF THAT PLAN TRIED" (5916) — so the causal
story was the first thing trimmed, every pass, until it was gone. Measured
on leg 19: observed 21958 characters of a 22000 budget, journal 12750, and
SEVENTY characters of journal survived. Four "FRESH_WATER is not on
CERULEANMART_CLERK's shelf" lines sat in that journal; none reached an
author, which is why leg 19 was rewritten five times as "buy Fresh Water at
Cerulean Mart" (user, 2026-08-30).

The graph says what EXISTS; the journal says what HAPPENED when the run
tried it. Neither may starve the other.

Two smaller things fell out of fixing it, both in `_fit`:
  - the largest block may be one that CANNOT give lines back (AREA CODES is
    2359 characters on two lines), and giving up there hard-cut the tail;
  - skipping those removed the accidental bail-out that stopped the loop, so
    it spun forever — the 12-minute CPU burn the guard below it was written
    for. Length is what is bounded, so length has to fall on every pass.
"""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

src = (ROOT / "planner" / "author.py").read_text()
ck("the journal has a named floor, not a leftover",
   "JOURNAL_SHARE" in src and "_j_floor = min(len(_j)" in src)
ck("...and the graph gets the larger share",
   0 < A.JOURNAL_SHARE < 0.5, A.JOURNAL_SHARE)
ck("...with either free to use what the other leaves",
   "_fit(_o, max(0, _room - _j_floor))" in src
   and "_fit(_j, max(0, _room - len(_o)))" in src)

# --- a graph that would eat the whole budget leaves the story standing ---
GRAPH = "\n\n".join(
    f"BLOCK {i} OF THE WALKED GRAPH (what exists)\n"
    + "\n".join(f"  ROUTE_{i}|{j},0 --{j},1--> ROUTE_{i+1}|0,0"
                for j in range(40))
    for i in range(40))
STORY = ("\n\nWHAT HAPPENED ON THE LAST RUN, in order:\n"
         + "\n".join("  SHOP    FRESH_WATER is not on CERULEANMART_CLERK's "
                     f"shelf, which holds: POKE_BALL, POTION ({i})"
                     for i in range(40)))
ck("the graph alone would fill the budget", len(GRAPH) > A.EVIDENCE_BUDGET)
t0 = time.time()
out = A._fit(GRAPH, int(A.EVIDENCE_BUDGET * (1 - A.JOURNAL_SHARE))) \
    + A._fit(STORY, int(A.EVIDENCE_BUDGET * A.JOURNAL_SHARE))
el = time.time() - t0
ck("the story survives beside it", "SHOP" in out and "FRESH_WATER" in out)
ck("...and so does the graph", "WALKED GRAPH" in out)
ck("the fit terminates promptly", el < 20, f"{el:.1f}s")

# --- the loop must always take something out ---
ck("a pass that removes nothing stops the loop",
   "_last is not None and len(text) >= _last" in src)
STUCK = "\n\n".join(f"HEAD {i}\n" + "\n".join(f"  line {j}" for j in range(3))
                    for i in range(30))
t0 = time.time()
A._fit(STUCK, 50)
ck("...even when no block can give a line back", time.time() - t0 < 10)

# --- and what does not fit is NAMED, never silently gone ---
ck("the last resort drops whole sections", "def _hard(" in src
   and "text[:budget] + \"\\n[evidence truncated to fit]\"" not in src)
gone = A._hard(GRAPH, 4000)
ck("...saying how many are missing and which",
   "EVIDENCE DID NOT FIT" in gone and "whole section(s) are missing" in gone
   and "BLOCK 11 OF THE WALKED GRAPH" in gone.split("DID NOT FIT")[1])
ck("...and never cuts a section in half",
   all(b.startswith("BLOCK") or b.startswith("[EVIDENCE")
       for b in gone.split("\n\n") if b.strip()
       and not b.startswith("  ")), gone[-200:])

# --- the biggest section makes room, not the last one written ---
# Dropping from the end sacrifices whatever happens to be written last,
# however small: the shelf record is ten lines and it sat at the tail.
BIG = "HUGE SECTION\n" + "\n".join(f"  filler line {i}" for i in range(400))
SMALL = "TINY BUT DECIDING SECTION\n  CERULEAN_MART: POKE_BALL, POTION"
kept = A._hard(BIG + "\n\n" + SMALL, 1200)
ck("a small trailing section survives a huge one",
   "CERULEAN_MART" in kept and "filler line 300" not in kept, kept[:120])
ck("...and the drop is named", "HUGE SECTION" in kept.split("DID NOT FIT")[1])

# --- vocabulary is not evidence and is never dropped ---
VOCAB = ("AREA CODES you may use with the \"area\" predicate\n  "
         + "X" * (len(BIG) + 500))
kept = A._hard(VOCAB + "\n\n" + BIG + "\n\n" + SMALL, 3400)
ck("the area vocabulary is never the thing dropped",
   "AREA CODES you may use" in kept, kept[:100])
ck("...even when it is the largest block", len(VOCAB) > len(BIG))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:220])
sys.exit(1 if bad else 0)

#!/usr/bin/env python3
"""Too early is asked before wrong sentence, and the wording prompt says
only what was actually asked.

"Obtain the Secret Key" sat between "Enter the Safari Zone" and "Navigate
the Safari Zone" — a misplacement. The ladder asked the WORDING rung
before the LATER rung, and the wording prompt opened "every other
question has already been asked and answered … no later objective of
yours has to come first" while too-early had never been asked. With
ordering declared settled, the only story left was a wrong sentence, and
the leg was rewritten three times into three wrong places (2026-08-26).
User: "it's essentially codified a hallucination where there wasn't one
before … just a misplacement in ordering."

A push is cheap and reversible; a rewrite is permanent (the old wording is
barred). The cheap one goes first, and the prompt lists what was asked.
"""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

sh = (ROOT / "fresh_discovery.sh").read_text()
fail = sh.index('if [ "$failed" = 1 ]; then')
tail = sh[fail:]
later = tail.index("--check-later")
word = tail.index('wording_rung "done,blocker,missing,later"')
ck("in the failure path the later rung is asked before the wording rung",
   later < word)
ck("...and the wording rung is told exactly what was asked before it",
   'wording_rung "done,blocker,missing,later"' in tail)
ck("the early ask (after the first attempt) says what little was asked",
   'wording_rung "$_early_asked"' in sh and '_early_asked="missing"' in sh)
ck("--asked reaches check-wording", '--asked "${1:-}"' in sh)
ck("the wording prompt no longer claims every other question was answered",
   "every other question" not in A.WORDING_SYS
   and "no later objective of yours has to come first" not in A.WORDING_SYS)

captured = []
def fake_chat(msgs, model):
    captured.append(msgs[-1]["content"])
    return '{"why": "fine", "reword": null}'
A.brock_probe.chat = fake_chat
A.recent_events = lambda: ""
A.done_ledger_text = lambda: ""
ahead = [(36, "Obtain the Secret Key"), (37, "Navigate the Safari Zone")]
A.check_wording("Obtain the Secret Key", ahead, [], "start", "", "m",
                asked=("done", "blocker", "missing", "later"))
body = captured[-1]
ck("with every rung asked, the prompt lists them all",
   "ALREADY ASKED" in body and "too early" in body and "already done" in body)
A.check_wording("Obtain the Secret Key", ahead, [], "start", "", "m", asked=())
body = captured[-1]
ck("with nothing asked, the prompt says nothing is settled",
   "NO OTHER QUESTION HAS BEEN ASKED" in body and "ALREADY ASKED" not in body)
A.check_wording("Obtain the Secret Key", ahead, [], "start", "", "m", asked=("missing",))
ck("the early ask lists only the missing rung",
   "missing" in captured[-1].split("ALREADY ASKED")[-1]
   and "too early" not in captured[-1].split("ALREADY ASKED")[-1])

A.check_wording("Obtain the Secret Key", ahead, [], "start", "", "m", asked=None)
ck("a caller that does not say what was asked gets no claim either way",
   "ASKED" not in captured[-1])

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

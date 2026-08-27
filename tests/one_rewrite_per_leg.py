#!/usr/bin/env python3
"""A leg gets one rewrite. After that it is still asked — stands and VOID
are real answers — but the prompt says a rewrite is not on offer, and one
that comes back anyway is refused, not applied.

Three rewordings of "Obtain the Secret Key" at leg 36 spent the whole
rolling reword budget (3 per 12 legs) on one sentence, each a fresh wrong
place. User, 2026-08-27: "we probably shouldn't let it burn all of its
rewrites on the same leg."
"""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

tmp = Path(tempfile.mkdtemp(prefix="rewrite_"))
(tmp / "run").mkdir()
os.chdir(tmp)

captured, reply = [], ['{"why": "wrong place", "reword": "Obtain the Secret Key from the Mansion"}']
def fake_chat(msgs, model):
    captured.append(msgs[-1]["content"])
    return reply[0]
A.brock_probe.chat = fake_chat
A.recent_events = lambda: ""
A.done_ledger_text = lambda: ""
A.check_already_done = lambda *a, **k: False
ahead = [(36, "Obtain the Secret Key from the Secret House"), (37, "Navigate the Safari Zone")]

# a fresh leg: the rewrite is offered and applied
new = A.check_wording("Obtain the Secret Key", ahead, [], "start", "", "m", asked=())
ck("a leg never rewritten gets its rewrite", new == "Obtain the Secret Key from the Mansion")
ck("...and the prompt did not say a rewrite was off the table",
   "NOT ON OFFER" not in captured[-1])

# the same leg, already rewritten once
(tmp / "run/outline_rewordings").write_text(
    "36\tObtain the Secret Key\tObtain the Secret Key from the Secret House\n")
new = A.check_wording("Obtain the Secret Key from the Secret House", ahead, [],
                      "start", "", "m", asked=("later",))
ck("a leg rewritten once is told a second rewrite is not on offer",
   "A REWRITE IS NOT ON OFFER" in captured[-1] and "rewritten once already" in captured[-1])
ck("...stands and VOID are named as the answers open",
   "the wording stands, or the line is VOID" in captured[-1])
ck("...and a rewrite that comes back anyway is refused, not applied", new == "")
reply[0] = '{"why": "not here", "reword": null, "void": true}'
A.WORDING_SAYS_VOID[0] = False
new = A.check_wording("Obtain the Secret Key from the Secret House", ahead, [],
                      "start", "", "m", asked=("later",))
ck("VOID is still open to a leg that cannot be rewritten",
   new == "" and A.WORDING_SAYS_VOID[0])

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

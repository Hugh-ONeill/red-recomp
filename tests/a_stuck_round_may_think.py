#!/usr/bin/env python3
"""Deliberation is spent where the round is going nowhere, not everywhere.

`"think": False` sat in the request body from brock_probe's first commit
(b584e43, 2026-08-10) and was never once measured against the alternative
-- a default that had hardened into a finding. Measured 2026-09-10 on a
real 8.5k-token escalation context replayed out of run/executor_log.*.jsonl,
warm weights: gemma4:31b went 9.4 s / 66 tokens to 100.1 s / 2167, and
qwen3.8:27b 7.5 s / 103 to 12.0 s / 564. The two models are not the same
trade at all, and the 10x in the batch-scoring note is a GEMMA fact rather
than an ollama one.

Neither ratio is the one to budget with. A real round carries ~14748 prompt
tokens and spends 23.5 of its 29.3 seconds reading them, so thinking only
inflates the 4.2 s tail: a gemma thinking round lands near 118 s, ~4x a
round. Too dear to leave on, cheap enough to spend on the rounds that
changed nothing -- which is where deliberation is the thing missing.

So it is gated, off by default, on the stale count the executor already
keeps. Deliberately BELOW the stale budget's own cutoff: over 7872 real
rounds STALE_CUTOFF of 6 fired 12 times (0.15%), too rare to ever be there
when it was needed.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import brock_probe as B   # noqa: E402
src = (ROOT / "planner" / "brock_probe.py").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
ag = (ROOT / "planner" / "agent.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

# OFF IS THE DEFAULT, AND OFF MEANS UNCHANGED. Every run that does not ask
# for this must send exactly the body it always sent; a lever that alters
# the baseline cannot be used to measure against the baseline.
ck("thinking is off unless the environment asks for it",
   B.THINK_ON_STUCK == 0)
ck("a call does not think unless its caller says to",
   "def chat(msgs, model, retries=2, think=False)" in src
   and "def _chat_once(msgs, model, think=False)" in src)
ck("the flag reaches the request body rather than stopping at the door",
   '"think": bool(think)' in src)
ck("the threshold is set by environment, like the window and the ceiling",
   'os.environ.get("RED_THINK_ON_STUCK")' in src)

# THE GATE READS THE STUCK SIGNAL THAT ALREADY EXISTS. _stale_rounds counts
# rounds that changed nothing you carry, know or are, per subgoal, and the
# stale budget keeps it whether or not anything thinks. Reading it is free;
# a second, parallel notion of "stuck" would be one more thing to drift.
ck("the gate reads the executor's own stale count",
   "self._stale_rounds >= brock_probe.THINK_ON_STUCK" in ex)
ck("it does not touch the count it reads",
   "_think = (brock_probe.THINK_ON_STUCK > 0" in ex)
ck("the escalation call is the one that may think",
   "self.model,\n                    think=_think)" in ex)

# A ROUND THAT THINKS SAYS SO, TWICE OVER: once when the gate opens, with
# what opened it, and again in the proposal row via stats_of. Neither alone
# is enough -- the first says what was intended, the second what it cost.
ck("the gate says when it fired and what opened it",
   'self.log("think_on"' in ex and "stale=self._stale_rounds" in ex
   and "threshold=brock_probe.THINK_ON_STUCK" in ex)
ck("and the round's own row carries what it cost",
   B.stats_of({"message": {"thinking": "..."}})["think"] is True)

# THE SECOND BODY DOES NOT DRIFT. agent.py carries its own copy of the
# request and its comment already says the two must not diverge -- they had
# diverged on num_ctx once before, silently, and a card swap changed the
# window underneath a run.
ck("the other request body carries the same parameter",
   "def ollama_chat(messages, model, think=False)" in ag
   and '"think": bool(think)' in ag)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("ok  " if ok else "FAIL"), n)
print(("ok " if not bad else "FAIL ") + f"{len(checks) - len(bad)}/{len(checks)} checks")
sys.exit(1 if bad else 0)

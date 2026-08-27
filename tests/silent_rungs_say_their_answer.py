#!/usr/bin/env python3
"""The blocker and missing rungs say their answer, "none" included.

Leg 37 stopped with no Seafoam leg inserted and the chain log had no
line from either rung: "none" and a turned-down proposal were both
silent, so there was no telling whether the rungs were asked, declined,
or had their answers thrown away (user, 2026-08-27: "why didn't it insert
a 'seafoam islands' leg?"). A rung that answers in silence cannot be
audited.
"""
from __future__ import annotations
import contextlib, io, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

tmp = Path(tempfile.mkdtemp(prefix="rungs_")); (tmp / "run").mkdir(); os.chdir(tmp)
reply = ['{"why": "nothing is missing", "insert": null}']
def fake_chat(msgs, model): return reply[0]
A.brock_probe.chat = fake_chat
A.done_ledger_text = lambda *a, **k: ""
A.check_already_done = lambda *a, **k: False
ahead = [(37, "Reach Cinnabar Island"), (38, "Defeat Blaine")]

def missing():
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = A.check_missing("Reach Cinnabar Island", ahead, "start", "m", behind=[(36, "Defeat Koga")], tries=3)
    return out, err.getvalue()

out, err = missing()
ck("a 'none' from the missing rung is said, with its reason", out == "" and "[missing] none: nothing is missing" in err)
reply[0] = '{"why": "it is on the list", "insert": "Reach Cinnabar Island"}'
out, err = missing()
ck("a proposal already on the list is said to be turned down", out == "" and "turned down 'Reach Cinnabar Island': already on your own list" in err)
ck("...and the exhausted tries are said", "every proposal was turned down" in err)
A.check_already_done = lambda *a, **k: True
reply[0] = '{"why": "must go through", "insert": "Go through the Seafoam Islands"}'
out, err = missing()
ck("a proposal judged already done is said to be turned down", out == "" and "judged already done" in err and "Seafoam" in err)
A.check_already_done = lambda *a, **k: False
out, err = missing()
ck("an accepted proposal is said", out == "Go through the Seafoam Islands" and "[missing] 'Go through the Seafoam Islands'" in err)
reply[0] = "I cannot answer that"
out, err = missing()
ck("no parseable answer is said", out == "" and "no parseable answer" in err)

def blocker(rep):
    reply[0] = rep
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = A.check_blocker("Reach Cinnabar Island", ahead, "start", "", "m", leg=37)
    return out, err.getvalue()
out, err = blocker('{"why": "nothing later must come first", "pull_forward": null}')
ck("a 'none' from the blocker rung is said, with its reason", not out and "[blocker] none: nothing later must come first" in err)
out, err = blocker("no json here")
ck("...and a non-answer", not out and "[blocker] no parseable answer" in err)
out, err = blocker('{"why": "x", "pull_forward": 99}')
ck("...and a leg number that is not ahead", not out and "not a leg still ahead" in err)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

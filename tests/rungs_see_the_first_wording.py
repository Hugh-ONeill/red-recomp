#!/usr/bin/env python3
"""Every rung that judges a leg sees the objective as it was FIRST written.

Once "Obtain the Secret Key" had been rewritten into "... from the Secret
House in the Safari Zone", the too-early question was being asked about a
sentence naming ground the run stood on, and could only answer "not
later". User, 2026-08-27: "it's not going to be recognized as supposed to
be happening later if we're using the altered version after leg rewrites;
we have to consider the original version."
"""
from __future__ import annotations
import inspect, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

tmp = Path(tempfile.mkdtemp(prefix="lineage_"))
(tmp / "run").mkdir()
os.chdir(tmp)
FIRST = "Obtain the Secret Key"
MID = "Obtain the Secret Key from the Warden in the Secret House"
NOW = "Obtain the Secret Key from the Secret House in the Safari Zone"
(tmp / "run/outline_rewordings").write_text(f"36\t{FIRST}\t{MID}\n36\t{MID}\t{NOW}\n")

text = A._wording_lineage(NOW)
ck("a rewritten leg's lineage opens with the first wording",
   "AS YOU FIRST WROTE IT: " + FIRST in text)
ck("...lists every rewrite, oldest first",
   text.index(f"{FIRST} -> {MID}") < text.index(f"{MID} -> {NOW}"))
ck("...and says which line is the intent", "what you set out to do" in text)
ck("a leg never rewritten has no lineage", A._wording_lineage(FIRST) == "")

captured = []
reply = ['{"why": "x", "after": null}']
def fake_chat(msgs, model):
    captured.append(msgs[-1]["content"])
    return reply[0]
A.brock_probe.chat = fake_chat
A.recent_events = lambda: ""
A.done_ledger_text = lambda: ""
ahead = [(36, NOW), (39, "Reach Cinnabar Island")]
A.check_later(NOW, 36, ahead, "start", "", "m")
ck("the later rung shows the first wording", "AS YOU FIRST WROTE IT: " + FIRST in captured[-1])
reply[0] = '{"why": "x", "leg": null}'
A.check_blocker(NOW, ahead, "start", "", "m", leg=36)
ck("the blocker rung shows it too", "AS YOU FIRST WROTE IT: " + FIRST in captured[-1])
for fn in (A.check_missing, A.check_done):
    ck(f"{fn.__name__} builds its prompt with the lineage",
       "_wording_lineage(goal)" in inspect.getsource(fn))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

#!/usr/bin/env python3
"""check-done's place guard matches a town by its first word, and an item
the objective names, sitting in the bag, is evidence enough.

"Retrieve the HM03 from the Cinnabar Island gym" met its plan at once
(HM_SURF had been in the bag for days) and was REFUSED: the guard wanted
the literal "CINNABAR_ISLAND" inside an event name, and the gym's events
say CINNABAR_GYM; nothing let the bag speak. The leg paid for a second
author pass (2026-08-28).
"""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
tmp = Path(tempfile.mkdtemp(prefix="town_")); (tmp / "run").mkdir(); os.chdir(tmp)
(tmp / "run/obs.json").write_text(json.dumps({"bag": {"HM_SURF": 1, "BICYCLE": 1}, "flags": []}))
seen = []
def fake_chat(msgs, model):
    seen.append(msgs[-1]["content"]); return '{"why": "x", "done": true}'
A.brock_probe.chat = fake_chat
A.recent_events = lambda: ""
A._never_stood_in = lambda *a, **k: None
A._badge_not_earned = lambda *a, **k: None
A._levels_not_reached = lambda *a, **k: None
A._item_not_held = lambda *a, **k: None
A._events_bearing = lambda goal: "\n\nEVENTS: EVENT_BEAT_CINNABAR_GYM_TRAINER_0, EVENT_BEAT_BLAINE"
import io, contextlib
def judge(goal, gained=""):
    err = io.StringIO()
    with contextlib.redirect_stdout(err):
        out = A.check_done(goal, "standing in CINNABAR_GYM", "m", gained=gained)
    return out, err.getvalue()
out, err = judge("Retrieve the HM03 from the Cinnabar Island gym")
ck("an item named by the objective and held in the bag lets the judge be asked", out is True and "refused" not in err)
A._events_bearing = lambda goal: "\n\nEVENTS: EVENT_BEAT_CINNABAR_GYM_TRAINER_0"
out, err = judge("Defeat the trainers in the Cinnabar Island gym")
ck("a town is matched by its first word in an event name", out is True and "refused" not in err)
A._events_bearing = lambda goal: "\n\nEVENTS: EVENT_BEAT_ROUTE16_SNORLAX"
out, err = judge("Wake the Snorlax sleeping on Route 12")
ck("the other Snorlax is still refused", out is False and "somewhere else" in err)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

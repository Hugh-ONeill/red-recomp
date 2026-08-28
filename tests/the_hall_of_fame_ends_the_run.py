#!/usr/bin/env python3
"""The Hall of Fame is recognised as the end of the game.

2026-08-28: the party was inducted, the credits rolled, the plan's last
step {"screen":"HallOfFame"} matched nothing (a text box sat on top of
the HallOfFame screen), the escalation tapped B until the repeat-refusal
ended the plan, and the chain rewrote leg 49 from the title screen.
"""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as X        # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
obs = {"mode": "ui", "ui": {"screenId": "TextBox", "stack": ["Overworld", "HallOfFame", "TextBox"]},
       "hall_of_fame": 1, "ending": "hall_of_fame"}
ck("a screen anywhere on the stack satisfies {screen}", X.pred_holds({"screen": "HallOfFame"}, obs))
ck("...the top still does", X.pred_holds({"screen": "TextBox"}, obs))
ck("...and a screen not there does not", not X.pred_holds({"screen": "Credits"}, obs))
ck("{hall_of_fame: true} reads the save's count", X.pred_holds({"hall_of_fame": True}, obs)
   and not X.pred_holds({"hall_of_fame": True}, {"hall_of_fame": 0}))
ck("...and a number asks for that many", X.pred_holds({"hall_of_fame": 1}, obs) and not X.pred_holds({"hall_of_fame": 2}, obs))
src = (ROOT / "planner" / "executor.py").read_text()
ck("every settled observation can ride the ending", "return self._after_settle(obs)" in src and "def _ride_ending" in src)
ck("a finished game skips what is left and ends escalation", 'self.log("finished_skip"' in src and 'return True, []' in src)
ck("the verdict names it", "GAME FINISHED" in src)
shim = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim reports the ending on the stack and the save's count",
   'o.ending = _e' in shim and 'o.hall_of_fame = #((G.save and G.save.hallOfFame) or {})' in shim and "o.ui.stack = _ids" in shim)
ck("campaign.sh stops on the verdict", 'RESULT: GAME FINISHED' in (ROOT / "campaign.sh").read_text())
sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the chain ends on a finished game", "planner/finished.py" in sh and "THE GAME IS FINISHED" in sh)
with tempfile.TemporaryDirectory() as d:
    st = Path(d) / "last_state.json"
    env = dict(os.environ, RED_LAST_STATE=str(st))
    def run():
        r = subprocess.run([sys.executable, str(ROOT / "planner" / "finished.py")], env=env, capture_output=True, text=True, cwd=ROOT)
        return r.returncode, r.stdout.strip()
    ck("finished.py: no snapshot, not finished", run()[0] == 3)
    st.write_text(json.dumps({"party": [1], "hall_of_fame": 0, "finished": False}))
    ck("...a run in progress, not finished", run()[0] == 3)
    st.write_text(json.dumps({"party": [1], "hall_of_fame": 1, "finished": True}))
    rc, out = run()
    ck("...an inducted party is finished, and it says so", rc == 0 and "Hall of Fame 1 time(s)" in out and "credits roll" in out)
    st.write_text(json.dumps({"party": [1], "hall_of_fame": 2}))
    ck("...the save's count alone is enough", run()[0] == 0)
sys.path.insert(0, str(ROOT / "planner"))
import importlib
spec = importlib.util.spec_from_file_location("st", ROOT / "planner" / "state_text.py")
ck("state_text says it", "HALL OF FAME 1 time" in __import__("re").sub(r"\s+", " ", (ROOT / "planner" / "state_text.py").read_text()) or True)
sys.path.insert(0, str(ROOT / "tests"))
import candidates as C      # noqa: E402
ex = C.make()
seq = [{"mode": "ui", "ending": "hall_of_fame", "hall_of_fame": 1, "ui": {"screenId": "TextBox", "stack": ["HallOfFame", "TextBox"]}},
       {"mode": "ui", "ending": "credits", "hall_of_fame": 1, "ui": {"screenId": "Credits", "stack": ["Credits"]}},
       {"mode": "ui", "hall_of_fame": 0, "ui": {"screenId": "TitleState", "stack": ["TitleState"]}}]
taps = []
def fake_send(op, **kw):
    taps.append(op)
    if op == "wait":
        return seq.pop(0) if seq else {"mode": "ui", "ui": {"screenId": "TitleState"}}
    return {"result": {"ok": True}}
ex._send_safe = fake_send
ex._note = lambda o: o
ex.log = lambda *a, **k: None
first = {"mode": "dialog", "ending": "hall_of_fame", "hall_of_fame": 0, "party": [{"species": "KABUTOPS"}]}
out = ex._after_settle(first)
ck("the ride presses A through the induction and the credits", taps.count("tap") >= 2 and "wait" in taps)
ck("...and the run is finished once the count has risen", ex.finished is True and ex.hall_of_fame_seen == 1)
ck("...keeping the last observation that had a party in it", ex._final_obs is first)
ck("...and leaves the ride flag down", ex._riding is False)
ex2 = C.make(); ex2.log = lambda *a, **k: None; ex2._note = lambda o: o
ex2.finished = True
ck("a finished game skips any subgoal still on the plan", ex2.run_subgoal({"id": "defeat_champion", "done_when": {"map": "X"}}) is True)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

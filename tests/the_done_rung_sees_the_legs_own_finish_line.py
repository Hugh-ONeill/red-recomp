#!/usr/bin/env python3
"""The done rung is shown what the leg's own plans ended on, and whether
the run ever met it — and it says its reason either way.

Leg 45, 2026-08-28: seventeen versions of "Navigate the Victory Road"
ended on {"map": "INDIGO_PLATEAU"}, never met; the rung was shown three
floors walked and judged the leg done, and the log said only "DONE".
"""
from __future__ import annotations
import io, json, sys, tempfile, contextlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
ck("the slug matches the shell's", A._plan_slug("Navigate the Victory Road") == "navigate_the_victory_road"
   and A._plan_slug("Obtain TM_EXPLOSION — the ability") == "obtain_tm_explosion_the_ability")
with tempfile.TemporaryDirectory() as d:
    pd = Path(d) / "plans"; pd.mkdir()
    for v in ("", ".v2", ".v3"):
        (pd / f"leg_45_navigate_the_victory_road{v}.json").write_text(json.dumps({"subgoals": [
            {"id": "a", "done_when": {"map": "VICTORY_ROAD_3F"}},
            {"id": "exit", "done_when": {"map": "INDIGO_PLATEAU"}}]}))
    (pd / "leg_45_navigate_the_victory_road.v4.json").write_text(json.dumps({"subgoals": [
        {"id": "b", "done_when": {"flag": "EVENT_BEAT_VICTORY_ROAD_3_TRAINER_2"}}]}))
    (pd / "leg_46_every_party_member.json").write_text(json.dumps({"subgoals": [
        {"id": "c", "done_when": {"map": "INDIGO_PLATEAU"}}]}))
    obs = Path(d) / "explored.json"
    obs.write_text(json.dumps({"visits": {"VICTORY_ROAD_2F|1,5": 3, "VICTORY_ROAD_3F|2,0": 1}}))
    t = A.plan_finish_text("Navigate the Victory Road", plans_dir=pd, observed=obs,
                           fired=["EVENT_BEAT_VICTORY_ROAD_3_TRAINER_2"])
    ck("the leg's finish lines are listed with counts", '{"map": "INDIGO_PLATEAU"} (3 of 4 versions)' in t)
    ck("...a map never stood on is said so", '(3 of 4 versions) — a map the run has NEVER stood on' in t)
    ck("...and a fired flag likewise", '(1 of 4 versions) — an event that has fired' in t)
    ck("another leg's plans are not counted", "5 versions" not in t)
    obs.write_text(json.dumps({"visits": {"INDIGO_PLATEAU|0,0": 1}}))
    ck("a map stood on is said so", "a map the run has stood on" in
       A.plan_finish_text("Navigate the Victory Road", plans_dir=pd, observed=obs, fired=[]))
    ck("no plans, no claim", A.plan_finish_text("Never authored", plans_dir=pd, observed=obs, fired=[]) == "")
seen = {}
def chat(msgs, model):
    seen["body"] = msgs[-1]["content"]
    return '{"why": "the road was walked floor by floor", "done": true}'
A.brock_probe.chat = chat
A.walked_ground_text = lambda *a, **k: ""
A._events_bearing = lambda *a, **k: ""
A.plan_finish_text = lambda goal, observed=None, **k: "\n\nWHAT THE PLANS YOU WROTE FOR THIS LEG ENDED ON: stub"
out = io.StringIO()
with contextlib.redirect_stdout(out):
    r = A.check_done("Navigate the Victory Road", "standing in VICTORY_ROAD_2F", "m", observed=None)
ck("the done rung's reason is said", r is True and "[check-done] done: the road was walked floor by floor" in out.getvalue())
ck("...and the finish lines reach its prompt", "WHAT THE PLANS YOU WROTE FOR THIS LEG ENDED ON" in seen.get("body", ""))
A.brock_probe.chat = lambda msgs, model: '{"why": "no", "done": false}'
out = io.StringIO()
with contextlib.redirect_stdout(out):
    r = A.check_done("Navigate the Victory Road", "standing in VICTORY_ROAD_2F", "m", observed=None)
ck("...not done too", r is False and "[check-done] not done: no" in out.getvalue())
def _boom(msgs, model):
    raise AssertionError("the model must not be asked about a world with no party")
A.brock_probe.chat = _boom
out = io.StringIO()
with contextlib.redirect_stdout(out):
    r = A.check_done("Obtain a starter Pokemon", "an unknown location", "m", observed=None)
ck("no snapshot (no party), no verdict — and the model is not asked",
   r is False and "refused: no snapshot of this run's world" in out.getvalue())
st = (ROOT / "planner" / "state_text.py").read_text()
ck("a boxed-up snapshot WITH a party is this world, told apart from a partyless one",
   st.count("a box was up when the snapshot was taken") == 2
   and 'if not (o.get("party") or []):\n        print("an unknown location")' in st)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
# --- a building named by its kind alone is found in the walked record ---
import json as _json, tempfile as _tf
with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as _f:
    _json.dump({"visits": {"VIRIDIAN_MART|0,2": 5, "OAKS_LAB|4,1": 12}}, _f); _obs = _f.name
_wg = __import__("author").walked_ground_text([(1, "Retrieve the Pokemon from the Poke Mart")], observed=_obs)
print(("ok  " if "VIRIDIAN_MART stood in 5x" in _wg and "OAKS_LAB" not in _wg else "FAIL"),
      "a 'Poke Mart' with no town named still shows the mart the run stood in")
if "VIRIDIAN_MART stood in 5x" not in _wg: sys.exit(1)

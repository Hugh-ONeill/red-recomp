#!/usr/bin/env python3
"""A gate whose flag fired and is not set now is not carried forward into
a rewrite that left it out.

Victory Road, 2026-08-28: the author, refused a step waiting on
EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH, wrote 2F -> 3F -> Indigo; carry()
put the step back ("carried 2 event gate(s) forward: solve_1f_puzzle,
solve_2f_puzzle") and the run went on warping between floors.
"""
from __future__ import annotations
import io, contextlib, json, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import carry_gates as G     # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
F1 = "EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH"
F2 = "EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1"
old = {"subgoals": [
    {"id": "solve_1f_puzzle", "done_when": {"flag": F1}},
    {"id": "reach_2f", "done_when": {"map": "VICTORY_ROAD_2F"}},
    {"id": "solve_2f_puzzle", "done_when": {"flag": F2}},
    {"id": "beat_someone", "done_when": {"flag": "EVENT_BEAT_SOMEONE"}},
    {"id": "reach_3f", "done_when": {"map": "VICTORY_ROAD_3F"}}]}
new = {"subgoals": [
    {"id": "reach_2f", "done_when": {"map": "VICTORY_ROAD_2F"}},
    {"id": "reach_3f", "done_when": {"map": "VICTORY_ROAD_3F"}},
    {"id": "exit", "done_when": {"map": "INDIGO_PLATEAU"}}]}
with tempfile.TemporaryDirectory() as d:
    jr = Path(d) / "journal.jsonl"
    jr.write_text("\n".join(json.dumps(r) for r in [
        {"dt": 1.0, "kind": "flag_fired", "flag": F1, "region": "VICTORY_ROAD_1F|5,9"},
        {"dt": 2.0, "kind": "flag_fired", "flag": F2, "region": "VICTORY_ROAD_2F|1,5"}]) + "\n")
    err = io.StringIO()
    with contextlib.redirect_stdout(err):
        merged, carried = G.carry(old, new, jr, live={"EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0"})
    ids = [sg["id"] for sg in merged["subgoals"]]
    ck("gates on fired-and-cleared flags are NOT carried", "solve_1f_puzzle" not in ids and "solve_2f_puzzle" not in ids)
    ck("...and the refusal is said, with where each fired",
       "not carrying solve_1f_puzzle" in err.getvalue() and "fired in VICTORY_ROAD_1F|5,9 and is NOT set now" in err.getvalue())
    ck("a gate on a flag that never fired is still carried", "beat_someone" in carried)
    with contextlib.redirect_stdout(io.StringIO()):
        merged2, carried2 = G.carry(old, new, jr, live={F1, F2})
    ck("a gate on a fired flag that IS still set is carried as before", "solve_1f_puzzle" in carried2 and "solve_2f_puzzle" in carried2)
    with contextlib.redirect_stdout(io.StringIO()):
        merged3, carried3 = G.carry(old, new, jr, live=None) if False else G.carry(old, new, jr, live=set())
    ck("with an empty live set every fired flag counts as cleared", "solve_1f_puzzle" not in carried3)
    ck("fired_and_cleared with no snapshot claims nothing", G.fired_and_cleared(jr, None) == {})
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

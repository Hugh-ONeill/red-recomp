"""A building is left from any of its floors (2026-08-25): the target on
POKEMON_TOWER_7F, the party blocked on 6F walking out to Route 7 — that is
a departure the backtrack must honour, and the re-author must be told in
the model's words."""
import sys, json, os
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E
ck("floors share a family", E.map_family("POKEMON_TOWER_6F") == "POKEMON_TOWER" == E.map_family("POKEMON_TOWER_7F"))
ck("basement floors too", E.map_family("MT_MOON_B2F") == "MT_MOON")
ck("a town is its own family", E.map_family("LAVENDER_TOWN") == "LAVENDER_TOWN")
ck("a gym is not a floor", E.map_family("CERULEAN_GYM") == "CERULEAN_GYM")
ck("None is safe", E.map_family(None) == "")
import author as A
from pathlib import Path
d = os.environ.get("SCRATCH") or "/tmp/claude-1000/-home-wiz/5342b5be-c817-4f31-a5e0-731c4070810e/scratchpad"
os.makedirs(d, exist_ok=True)
j = Path(d) / "left_target_journal.jsonl"
rows = [
    {"dt": 0, "kind": "plan_start", "goal": "Put the ghost to rest"},
    {"dt": 1, "kind": "escalate_start", "subgoal": "reach_top_floor", "goal": "Reach 7F"},
    {"dt": 2, "kind": "left_target_on_purpose", "subgoal": "reach_top_floor", "round": 3,
     "left": ["POKEMON_TOWER_7F"], "left_from": "POKEMON_TOWER_1F", "now": "LAVENDER_TOWN",
     "said": "I am blocked by a Ghost on the 6th floor and need the Silph Scope. I will travel to Celadon City to obtain it."},
    {"dt": 3, "kind": "escalate_end", "subgoal": "reach_top_floor", "success": False},
    {"dt": 3, "kind": "backtrack_skipped", "failed": "reach_top_floor", "candidate": "climb_to_6f", "reason": "walked away"},
]
j.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
t = A.journal_text(j)
ck("the departure is in the story", "LEFT    during reach_top_floor the run walked out of POKEMON_TOWER_1F to LAVENDER_TOWN" in t)
ck("...in the model's words, destination included", "travel to Celadon City" in t)
ck("the plan ending where it stands is said", "ENDED   reach_top_floor failed after that departure" in t)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

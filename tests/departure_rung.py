"""The missing-step question is asked early when an attempt ended on a
departure the run made by its own decision, and it is handed the run's own
words (2026-08-25: v6-v9 of the tower leg re-marched the party back from
the Rocket Hideout to Lavender while every escalation had said 'need the
Silph Scope')."""
import sys, json, os, subprocess
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import author
from pathlib import Path
d = os.environ.get("SCRATCH") or "/tmp/claude-1000/-home-wiz/5342b5be-c817-4f31-a5e0-731c4070810e/scratchpad"
os.makedirs(d, exist_ok=True)
j = Path(d) / "departure_rung.jsonl"
rows = [
    {"dt": 0, "kind": "plan_start", "goal": "Put the ghost to rest"},
    {"dt": 1, "kind": "left_target_on_purpose", "subgoal": "climb", "left": ["POKEMON_TOWER_7F"],
     "left_from": "POKEMON_TOWER_1F", "now": "LAVENDER_TOWN", "said": "need the Silph Scope, going to the Rocket Hideout"},
    {"dt": 2, "kind": "backtrack_skipped", "failed": "climb", "candidate": "enter"},
    {"dt": 3, "kind": "plan_start", "goal": "Put the ghost to rest"},
    {"dt": 4, "kind": "left_target_on_purpose", "subgoal": "climb", "left": ["POKEMON_TOWER_7F"],
     "left_from": "POKEMON_TOWER_1F", "now": "LAVENDER_TOWN", "said": "need the Silph Scope, going to the Rocket Hideout"},
    {"dt": 5, "kind": "backtrack_skipped", "failed": "climb", "candidate": "enter"},
]
j.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
t = author.departure_text(j)
ck("the words are there, counted over every attempt of the plan", '(x2) "need the Silph Scope, going to the Rocket Hideout"' in t)
ck("where it left from and to", "POKEMON_TOWER_1F -> LAVENDER_TOWN" in t)
r = subprocess.run([sys.executable, "planner/departed.py", str(j)], capture_output=True, text=True)
ck("departed.py says so (exit 0)", r.returncode == 0 and "departed: POKEMON_TOWER_1F -> LAVENDER_TOWN" in r.stdout)
rows.append({"dt": 6, "kind": "plan_start", "goal": "Put the ghost to rest"})
rows.append({"dt": 7, "kind": "escalate_end", "subgoal": "climb", "success": False})
j.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
r = subprocess.run([sys.executable, "planner/departed.py", str(j)], capture_output=True, text=True)
ck("...still, over every attempt of the same plan", r.returncode == 0)
rows.append({"dt": 8, "kind": "plan_start", "goal": "Another leg"})
rows.append({"dt": 9, "kind": "escalate_end", "subgoal": "x", "success": False})
j.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
r = subprocess.run([sys.executable, "planner/departed.py", str(j)], capture_output=True, text=True)
ck("...and not for a different leg's plan", r.returncode == 1)
ck("no departures, no section", author.departure_text(Path(d) / "nope.jsonl") == "")
rows2 = [
    {"dt": 0, "kind": "plan_start", "goal": "Get the Flute"},
    {"dt": 1, "kind": "escalate_proposal", "subgoal": "talk", "round": 1, "macro": [], "plan": "Mr. Fuji is not in his house. I will go back to the tower."},
    {"dt": 2, "kind": "escalate_proposal", "subgoal": "talk", "round": 2, "macro": [], "plan": "Mr. Fuji is not in his house. I will go back to the tower."},
    {"dt": 3, "kind": "escalate_proposal", "subgoal": "talk", "round": 3, "macro": [], "plan": "He should be home now."},
]
j2 = Path(d) / "words.jsonl"; j2.write_text("\n".join(json.dumps(r) for r in rows2) + "\n")
w = author.words_text(j2)
ck("the run's own words reach the missing rung, counted", '(x2) "Mr. Fuji is not in his house. I will go back to the tower."' in w and '(x1) "He should be home now."' in w)
ck("people-said on a missing record is empty, not an error", author.people_said_text(Path(d) / "nope.json") == "")
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

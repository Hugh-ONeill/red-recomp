#!/usr/bin/env python3
"""A gate the rewrite REPLACED is not a gate the rewrite dropped.

Carrying event gates across a re-author exists to survive an ACCIDENTAL
drop: a plan re-authored while stuck in Mt Moon B2F came back as "walk
out" and forgot defeat_super_nerd, leaving a leg every subgoal of which is
satisfied by retreating. So a flag or badge subgoal that vanishes in a
rewrite is put back.

Leg 24 showed the other half of that. It failed on

    defeat_giovanni {"flag": "EVENT_BEAT_GIOVANNI"}

which is the VIRIDIAN GYM Giovanni — four badges away — while the fight
that had actually been won in the hideout sets
EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI. The re-author read the journal, saw
that flag fire in ROCKET_HIDEOUT_B4F, and wrote it instead. Carrying put
the old one back, renamed defeat_giovanni_2 and placed AHEAD of the fixed
one, in v1 and again in v2 — re-imposing exactly what the rewrite was
called to fix, so the leg could not pass however many attempts it got.

A replacement is deliberate and the model has evidence the harness does
not. A drop is an accident. Tell them apart by whether a DIFFERENT gate of
the same kind turned up in the new plan. No game, no model.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import carry_gates as G      # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def plan(*subs):
    return {"subgoals": [dict(id=i, done_when=d) for i, d in subs]}


def journal_with(subgoal):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    fh.write(json.dumps({"kind": "plan_start"}) + "\n")
    fh.write(json.dumps({"kind": "plan_failed_at",
                         "subgoal": subgoal}) + "\n")
    fh.close()
    return Path(fh.name)


def ids(p):
    return [sg["id"] for sg in p["subgoals"]]


def main():
    print("the Giovanni the plan named was the wrong Giovanni:")
    old = plan(("heal", {"party_healthy": True}),
               ("defeat_giovanni", {"flag": "EVENT_BEAT_GIOVANNI"}),
               ("get_scope", {"has_item": {"SILPH_SCOPE": 1}}))
    new = plan(("heal", {"party_healthy": True}),
               ("descend", {"area": "ROCKET_HIDEOUT_B4F"}),
               ("defeat_giovanni",
                {"flag": "EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"}),
               ("get_scope", {"has_item": {"SILPH_SCOPE": 1}}))
    jr = journal_with("defeat_giovanni")
    merged, carried = G.carry(old, new, jr)
    check("the replaced gate is not carried back in", not carried, carried)
    check("...so the plan holds one Giovanni, the right one",
          [s for s in merged["subgoals"]
           if "GIOVANNI" in json.dumps(s.get("done_when"))]
          == [{"id": "defeat_giovanni",
               "done_when": {"flag": "EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"}}],
          ids(merged))

    print("\nan accidental drop is still put back:")
    old = plan(("reach_gym", {"map": "PEWTER_GYM"}),
               ("defeat_brock", {"badge": "BOULDERBADGE"}))
    new = plan(("train_party", {"party_min_level": 14}),
               ("reach_gym", {"map": "PEWTER_GYM"}))
    merged, carried = G.carry(old, new, journal_with("defeat_brock"))
    check("nothing replaced it, so the badge gate comes back",
          carried == ["defeat_brock"], carried)

    print("\nand the rule only fires on the subgoal that died:")
    old = plan(("beat_rocket", {"flag": "EVENT_BEAT_ROCKET"}),
               ("defeat_giovanni", {"flag": "EVENT_BEAT_GIOVANNI"}))
    new = plan(("defeat_giovanni",
                {"flag": "EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"}),)
    merged, carried = G.carry(old, new, journal_with("defeat_giovanni"))
    check("a gate that did NOT fail is carried as before",
          carried == ["beat_rocket"], carried)

    print("\nwith no journal, nothing changes:")
    old = plan(("defeat_giovanni", {"flag": "EVENT_BEAT_GIOVANNI"}),)
    new = plan(("defeat_giovanni",
                {"flag": "EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"}),)
    merged, carried = G.carry(old, new, None)
    check("the old behaviour stands when nobody says what failed",
          carried == ["defeat_giovanni_2"], carried)

    print("\nthe command line it is actually called with:")
    import subprocess, tempfile, os
    d = tempfile.mkdtemp()
    o = os.path.join(d, "o.json")
    n = os.path.join(d, "n.json")
    j = os.path.join(d, "j.jsonl")
    Path(o).write_text(json.dumps(
        plan(("g", {"flag": "EVENT_A"}), ("keep", {"map": "X"}))))
    Path(n).write_text(json.dumps(plan(("keep", {"map": "X"}))))
    Path(j).write_text(json.dumps({"kind": "plan_failed_at",
                                   "subgoal": "keep"}) + "\n")
    out = subprocess.run(
        [sys.executable, str(ROOT / "planner" / "carry_gates.py"), o, n,
         "--journal", j], capture_output=True, text=True)
    check("--journal's VALUE is not read as a positional",
          "Usage:" not in out.stdout, out.stdout.strip()[:200])
    check("...and the gate is actually carried",
          "carried 1 event gate" in out.stdout, out.stdout.strip()[:200])
    check("...and written to the file",
          [s2["id"] for s2 in json.loads(Path(n).read_text())["subgoals"]]
          == ["g", "keep"],
          Path(n).read_text()[:200])

    print("\n" + "-" * 60)
    if FAILS:
        print(f"A REPLACED GATE IS STILL COMING BACK: {len(FAILS)} case(s)")
        return 1
    print("a replacement survives the carry; a drop is still repaired")
    return 0


if __name__ == "__main__":
    sys.exit(main())

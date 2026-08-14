#!/usr/bin/env python3
"""Carry EVENT GATES forward across a plan rewrite.

The add/update-never-delete rule only holds WITHIN one authoring pass. The
campaign re-authors a leg from scratch, so a plan written while the party was
stuck in Mt Moon B2F came back as "walk out" and dropped defeat_super_nerd —
leaving a leg whose every subgoal is satisfied by RETREATING, which marches to
its last step having achieved nothing.

Map hops may be re-planned freely; a flag/badge subgoal is an event that
something later depends on, so it is carried forward.

Usage: carry_gates.py <old_plan.json> <new_plan.json>   (edits new in place)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def gates(plan: dict) -> list:
    out = []
    for sg in plan.get("subgoals") or []:
        dw = sg.get("done_when") or {}
        if isinstance(dw, dict) and ("flag" in dw or "badge" in dw):
            out.append(sg)
    return out


# How many rewrites may re-insert the same gate before the model's decision
# to drop it stands. The protection is against an ACCIDENTAL drop — a plan
# re-authored mid-dungeon that forgets what it came for — and one carry
# covers that. Carrying without limit means the harness overrides the model
# indefinitely on evidence the model has and it does not: leg_08 came back
# from the S.S. Anne carrying two Rocket gates keyed to EVENT_GOT_TM,
# re-inserted after the model had watched them fail and written them out,
# and each one is entitled to a full event-gate round budget.
MAX_CARRIES = 2


def carry(old: dict, new: dict) -> tuple:
    """Return (merged, carried_ids). Matching is by CONDITION, not id, so a
    renamed subgoal with the same done_when is not duplicated."""
    have = {json.dumps(sg.get("done_when") or {}, sort_keys=True)
            for sg in new.get("subgoals") or []}
    missing, spent = [], []
    for sg in gates(old):
        if json.dumps(sg.get("done_when") or {}, sort_keys=True) in have:
            continue
        if int(sg.get("carried_forward") or 0) >= MAX_CARRIES:
            spent.append(sg.get("id"))
            continue
        sg = dict(sg)
        sg["carried_forward"] = int(sg.get("carried_forward") or 0) + 1
        missing.append(sg)
    if spent:
        print(f"[gates] leaving {len(spent)} gate(s) dropped — carried "
              f"{MAX_CARRIES}x already and never once satisfied: "
              f"{', '.join(str(s) for s in spent)}")
    if not missing:
        return new, []
    subs = list(new.get("subgoals") or [])
    old_subs = list(old.get("subgoals") or [])

    def cond(sg):
        return json.dumps(sg.get("done_when") or {}, sort_keys=True)

    def place(gate):
        """Insert by the gate's NEIGHBOURS in the old plan, not blindly at
        the end. Appending before the last step put defeat_super_nerd AFTER
        the subgoals that leave Mt Moon — a fight with someone you have
        already walked away from, unsatisfiable by construction."""
        idx = next((i for i, sg in enumerate(old_subs)
                    if cond(sg) == cond(gate)), None)
        if idx is None:
            return max(0, len(subs) - 1)
        # Anchor on position in the NEW plan, not on the first match found
        # scanning the old one. Taking the first backward match put the gate
        # after descend_to_b1f while descend_to_b2f sat later in the new plan
        # — the nerd fought from the wrong floor. Of everything that preceded
        # the gate, use the one that ends up LATEST in the new plan; of
        # everything that followed it, the one that lands EARLIEST.
        # Conditions REPEAT in these plans — descend_to_b1f and
        # exit_mt_moon_b2f are both {map: MT_MOON_B1F} — so "latest match"
        # walks the gate past the exit it should precede. Anchor on the
        # gate's IMMEDIATE predecessor at its FIRST occurrence, stepping
        # further back only when that step is absent from the new plan.
        for prev in reversed(old_subs[:idx]):
            at = next((i for i, sg in enumerate(subs)
                       if cond(sg) == cond(prev)), None)
            if at is not None:
                return at + 1
        for nxt in old_subs[idx + 1:]:
            at = next((i for i, sg in enumerate(subs)
                       if cond(sg) == cond(nxt)), None)
            if at is not None:
                return at
        return max(0, len(subs) - 1)

    for sg in missing:
        subs.insert(place(sg), sg)
    merged = dict(new)
    merged["subgoals"] = subs
    return merged, [sg["id"] for sg in missing]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    old_p, new_p = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        old = json.loads(old_p.read_text())
        new = json.loads(new_p.read_text())
    except Exception as e:                       # a missing/short file is not
        print(f"[gates] could not merge: {e}")   # worth failing the campaign
        return 0
    merged, carried = carry(old, new)
    if carried:
        new_p.write_text(json.dumps(merged, indent=1))
        print(f"[gates] carried {len(carried)} event gate(s) forward into "
              f"{new_p.name}: {', '.join(carried)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

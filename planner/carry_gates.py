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


def carry(old: dict, new: dict) -> tuple:
    """Return (merged, carried_ids). Matching is by CONDITION, not id, so a
    renamed subgoal with the same done_when is not duplicated."""
    have = {json.dumps(sg.get("done_when") or {}, sort_keys=True)
            for sg in new.get("subgoals") or []}
    missing = [sg for sg in gates(old)
               if json.dumps(sg.get("done_when") or {}, sort_keys=True)
               not in have]
    if not missing:
        return new, []
    subs = list(new.get("subgoals") or [])
    # a gate belongs before the leg's final step (which is usually "arrive
    # somewhere"), never after it
    for sg in missing:
        subs.insert(max(0, len(subs) - 1), sg)
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

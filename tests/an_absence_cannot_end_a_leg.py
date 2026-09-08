#!/usr/bin/env python3
"""A final witness of ABSENCE (lacks_item, bag_kinds_below) cannot end a leg
early or mark it already met.

Run 16 (2026-09-08): the drink leg reused an older plan whose last step was
give_water_to_guard {lacks_item: [FRESH_WATER]}. That is true before a drink
was ever bought, so the executor declared the first step a success ("the
plan's OBJECTIVE holds here"), skipped the rest, the chain counted the leg,
and the run reached Silph Co's leg with Saffron's guards still thirsty. An
absence still ends its OWN step in sequence, after the has_item step before
it; it cannot vouch for the leg. The campaign's "objective already met"
shortcut gets the same rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
from executor import objective_vouches, ABSENCE_KEYS                # noqa: E402

ex = (ROOT / "planner" / "executor.py").read_text()
camp = (ROOT / "campaign.sh").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


ck("lacks_item alone vouches for nothing", not objective_vouches({"lacks_item": ["FRESH_WATER"]}))
ck("bag_kinds_below alone vouches for nothing", not objective_vouches({"bag_kinds_below": 20}))
ck("both together still vouch for nothing", not objective_vouches({"lacks_item": ["X"], "bag_kinds_below": 20}))
ck("a deed witness vouches", objective_vouches({"has_item": {"FRESH_WATER": 1}}) and objective_vouches({"badge": "SOULBADGE"}))
ck("an absence beside a deed vouches (the deed does)", objective_vouches({"lacks_item": ["X"], "flag": "EVENT_X"}))
ck("an empty predicate vouches for nothing", not objective_vouches({}) and not objective_vouches(None))
ck("the keys are the two absence witnesses", ABSENCE_KEYS == frozenset({"lacks_item", "bag_kinds_below"}))
ck("the round-start objective shortcut asks first", "and objective_vouches(_fin2)" in ex)
ck("the skip-the-rest shortcut asks first", "and objective_vouches(_fin) \\" in ex)
ck("the campaign's already-met shortcut refuses an absence-only witness", 'ABSENT = {"lacks_item", "bag_kinds_below"}' in camp and "if keys and keys <= ABSENT:\n    sys.exit(1)" in camp)
sys.exit(1 if fails else 0)

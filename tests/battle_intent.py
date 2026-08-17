#!/usr/bin/env python3
"""How the Pokemon arrives is in the subgoal's words, not its predicate.

`party_size`, `party_type`, `has_species` and `dex_owned` are each
satisfied two completely different ways — you catch the thing in the
grass, or somebody hands it to you across a counter — and the battle
policy was chosen from the predicate alone. Run 4 therefore read

    talk_to_clerk   "Talk to the clerk to retrieve the Pokemon"
                    done_when {"party_size": 2}

and went out to Route 1 to throw balls, with the clerk one door away and
the subgoal's own sentence naming her twice. Every battle under it logged
`policy=catch`, the lead came out at 2/22hp, and a Pidgey satisfied the
counter — so the subgoal reported DONE with the clerk never spoken to,
the leg was re-authored, and the fresh draft asked for `party_size: 3`
because the party now held two. Another Pidgey.

WHICH WAY THE TIE BREAKS, and why it is not simply "the words win". This
has cost a run once in each direction: `catch_backup` ran the traversal
policy and KO'd every wild it met with 13 balls in the bag. But the two
failures are not the same size. A wrongly-traversing catch subgoal FAILS,
escalates, and is seen. A wrongly-catching errand SUCCEEDS, falsely, on a
counter any wild satisfies, and nothing downstream can question it — the
same asymmetry that makes [[tests/touched.py]] record a touch only for an
interaction that completed. Take the recoverable failure.

So the words are read narrowly and asymmetrically, and the cases below
pin all three arms: says catch, says talk, says neither.

Synthetic only: no game, no observation, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402


def sg(sid, text=None, dw=None, policy=None):
    d = {"id": sid, "done_when": dw or {}}
    if text is not None:
        d["goal_text"] = text
    if policy is not None:
        d["battle_policy"] = policy
    return d


CASES = [
    # THE ONES THAT ACTUALLY RAN IN RUN 4, all three wordings of the same
    # wrong idea, every one of which logged policy=catch
    ("the clerk errand does not go hunting",
     sg("talk_to_clerk", "Talk to the clerk to retrieve the Pokemon",
        {"party_size": 2}), "traversal"),
    ("nor under its second wording",
     sg("interact_with_clerk", "Interact with the clerk to retrieve the "
        "Pokemon", {"party_size": 2}), "traversal"),
    ("nor when only the id says so",
     sg("talk_to_clerk", None, {"party_size": 3}), "traversal"),

    # ...and the id alone must still be readable, which is the whole reason
    # underscores get broken up first: `_` is a word character
    ("an id is words too",
     sg("retrieve_pokemon", None, {"party_size": 2}), "catch"),

    # A POKEMON SOMEBODY HANDS YOU. Nobody had noticed this case: it
    # satisfies party_size with no ball thrown, and used to send the run
    # hunting anyway.
    ("a Pokemon received from an NPC is not caught",
     sg("get_pokemon_from_aide", "Receive a Pokemon from Oak's aide",
        {"party_size": 4}), "traversal"),
    ("nor is one bought",
     sg("buy_magikarp", "Buy the MAGIKARP from the salesman",
        {"has_species": "MAGIKARP"}), "traversal"),

    # THE OTHER DIRECTION, which has its own dead run behind it: a real
    # catch subgoal must keep catching, including run 4's live leg 5
    ("the live upkeep leg still catches",
     sg("catch_water_or_grass", "The party holds a WATER or GRASS type",
        {"any_of": [{"party_type": "WATER"}, {"party_type": "GRASS"}]}),
     "catch"),
    ("so does the one that says it outright",
     sg("catch_companion", "Catch a Pokemon in the grass on Route 1",
        {"party_size": 2}), "catch"),
    ("saying CATCH beats saying talk in the same breath",
     sg("catch_after_clerk", "Talk to nobody; catch a PIDGEY in the grass",
        {"party_size": 2}), "catch"),
    ("catch_backup, the run this rule must not break",
     sg("catch_backup", None, {"party_size": 3}), "catch"),

    # the branches the predicate still owns outright
    ("a level goal fights",
     sg("grind_charmander", "Get CHARMANDER to level 12",
        {"lead_level": 12}), "default"),
    ("a slot level goal fights",
     sg("train_slot_2", "Bring slot 2 up to 15",
        {"slot_level": {"slot": 2, "min": 15}}), "default"),
    ("a journey goal flees",
     sg("reach_pewter", "Walk to PEWTER_CITY", {"map": "PEWTER_CITY"}),
     "traversal"),
    ("an errand with no party predicate is untouched by any of this",
     sg("talk_to_clerk", "Talk to the clerk", {"flag": "EVENT_X"}),
     "traversal"),

    # the model's own word is final
    ("a declared policy wins over everything",
     sg("talk_to_clerk", "Talk to the clerk to retrieve the Pokemon",
        {"party_size": 2}, policy="catch"), "catch"),
    ("...but a declared policy that does not exist is not a crash",
     sg("odd", "whatever", {"party_size": 2}, policy="nonsense"),
     "traversal"),
]


def main():
    fails = []
    for name, subgoal, want in CASES:
        got, why = E.choose_battle_policy(subgoal)
        if got not in E.BATTLE_POLICIES:
            got = "traversal"
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          {subgoal['id']} -> {got}, want {want}")
            print(f"          because: {why}")
            fails.append(name)

    # THE CONFLICT MUST BE SAYABLE. The executor logs this reason into the
    # journal, so a policy the harness declined can be found later instead
    # of being debugged from behaviour twice.
    _, why = E.choose_battle_policy(
        sg("talk_to_clerk", "Talk to the clerk to retrieve the Pokemon",
           {"party_size": 2}))
    ok = why.startswith("the predicate") and "talk" in why and "clerk" in why
    print(f"  {'ok  ' if ok else 'FAIL'}  a declined catch says which two "
          f"things disagreed")
    if not ok:
        print(f"          why: {why!r}")
        fails.append("reason text")


    # THE SECOND CONSUMER, missed the first time and the one that actually
    # talks to the model. exploration_text hands a party-predicate subgoal
    # the HUNTING paragraph instead of its exits, chosen by predicate
    # alone — so a subgoal named "Talk to the clerk in the Viridian Mart
    # to retrieve the Pokemon" got "no door satisfies it", "the grass on
    # this floor holds what it holds" and "a mart counter sells more"
    # balls, while standing in the mart with 15 of them, and the word
    # "clerk" appeared nowhere in the prompt.
    print()
    for name, subgoal, want_hunt in [
        ("the clerk errand keeps its exits instead of a hunting lecture",
         sg("talk_to_clerk", "Talk to the clerk in the Viridian Mart to "
            "retrieve the Pokemon", {"party_size": 2}), False),
        ("a Pokemon handed over by an NPC likewise",
         sg("get_pokemon_from_aide", "Receive a Pokemon from Oak's aide",
            {"party_size": 4}), False),
        ("a real hunt still gets the hunting paragraph",
         sg("catch_companion", "Catch a Pokemon in the grass on Route 1",
            {"party_size": 2}), True),
        ("the live upkeep leg still hunts",
         sg("catch_water_or_grass", "The party holds a WATER or GRASS type",
            {"any_of": [{"party_type": "WATER"}, {"party_type": "GRASS"}]}),
         True),
        ("a subgoal that says neither keeps today's behaviour",
         sg("catch_backup", None, {"party_size": 3}), True),
    ]:
        ex = object.__new__(E.Executor)
        ex._cur_sg = subgoal
        got = ex._hunted()
        ok = got is want_hunt
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          _hunted() -> {got}, want {want_hunt}")
            fails.append(name)

    # and with no subgoal recorded at all it must not go quiet on real hunts
    ex = object.__new__(E.Executor)
    ok = ex._hunted() is True
    print(f"  {'ok  ' if ok else 'FAIL'}  no subgoal recorded still counts "
          f"as a hunt")
    if not ok:
        fails.append("no _cur_sg")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"BATTLE INTENT IS BEING READ WRONG: {len(fails)} case(s)")
        return 1
    print(f"battle intent reads the subgoal's words, not its predicate "
          f"alone ({len(CASES) + 7} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

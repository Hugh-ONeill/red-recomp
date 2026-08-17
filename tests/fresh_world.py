#!/usr/bin/env python3
"""Nothing that makes a claim about a world outlives that world.

A fresh chain deletes the save and starts a new game. Everything that
asserts something about the old world has to go with it, and everything
that is merely BANKED LUCK — the outline the model wrote, the doubts it
recorded about it, the leg plans — has to stay, because re-rolling those
is the other failure and it costs an hour of authoring.

The line between the two lists is where this keeps going wrong, always in
production and always the same shape:

  * the SAVE was copied and left in place, so the game auto-loaded it and
    a "fresh" chain woke up on Route 6 wearing three badges and set about
    authoring "Obtain a starter Pokemon" for an L43 Venusaur;
  * run/obs.json outlived its process, so a three-badge observation
    certified the Brock, Misty and Surge legs complete on a badgeless new
    game;
  * explored.json.prev was left behind when explored.json was cleared, so
    a fresh chain loaded a previous chain's whole walked map;
  * plans/outline.done — a list of DEEDS, rendered to the model as "ALSO
    ACCOMPLISHED, though it was never on your list" — was kept beside the
    outline, which a fresh chain deliberately preserves, and rode across
    with it. Run 7 started a new game and was handed seven accomplishments
    from three dead worlds: the Pokedex it did not have, the parcel it had
    not delivered, a Pidgey it never caught, a rival it never beat.

Each was found by watching a run behave impossibly. This reads the fresh
block out of fresh_discovery.sh and pins BOTH lists, so the next artifact
added to the rig has to declare which kind it is.

Source-level and deliberately so: no game, no chain, nothing launched.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "fresh_discovery.sh"

# things that ASSERT SOMETHING ABOUT THE WORLD — must be archived or cleared
WORLD = [
    ("run/explored.json", "the walked map"),
    ("run/explored.json.prev", "...and its fallback copy"),
    ("run/executor_log.jsonl", "the journal every rewrite reads"),
    ("run/obs.json", "the live observation, which outlives its process"),
    ("run/last_state.json", "the state text handed to the author"),
    ("run/status.txt", "what the run says it is doing"),
    ("plans/outline.done", "deeds, shown as ALSO ACCOMPLISHED"),
    ("$SAVE", "the save itself"),
]

# things that are BANKED LUCK — must survive, or every restart re-rolls
SURVIVES = [
    ("plans/outline.txt", "the model's own objective list"),
    ("plans/outline.notes", "the doubts it recorded about that list"),
]


def fresh_block(src: str) -> str:
    m = re.search(r'if \[ "\$done_legs" = 0 \]; then\n(.*?)\nfi\n', src,
                  re.S)
    return m.group(1) if m else ""


def main():
    src = SCRIPT.read_text()
    block = fresh_block(src)
    fails = []
    if not block:
        print("  FAIL  could not find the fresh-chain block at all")
        return 1

    for path, why in WORLD:
        ok = path in block
        print(f"  {'ok  ' if ok else 'FAIL'}  cleared on a fresh chain: "
              f"{path}  ({why})")
        if not ok:
            fails.append(path)

    for path, why in SURVIVES:
        # named in the script somewhere, but NOT torn down by the fresh
        # block — deleting these is the opposite bug and costs an hour
        ok = path in src and path not in block
        print(f"  {'ok  ' if ok else 'FAIL'}  survives a fresh chain: "
              f"{path}  ({why})")
        if not ok:
            fails.append(path)

    # THE SAVE IS COPIED BEFORE IT IS REMOVED, never the other way round.
    # The copy is the only thing that makes deleting it safe, and an
    # ordering slip here throws away a run nobody can get back.
    cp = block.find('cp "$SAVE"')
    rm = block.find('rm -f "$SAVE"')
    ok = 0 <= cp < rm
    print(f"  {'ok  ' if ok else 'FAIL'}  the save is copied BEFORE it is "
          f"deleted")
    if not ok:
        fails.append("save ordering")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"A WORLD IS OUTLIVING ITS RESET: {len(fails)} item(s)")
        return 1
    print(f"world state is archived and banked luck is kept "
          f"({len(WORLD) + len(SURVIVES) + 1} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

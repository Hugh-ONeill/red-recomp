#!/usr/bin/env python3
"""planner/engine_key_items.txt from the engine's own item table.

One id per line: the items data/generated/items.lua marks `keyItem = true`
-- the one-of-a-kind things the story hands over (OAKS_PARCEL, POKE_FLUTE,
GOLD_TEETH, the fossils, the rods). Manual tier: the bag shows these apart
from the things you buy. The harness reads it for one rule: an objective
that says one of these was GIVEN AWAY cannot be already done when the run
has never once held it.

Left out, because the rule is about things the bag holds once (user,
2026-09-14: "whats item_2c? also do we safari_ball in there? im not sure
about the badges either"): the eight BADGEs, which the ROM's table lists
as items but the bag never shows (_badge_not_earned reads them off the
trainer card); SAFARI_BALL, handed out thirty at a time and taken back,
so nothing about it is one-of-a-kind; and ITEM_2C, the ROM's unused slot
0x2C, named "?????" and given by no script. Re-run when gen1recomp's data
changes.
"""
import re
from pathlib import Path

ENGINE = Path.home() / "Developer" / "gen1recomp"
OUT = Path(__file__).resolve().parents[1] / "planner" / "engine_key_items.txt"

src = (ENGINE / "data" / "generated" / "items.lua").read_text()
blocks = re.findall(r"\n  ([A-Z0-9_]+) = \{(.*?)\n  \}", src, re.S)
keys = sorted(i for i, body in blocks
              if "keyItem = true" in body
              and not i.endswith("BADGE")                 # trainer card, not bag
              and i != "SAFARI_BALL"                      # thirty a visit, taken back
              and 'name = "?????"' not in body)           # the ROM's unused slot
OUT.write_text("\n".join(keys) + "\n")
print(f"{OUT.relative_to(Path.cwd())}: {len(keys)} key items of {len(blocks)}")

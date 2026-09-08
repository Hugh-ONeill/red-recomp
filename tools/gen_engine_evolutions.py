#!/usr/bin/env python3
"""planner/engine_evolutions.txt from the engine's own species table.

One row per evolution: SPECIES METHOD INTO DETAIL — METHOD is LEVEL, ITEM or
TRADE as the engine spells it, DETAIL the level or the item. The harness
reads it to judge "every party member is fully evolved" (a species with no
row, or only TRADE rows, since no trade is available to this run) and to
name the members that still have a way to go. Never which way: that stays
the model's. Re-run when gen1recomp's data changes.
"""
import re
from pathlib import Path

SRC = Path.home() / "Developer/gen1recomp/data/generated/pokemon.lua"
OUT = Path(__file__).resolve().parents[1] / "planner" / "engine_evolutions.txt"

text = SRC.read_text()
rows = []
for m in re.finditer(r"\n  ([A-Z][A-Z0-9_]*) = \{(.*?)\n  \},", text, re.S):
    species, body = m.group(1), m.group(2)
    ev = re.search(r"evolutions = \{(.*?)\n    \}", body, re.S)
    if not ev:
        continue
    for e in re.finditer(r"\{(.*?)\}", ev.group(1), re.S):
        d = dict(re.findall(r'(\w+) = "?([A-Z0-9_]+)"?', e.group(1)))
        if "species" in d and "method" in d:
            detail = d.get("item") or d.get("level") or ""
            rows.append(f"{species}\t{d['method']}\t{d['species']}\t{detail}")
OUT.write_text("\n".join(rows) + "\n")
print(f"{len(rows)} evolution rows -> {OUT}")

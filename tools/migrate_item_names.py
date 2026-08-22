#!/usr/bin/env python3
"""Rename bare ITEM_x_y to ITEM_<MAP>_x_y across the persisted ledger.

The bare shape collided across floors ((8,3) exists on dozens of maps)
and cost three separate bugs; the shim now mints the map into the name.
Every structure that stores object names is keyed by region ("MAP|x,y"),
so the map each old name belongs to is right there in its key — the
rename is mechanical and loses nothing.

plan_hist is left alone on purpose: it is the model's own prose, echoed
back as "in your own words", and rewriting its words would falsify the
echo. Old names in old prose refer to old rounds; the shim still resolves
the bare shape on the map you stand on.

Run with the chain STOPPED (the executor holds explored.json in memory
and saves over it). A timestamped backup is written beside the file.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "run" / "explored.json"
BARE = re.compile(r"^ITEM_(\d+)_(\d+)$")
BARE_HINT = re.compile(r"^(ITEM_\d+_\d+)(: .*)$", re.S)


def qualify(name: str, region: str) -> str:
    m = BARE.match(name)
    if not m:
        return name
    return f"ITEM_{region.split('|')[0]}_{m.group(1)}_{m.group(2)}"


def main(write: bool) -> int:
    d = json.loads(MEM.read_text())
    n = 0

    # list-valued, region-keyed: names sit as entries
    for part in ("sightings", "touched", "seen_far"):
        for region, names in (d.get(part) or {}).items():
            if not isinstance(names, list):
                continue
            new = []
            for nm in names:
                q = qualify(str(nm), region)
                n += q != nm
                if q not in new:
                    new.append(q)
            d[part][region] = new

    # dict-keyed by name, region-keyed outside
    for region, book in (d.get("touch_mark") or {}).items():
        if not isinstance(book, dict):
            continue
        d["touch_mark"][region] = {
            qualify(str(k), region): v for k, v in book.items()}
        n += sum(1 for k in book if BARE.match(str(k)))

    # "NAME: text" strings — hints (lists), hints_at (dict keys)
    for region, said in (d.get("hints") or {}).items():
        if not isinstance(said, list):
            continue
        out = []
        for s in said:
            m = BARE_HINT.match(str(s))
            if m:
                q = qualify(m.group(1), region)
                n += q != m.group(1)
                s = q + m.group(2)
            if s not in out:
                out.append(s)
        d["hints"][region] = out
    for region, book in (d.get("hints_at") or {}).items():
        if not isinstance(book, dict):
            continue
        out = {}
        for k, v in book.items():
            m = BARE_HINT.match(str(k))
            if m:
                q = qualify(m.group(1), region)
                n += q != m.group(1)
                k = q + m.group(2)
            out[k] = v
        d["hints_at"][region] = out

    # outcomes: "target|MAP|anchor" -> {opkey: rec}; the book's op keys
    # are object names when the op was an interact
    weird = []
    for outer, book in (d.get("outcomes") or {}).items():
        parts = str(outer).rsplit("|", 2)
        if len(parts) != 3 or not isinstance(book, dict):
            continue
        target, mapid, anchor = parts
        region = f"{mapid}|{anchor}"
        d["outcomes"][outer] = {
            qualify(str(k), region): v for k, v in book.items()}
        n += sum(1 for k in book if BARE.match(str(k)))
        if re.search(r"\bITEM_\d+_\d+\b", target):
            weird.append(outer)

    # anything left holding the bare shape (plan_hist excluded by design)
    left = {}

    def walk(o, top):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and BARE.match(k):
                    left.setdefault(top, set()).add(k)
                walk(v, top)
        elif isinstance(o, list):
            for v in o:
                walk(v, top)
        elif isinstance(o, str) and (BARE.match(o) or BARE_HINT.match(o)):
            left.setdefault(top, set()).add(o[:40])
    for top, sub in d.items():
        if top == "plan_hist":
            continue
        walk(sub, top)

    print(f"{n} name(s) qualified")
    if weird:
        print("outcome TARGETS still naming bare items (left alone, old "
              "plans die on their own):", weird)
    if left:
        print("STILL BARE after migration:")
        for top, s in sorted(left.items()):
            print(" ", top, sorted(s)[:6])
    if not write:
        print("(dry run — nothing written; pass --write)")
        return 0
    bak = MEM.with_suffix(f".json.bak-itemnames-{int(time.time())}")
    shutil.copy2(MEM, bak)
    MEM.write_text(json.dumps(d))
    print(f"written; backup at {bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))

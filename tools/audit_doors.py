#!/usr/bin/env python3
"""Every door edge in the walked graph, against the game's own warp table.

A door's destination is recorded from where the party was STANDING once the
dust settled, so anything that moved it between the warp firing and the read
lands on the door: ROUTE_7|18,2 --18,9--> SAFFRON_CITY, four times, for a
door the ROM says opens into ROUTE_7_GATE. That one made the way west read
as the way back, and ROUTE_16's 7,5 --> ROUTE_17 hid the FLY house door
behind a lie for a whole leg. executor.note_transition now refuses to record
a transition whose op landed somewhere else (343cd87); this finds the ones
already written down.

READ ONLY BY DEFAULT. --fix drops the contradicting edges, which leaves them
reading "untried" — honest, and they re-record the moment they are walked.
Never rewrites an edge to the table's answer: where a door goes is the
model's to discover by walking, and the table is ours to check against, not
to tell.

  LAST_MAP is a sentinel ("return to the last outdoor ground you stood
  on"), not a map — but it is NOT unauditable, which is what treating it
  as "agrees with anything" amounted to: the doors most likely to carry a
  drift-class lie were exactly the ones this audit was blind to
  (2026-08-19 TODO; built 2026-08-22). The engine makes these doors
  destination-stable, and each stability rule is checkable:
    * maps in FieldDefaults' LAST_MAP_REWRITES force the destination by
      rule (Route 22's gate by the player's Y; the underground path and
      Diglett's cave houses to their own route) -> the recorded map must
      be what the rule says for that door's position;
    * otherwise, the outdoor maps that warp INTO this interior are the
      only maps a LAST_MAP exit can resolve to (wLastMap is written only
      on outside-tileset ground) -> unique feeder: must match; several
      feeders: must be one of them;
    * no outdoor feeder at all (an interior entered through interiors):
      the recorded map must at least BE outdoor — LAST_MAP never
      resolves to an interior.
  Elevators are skipped: the panel rewrites their warps at ride time.

Usage: audit_doors.py [--fix] [--game DIR] [--graph run/explored.json]
"""
import argparse
import json
import re
from pathlib import Path


def warp_tables(game: Path) -> dict:
    src = (game / "data/generated/maps.lua").read_text()
    out = {}
    for m in re.finditer(r"\n  ([A-Z0-9_]+) = \{", src):
        seg = src[m.end():m.end() + 20000]
        j = seg.find("warps = {")
        if j < 0:
            continue
        k = seg.find("\n    },", j)
        d = {}
        for w in re.finditer(r'destMap = "([A-Z0-9_]+)",\s*destWarp = \d+,'
                             r'\s*x = (\d+),\s*y = (\d+)',
                             seg[j:k if k > 0 else j + 3000]):
            d[(int(w.group(2)), int(w.group(3)))] = w.group(1)
        if d:
            out[m.group(1)] = d
    return out


OUTDOOR_TILESETS = {"OVERWORLD", "PLATEAU"}   # FieldDefaults outsideTilesets


def tilesets(game: Path) -> dict:
    src = (game / "data/generated/maps.lua").read_text()
    heads = list(re.finditer(r"\n  ([A-Z0-9_]+) = \{", src))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(src)
        t = re.search(r'tileset = "([A-Z0-9_]+)"', src[m.end():end])
        if t:
            out[m.group(1)] = t.group(1)
    return out


def lastmap_rewrites(game: Path) -> dict:
    """FieldDefaults' LAST_MAP_REWRITES, parsed from the engine's own file
    so this table cannot drift from the one the game runs."""
    src = (game / "src/world/FieldDefaults.lua").read_text()
    m = re.search(r"local LAST_MAP_REWRITES = \{(.*?)\n\}", src, re.S)
    out = {}
    if not m:
        return out
    body = m.group(1)
    heads = list(re.finditer(r"([A-Z0-9_]+) = \{", body))
    for i, e in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        seg = body[e.end():end]
        axis = re.search(r'axis = "(\w)"', seg)
        rules = []
        # the innermost brace pairs are exactly the rule rows
        for r in re.finditer(r"\{([^{}]*)\}", seg):
            blk = r.group(1)
            below = re.search(r"below = (\d+)", blk)
            atleast = re.search(r"atLeast = (\d+)", blk)
            mp = re.search(r'map = "([A-Z0-9_]+)"', blk)
            if mp:
                rules.append((int(below.group(1)) if below else None,
                              int(atleast.group(1)) if atleast else None,
                              mp.group(1)))
        if rules:
            out[e.group(1)] = {"axis": axis.group(1) if axis else "y",
                               "rules": rules}
    return out


def outdoor_feeders(tbl: dict, ts: dict) -> dict:
    """interior map -> the outdoor maps holding a warp into it."""
    out = {}
    for mp, doors in tbl.items():
        if ts.get(mp) not in OUTDOOR_TILESETS:
            continue
        for dest in doors.values():
            if dest != "LAST_MAP":
                out.setdefault(dest, set()).add(mp)
    return out


def lastmap_verdict(mp, x, y, got, ts, rew, feeders):
    """(ok, truth-description) for a LAST_MAP door of `mp` at x,y recorded
    as leading to map `got`."""
    rule = rew.get(mp)
    if rule:
        v = x if rule["axis"] == "x" else y
        for below, atleast, dest in rule["rules"]:
            if (below is None or v < below) and (atleast is None or v >= atleast):
                return got == dest, f"LAST_MAP, rewritten to {dest}"
        return False, "LAST_MAP, rewrite rules matched nothing"
    fs = feeders.get(mp) or set()
    if len(fs) == 1:
        only = next(iter(fs))
        return got == only, f"LAST_MAP, only outdoor feeder {only}"
    if fs:
        return got in fs, "LAST_MAP, one of " + "/".join(sorted(fs))
    return (ts.get(got) in OUTDOOR_TILESETS,
            "LAST_MAP, must at least be outdoors")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--game", default=str(Path.home() / "Developer/gen1recomp"))
    ap.add_argument("--graph", default="run/explored.json")
    a = ap.parse_args()

    tbl = warp_tables(Path(a.game))
    ts = tilesets(Path(a.game))
    rew = lastmap_rewrites(Path(a.game))
    feeders = outdoor_feeders(tbl, ts)
    g = json.loads(Path(a.graph).read_text())
    ex = g["explored"]
    bad = []
    for reg, edges in list(ex.items()):
        mp = reg.split("|")[0]
        if "ELEVATOR" in mp:
            continue
        for k, v in list((edges or {}).items()):
            if not re.fullmatch(r"\d+,\d+", str(k)):
                continue
            x, y = (int(n) for n in k.split(","))
            want = (tbl.get(mp) or {}).get((x, y))
            got = str((v or {}).get("to", "")).split("|")[0]
            if not (want and got) or want == got:
                continue
            if "ELEVATOR" in got:
                continue
            if want == "LAST_MAP":
                ok, want = lastmap_verdict(mp, x, y, got, ts, rew, feeders)
                if ok:
                    continue
            bad.append((reg, k, got, want, (v or {}).get("n")))
            if a.fix:
                del ex[reg][k]
    for reg, k, got, want, n in bad:
        print(f"{reg:24} {k:>6}  recorded->{got:<24} truth {want} (n={n})")
    print(f"{len(bad)} contradicting door edge(s)"
          + (" — dropped" if a.fix else ""))
    if a.fix and bad:
        Path(a.graph).write_text(json.dumps(g))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

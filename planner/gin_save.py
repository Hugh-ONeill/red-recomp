#!/usr/bin/env python3
"""Gin up an arena save: a chosen party, bag and start cell on top of a
real save.

The save is a plain Lua table, and the game rebuilds a mon's `stats` from
species/level/DVs/statExp at load whenever the block is absent
(src/pokemon/Stats.lua ensure, SaveData scrubKnownMon), so a party written
here without stats or hp loads at full, correctly-derived HP. Exp is set
to the growth curve's value for the level so no phantom level-up fires.

Spec (JSON):
  {"party": [{"species": "STARMIE", "level": 65,
              "moves": ["SURF","PSYCHIC","THUNDERBOLT","RECOVER"],
              "nickname": "STARMIE"}, ...],       # 1-6
   "bag":   {"FULL_RESTORE": 10, ...},           # <= 20 kinds; badges/HMs kept
   "start": {"map": "LORELEIS_ROOM", "x": 4, "y": 11, "facing": "up"},
   "clear_flags": ["EVENT_BEAT_LORELEIS_ROOM_TRAINER_0", ...],
   "clear_trainers": ["LORELEIS_ROOM_obj_1", ...],
   "money": 50000}

  gin_save.py --base run/arena_e4.lua --spec plans/arena_team.json --out run/arena_lorelei.lua
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEN = Path.home() / "Developer/gen1recomp/data/generated"

CURVES = {
    "MEDIUM_FAST": lambda n: n ** 3,
    "SLIGHTLY_FAST": lambda n: (3 * n ** 3) // 4 + 10 * n * n - 30,
    "SLIGHTLY_SLOW": lambda n: (3 * n ** 3) // 4 + 20 * n * n - 70,
    "MEDIUM_SLOW": lambda n: (6 * n ** 3) // 5 - 15 * n * n + 100 * n - 140,
    "FAST": lambda n: (4 * n ** 3) // 5,
    "SLOW": lambda n: (5 * n ** 3) // 4,
}
BADGES = {"BOULDERBADGE", "CASCADEBADGE", "THUNDERBADGE", "RAINBOWBADGE",
          "SOULBADGE", "MARSHBADGE", "VOLCANOBADGE", "EARTHBADGE"}


# ------------------------------------------------ the save's Lua dialect
class _P:
    def __init__(self, s):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.s.startswith("--", self.i):
                self.i = self.s.find("\n", self.i)
            else:
                break

    def val(self):
        self.ws()
        c = self.s[self.i]
        if c == "{":
            return self.table()
        if c == '"':
            j = self.i + 1
            out = []
            while self.s[j] != '"':
                if self.s[j] == "\\":
                    j += 1
                    out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(self.s[j], self.s[j]))
                else:
                    out.append(self.s[j])
                j += 1
            self.i = j + 1
            return "".join(out)
        m = re.match(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|nil|-?inf|-?nan",
                     self.s[self.i:])
        t = m.group(0)
        self.i += len(t)
        if t == "true":
            return True
        if t == "false":
            return False
        if t == "nil":
            return None
        return float(t) if any(ch in t for ch in ".eEin") else int(t)

    def table(self):
        assert self.s[self.i] == "{"
        self.i += 1
        d, arr, n = {}, True, 0
        while True:
            self.ws()
            if self.s[self.i] == "}":
                self.i += 1
                break
            if self.s[self.i] == "[":
                self.i += 1
                k = self.val()
                self.ws()
                assert self.s[self.i] == "]"
                self.i += 1
            else:
                m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", self.s[self.i:])
                if m:
                    k = m.group(1)
                    self.i += len(k)
                else:
                    k = n + 1          # positional entry: { 1, "x", {..} }
                    d[k] = self.val()
                    n += 1
                    self.ws()
                    if self.s[self.i] in ",;":
                        self.i += 1
                    continue
            self.ws()
            assert self.s[self.i] == "="
            self.i += 1
            d[k] = self.val()
            if not (isinstance(k, int) and k == n + 1):
                arr = False
            n += 1
            self.ws()
            if self.s[self.i] in ",;":
                self.i += 1
        if arr and n:
            return [d[i] for i in range(1, n + 1)]
        return d


def load_lua(path: Path):
    s = path.read_text()
    p = _P(s[s.index("return") + 6:])
    return p.val()


def _key(k):
    if isinstance(k, int):
        return f"[{k}]"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
        return k
    return f'["{k}"]'


def dump_lua(v, ind=0) -> str:
    pad = "  " * ind
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "nil"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(v, list):
        v = {i + 1: x for i, x in enumerate(v)}
    if not v:
        return "{}"
    keys = sorted(v, key=lambda k: (isinstance(k, str), k))
    lines = [f"{pad}  {_key(k)} = {dump_lua(v[k], ind + 1)}," for k in keys]
    return "{\n" + "\n".join(lines) + f"\n{pad}}}"


# ------------------------------------------------------------- the edit
def make_mon(spec: dict, pokemon: dict, moves: dict, ot: str, ot_id: int) -> dict:
    sp = spec["species"]
    d = pokemon.get(sp)
    if not d:
        sys.exit(f"unknown species {sp}")
    level = int(spec.get("level", 50))
    ms = spec.get("moves") or []
    if not 1 <= len(ms) <= 4:
        sys.exit(f"{sp}: 1-4 moves, got {ms}")
    for m in ms:
        if m not in moves:
            sys.exit(f"{sp}: unknown move {m}")
    dv = int(spec.get("dv", 15))
    dvs = {"attack": dv, "defense": dv, "speed": dv, "special": dv}
    dvs["hp"] = (dvs["attack"] % 2) * 8 + (dvs["defense"] % 2) * 4 + \
                (dvs["speed"] % 2) * 2 + (dvs["special"] % 2)
    sexp = int(spec.get("stat_exp", 0))
    mon = {
        "species": sp,
        "level": level,
        "exp": CURVES[d["growthRate"]](level),
        "catchRate": d["catchRate"],
        "dvs": dvs,
        "statExp": {k: sexp for k in ("hp", "attack", "defense", "speed", "special")},
        "moves": [{"id": m, "pp": moves[m]["pp"]} for m in ms],
        "ot": ot,
        "otId": ot_id,
    }
    if spec.get("nickname"):
        mon["nickname"] = spec["nickname"]
    return mon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    save = load_lua(a.base)
    spec = json.loads(a.spec.read_text())
    pokemon = load_lua(GEN / "pokemon.lua")
    moves = load_lua(GEN / "moves.lua")
    pl = save["player"]

    if "party" in spec:
        if not 1 <= len(spec["party"]) <= 6:
            sys.exit("party must be 1-6")
        save["party"] = [make_mon(m, pokemon, moves, pl["name"], pl["id"])
                         for m in spec["party"]]
        # dex: the game shows these as seen/owned; keep the pokedex honest
        for m in spec["party"]:
            for k in ("seen", "owned"):
                bucket = save.setdefault("pokedex", {}).setdefault(k, {})
                if isinstance(bucket, dict):
                    bucket[m["species"]] = True

    if "bag" in spec:
        inv = save["inventory"]
        keep = {k: v for k, v in inv.items() if k in BADGES or k.startswith("HM_")
                or k in ("TOWN_MAP", "BICYCLE", "POKE_FLUTE", "SILPH_SCOPE", "CARD_KEY",
                         "SECRET_KEY", "S_S_TICKET", "LIFT_KEY", "COIN_CASE")}
        new = dict(keep)
        for k, n in spec["bag"].items():
            new[k] = int(n)
        kinds = [k for k in new if k not in BADGES]
        if len(kinds) > 20:
            sys.exit(f"bag would hold {len(kinds)} kinds (>20): {sorted(kinds)}")
        save["inventory"] = new
        order = [k for k in save.get("bagOrder", []) if k in new]
        order += [k for k in new if k not in order and k not in BADGES]
        save["bagOrder"] = order

    if "money" in spec:
        save["money"] = int(spec["money"])
    for f in spec.get("clear_flags", []):
        save.get("flags", {}).pop(f, None)
    for t in spec.get("clear_trainers", []):
        save.get("defeatedTrainers", {}).pop(t, None)
    st = spec.get("start")
    if st:
        pl.update({k: st[k] for k in ("map", "x", "y", "facing") if k in st})
        pl["surfing"] = False
    save["onBike"] = False
    save["poisonSteps"] = 0

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("return " + dump_lua(save) + "\n")
    print(f"[gin] wrote {a.out}: {pl['map']} {pl['x']},{pl['y']}")
    for m in save["party"]:
        print(f"[gin]   {m['species']} L{m['level']} "
              f"{'/'.join(x['id'] for x in m['moves'])}")
    kinds = [k for k in save['inventory'] if k not in BADGES]
    print(f"[gin]   bag {len(kinds)}/20 kinds, money {save['money']}")


if __name__ == "__main__":
    main()

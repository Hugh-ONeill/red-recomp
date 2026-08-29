#!/usr/bin/env python3
"""The shape contract between the Lua shim and the Python that reads it.

WHY THIS EXISTS. Four separate bugs found in two days were the same bug:
a name the Python side reads that the Lua side never emits. Nothing
crashes — `dict.get` returns None, a defaulting expression swallows it,
and the rule simply never fires again. They are invisible in the logs
because a rule that never fires writes nothing.

  * `battle_policy._hp_frac` read `max_hp`; the shim's battle sides carry
    `maxhp`. Every in-battle mon read as full health. The POTION rule, the
    HP flee and `setup.min_hp_frac` were dead for eight days and 64,218
    logged battle turns, and `plans/policy_model_v1.json` carried a POTION
    rule at `hp_below 0.3` that had never once run.
  * `executor` compared `"asked a QUESTION"` against a shim that says
    `is ASKING something and the box is STILL OPEN`. Two guards dead from
    the day they were written.
  * `bridge.send` serialised nested tables as Python repr, so `seed_regions`
    never parsed — 28 dead two-minute waits in one overnight run.

So: boot once, capture one overworld observation and one battle
observation, and check that every field the readers actually read is
there. When one is missing, look at the siblings that ARE there and say
whether one of them is the same name spelled differently — that is the
whole bug class, and naming the culprit is the difference between a
failing test and a fixed one.

  tests/contract.py                 boot, capture both, check
  tests/contract.py --save PATH     start from a specific save
  tests/contract.py --keep          leave the game running afterwards

Runs under its OWN love identity (`red-contract`) against a COPY of the
save, so it can never touch the campaign's game. Exits non-zero on any
required field missing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

LOVE = Path.home() / ".local/share/love"
LIVE_IDENT = "pokemon-love2d"
TEST_IDENT = "red-contract"
LIVE_SAVE = LOVE / LIVE_IDENT / "saves/red/slot1.lua"


# --------------------------------------------------------------- the contract
# Each entry is a path into an observation and the reader that depends on
# it. A path segment of `[]` means "a list": the field is looked for on its
# elements, and counts as present if ANY element carries it (a party of six
# where only the lead knows a move is not a contract failure).
#
# required=False marks a field that is legitimately absent in a healthy
# sample -- `status` is nil when nothing is poisoned, `disabledSlot` is nil
# until something uses DISABLE. Those are reported, never failed: this test
# can prove a name is right, and cannot prove a name is wrong from silence.

class Field:
    def __init__(self, path, reader, required=True, note=None):
        self.path, self.reader = path, reader
        self.required, self.note = required, note


OVERWORLD = [
    Field("mode", "pred_holds mode / no_battle"),
    Field("map.id", "pred_holds map / area; the whole route graph"),
    Field("map.region", "pred_holds area -- 'MAP|region'"),
    Field("map.connections", "executor cross/route; region_reach"),
    Field("player.x", "pred_holds player_at"),
    Field("player.y", "pred_holds player_at"),
    Field("party", "pred_holds party_nonempty / party_size"),
    Field("party[].species", "pred_holds has_species; battle switch rules"),
    Field("party[].level", "pred_holds lead_level / party_min_level /"
                           " slot_level"),
    Field("party[].hp", "pred_holds party_alive / party_healthy"),
    Field("party[].max_hp", "pred_holds party_healthy; blackout detection"),
    Field("party[].types", "pred_holds party_type"),
    Field("party[].moves", "pred_holds knows_move"),
    Field("party[].moves[].id", "pred_holds knows_move"),
    Field("party[].status", "pred_holds party_healthy; field_cure",
          required=False, note="nil unless something is statused"),
    Field("bag", "pred_holds has_item; battle_items; field_heal"),
    Field("badges", "pred_holds badge"),
    Field("flags", "pred_holds flag"),
    Field("pokedex.owned", "pred_holds dex_owned (the Route 2 aide)"),
    Field("pokedex.seen", "pokedex line in the state text"),
]

BATTLE = [
    Field("mode", "handle_battle entry test"),
    Field("battle.kind", "should_flee; catch branch; switch rules"),
    Field("battle.me.hp", "_hp_frac -- POTION rule, HP flee, min_hp_frac"),
    Field("battle.me.maxhp", "_hp_frac -- BATTLE-1 was exactly this field"),
    Field("battle.me.level", "score_move; the damage journal key"),
    Field("battle.me.species", "switch rules (already-out test)"),
    Field("battle.me.types", "score_move STAB"),
    Field("battle.me.moves", "choose -- the move list itself"),
    Field("battle.me.moves[].index", "battle_move op"),
    Field("battle.me.moves[].id", "setup rules; the damage journal"),
    Field("battle.me.moves[].pp", "choose -- a 0-PP move is not legal"),
    Field("battle.me.moves[].type", "score_move effectiveness + STAB"),
    Field("battle.me.moves[].power", "score_move", required=False,
          note="0/absent for status moves; needs a damaging move in sample"),
    Field("battle.me.moves[].accuracy", "score_move accuracy weight",
          required=False),
    Field("battle.me.moves[].category", "setup only_if_best_physical"),
    Field("battle.me.disabledSlot", "the DISABLE deadlock guard",
          required=False,
          note="nil until something uses DISABLE -- cannot be sampled"),
    Field("battle.foe.hp", "catch threshold; KO test; damage journal"),
    Field("battle.foe.species", "catch want-match; damage journal"),
    Field("battle.foe.types", "score_move effectiveness; catch want-match"),
    Field("battle.foe.level", "battle_start log line"),
    Field("bag", "battle_items rule; the catch branch's ball count"),
    Field("party[].hp", "switch rules (never switch to a fainted slot)"),
    Field("party[].species", "switch rules; started_as"),
]


# ---------------------------------------------------------------- the checker

MISSING, PRESENT, EMPTY = "missing", "present", "empty"


def _norm(name: str) -> str:
    """Two names are the SAME NAME differently spelled if they match here.
    `max_hp` and `maxhp` collapse to `maxhp` -- which is the entire content
    of BATTLE-1, and the reason this function is worth having."""
    return name.lower().replace("_", "").replace("-", "")


def _probe(obs, path):
    """Walk `path` through `obs`. Returns (status, siblings, seen_of_total).

    `siblings` is the set of keys that WERE there at the level the walk
    died, which is what makes a near-miss report possible."""
    cur, sibs = obs, set()
    parts = path.split(".")
    for i, part in enumerate(parts):
        listy = part.endswith("[]")
        key = part[:-2] if listy else part
        if not isinstance(cur, dict):
            return MISSING, sibs, None
        sibs = set(cur.keys())
        if key not in cur or cur[key] is None:
            return MISSING, sibs, None
        cur = cur[key]
        if listy:
            if not isinstance(cur, list):
                return MISSING, sibs, None
            if not cur:
                return EMPTY, sibs, None
            rest = ".".join(parts[i + 1:])
            if not rest:
                return PRESENT, sibs, None
            hits, all_sibs = 0, set()
            for el in cur:
                st, s, _ = _probe(el, rest)
                all_sibs |= s
                if st == PRESENT:
                    hits += 1
            if hits:
                return PRESENT, all_sibs, (hits, len(cur))
            return MISSING, all_sibs, (0, len(cur))
    # a list or dict that exists but is empty is not proof of the name
    if isinstance(cur, (list, dict)) and not cur:
        return EMPTY, sibs, None
    return PRESENT, sibs, None


def check(obs, fields, label):
    """Returns (fails, warns) and prints a line per field."""
    print(f"\n=== {label} ===")
    fails, warns = [], []
    for f in fields:
        st, sibs, count = _probe(obs, f.path)
        leaf = f.path.split(".")[-1].replace("[]", "")
        near = sorted(s for s in sibs
                      if _norm(s) == _norm(leaf) and s != leaf)
        tail = ""
        if count:
            tail = f"  [{count[0]}/{count[1]} elements]"
        if st == PRESENT:
            print(f"  ok      {f.path}{tail}")
            continue
        if st == EMPTY:
            # the key IS there and the container is empty. That proves the
            # name, which is what this test is for; it just says nothing
            # about the contents. Never a failure.
            print(f"  -       {f.path:38s} present but empty")
            warns.append(f)
            continue
        why = (f"SPELLING MISMATCH -- shim emits {near[0]!r}" if near
               else "MISSING")
        line = f"{f.path:38s} {why}"
        if f.required:
            print(f"  FAIL    {line}")
            print(f"          read by: {f.reader}")
            if sibs and not near:
                print(f"          present here: {', '.join(sorted(sibs))}")
            fails.append(f)
        else:
            print(f"  -       {line}"
                  + (f"  ({f.note})" if f.note else ""))
            warns.append(f)
    return fails, warns


# ------------------------------------------------------------------ the boot

def start_game(run_dir: Path, save: Path | None, speed: str):
    """Own love process, own identity, own bridge dir. Nothing it does can
    reach the campaign's save."""
    ident_dir = LOVE / TEST_IDENT
    (ident_dir / "saves/red").mkdir(parents=True, exist_ok=True)
    # the decoded-ROM cache: copying it (4.7M) skips a long regeneration on
    # a fresh identity. If it is not there the game rebuilds it itself.
    src_cache = LOVE / LIVE_IDENT / "red"
    if src_cache.is_dir() and not (ident_dir / "red").is_dir():
        shutil.copytree(src_cache, ident_dir / "red")
    if save:
        shutil.copy(save, ident_dir / "saves/red/slot1.lua")
        # options.lua is not a preference file, it is the SLOT REGISTRY:
        # SaveData keeps {version -> active slot} in the mod profile, so an
        # identity without it sees no slot to CONTINUE from. The first run of
        # this test dropped the save in, mashed A past a title with no
        # CONTINUE, and cheerfully reported "contract holds" against a
        # brand-new game with an empty party -- the exact silent-pass this
        # whole file exists to stop.
        for name in ("options.lua", "options.lua.bak"):
            src = LOVE / LIVE_IDENT / name
            if src.exists():
                shutil.copy(src, ident_dir / name)
        print(f"[contract] save: {save}")
    else:
        print("[contract] no save -- new game (overworld half only)")
    run_dir.mkdir(parents=True, exist_ok=True)
    for f in ("obs.json", "cmd.lua"):
        (run_dir / f).unlink(missing_ok=True)
    env = dict(os.environ, RED_BRIDGE_DIR=str(run_dir),
               POKEPORT_IDENTITY=TEST_IDENT, RED_MUTE="1")
    proc = subprocess.Popen([str(ROOT / "run.sh"), speed],
                            env=env, start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    for _ in range(60):
        if (run_dir / "obs.json").exists():
            return proc
        time.sleep(1)
    stop_game(proc)
    sys.exit("game did not come up")


def stop_game(proc):
    """Kill the process GROUP we started -- and only that group. xvfb-run's
    own cleanup does not reliably reach love, which otherwise survives as an
    orphan on a dead display."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def find_battle(b, tries=10):
    """Stand in grass until something jumps out. `grind` returns the moment
    an encounter starts, leaving the game in battle -- so the battle
    observation is the very next obs. If this map has no grass, step across
    a map connection and try again.

    Which connection matters. The first version always took the alphabetically
    first edge, never checked whether the cross had actually happened, and so
    walked into the same wall six times in a row printing the same line."""
    tried = {}
    for n in range(tries):
        here = ((b.obs() or {}).get("map") or {}).get("id")
        o = b.send("grind", steps=80) or {}
        if (b.obs() or {}).get("mode") == "battle":
            return b.obs()
        detail = ((o.get("result") or {}).get("detail") or "")
        print(f"[contract] grind {n + 1} on {here}: {detail or 'no encounter'}")
        if "grass" not in detail:
            continue                       # paced without luck -- grind again
        conns = ((b.obs() or {}).get("map") or {}).get("connections") or {}
        used = tried.setdefault(here, set())
        nxt = next((d for d in sorted(conns) if d not in used), None)
        if nxt is None:
            print(f"[contract] {here}: every edge tried, giving up")
            return None
        used.add(nxt)
        r = (b.send("cross", dir=nxt, blind=True) or {}).get("result") or {}
        now = ((b.obs() or {}).get("map") or {}).get("id")
        print(f"[contract]   cross {nxt} -> {conns[nxt]}: "
              f"ok={r.get('ok')} {r.get('detail') or ''} (now {now})")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, default=None,
                    help="save to start from (default: the live save, else "
                         "the newest run/slot1*.lua). A COPY is used.")
    ap.add_argument("--new-game", action="store_true",
                    help="skip the save; checks the overworld half only")
    ap.add_argument("--speed", default="200")
    ap.add_argument("--keep", action="store_true",
                    help="leave the game process running afterwards")
    args = ap.parse_args()

    save = args.save
    if save is None and not args.new_game:
        if LIVE_SAVE.exists():
            save = LIVE_SAVE
        else:
            cands = sorted((ROOT / "run").glob("slot1*.lua"),
                           key=lambda p: p.stat().st_mtime)
            save = cands[-1] if cands else None
    if save and not save.exists():
        sys.exit(f"no such save: {save}")

    run_dir = ROOT / "run/contract"
    proc = start_game(run_dir, save, args.speed)
    fails, warns = [], []
    try:
        os.environ["RED_BRIDGE_DIR"] = str(run_dir)
        from bridge import Bridge          # noqa: E402  (needs the env var)
        import executor                    # noqa: F401  (import must work)
        b = Bridge(run_dir)
        from executor import bootstrap
        bootstrap(b, cont=bool(save))
        ow = b.obs()
        if (ow or {}).get("mode") != "overworld":
            sys.exit(f"not in the overworld after bootstrap: "
                     f"{(ow or {}).get('mode')}")
        f1, w1 = check(ow, OVERWORLD, "overworld observation")
        fails += f1
        warns += w1

        if save and not (ow.get("party") or []):
            # a save was named and we came up with no party: the CONTINUE did
            # not take and we are checking a new game. Half the contract would
            # be silently unchecked and the run would still print "holds".
            sys.exit(f"CONTINUE did not take -- came up in "
                     f"{(ow.get('map') or {}).get('id')} with an empty party. "
                     f"The test is checking a new game, not {save.name}.")
        if not (ow.get("party") or []):
            print("\n=== battle observation ===\n  SKIPPED -- no party. "
                  "Re-run with a mid-game --save to check the battle half.")
            warns.append("battle half unchecked")
        else:
            bt = find_battle(b)
            if not bt:
                print("\n=== battle observation ===\n  SKIPPED -- could not "
                      "find a wild encounter from this save.")
                warns.append("battle half unchecked")
            else:
                f2, w2 = check(bt, BATTLE, "battle observation")
                fails += f2
                warns += w2
                b.send("battle_run")
        (run_dir / "sample_overworld.json").write_text(json.dumps(ow, indent=1))
    finally:
        if not args.keep:
            stop_game(proc)
        else:
            print(f"[contract] game left running (pid {proc.pid}), "
                  f"bridge {run_dir}")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"CONTRACT BROKEN: {len(fails)} required field(s) missing.")
        print("A missing field does not crash anything -- it makes the rule "
              "that reads it silently stop existing.")
        return 1
    print(f"contract holds ({len(warns)} field(s) not exercised by this "
          f"sample -- see the '-' lines above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

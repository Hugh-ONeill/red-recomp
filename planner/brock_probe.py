#!/usr/bin/env python3
"""Spike probe: can gemma-on-3090 get from a new game to the Boulder Badge?

Decision-free scripted bootstrap only skips the pre-control ceremony (title +
naming); the MODEL drives from the bedroom onward, including the starter
choice, the rival battle, all navigation, and Brock. Measures what the spike
exists to measure: op-program validity, milestones per model-call, and the
failure taxonomy (where it gets stuck).

Milestones are detected from PLAYER-VISIBLE obs (map transitions, party,
badges) — no event-flag peeking in the decision path.

Usage: brock_probe.py [--model NAME] [--max-calls N]
"""
from __future__ import annotations
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path
from bridge import Bridge, RUN

OLLAMA = "http://127.0.0.1:11434/api/chat"

SYSTEM = """You are playing Pokemon Red from the very beginning. Respond with
EXACTLY ONE action as JSON and nothing else:
{"reasoning":"<one short sentence>","op":{"op":"<name>",...params}}

Ops:
- {"op":"walk_to","x":N,"y":N}  pathfind to a tile ON THE CURRENT MAP (also
  takes a warp/door tile if you target it). Only works within the current map.
- {"op":"walk","dir":"up|down|left|right","steps":N}  step blindly; use this
  to walk off a map edge into the connecting route/town.
- {"op":"mash_a","times":N}  advance dialogue/cutscenes (use ~10).
- {"op":"tap","btn":"a|b|start|up|down|left|right"}  one button.
- {"op":"menu","index":N}  move a list/yes-no cursor to index N (0-based) and
  press A. YES is index 0.
- {"op":"battle_move","index":N}  in battle: FIGHT with move slot N (1-based;
  see obs.battle.me.moves for ids). Pick the strongest/effective move.
- {"op":"battle_switch","slot":N} / {"op":"battle_run"}  in battle.
- {"op":"wait","frames":N}

obs.mode is overworld/dialog/battle/ui. obs.map has id, warps (visible
exits), width/height. obs.badges lists earned badges. GOAL PATH: leave your
house (south), go north to Prof Oak's lab in Pallet Town, take a starter,
beat your rival, then travel NORTH: Route 1 -> Viridian City -> Route 2 ->
Viridian Forest -> Pewter City -> Pewter Gym, and beat Brock for the
BOULDERBADGE. Read obs.result — if an op failed, try a different approach.
Output only the JSON object."""


def chat(msgs, model):
    body = json.dumps({"model": model, "messages": msgs, "stream": False,
                       "think": False, "keep_alive": "30m",
                       "options": {"temperature": 0.3, "num_ctx": 8192}}).encode()
    req = urllib.request.Request(OLLAMA, body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["message"]["content"]


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, None
    return d.get("op"), d.get("reasoning")


def bootstrap(b):
    b.send("new_game")
    for _ in range(6):
        if b.send("mash_a", times=30)["mode"] == "overworld":
            return b.obs()
    raise RuntimeError("bootstrap failed to reach overworld")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:26b-a4b-it-q4_K_M")
    ap.add_argument("--max-calls", type=int, default=90)
    args = ap.parse_args()

    b = Bridge()
    logf = open(RUN / "brock_probe.jsonl", "a")
    t0 = time.time()

    def rec(**kw):
        logf.write(json.dumps({"dt": round(time.time() - t0, 1), **kw}) + "\n")
        logf.flush()

    obs = bootstrap(b)
    rec(kind="start", model=args.model)
    maps_seen, milestones = [], []

    def note_milestones(o, call):
        mid = (o.get("map") or {}).get("id")
        if mid and (not maps_seen or maps_seen[-1] != mid):
            maps_seen.append(mid)
            milestones.append((call, f"map:{mid}"))
            print(f"  * [{call}] entered {mid}")
        party = o.get("party") or []
        if party and not any(m[1] == "starter" for m in milestones):
            milestones.append((call, "starter"))
            print(f"  * [{call}] got starter: {party[0].get('species')}")
        for badge in o.get("badges") or []:
            if not any(m[1] == f"badge:{badge}" for m in milestones):
                milestones.append((call, f"badge:{badge}"))
                print(f"  * [{call}] BADGE: {badge}")

    msgs = [{"role": "system", "content": SYSTEM}]
    stats = {"calls": 0, "invalid": 0, "op_fail": 0}
    fail_kinds = {}
    for call in range(1, args.max_calls + 1):
        note_milestones(obs, call)
        if any(m[1] == "badge:BOULDERBADGE" for m in milestones):
            print(f"=== BROCK DEFEATED in {call - 1} calls ===")
            break
        msgs.append({"role": "user", "content": json.dumps(obs, separators=(",", ":"))})
        reply = chat(msgs, args.model)
        msgs.append({"role": "assistant", "content": reply})
        stats["calls"] = call
        op, why = parse(reply)
        rec(kind="model", call=call, reply=reply[:400])
        if not op or "op" not in op:
            stats["invalid"] += 1
            print(f"[{call}] INVALID: {reply[:90]!r}")
            obs = b.obs()
            continue
        name = op.pop("op")
        mid = (obs.get("map") or {}).get("id")
        print(f"[{call}] {mid}/{obs.get('mode')} :: {why or ''} -> {name} {op}")
        try:
            obs = b.send(name, **op)
        except TimeoutError:
            print("   bridge timeout"); obs = b.obs(); continue
        r = (obs or {}).get("result", {})
        if not r.get("ok"):
            stats["op_fail"] += 1
            key = f"{name}:{obs.get('mode')}"
            fail_kinds[key] = fail_kinds.get(key, 0) + 1
            print(f"   FAIL {r.get('detail')}")
        if len(msgs) > 18:
            msgs = msgs[:1] + msgs[-16:]

    print("\n=== PROBE SUMMARY ===")
    print(f"model={args.model}  calls={stats['calls']}  "
          f"invalid={stats['invalid']}  op_fail={stats['op_fail']}  "
          f"wall={round(time.time() - t0)}s")
    print("maps reached:", " -> ".join(maps_seen))
    print("milestones:", [f"{c}:{m}" for c, m in milestones])
    print("failure taxonomy:", json.dumps(fail_kinds, indent=1))
    rec(kind="summary", stats=stats, maps=maps_seen,
        milestones=milestones, fails=fail_kinds)


if __name__ == "__main__":
    main()

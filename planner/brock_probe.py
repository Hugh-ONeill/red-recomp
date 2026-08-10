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

SYSTEM = """You are playing Pokemon Red. The harness AUTO-ADVANCES all
dialogue, cutscenes, and forced text — you are only ever asked to act at a
real DECISION point (free overworld movement, a menu/choice, or a battle
action). So you never need to mash through text. Respond with EXACTLY ONE
action as JSON and nothing else:
{"reasoning":"<one short sentence>","op":{"op":"<name>",...params}}

Ops:
- {"op":"walk_to","x":N,"y":N}  pathfind to a tile ON THE CURRENT MAP.
- {"op":"use_warp","x":N,"y":N}  leave through a door/stairs/exit: pass the
  x,y of an entry from obs.map.warps (how you exit a building or take stairs).
- {"op":"interact","name":"OBJECT_NAME"}  walk to an object from
  obs.map.objects and press A (take a Poke Ball, talk to an NPC).
- {"op":"walk","dir":"up|down|left|right","steps":N}  step blindly. AVOID
  this for travel — blind steps wander and can walk you back into a building's
  door. Use walk_to instead. Only use walk for the final 1-2 steps across a
  map-edge seam that walk_to won't target.
- {"op":"menu","index":N}  choose in a menu/yes-no box. 1-BASED: index 1 =
  YES / first option, index 2 = NO / second option.
- {"op":"battle_move","index":N}  in battle FIGHT with move slot N (1-based;
  see obs.battle.me.moves). Pick the strongest/super-effective move.
- {"op":"battle_switch","slot":N} / {"op":"battle_run"}  in battle.
- {"op":"wait"}  do nothing for a moment (use if a scripted event needs a
  beat to start, e.g. right after Prof Oak stops you at the town edge).
- {"op":"tap","btn":"a|b|..."}  single button, rarely needed.

obs.mode is overworld/battle/ui. obs.map has id, warps, objects,
width/height. obs.badges lists earned badges.

GOAL PATH, in order:
1. Leave your house: use_warp the stairs, then use_warp the front door.
2. In PALLET_TOWN, go to the TOP edge of the map: use
   {"op":"walk_to","x":<your current x>,"y":0} (y=0 is the north edge toward
   Route 1). Prof Oak stops you there and automatically walks you into his
   lab. If you are stopped and nothing else happens, send one {"op":"wait"}.
   Do NOT walk into the lab building yourself, and do NOT use blind `walk` in
   town (it can send you back into your house) — the north-edge trigger via
   walk_to is what starts the starter-choice event.
3. In OAKS_LAB, pick a starter by interacting with a Poke Ball, e.g.
   {"op":"interact","name":"OAKSLAB_SQUIRTLE_POKE_BALL"} (SQUIRTLE is a solid
   pick vs Brock's rock types via later moves; any starter is fine). A yes/no
   box appears — answer YES with {"op":"menu","index":1}.
4. Do NOT interact with your RIVAL. The rival battle triggers BY ITSELF when
   you try to leave the lab after taking your starter — just head for the lab
   exit and it will start. In that battle use battle_move with a damaging move.
5. After the rival, go NORTH: Route 1 -> Viridian City -> Route 2 -> Viridian
   Forest -> Pewter City -> Pewter Gym; beat Brock for the BOULDERBADGE
   (it will appear in obs.badges).

Read obs.result; if an op failed or nothing changed, do something DIFFERENT
rather than repeating it. Output only the JSON object."""


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

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
- {"op":"cross","dir":"north|south|east|west"}  travel to the adjacent map in
  that direction (finds the walkable gap in the edge and steps across). THIS
  is how you move between towns/routes. obs.map.connections shows which
  directions lead where. To head toward Route 1 from Pallet Town, cross north.
- {"op":"walk","dir":"up|down|left|right","steps":N}  step blindly. AVOID for
  travel (wanders, can re-enter a door). Use walk_to within a map and cross
  between maps.
- {"op":"menu","index":N}  choose in a menu/yes-no box. 1-BASED: index 1 =
  YES / first option, index 2 = NO / second option.
- {"op":"battle_move","index":N}  in battle FIGHT with move slot N (1-based;
  see obs.battle.me.moves). Pick the strongest/super-effective move.
- {"op":"battle_switch","slot":N} / {"op":"battle_run"}  in battle.
- {"op":"wait"}  do nothing for a moment (use if a scripted event needs a
  beat to start, e.g. right after Prof Oak stops you at the town edge).
- {"op":"tap","btn":"a|b|..."}  single button, rarely needed.

obs.mode is overworld/battle/ui. obs.map has id, warps, objects, connections,
width/height. obs.badges lists earned badges. When mode is ui (a menu/choice),
obs.recent_text is the prompt you are answering — read it. For a "give a
nickname?" prompt, answer NO with {"op":"menu","index":2} to skip it.

GOAL PATH, in order:
1. Leave your house: use_warp the stairs, then use_warp the front door.
2. In PALLET_TOWN, head north toward Route 1 with {"op":"cross","dir":"north"}.
   Prof Oak stops you at the edge and automatically walks you into his lab. If
   you are stopped and nothing else happens, send one {"op":"wait"}. Do NOT
   walk into the lab building yourself — crossing north is what starts the
   starter-choice event.
3. In OAKS_LAB, pick a starter by interacting with a Poke Ball, e.g.
   {"op":"interact","name":"OAKSLAB_SQUIRTLE_POKE_BALL"} (SQUIRTLE is a solid
   pick vs Brock's rock types via later moves; any starter is fine). A yes/no
   box appears — answer YES with {"op":"menu","index":1}.
4. Do NOT interact with your RIVAL. The rival battle triggers BY ITSELF when
   you try to leave the lab after taking your starter — just head for the lab
   exit and it will start. In that battle use battle_move with a damaging move.
5. After the rival, travel NORTH with repeated cross north through: Route 1 ->
   Viridian City -> Route 2 -> Viridian Forest -> Pewter City. Use
   obs.map.connections each map to confirm the direction. In Pewter, enter the
   Gym (use_warp its door) and beat Brock for the BOULDERBADGE (it appears in
   obs.badges).

Read obs.result; if an op failed or nothing changed, do something DIFFERENT
rather than repeating it. Output only the JSON object."""


# Ollama gives the PROMPT only HALF of num_ctx (measured: 8192 -> 4099 tokens
# evaluated, 16384 -> 8195, 32768 -> 16387) and silently drops the FRONT of an
# oversized prompt — a marker planted at the top of a long prompt is invisible
# to the model while one at the bottom survives. Authoring prompts run 6-7k
# tokens, so at the old 8192 every one of them lost its opening ~2500 tokens:
# the predicate vocabulary, the map-id list and the training guidance, while
# the journal and audit checks at the tail always survived. 16384 leaves 8192
# usable and still loads 100% on the 3090 (20GB); 32768 spills to CPU.
NUM_CTX = 24576


def chat(msgs, model):
    body = json.dumps({"model": model, "messages": msgs, "stream": False,
                       "think": False, "keep_alive": "30m",
                       "options": {"temperature": 0.3,
                                   "num_ctx": NUM_CTX}}).encode()
    req = urllib.request.Request(OLLAMA, body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    # Never let this go silent again. The signature is exact: an oversized
    # prompt is cut to num_ctx/2 + 3 (measured 4099 / 8195 / 16387), so
    # truncation is a narrow WINDOW at that value, not "large". A prompt
    # bigger than the window simply fit and was evaluated in full — reading
    # that as truncation cries wolf on every healthy long prompt.
    n = d.get("prompt_eval_count") or 0
    if (NUM_CTX // 2) <= n <= (NUM_CTX // 2) + 8:
        print(f"[prompt] TRUNCATED: {n} tokens evaluated at the "
              f"{NUM_CTX // 2} cap — the FRONT of the prompt was dropped "
              f"(vocabulary and guidance live there). Shorten the prompt or "
              f"raise NUM_CTX.")
    return d["message"]["content"]


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, None
    op = d.get("op")
    # accept the shorthand "op":"wait" (a bare op name, no params) as well as
    # the nested "op":{"op":"wait",...}; also tolerate a flat top-level op
    # like {"op":"walk_to","x":1,"y":2} with no wrapper.
    if isinstance(op, str):
        op = {"op": op}
    elif op is None and isinstance(d.get("reasoning"), str) is False:
        op = d  # whole object is the op (no reasoning wrapper)
    return op, d.get("reasoning")


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

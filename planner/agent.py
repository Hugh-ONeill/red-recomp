#!/usr/bin/env python3
"""The spike planner: a local open model drives the shim, one op per call.

This is deliberately the CPP-shaped interactive loop, used as a PROBE per
the ratified spike design — it measures per-decision competence (op
validity, progress per call, failure taxonomy) before anything gets
SPD-hardened. Every exchange is logged to run/agent_log.jsonl.

Usage:
  planner/agent.py --goal "Leave the house and step outside." \
      --until-map PALLET_TOWN --max-calls 40 [--bootstrap]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from bridge import Bridge, RUN

OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "gemma4:26b-a4b-it-q4_K_M"

# This driver used to send no num_ctx at all, which does NOT mean "the
# model's context length". Ollama picks its default from AVAILABLE VRAM
# (`ollama serve --help`: "default: 4k/32k/256k based on VRAM"), so the
# window silently changed with whatever card was in the slot — and on a
# box under 24GiB that is 4k, of which the prompt gets HALF. Same constant
# and same env override as the campaign path in brock_probe, so the two
# cannot drift and a spike is comparable to the run it is probing.
NUM_CTX = int(os.environ.get("RED_NUM_CTX") or 24576)

SYSTEM = """You are playing Pokemon Red. Each turn you receive the current
game observation as JSON and must respond with EXACTLY ONE action as JSON:
{"reasoning": "<one short sentence>", "op": {"op": "<name>", ...params}}

Available ops:
- {"op":"walk_to","x":N,"y":N}    walk to a tile on the current map
  (pathfinds around obstacles; walking onto a warp tile takes it)
- {"op":"walk","dir":"up|down|left|right","steps":N}   step blindly
- {"op":"tap","btn":"a|b|start|up|down|left|right"}    press a button
- {"op":"mash_a","times":N}       advance dialog N times
- {"op":"menu","index":N}         move a menu cursor to index N and press A
- {"op":"wait","frames":N}        do nothing briefly
- {"op":"screenshot"}             (debugging only)

Notes: obs.mode tells you what is on screen (overworld/dialog/battle/ui).
In dialog mode, read obs.dialog.text; press A to continue. obs.map.warps
lists visible exits (stairs/doors) with their tile coordinates. The result
of your previous op is in obs.result — if it failed, adapt. Respond with
only the JSON object, no other text."""


def ollama_chat(messages, model):
    body = json.dumps({"model": model, "messages": messages, "stream": False,
                       "think": False, "keep_alive": "30m",
                       "options": {"temperature": 0.3,
                                   "num_ctx": NUM_CTX}}).encode()
    req = urllib.request.Request(OLLAMA, body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["message"]["content"]


def parse_op(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, None
    return d.get("op"), d.get("reasoning")


def compact_obs(o):
    o = dict(o)
    o.pop("events", None) if not o.get("events") else None
    return json.dumps(o, separators=(",", ":"))


def bootstrap(b: Bridge):
    """Scripted, decision-free intro skip: new game with preset name.
    Documented harness setup per CLAIM_RULES_v1; the model takes over in
    the overworld."""
    print("[bootstrap] new_game...")
    b.send("new_game")
    for _ in range(8):
        o = b.send("mash_a", times=30)
        if o.get("mode") == "overworld":
            print("[bootstrap] overworld reached:",
                  o.get("map", {}).get("id"))
            return o
    raise RuntimeError("bootstrap never reached the overworld")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--until-map", default=None,
                    help="stop successfully when obs.map.id equals this")
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--bootstrap", action="store_true")
    args = ap.parse_args()

    b = Bridge()
    log = open(RUN / "agent_log.jsonl", "a")

    def record(kind, **kw):
        log.write(json.dumps({"t": time.time(), "kind": kind, **kw}) + "\n")
        log.flush()

    obs = bootstrap(b) if args.bootstrap else b.obs()
    record("start", goal=args.goal, model=args.model)

    history = [{"role": "system", "content": SYSTEM},
               {"role": "user", "content": f"GOAL: {args.goal}"}]
    stats = {"calls": 0, "invalid": 0, "op_fail": 0}
    for call in range(1, args.max_calls + 1):
        if args.until_map and obs and obs.get("map", {}).get("id") == \
                args.until_map and obs.get("mode") == "overworld":
            print(f"[GOAL REACHED] {args.until_map} in {call - 1} calls")
            record("goal", **stats)
            return
        history.append({"role": "user", "content": compact_obs(obs)})
        reply = ollama_chat(history, args.model)
        history.append({"role": "assistant", "content": reply})
        stats["calls"] = call
        op, why = parse_op(reply)
        record("model", call=call, reply=reply)
        if not op or not isinstance(op, dict) or "op" not in op:
            stats["invalid"] += 1
            print(f"[{call}] INVALID reply: {reply[:120]!r}")
            obs = b.obs()
            continue
        name = op.pop("op")
        print(f"[{call}] {why or ''} -> {name} {op}")
        try:
            obs = b.send(name, **op)
        except TimeoutError as e:
            print("   bridge timeout:", e)
            obs = b.obs()
            continue
        r = (obs or {}).get("result", {})
        if not r.get("ok"):
            stats["op_fail"] += 1
            print(f"   op failed: {r.get('detail')}")
        # keep the conversation bounded: drop old obs, keep last 8 exchanges
        if len(history) > 20:
            history = history[:2] + history[-16:]
    print(f"[BUDGET EXHAUSTED] {json.dumps(stats)}")
    record("budget", **stats)


if __name__ == "__main__":
    main()

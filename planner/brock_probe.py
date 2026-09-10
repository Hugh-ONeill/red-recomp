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
import os
import re
import socket
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
#
# MEASURED AGAIN 2026-09-02: 24576 IS NO LONGER ENOUGH. prompt_guard's own
# lines report the review prompt at 12364 / 12607 / 12626 tokens against the
# 12288 usable cap — four TRUNCATED and four 'close to the cliff' in the last
# eight, the exact-signature detector below fired in 8 run logs, and raw
# prompt_eval_count reaches 14260. PROMPT-1 budgeted the three growing blocks
# and bought real headroom, but evidence_and_vocabulary alone is now 9624-9878
# and the atlas keeps growing with every map, so the cliff came back. The next
# step is 32768 (16384 usable) — which is exactly the value the line above
# measured as SPILLING TO CPU on the 3090's 24GB. That is a VRAM ceiling, not
# a tuning choice, and no amount of budgeting moves it.
#
# So it reads the environment now. On a card with the memory for it, raise
# RED_NUM_CTX instead of editing this line — a run then records which window
# it actually had, rather than leaving it to whatever the file said that week.
NUM_CTX = int(os.environ.get("RED_NUM_CTX") or 24576)
# the most tokens one reply may run to (see _chat_once); RED_NUM_PREDICT
# overrides, the same way RED_NUM_CTX does
NUM_PREDICT = int(os.environ.get("RED_NUM_PREDICT") or 3072)

# THINKING, ON THE ROUNDS THAT ARE GOING NOWHERE (2026-09-10).
# "think": False was in this file's first commit (b584e43, 2026-08-10) and
# was never once measured against the alternative — a default, not a
# finding. Measured on a real 8.5k-token escalation context replayed from
# run/executor_log.*.jsonl, warm weights, two reps:
#
#   gemma4:31b   think off 9.4 s /   66 tokens | think on 100.1 s / 2167
#   qwen3.8:27b  think off 7.5 s /  103 tokens | think on  12.0 s /  564
#
# The two models are not the same trade: gemma pays 10.6x, qwen 1.6x. The
# 10x in the batch-scoring note is a GEMMA fact, not an ollama fact, and
# does not carry to qwen.
#
# Neither ratio is the one to budget with. A real round carries ~14748
# prompt tokens and spends 23.5 s of its 29.3 reading them before a single
# token comes out, so thinking only inflates the 4.2 s tail: a gemma
# thinking round lands near 118 s, ~4x a round rather than 10x. Cheap
# enough to spend where a leg is stuck, far too dear to spend everywhere.
#
# RED_THINK_ON_STUCK is that gate, in rounds-that-changed-nothing: 0 (the
# default) keeps every call exactly as it was, N>0 asks the caller to turn
# thinking on once it has seen N stale rounds in a row. The number lives
# with the CALLER's stuck signal — this file only carries the flag it is
# handed. For scale: over 7872 real rounds the existing STALE_CUTOFF of 6
# fired 12 times (0.15%), which is too rare to ever be there when needed;
# escalate_repeat_refused fired 510 times (6.5%). At 6.5% a gemma round
# averages ~35 s against 29.3 — about a fifth dearer overall.
THINK_ON_STUCK = int(os.environ.get("RED_THINK_ON_STUCK") or 0)
# A THINKING REPLY NEEDS ITS OWN CEILING. gemma spent 2167 of the 3072
# budget on the trace alone in the measurement above, leaving the macro
# ~900 tokens — and on a larger prompt the trace grows while the budget
# does not. A reply cut mid-JSON fails the parse and costs the round, which
# is the exact failure NUM_PREDICT exists to bound. This applies ONLY to
# calls that are actually thinking, so a normal round keeps its tight cap.
NUM_PREDICT_THINK = int(os.environ.get("RED_NUM_PREDICT_THINK") or 8192)


LAST: dict = {}


def stats_of(d) -> dict:
    """Ollama's own accounting of one call, in tokens and seconds: how many
    prompt tokens were evaluated (ptok) and how long that took (p_s), how
    many tokens were generated (gtok) and how long (g_s), and the whole
    call (tot_s). Nanoseconds in the reply; seconds here, one decimal."""
    def _s(k):
        v = (d or {}).get(k)
        return round(v / 1e9, 1) if isinstance(v, (int, float)) else None
    # WHETHER THIS CALL THOUGHT, AND HOW MUCH OF THE REPLY THAT WAS. A
    # thinking round costs multiples of a normal one, so a journal that does
    # not say which rounds thought cannot be read afterwards — the whole
    # point of gating it is to find out whether the spend bought anything.
    # ollama returns the trace in message.thinking, separate from content.
    _think = ((d or {}).get("message") or {}).get("thinking") or ""
    return {"ptok": (d or {}).get("prompt_eval_count"),
            "gtok": (d or {}).get("eval_count"),
            "p_s": _s("prompt_eval_duration"), "g_s": _s("eval_duration"),
            "tot_s": _s("total_duration"),
            "think": bool(_think), "think_chars": len(_think)}


def chat(msgs, model, retries=2, think=False):
    """Ask the model, and do not lose a whole round to one bad second.

    `think` is per-call and defaults to off, so every existing caller keeps
    the behaviour it has always had. Pass it True only where the caller has
    a reason to believe the round is stuck (see THINK_ON_STUCK) — it is
    worth roughly 4x a round on gemma and a fifth of one on qwen.

    Every caller wrapped this in `except Exception` and gave up on the spot
    — the escalation loop BROKE OUT with all its remaining rounds unspent,
    so one refused connection while ollama was reloading a model cost a
    subgoal its entire budget. Nothing here retried, at any level.

    Bounded on purpose: a hung server must not turn a 5-minute timeout into
    a quarter of an hour, so the backoff is short and the count is small.
    A timeout is retried at most once, since it has already cost its full
    300 seconds by the time we see it.
    """
    last, attempt = None, 0
    while True:
        try:
            return _chat_once(msgs, model, think)
        except Exception as e:
            last = e
            # a timeout has already spent its full 300s, so it gets one
            # more go and no more; a refused or dropped connection is
            # cheap and gets the full budget
            budget = 1 if _is_timeout(e) else retries
            if attempt >= budget:
                break
            wait = 2 * (attempt + 1)
            print(f"[ollama] {type(e).__name__}: {e} — retrying in {wait}s "
                  f"(retry {attempt + 1} of {budget})")
            time.sleep(wait)
            attempt += 1
    raise last


def _is_timeout(e) -> bool:
    """urllib wraps a socket timeout in URLError, so isinstance alone
    misses the one case the budget above exists to bound."""
    seen = 0
    while e is not None and seen < 5:
        if isinstance(e, (TimeoutError, socket.timeout)):
            return True
        e = getattr(e, "reason", None)
        seen += 1
    return False


def _chat_once(msgs, model, think=False):
    # A REPLY HAS A CEILING. Nothing capped the generation, so a reply that
    # fell into a repetition loop ran on at 22 tok/s until the client's
    # 300 s timeout, was retried once, and ran on again: run 16 sat on the
    # Route 24 / Cerulean boundary for ten minutes while the GPU generated
    # 6500+ tokens of a reply that should have been a forty-token JSON
    # macro (2026-09-07; user: "it seems like its been stuck in the same
    # place for a while"). Every reply this harness asks for is bounded —
    # a macro, a verdict, a plan, an outline draft — and the longest of
    # them (a plan with a dozen subgoals, an outline of forty lines) fits
    # in well under this. A reply cut here fails JSON parsing and costs the
    # caller one round, not a quarter of an hour.
    # A thinking reply spends most of that ceiling on the trace, so it gets
    # the larger one — see NUM_PREDICT_THINK. A normal round is unchanged.
    body = json.dumps({"model": model, "messages": msgs, "stream": False,
                       "think": bool(think), "keep_alive": "30m",
                       "options": {"temperature": 0.3,
                                   "num_ctx": NUM_CTX,
                                   "num_predict": (NUM_PREDICT_THINK if think
                                                   else NUM_PREDICT)}}).encode()
    req = urllib.request.Request(OLLAMA, body,
                                 {"Content-Type": "application/json"})
    # THE CLOCK HAS TO GROW WITH THE CEILING. 300 s bounds a 3072-token
    # reply comfortably, but a thinking reply may run to NUM_PREDICT_THINK,
    # and at the ~23 tok/s a 31B generates on this card that alone is well
    # past 300 s before the prompt is read. Timing out here is the dearest
    # possible failure — the budget above then spends a SECOND full timeout
    # on the retry — so a thinking call gets a clock sized to what it was
    # allowed to generate rather than a promise that it will be brief.
    _timeout = 300 if not think else max(
        300, int(NUM_PREDICT_THINK / 15) + 120)
    with urllib.request.urlopen(req, timeout=_timeout) as r:
        d = json.loads(r.read())
    # Never let this go silent again. The signature is exact: an oversized
    # prompt is cut to num_ctx/2 + 3 (measured 4099 / 8195 / 16387), so
    # truncation is a narrow WINDOW at that value, not "large". A prompt
    # bigger than the window simply fit and was evaluated in full — reading
    # that as truncation cries wolf on every healthy long prompt.
    # WHAT THE CALL COST, kept for the caller's journal. Run 16's rounds
    # took 30 s where run 14's took 16 (2026-09-07, user: "this is taking
    # longer than the last runthrough in this area") and nothing recorded
    # whether the prompt or the reply was the cost. Ollama says both.
    global LAST
    LAST = stats_of(d)
    n = d.get("prompt_eval_count") or 0
    if (NUM_CTX // 2) <= n <= (NUM_CTX // 2) + 8:
        print(f"[prompt] TRUNCATED: {n} tokens evaluated at the "
              f"{NUM_CTX // 2} cap — the FRONT of the prompt was dropped "
              f"(vocabulary and guidance live there). Shorten the prompt or "
              f"raise NUM_CTX.")
    # THE OTHER END OF THE SAME FAILURE. A reply that runs INTO its ceiling
    # is cut wherever it happened to be — mid-JSON, which fails the parse
    # and costs the round with nothing on the page to say why. The prompt
    # side has said so since run 16; the reply side never did, and thinking
    # is what makes it likely: the trace eats the budget the macro needs.
    _cap = NUM_PREDICT_THINK if think else NUM_PREDICT
    _g = d.get("eval_count") or 0
    if _g >= _cap:
        print(f"[reply] TRUNCATED: generation stopped at the {_cap}-token "
              f"ceiling{' (thinking)' if think else ''} — the reply is cut "
              f"where it stood and will likely fail JSON parsing. Raise "
              f"{'RED_NUM_PREDICT_THINK' if think else 'RED_NUM_PREDICT'}.")
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

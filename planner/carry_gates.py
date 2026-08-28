#!/usr/bin/env python3
"""Carry EVENT GATES forward across a plan rewrite.

The add/update-never-delete rule only holds WITHIN one authoring pass. The
campaign re-authors a leg from scratch, so a plan written while the party was
stuck in Mt Moon B2F came back as "walk out" and dropped defeat_super_nerd —
leaving a leg whose every subgoal is satisfied by RETREATING, which marches to
its last step having achieved nothing.

Map hops may be re-planned freely; a flag/badge subgoal is an event that
something later depends on, so it is carried forward.

Usage: carry_gates.py <old_plan.json> <new_plan.json> [--journal run/executor_log.jsonl]
       (edits new in place)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def gates(plan: dict) -> list:
    out = []
    for sg in plan.get("subgoals") or []:
        dw = sg.get("done_when") or {}
        if isinstance(dw, dict) and ("flag" in dw or "badge" in dw):
            out.append(sg)
    return out


# How many rewrites may re-insert the same gate before the model's decision
# to drop it stands. The protection is against an ACCIDENTAL drop — a plan
# re-authored mid-dungeon that forgets what it came for — and one carry
# covers that. Carrying without limit means the harness overrides the model
# indefinitely on evidence the model has and it does not: leg_08 came back
# from the S.S. Anne carrying two Rocket gates keyed to EVENT_GOT_TM,
# re-inserted after the model had watched them fail and written them out,
# and each one is entitled to a full event-gate round budget.
MAX_CARRIES = 2


def failed_at(journal: Path | None, old: dict) -> dict | None:
    """The subgoal the attempt just died on, out of the journal the
    re-author was handed. Returns its record from the OLD plan, or None."""
    if not journal or not journal.exists():
        return None
    want = None
    try:
        with journal.open() as fh:
            for line in fh:
                if '"plan_failed_at"' not in line:
                    continue
                try:
                    want = json.loads(line).get("subgoal") or want
                except Exception:
                    pass
    except Exception:
        return None
    if not want:
        return None
    for sg in old.get("subgoals") or []:
        if sg.get("id") == want:
            return sg
    return None


def _kinds(sg) -> set:
    dw = sg.get("done_when") or {}
    return {k for k in ("flag", "badge") if k in dw}


def replaced(sg, old: dict, new: dict) -> bool:
    """Did the rewrite put a DIFFERENT gate of the same kind in its place?

    Carrying exists to survive an ACCIDENTAL drop — a plan re-authored
    mid-dungeon that forgets what it came for. A REPLACEMENT is not a drop.
    Leg 24 failed on defeat_giovanni {flag: EVENT_BEAT_GIOVANNI}, which is
    the VIRIDIAN GYM Giovanni and four badges away; the re-author read the
    journal, saw EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI fire in
    ROCKET_HIDEOUT_B4F, and wrote that instead. Carrying the old one back
    in — renamed defeat_giovanni_2, ahead of the fixed one — re-imposed
    exactly what the rewrite was called to fix, twice, and the leg could
    not pass however many attempts it was given (user: "not triggering,
    probably a different event flag for defeating giovanni the first time
    in the hideout").

    A drop still gets carried: if the rewrite answered "party too weak for
    Brock" by writing a training plan with no badge gate at all, nothing
    replaced it and the gate comes back.
    """
    mine = _kinds(sg)
    if not mine:
        return False
    was = {json.dumps(g.get("done_when") or {}, sort_keys=True)
           for g in gates(old)}
    for cand in gates(new):
        if not (_kinds(cand) & mine):
            continue
        if json.dumps(cand.get("done_when") or {}, sort_keys=True) in was:
            continue                       # the new plan simply kept an old
        return True                        # gate; a NEW one is a substitute
    return False


def live_flags(state: Path | None = None):
    """The event flags SET in the state snapshot the re-author reads, or
    None when there is no snapshot to read."""
    srcs = [state] if state else [Path("run/last_state.json"),
                                  Path("run/obs.json")]
    for src in srcs:
        try:
            o = json.loads(src.read_text())
        except Exception:
            continue
        if isinstance(o, dict) and isinstance(o.get("flags"), list):
            return {str(f) for f in o["flags"]}
    return None


def fired_and_cleared(journal: Path | None, live) -> dict:
    """flag -> where it fired, for every flag the journal watched fire that
    is NOT set now. A gate on such a flag is not a milestone the rewrite
    dropped by mistake: it is a condition that came and went (a boulder-
    switch event is kept only while the boulder sits on the switch and is
    cleared on leaving the floor). Victory Road, 2026-08-28: the author,
    refused a step on EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH, wrote a clean
    2F -> 3F -> Indigo plan, and this file put the step back — twice, on
    two flags — so the run went on warping between floors after an event
    that cannot be true from where the plan had brought it."""
    if not journal or not journal.exists() or live is None:
        return {}
    out = {}
    try:
        with journal.open() as fh:
            for line in fh:
                if '"flag_fired"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                f = r.get("flag")
                if f and f not in live:
                    out[f] = r.get("region") or "?"
    except Exception:
        return {}
    return out


def carry(old: dict, new: dict, journal: Path | None = None,
          live=None) -> tuple:
    """Return (merged, carried_ids). Matching is by CONDITION, not id, so a
    renamed subgoal with the same done_when is not duplicated."""
    have = {json.dumps(sg.get("done_when") or {}, sort_keys=True)
            for sg in new.get("subgoals") or []}
    _died_on = failed_at(journal, old)
    _swap = (_died_on is not None and replaced(_died_on, old, new))
    if _swap:
        print(f"[gates] not carrying {_died_on.get('id')} "
              f"{json.dumps(_died_on.get('done_when') or {})} — the attempt "
              f"failed on it and the rewrite put a different gate of the "
              f"same kind in its place. That is a replacement, not a drop.")
    _gone = fired_and_cleared(journal, live_flags() if live is None else live)
    missing, spent = [], []
    for sg in gates(old):
        if _swap and sg.get("id") == _died_on.get("id"):
            continue
        _fl = (sg.get("done_when") or {}).get("flag")
        if _fl in _gone:
            print(f"[gates] not carrying {sg.get('id')} — its flag {_fl} "
                  f"fired in {_gone[_fl]} and is NOT set now; a condition "
                  f"that came and went is not a milestone the rewrite "
                  f"dropped by mistake")
            continue
        if json.dumps(sg.get("done_when") or {}, sort_keys=True) in have:
            continue
        if int(sg.get("carried_forward") or 0) >= MAX_CARRIES:
            spent.append(sg.get("id"))
            continue
        sg = dict(sg)
        sg["carried_forward"] = int(sg.get("carried_forward") or 0) + 1
        # Matching is by CONDITION, so a gate can arrive beside a subgoal
        # that already answers to its name: v2 wrote defeat_giovanni
        # {no_battle} and v1's defeat_giovanni {flag: EVENT_BEAT_GIOVANNI}
        # was carried in next to it. Ids key the failure rap sheet and the
        # status line, and validate() has already run by the time we merge,
        # so a collision here is never caught. Rename rather than collide.
        taken = {s.get("id") for s in new.get("subgoals") or []}
        if sg.get("id") in taken:
            base, n = sg["id"], 2
            while f"{base}_{n}" in taken:
                n += 1
            sg["id"] = f"{base}_{n}"
        missing.append(sg)
    if spent:
        print(f"[gates] leaving {len(spent)} gate(s) dropped — carried "
              f"{MAX_CARRIES}x already and never once satisfied: "
              f"{', '.join(str(s) for s in spent)}")
    if not missing:
        return new, []
    subs = list(new.get("subgoals") or [])
    old_subs = list(old.get("subgoals") or [])

    def cond(sg):
        return json.dumps(sg.get("done_when") or {}, sort_keys=True)

    def place(gate):
        """Insert by the gate's NEIGHBOURS in the old plan, not blindly at
        the end. Appending before the last step put defeat_super_nerd AFTER
        the subgoals that leave Mt Moon — a fight with someone you have
        already walked away from, unsatisfiable by construction."""
        idx = next((i for i, sg in enumerate(old_subs)
                    if cond(sg) == cond(gate)), None)
        if idx is None:
            return max(0, len(subs) - 1)
        # Anchor on position in the NEW plan, not on the first match found
        # scanning the old one. Taking the first backward match put the gate
        # after descend_to_b1f while descend_to_b2f sat later in the new plan
        # — the nerd fought from the wrong floor. Of everything that preceded
        # the gate, use the one that ends up LATEST in the new plan; of
        # everything that followed it, the one that lands EARLIEST.
        # Conditions REPEAT in these plans — descend_to_b1f and
        # exit_mt_moon_b2f are both {map: MT_MOON_B1F} — so "latest match"
        # walks the gate past the exit it should precede. Anchor on the
        # gate's IMMEDIATE predecessor at its FIRST occurrence, stepping
        # further back only when that step is absent from the new plan.
        for prev in reversed(old_subs[:idx]):
            at = next((i for i, sg in enumerate(subs)
                       if cond(sg) == cond(prev)), None)
            if at is not None:
                return at + 1
        for nxt in old_subs[idx + 1:]:
            at = next((i for i, sg in enumerate(subs)
                       if cond(sg) == cond(nxt)), None)
            if at is not None:
                return at
        return max(0, len(subs) - 1)

    for sg in missing:
        subs.insert(place(sg), sg)
    merged = dict(new)
    merged["subgoals"] = subs
    return merged, [sg["id"] for sg in missing]


def carry_macros(old: dict, new: dict) -> list:
    """Attach the old plan's distilled MACROS to the rewrite, in place.

    A macro is the run's accumulated skill: an op sequence escalation
    proved and distill wrote back. A rewrite is authored from scratch and
    author.py never writes macros, so every rewrite arrived empty and the
    leg re-derived routes it already had. leg_03.v1 carried seven — five
    ops to Route 2, seven into the forest, a twelve-op training macro,
    four out, Pewter, the gym, Brock — and leg_03.v2 had none, after
    which the run spent eight escalations in two legs and was still in
    Viridian with a level 5 CHARMANDER.

    MATCHED BY CONDITION, NOT BY ID, exactly as gates are: ids are renamed
    freely between passes (reach_pallet_town -> go_to_pallet_town in the
    very next rewrite), while done_when is the contract a macro satisfies.

    ONLY ONTO SUBGOALS THE REWRITE LEFT EMPTY. If the new plan already
    carries a macro for that condition it is the newer evidence and wins;
    nothing the model wrote is overwritten.

    Not bounded like the gates. MAX_CARRIES exists because re-inserting a
    gate overrides a decision the model made to drop it — but a plan
    author cannot express "do not use that route", since authored plans
    have no macros at all. There is no decision here to override. A macro
    that has stopped working simply fails on replay and escalation takes
    over, which is what would have happened with no macro anyway.
    """
    by_cond = {}
    for sg in old.get("subgoals") or []:
        m = sg.get("macro")
        if isinstance(m, list) and m:
            by_cond.setdefault(
                json.dumps(sg.get("done_when") or {}, sort_keys=True),
                (m, sg.get("macro_provenance")))
    if not by_cond:
        return []
    done = []
    for sg in new.get("subgoals") or []:
        if sg.get("macro"):
            continue
        hit = by_cond.get(json.dumps(sg.get("done_when") or {},
                                     sort_keys=True))
        if not hit:
            continue
        macro, prov = hit
        sg["macro"] = macro
        # the model authored this route in an earlier pass, and the marker
        # has to keep saying so — provenance travels with the macro
        if prov:
            sg["macro_provenance"] = dict(prov)
            sg["macro_provenance"]["carried_from_rewrite"] = True
        done.append(f"{sg['id']}({len(macro)})")
    return done


def main() -> int:
    # A FLAG'S VALUE IS NOT A POSITIONAL. Filtering only the "--" words left
    # the journal PATH in the positional list, so the usage text printed and
    # no gate was carried at all — the opposite of this file's whole job,
    # shipped live for one leg.
    argv, args, journal = list(sys.argv[1:]), [], None
    while argv:
        a = argv.pop(0)
        if a == "--journal" and argv:
            journal = Path(argv.pop(0))
        elif a.startswith("--"):
            continue
        else:
            args.append(a)
    if len(args) != 2:
        print(__doc__)
        return 2
    old_p, new_p = Path(args[0]), Path(args[1])
    try:
        old = json.loads(old_p.read_text())
        new = json.loads(new_p.read_text())
    except Exception as e:                       # a missing/short file is not
        print(f"[gates] could not merge: {e}")   # worth failing the campaign
        return 0
    merged, carried = carry(old, new, journal)
    macros = carry_macros(old, merged)
    if carried or macros:
        new_p.write_text(json.dumps(merged, indent=1))
    if carried:
        print(f"[gates] carried {len(carried)} event gate(s) forward into "
              f"{new_p.name}: {', '.join(carried)}")
    if macros:
        print(f"[gates] carried {len(macros)} distilled macro(s) forward "
              f"into {new_p.name}: {', '.join(macros)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

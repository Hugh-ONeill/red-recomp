#!/usr/bin/env python3
"""Put outline candidates side by side for a HAND pick.

    planner/compare_outlines.py plans/candidates/outline.*.txt
    planner/compare_outlines.py plans/outline.authored plans/candidates/*.txt

For each outline: how many legs, the badge order it chose, how many upkeep
legs (levels, types, moves), objectives that look like the same thing twice,
and whether the gates a run cannot get past without are NAMED and in a
place that can work — the parcel before Brock, CUT before Surge's gym, the
Silph Scope before the Tower, the Flute from Fuji before the Snorlax, SURF
from the Safari Warden (not a gym) before the sea, STRENGTH before Seafoam
and Victory Road, Silph Co before Sabrina, the Secret Key before Blaine,
Victory Road before the Plateau. And an arrival that comes AFTER acting in
that town ("Reach Pewter City" after "Defeat Brock", run 15's outline).

THIS IS OUR JUDGE FOR OUR CHOICE, and nothing here reaches the model. The
never-point rule governs what the model is told; the person choosing
between its drafts is owed the truth about them in one screen. What each
outline gets right or wrong is still only what the game's box and a
finished run make obvious, and the pick stays a person's.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BADGES = [("boulder", "B"), ("cascade", "C"), ("thunder", "T"),
          ("rainbow", "R"), ("marsh", "M"), ("soul", "S"),
          ("volcano", "V"), ("earth", "E")]

# leader -> the town whose gym is theirs, for the "arrive after acting" check
TOWN_OF = {"brock": "pewter", "misty": "cerulean", "surge": "vermilion",
           "erika": "celadon", "sabrina": "saffron", "koga": "fuchsia",
           "blaine": "cinnabar", "giovanni": "viridian"}

# (gate, what names it, what it must come BEFORE, what makes its source
#  wrong, what must have happened FIRST — the town it is got in)
GATES = [
    ("parcel",  r"parcel",
     r"boulder badge", None, r"viridian"),
    ("scope",   r"silph scope|rocket hideout|game corner|hideout",
     r"pokemon tower|cleanse|fuji|flute", None, r"celadon"),
    ("fuji",    r"fuji|pokemon tower|cleanse",
     r"flute", None, r"lavender"),
    ("flute",   r"flute",
     r"snorlax|soul badge|fuchsia|cycling|route 12|route 16", None,
     r"fuji|pokemon tower|lavender"),
    ("cut",     r"\bcut\b|hm01|captain|s\.?\s?s\.?\s?anne",
     r"thunder badge", None, r"vermilion|cascade badge"),
    ("silph",   r"silph co|card key|president|master ball",
     r"marsh badge", None, r"saffron"),
    ("surf",    r"\bsurf\b|hm03",
     r"seafoam|cinnabar|volcano badge", r"gym|blaine|cinnabar",
     r"fuchsia|soul badge"),
    ("strength", r"strength|hm04|warden|gold teeth",
     r"seafoam|victory road", None, r"fuchsia|soul badge"),
    ("secret key", r"secret key|mansion",
     r"volcano badge", None, r"cinnabar"),
    ("victory road", r"victory road",
     r"elite four|champion|indigo plateau", None, r"earth badge"),
]

ARRIVE = re.compile(r"(reach|arrive|travel|go|sail|enter|walk|fly|ride|"
                    r"navigate|cross|get to|head|make your way)\b", re.I)

ACQUIRE = re.compile(r"(obtain|retrieve|get|receive|collect|find|acquire|"
                     r"pick up|take|grab)\b", re.I)

UPKEEP = re.compile(r"^(every party member|the party holds|a party pokemon "
                    r"knows|the party has|a .* type is in the party|"
                    r"a .* is in the party)", re.I)

STOP = set("the a an for to from of in on at and or with into by up out "
           "reach retrieve obtain get defeat go city town island route the "
           "poke pokemon navigate through clear cross travel".split())


def _words(leg: str) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", leg.lower())
            if w not in STOP and len(w) > 2}


def _first(legs, rx):
    r = re.compile(rx, re.I)
    for i, l in enumerate(legs):
        if r.search(l):
            return i
    return None


def _badge_index(legs, badge):
    r = re.compile(rf"{badge} badge", re.I)
    for i, l in enumerate(legs):
        if r.search(l):
            return i
    return None


def judge(legs: list) -> dict:
    out = {"legs": len(legs)}
    order = sorted(((i, code) for name, code in BADGES
                    for i in [_badge_index(legs, name)] if i is not None))
    out["badges"] = "".join(c for _, c in order)
    out["badges_missing"] = [n.capitalize() for n, c in BADGES
                             if c not in out["badges"]]
    out["upkeep"] = sum(1 for l in legs if UPKEEP.search(l))
    # gates
    gates, flags = {}, []
    for name, need, before, wrong, after in GATES:
        i = _first(legs, need)
        if i is None:
            gates[name] = "✗"
            flags.append(f"{name}: not named")
            continue
        j = _first(legs, before)
        # the first leg that ARRIVES where it is got (or wins a badge
        # there); a deed that merely names the town is not an arrival
        k = next((n for n, l in enumerate(legs)
                  if n != i and re.search(after, l, re.I)
                  and (ARRIVE.match(l) or "badge" in l.lower())), None)
        if wrong and re.search(wrong, legs[i], re.I):
            gates[name] = "?"
            flags.append(f"{name}: named at a wrong source — {legs[i]!r}")
        elif j is not None and j < i:
            gates[name] = "↓"
            flags.append(f"{name}: {legs[i]!r} comes AFTER {legs[j]!r}")
        elif k is not None and k > i:
            gates[name] = "↑"
            flags.append(f"{name}: {legs[i]!r} comes BEFORE {legs[k]!r}, "
                         f"where it is got")
        else:
            gates[name] = "✓"
    out["gates"] = gates
    # Viridian's gym is shut until the other seven badges are won
    e = _badge_index(legs, "earth")
    if e is not None:
        late = [n.capitalize() for n, c in BADGES if n != "earth"
                and (_badge_index(legs, n) or 0) > e]
        if late:
            flags.append(f"Earth Badge before {', '.join(late)}: Viridian's "
                         f"gym is shut until the other seven are won")
    # arriving after acting there
    for leader, town in TOWN_OF.items():
        a = _first(legs, rf"^(reach|arrive|travel|get)\b.*{town}")
        d = _first(legs, rf"{leader}")
        if a is not None and d is not None and d < a:
            flags.append(f"arrival after the deed: {legs[a]!r} comes after "
                         f"{legs[d]!r}")
    # the same thing twice (two shared significant words, the author's own
    # dedupe threshold), badges and upkeep legs excluded
    plain = [(i, l) for i, l in enumerate(legs)
             if not UPKEEP.search(l) and not re.search(r"badge", l, re.I)]
    dupes = []
    for a in range(len(plain)):
        for b in range(a + 1, len(plain)):
            wa, wb = _words(plain[a][1]), _words(plain[b][1])
            both = len(wa & wb)
            if both >= 2 and both / max(1, min(len(wa), len(wb))) >= 0.67:
                dupes.append((plain[a][1], plain[b][1]))
    # ...and a thing the game hands over ONCE, named by two legs (run 15's
    # "Retrieve the Pokemon Flute from Mr. Fuji" and "Retrieve the
    # Snorlax-blocking Poke Flute" share one word, so the two-word rule
    # let both through)
    for name, rx in [("flute", r"flute"), ("s.s. ticket", r"ticket"),
                     ("silph scope", r"scope"), ("card key", r"card key"),
                     ("secret key", r"secret key"), ("bike", r"bike|bicycle"),
                     ("hm01", r"hm01"), ("hm02", r"hm02"), ("hm03", r"hm03"),
                     ("hm04", r"hm04"), ("hm05", r"hm05"),
                     ("gold teeth", r"gold teeth"), ("parcel", r"parcel")]:
        # two legs that GET it; a leg that then uses it is not a twin
        hits = [l for _, l in plain if re.search(rx, l, re.I)
                and ACQUIRE.match(l)]
        if len(hits) > 1 and not any(set(h) == set(hits) for h in
                                     ([x, y] for x, y in dupes)):
            dupes.append((hits[0], hits[1]))
    out["dupes"] = dupes
    for x, y in dupes:
        flags.append(f"twice?: {x!r} / {y!r}")
    out["flags"] = flags
    return out


def main(paths):
    rows = []
    for p in paths:
        p = Path(p)
        legs = [l.strip() for l in p.read_text().splitlines() if l.strip()]
        j = judge(legs)
        secs = p.with_suffix(".seconds")
        j["seconds"] = (int(secs.read_text().strip())
                        if secs.exists() else None)
        rows.append((p, legs, j))
    names = [str(p.name) for p, _, _ in rows]
    w = max(len(n) for n in names)
    gate_names = [g[0] for g in GATES]
    print(f"{'outline':<{w}}  legs  badges    upkeep  time    "
          + "  ".join(g[:8].center(8) for g in gate_names))
    for p, legs, j in rows:
        t = f"{j['seconds'] // 60}m{j['seconds'] % 60:02d}s" if j["seconds"] else "--"
        b = j["badges"] + ("" if not j["badges_missing"]
                           else f" -{len(j['badges_missing'])}")
        print(f"{p.name:<{w}}  {j['legs']:>4}  {b:<9} {j['upkeep']:>6}  "
              f"{t:<7} "
              + "  ".join(j["gates"][g].center(8) for g in gate_names))
    print("\n  ✓ named and in a place that can work   ↓ named, but after what "
          "needs it   ↑ named before the town it is got in   ? named at a "
          "wrong source   ✗ not named")
    print("  badges: the order of the eight, first letter each "
          "(B C T R M S V E is the box's order; R/M/S can swap)")
    for p, legs, j in rows:
        print(f"\n== {p.name}: {j['legs']} legs"
              + (f", {j['seconds']}s" if j["seconds"] else ""))
        if j["badges_missing"]:
            print(f"   MISSING BADGES: {', '.join(j['badges_missing'])}")
        for f in j["flags"]:
            print(f"   ! {f}")
        if not j["flags"] and not j["badges_missing"]:
            print("   no flags")
        for i, l in enumerate(legs, 1):
            print(f"   {i:>2}. {l}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])

#!/usr/bin/env python3
"""What the outline author keeps getting wrong, across every pass drawn.

    planner/outline_trends.py                    # every plans/candidates/*.log
    planner/outline_trends.py plans/candidates/outline.20260906-14*.log

One drawn outline is one sample of the model's recall; the judge
(compare_outlines.py) reads it alone. This reads ALL of them together — the
kept outline, every objective the merge left out, every one the dedupe
dropped, the era checklist — and tallies what recurs: a thing fetched from
the wrong place in pass after pass, a badge under a name the game never
uses, a real gate that no pass ever names, an objective that is nonsense
every time. Persistent across passes means it is not variance; it is either
the model's belief or something our prompt does to it (user, 2026-09-06:
"we should also be looking through all of them for alarming trends, if
theres persistent model hallucinations or something pointing to a prompt
issue").

OURS, OFFLINE. The game facts below are the checker's, for reading the
model's drafts; nothing here is shown to the model.
"""
from __future__ import annotations

import glob
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from author import _norm_obj                      # noqa: E402
except Exception:                                     # pragma: no cover
    def _norm_obj(t):
        return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()

# (item, where the game gives it, the wrong places drafts name it)
SOURCES = [
    ("Secret Key", r"secret key", r"pokemon mansion|mansion",
     r"game corner|safari|celadon|saffron|ruins|cinnabar (gym|lab)|blaine"),
    ("HM03 SURF", r"hm03|\bsurf\b", r"safari|secret house|warden",
     r"cinnabar|gym|blaine|mansion|seafoam|fuchsia gym|koga"),
    ("HM04 STRENGTH", r"hm04|strength", r"warden|fuchsia|safari|gold teeth",
     r"cinnabar|seafoam|victory|mansion|gym|celadon|game corner"),
    ("HM01 CUT", r"hm01|\bcut\b", r"s\.?\s?s\.?\s?anne|captain|vermilion",
     r"viridian|pewter|forest|mt\.? moon|cerulean|bill|celadon|game corner"),
    ("HM02 FLY", r"hm02|\bfly\b", r"route 16|celadon|cycling",
     r"vermilion|saffron|fuchsia|cinnabar|s\.?\s?s\.?\s?anne|lavender"),
    ("HM05 FLASH", r"hm05|flash", r"route 2|oak's aide|aide|viridian forest",
     r"rock tunnel|celadon|lavender|vermilion|s\.?\s?s\.?\s?anne"),
    ("Silph Scope", r"silph scope|\bscope\b", r"hideout|game corner|giovanni|rocket",
     r"silph co|saffron|lavender|tower|fuji|cinnabar"),
    ("Poke Flute", r"flute", r"fuji|tower|lavender",
     r"celadon|game corner|silph|saffron|vermilion|cycling|route 16"),
    ("S.S. Ticket", r"ticket", r"bill|cerulean|sea cottage|route 25",
     r"captain|celadon|game corner|saffron|chief|vermilion|dock|fan club"),
    ("Bike Voucher", r"voucher", r"fan club|vermilion", r"cerulean|celadon|game corner"),
    ("Card Key", r"card key", r"silph|5f", r"celadon|game corner|hideout|saffron gym"),
    ("Gold Teeth", r"gold teeth", r"safari", r"tower|lavender|celadon|cinnabar"),
    ("Master Ball", r"master ball", r"silph|president", r"game corner|celadon|cinnabar"),
    ("Oak's Parcel", r"parcel", r"mart|viridian", r"pewter|oak's lab$|cerulean"),
    ("Old Amber", r"old amber|amber", r"museum|pewter", r"mt\.? moon|cinnabar|lab"),
]

# names the game never prints
WRONG_BADGE = re.compile(r"\b(thunderbolt|grass|psychic|fire|poison|water|"
                         r"rock|electric|ground|ghost|fighting) badge", re.I)
BADGES = ["boulder", "cascade", "thunder", "rainbow", "soul", "marsh",
          "volcano", "earth"]

# things that are not in this game, or garbled past use
NONSENSE = [
    ("Pokemon/ball 'retrieved' from the Poke Mart (the parcel, garbled)",
     r"(retrieve|get|obtain).*(pokemon|poke ?balls?) from the (poke ?mart|pokemon center|mart)"),
    ("a Pikachu from the S.S. Anne", r"pikachu.*anne|anne.*pikachu"),
    ("'Ethereal' Bike", r"ethereal"),
    ("Secret Key 'returned' anywhere", r"return the secret key"),
    ("'Secret Technique'", r"secret technique"),
    ("Cycling Road as a place to GET the bicycle", r"bicycle from the cycling road|bike from the cycling road"),
    ("Rival as Champion by name 'Champion' before the Elite Four", r"defeated rival as the champion"),
]

# real gates worth counting the passes that never name them
WATCH = [
    ("Oak's parcel", r"parcel"),
    ("Bill", r"\bbill\b"),
    ("Viridian Forest", r"viridian forest|forest"),
    ("Mt. Moon", r"mt\.? moon"),
    ("Nugget Bridge", r"nugget bridge|bridge"),
    ("Rock Tunnel", r"rock tunnel"),
    ("Rocket Hideout / Scope", r"hideout|silph scope|\bscope\b"),
    ("Pokemon Tower / Fuji", r"tower|fuji"),
    ("Poke Flute", r"flute"),
    ("Snorlax", r"snorlax"),
    ("Silph Co", r"silph co|silph\b(?! scope)|liberate silph|rescue silph"),
    ("Safari Zone", r"safari"),
    ("SURF", r"\bsurf\b|hm03"),
    ("STRENGTH", r"strength|hm04"),
    ("Seafoam", r"seafoam"),
    ("Pokemon Mansion / Secret Key", r"mansion|secret key"),
    ("Victory Road", r"victory road"),
    ("Elite Four", r"elite four|lorelei"),
]


def read_pass(log: Path) -> dict:
    txt = log.with_suffix(".txt")
    kept = ([l.strip() for l in txt.read_text().splitlines() if l.strip()]
            if txt.exists() else [])
    left, dropped, era, adds, inserted, doubted = [], [], [], [], [], []
    for line in log.read_text(errors="replace").splitlines():
        m = re.match(r"\[outline\]\s+left out: '(.*)'$", line)
        if m:
            left.append(m.group(1)); continue
        m = re.match(r"\[outline\] dropped '(.*)': the same objective as '(.*)' \(", line)
        if m:
            dropped.append((m.group(1), m.group(2))); continue
        m = re.match(r"\[era\]   (.*)$", line)
        if m:
            era.append(m.group(1)); continue
        m = re.match(r"\[upkeep\] \+ '(.*)' (after|before) ", line)
        if m:
            adds.append(m.group(1)); continue
        m = re.match(r"\[outline\] inserted '(.*)' (after|before) ", line)
        if m:
            inserted.append(m.group(1)); continue
        m = re.match(r"\[outline\] doubted, kept: '(.*)'(?: — (.*))?$", line)
        if m:
            doubted.append((m.group(1), m.group(2) or "")); continue
    menu = list(dict.fromkeys(kept + left + [d for d, _ in dropped] + era
                              + inserted))
    return {"log": log, "kept": kept, "left": left, "dropped": dropped,
            "era": era, "adds": adds, "inserted": inserted,
            "doubted": doubted, "menu": menu}


def main(paths):
    passes = [read_pass(Path(p)) for p in paths]
    passes = [p for p in passes if p["menu"]]
    n = len(passes)
    if not n:
        sys.exit("no passes with anything in them")
    print(f"{n} pass(es); {sum(len(p['menu']) for p in passes)} objectives "
          f"drafted in all, {sum(len(p['kept']) for p in passes)} kept\n")

    # 1. wrong sources, by pass
    print("WHERE THINGS ARE FETCHED FROM — passes whose drafts name a wrong place")
    print("  (kept = it survived into the final outline; menu = any draft said it)")
    for item, rx, right, wrong in SOURCES:
        r_item, r_wrong = re.compile(rx, re.I), re.compile(wrong, re.I)
        r_right = re.compile(right, re.I)
        bad_menu, bad_kept, ok_kept, ex = 0, 0, 0, []
        for p in passes:
            bm = [l for l in p["menu"] if r_item.search(l) and r_wrong.search(l)
                  and not r_right.search(l)]
            bk = [l for l in p["kept"] if r_item.search(l) and r_wrong.search(l)
                  and not r_right.search(l)]
            ok = [l for l in p["kept"] if r_item.search(l) and r_right.search(l)]
            bad_menu += bool(bm); bad_kept += bool(bk); ok_kept += bool(ok)
            ex += bm[:1]
        if bad_menu or bad_kept:
            print(f"  {item:<14} wrong in {bad_menu}/{n} menus, kept wrong in "
                  f"{bad_kept}/{n}, kept RIGHT in {ok_kept}/{n}")
            for e in list(dict.fromkeys(ex))[:3]:
                print(f"      e.g. {e!r}")

    # 2. badge names the game never prints
    print("\nBADGE NAMES THE GAME NEVER PRINTS")
    c = Counter()
    for p in passes:
        for l in p["menu"]:
            m = WRONG_BADGE.search(l)
            if m:
                c[m.group(0).lower()] += 1
    if c:
        for k, v in c.most_common():
            print(f"  {k:<20} {v} draft line(s)")
        era_only = all(
            WRONG_BADGE.search(l) is None for p in passes for l in p["kept"])
        print("  " + ("none survived into a final outline — they come from "
                      "the era conversation, which is not handed the eight "
                      "badge names" if era_only else
                      "SOME SURVIVED INTO A FINAL OUTLINE"))
    else:
        print("  none")

    # 3. nonsense that recurs
    print("\nOBJECTIVES THAT ARE NOT IN THIS GAME, OR GARBLED — passes that drafted them")
    for label, rx in NONSENSE:
        r = re.compile(rx, re.I)
        hits = [(p, [l for l in p["menu"] if r.search(l)]) for p in passes]
        hits = [(p, ls) for p, ls in hits if ls]
        if hits:
            kept = sum(1 for p, ls in hits if any(l in p["kept"] for l in ls))
            print(f"  {label}: {len(hits)}/{n} passes, kept in {kept}")
            seen = list(dict.fromkeys(l for _, ls in hits for l in ls))
            for e in seen[:3]:
                print(f"      e.g. {e!r}")

    # 4. real gates, by how many passes ever name them
    print("\nREAL GATES — how many passes name each, anywhere in their drafts / in the kept outline")
    for label, rx in WATCH:
        r = re.compile(rx, re.I)
        menu_n = sum(1 for p in passes if any(r.search(l) for l in p["menu"]))
        kept_n = sum(1 for p in passes if any(r.search(l) for l in p["kept"]))
        flag = "  <- NEVER" if menu_n == 0 else ("  <- drafted, never kept"
                                                if kept_n == 0 else "")
        print(f"  {label:<26} drafted {menu_n}/{n}   kept {kept_n}/{n}{flag}")

    # 5. what the dedupe and the merge keep eating
    print("\nWHAT THE DEDUPE DROPPED, by shared words (a place name shared is the false-match class)")
    c = Counter()
    ex = defaultdict(list)
    for p in passes:
        for d, k in p["dropped"]:
            m = re.search(rf"dropped '{re.escape(d)}': the same objective as '{re.escape(k)}' \((.*?)\)",
                          p["log"].read_text(errors="replace"))
            key = m.group(1) if m else "?"
            c[key] += 1
            ex[key].append((d, k))
    for key, v in c.most_common(12):
        d, k = ex[key][0]
        print(f"  {v}x  ({key}): {d!r}  <-  {k!r}")

    # 6. what the review doubted
    doubts = [(l, w) for p in passes for l, w in p["doubted"]]
    if doubts:
        print("\nWHAT THE REVIEW DOUBTED (kept anyway)")
        for l, w in doubts[:12]:
            print(f"  {l!r}" + (f" — {w[:110]}" if w else ""))

    # 7. objectives every pass agrees on, and singletons
    freq = Counter()
    first = {}
    for p in passes:
        seen = set()
        for l in p["menu"]:
            k = _norm_obj(l)
            if k in seen:
                continue
            seen.add(k)
            freq[k] += 1
            first.setdefault(k, l)
    core = [first[k] for k, v in freq.items() if v == n]
    print(f"\nIN EVERY PASS'S DRAFTS ({len(core)}):")
    for l in sorted(core):
        print(f"  {l}")
    print(f"\nIN ONE PASS ONLY: {sum(1 for v in freq.values() if v == 1)} "
          f"of {len(freq)} distinct objectives")


if __name__ == "__main__":
    paths = sys.argv[1:] or sorted(glob.glob("plans/candidates/outline.*.log"))
    main(paths)

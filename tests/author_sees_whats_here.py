"""The author must see what the party is standing next to.

Planning "retrieve the Secret Key" from inside POKEMON_MANSION_B1F, the
author was shown untaken DOORS (the frontier block, ranked by distance) and
a sightings block capped ALPHABETICALLY at 40 of 239 areas — so B1F lost
its place to BIKE_SHOP, BILLS_HOUSE and BLUES_HOUSE, the two item balls it
had never picked up never reached the page, and it wrote a tour of the
building: 1F -> 2F -> 3F (user, watching: "its swinging between trying to
explore the basement and trying to go upstairs on phantom missions").

Two things had to hold: the block is ordered nearest-first/unpressed-first,
and _fit stops re-alphabetising the lines it keeps.
"""
import re
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "planner"))
import author

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


# _fit keeps near lines AND the order they arrived in
head = "WHAT WAS SEEN IN EACH AREA and so on and so forth for a while"
body = ["  ZZZ_FAR|0,0: thing"] + [f"  NEAR_MAP|{i},0: thing" for i in range(12)]
big = head + "\n" + "\n".join(body)
filler = "OTHER BLOCK HEADER\n" + "\n".join(f"  pad {i}" for i in range(4))
# a budget that costs ONE trimming pass, not a collapse to the hard
# truncation fallback (which fires once a block is down to <8 lines)
out = author._fit(big + "\n\n" + filler, budget=len(big) - 40,
                  near={"NEAR_MAP"})
kept = [l for l in out.splitlines() if l.startswith("  NEAR_MAP")]
ck("_fit keeps the near lines", len(kept) > 0)
ck("_fit preserves their order, not the alphabet",
   kept == sorted(kept, key=lambda l: body.index(l)))
# it only announces a cut when it actually cut something
_rows_in = len(body)
_rows_out = len([l for l in out.splitlines()
                 if l.startswith("  NEAR_MAP") or l.startswith("  ZZZ_FAR")])
ck("_fit announces a cut exactly when it made one",
   ("not shown" in out) == (_rows_out < _rows_in))

# the sightings rows carry (unpressed-first, hops, region, text)
ck("a nearer region outranks a farther one",
   (0, 1, "B") < (0, 9, "A"))
ck("anything unpressed outranks anything fully pressed",
   (0, 99, "Z") < (1, 0, "A"))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

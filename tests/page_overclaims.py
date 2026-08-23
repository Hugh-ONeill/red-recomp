"""Two things the page said that it could not know.

1. "You are STANDING on the closest ground you have walked to CINNABAR_ISLAND
   ... nothing else you have covered gets nearer. The way on is not on walked
   ground."  The distance behind that is measured MAP to map, so every walked
   part of Route 20 scores the same 1 leg and the tie breaks on `here`.  Both
   halves overclaim: ROUTE_20|58,9 is walked ground and is the one shore that
   touches the seam.  Read from the east side, it says stop looking at walked
   routes and force a way through HERE -- which is what 187 crossings did.

2. B4F's (20,17)/(21,17) offered as "plain untried doors, 5 leg(s) away".
   They are the cells the current bumps you back off, modelled since 86874b2.
   Untried they are; plain they are not.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

# --- 1. the closest-ground line ----------------------------------------
def route_line(want_map, legs, ties):
    if ties:
        return ("The printed map puts %s %d leg(s) from this map, and you "
                "are standing on a part of it you have walked. It CANNOT "
                "say which part touches the way on — these other walked "
                "parts are exactly as near by that measure and are "
                "different places: %s. Which of them the way on is "
                "actually through is not something the printed map knows."
                % (want_map, legs, ", ".join(ties[:4])))
    return ("You are STANDING on the closest ground you have walked to %s — "
            "the printed map puts it %d leg(s) from here, and nothing else "
            "you have covered gets nearer. The way on is not on walked "
            "ground: it is through something here you have not been "
            "through yet." % (want_map, legs))

tied = route_line("CINNABAR_ISLAND", 1, ["ROUTE_20|52,2", "ROUTE_20|58,9"])
ck("it stops saying the way on is not on walked ground",
   "not on walked ground" not in tied)
ck("it names the other walked parts", "ROUTE_20|58,9" in tied)
ck("it says the map cannot rank them", "CANNOT say which part" in tied)
ck("it still gives the printed distance", "1 leg(s)" in tied)
ck("it does not pick one for the model",
   "should" not in tied.lower() and "go to" not in tied.lower())

alone = route_line("CINNABAR_ISLAND", 1, [])
ck("with no other walked part the old wording stands",
   "nothing else you have covered gets nearer" in alone)

# --- 2. the floors-not-finished row ------------------------------------
def floor_row(mid, n, total, open_keys, forced):
    bad = [k for k in open_keys if k in forced]
    if bad:
        return ("%s has %d doorway(s): %d never taken and on ground you have "
                "stood on (%s), %d leg(s) away — but %s the water pushed you "
                "back off when you rode there, so being untried is not the "
                "same as being open"
                % (mid, total, len(open_keys), ", ".join(open_keys), n,
                   "both of those" if len(bad) == len(open_keys) == 2
                   else ", ".join(bad)))
    return ("%s has %d doorway(s): %d never taken and on ground you have "
            "stood on (%s) — plain untried doors, %d leg(s) away"
            % (mid, total, len(open_keys), ", ".join(open_keys), n))

r = floor_row("SEAFOAM_ISLANDS_B4F", 5, 4, ["20,17", "21,17"],
              {"20,17", "21,17", "20,16", "21,16"})
ck("forced doors are not called plain", "plain untried doors" not in r)
ck("it says the water pushed you back", "pushed you back off" in r)
ck("it still says they are untried", "never taken" in r)

r2 = floor_row("SEAFOAM_ISLANDS_B1F", 2, 7, ["25,3"], set())
ck("an ordinary untried door is still plain", "plain untried doors" in r2)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

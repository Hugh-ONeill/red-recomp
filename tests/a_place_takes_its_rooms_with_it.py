"""A leg that happens inside a place is not left before the leg that reaches it.

2026-09-02. "Reach Lavender Town" was deferred from 22 to 26 while "Cleanse
the Pokemon Tower" and "Retrieve the Pokemon Flute from Mr. Fuji" stayed at 22
and 23. Both of those happen INSIDE Lavender Town, and the Flute is the very
item the deferral's own stated reason named as the prerequisite for reaching
it, so the outline now said: fetch the thing from the tower in the town, then
later, arrive at the town. The chain began authoring a walk into a place the
run had never once entered.

The model saw it before the harness did — the tower plan it wrote opened with
go_to_lavender_town — but the outline is what the ladder reasons about.

Neither existing guard could catch it. The inserts ledger only knows legs that
were INSERTED to unblock something, and nothing had been. The prerequisite
guard reasons about items and flags, and this dependency is a PLACE.

The answer is the one the inserts case already settled: the deferral is the
model's and it stands; what cannot happen before it travels with it. Which
rooms belong to a place is read from the engine's own warp table, outward from
the place, because a building's way out is LAST_MAP and names nothing while a
town names every door in it."""
import os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "planner")
import author

REPO = Path.cwd().resolve()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

OUTLINE = ["Defeat Lt. Surge for the Thunder Badge",
           "Clear Rock Tunnel",
           "Reach Lavender Town",
           "Cleanse the Pokemon Tower",
           "Retrieve the Pokemon Flute from Mr. Fuji",
           "Reach Celadon City",
           "Obtain Fresh Water"]


def push(frm, after, outline=OUTLINE):
    d = Path(tempfile.mkdtemp())
    (d / "plans").mkdir(); (d / "run").mkdir()
    (d / "plans/outline.txt").write_text("\n".join(outline) + "\n")
    r = subprocess.run([sys.executable, str(REPO / "planner/push_leg.py"),
                        str(frm), str(after)],
                       cwd=d, capture_output=True, text=True)
    return ([l for l in (d / "plans/outline.txt").read_text().splitlines()
             if l.strip()], r.stdout + r.stderr)


lines, said = push(3, 6)          # Reach Lavender Town, 3 -> 6
def at(t): return lines.index(t) + 1

ck("the deferral itself still happens", at("Reach Lavender Town") > 3)
ck("the tower does not end up before the town it is in",
   at("Cleanse the Pokemon Tower") > at("Reach Lavender Town"))
ck("nor does Mr Fuji's house",
   at("Retrieve the Pokemon Flute from Mr. Fuji") > at("Reach Lavender Town"))
ck("the rooms keep their order among themselves",
   at("Cleanse the Pokemon Tower")
   < at("Retrieve the Pokemon Flute from Mr. Fuji"))
ck("a leg somewhere else is not dragged along",
   at("Reach Celadon City") < at("Reach Lavender Town"))
ck("...and the run is told they moved together",
   "and with it" in said and "Pokemon Tower" in said)
ck("nothing is lost", sorted(lines) == sorted(OUTLINE))

# the relation itself, read from the engine
rooms = author.rooms_of(["LAVENDER_TOWN"])
ck("a town's rooms include the tower's every floor",
   {"POKEMON_TOWER_1F", "POKEMON_TOWER_7F"} <= rooms)
ck("...and the houses in it", "MR_FUJIS_HOUSE" in rooms)
ck("a place is not a room of itself", "LAVENDER_TOWN" not in rooms)
ck("an outdoor map is a place, not a room: Route 10 owns Rock Tunnel",
   "ROCK_TUNNEL_1F" in author.rooms_of(["ROUTE_10"]))
ck("...and the walk through it does not swallow the far side",
   "LAVENDER_TOWN" not in author.rooms_of(["ROUTE_10"]))
ck("a cave between two routes does not leak into the other one",
   "ROUTE_2" not in author.rooms_of(["ROUTE_11"]))

lines2, _ = push(6, 7)            # Reach Celadon City, nothing of its own here
ck("a push with no rooms in the way is left alone",
   lines2.index("Reach Celadon City") > lines2.index("Obtain Fresh Water"))

src = Path("planner/push_leg.py").read_text()
ck("a failure to read the map never blocks a push",
   "ordering help, never a reason the push cannot happen" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)

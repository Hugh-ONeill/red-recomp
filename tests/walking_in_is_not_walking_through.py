"""Visit counts cannot tell walking IN from walking THROUGH.

"Clear Rock Tunnel" was judged already accomplished before it ever ran, on
this reasoning: "The player is currently on Route 9, which is the exit path
after successfully traversing Rock Tunnel." Route 9 is the side it went IN
by, the run has never stood in Lavender, and it had seen 542 of the tunnel's
1440 tiles (2026-08-30).

What check-done was given about that map was a stood-in count and a tile
count, and both are true of a party that walked one room in and turned round.
The doors it has come and gone by are the run's own record and say which
sides it has ever been out of. Whether that counts as "cleared" is still the
model's to judge — the harness only stops leaving the fact out.
"""
import sys, json, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

d = Path(tempfile.mkdtemp()) / "explored.json"
d.write_text(json.dumps({"explored": {
    "ROCK_TUNNEL_1F|14,2": {"15,3": {"to": "ROUTE_10|0,4"},
                            "37,3": {"to": "ROCK_TUNNEL_B1F|26,2"}},
    "ROCK_TUNNEL_B1F|26,2": {"33,25": {"to": "ROCK_TUNNEL_1F|14,2"}}},
    "visits": {"ROCK_TUNNEL_1F|14,2": 18, "ROCK_TUNNEL_B1F|26,2": 4}}))
t = A.walked_ground_text([(0, "Clear Rock Tunnel")], d)
ck("the map is still counted as before",
   "ROCK_TUNNEL_1F stood in 18x" in t, t)
ck("...and now says where its taken ways have led",
   "every way out of it you have ever taken led to" in t, t)
ck("...naming them, so a one-sided visit reads as one-sided",
   "ROCK_TUNNEL_B1F, ROUTE_10" in t, t)
ck("...and never LAVENDER_TOWN, which no way out has reached",
   "LAVENDER" not in t, t)
ck("nothing is claimed about whether that is 'cleared'",
   "clear" not in t.lower().replace("clear rock tunnel", ""), t)

# a map the run has walked but never left says only that
d.write_text(json.dumps({"explored": {"ROCK_TUNNEL_1F|14,2": {}},
                         "visits": {"ROCK_TUNNEL_1F|14,2": 3}}))
t2 = A.walked_ground_text([(0, "Clear Rock Tunnel")], d)
ck("a map with no taken way out adds no clause",
   "every way out" not in t2 and "stood in 3x" in t2, t2)

src = (ROOT / "planner" / "author.py").read_text()
ck("check-done is the caller that gets this",
   "walked_ground_text([(0, goal)], observed)" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:220])
sys.exit(1 if bad else 0)

"""A try that carried you twenty cells did not come to nothing.

The 3-strikes gate claims "this came to nothing 3 times, with nothing about
you changed since".  It was banking strikes against a cross whose own
failure line read: "a fight started 38 cell(s) short of the west edge gap
(0,16) -- the walk stopped at (38,16) because of the battle, not because of
the ground".  Twenty cells of open sea crossed and a wild fight survived,
called nothing -- and then the one move that was working was refused, so the
run flew back to Fuchsia because that was all the harness had left unblocked.
A wild battle is the sea being the sea.  Interrupting is not refusing.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

class Gate:
    """_strike / _gated, with the rule as executor.py applies it."""
    def __init__(self):
        self._dead_ops, self._dead_at, self._dead_why = {}, {}, {}
        self._mark_now = "mark-1"
    @staticmethod
    def _spot(obs):
        o = obs or {}
        pl = o.get("player") or {}
        return (((o.get("map") or {}).get("id")), pl.get("x"), pl.get("y"))
    def _strike(self, sig, det, pre=None, post=None):
        if pre is not None and post is not None:
            if self._spot(pre) != self._spot(post):
                self._dead_ops[sig] = 0
                self._dead_at[sig] = self._mark_now
                self._dead_why[sig] = str(det or "")[:160]
                return
        _d = str(det or "").lower()
        if "because of the battle" in _d or "a fight started" in _d:
            self._dead_why[sig] = str(det or "")[:160]
            return
        if self._dead_at.get(sig) != self._mark_now:
            self._dead_ops[sig] = 0
            self._dead_at[sig] = self._mark_now
        self._dead_ops[sig] = self._dead_ops.get(sig, 0) + 1
        self._dead_why[sig] = str(det or "")[:160]
    def refuses(self, sig):
        return self._dead_ops.get(sig, 0) >= 3

def at(x, y):
    return {"map": {"id": "ROUTE_20"}, "player": {"x": x, "y": y}}

SIG = ("cinnabar", "ROUTE_20|58,9", "cross", "west", None, None, None, None, None)
BATTLE = ("a fight started 38 cell(s) short of the west edge gap (0,16) — the "
          "walk stopped at (38,16) because of the battle, not because of the ground")
WALL = ("the west seam of ROUTE_20 (to CINNABAR_ISLAND) cannot be walked to "
        "from here — no walkable path reaches it")

# the live sequence: three crossings cut short by wild fights, each of which
# carried the party a long way west
g = Gate()
for start in ((58, 12), (52, 14), (48, 15)):
    g._strike(SIG, BATTLE, at(*start), at(38, 16))
ck("three battle-cut crossings do not refuse the fourth", not g.refuses(SIG))
ck("the reason is still remembered", "fight started" in g._dead_why[SIG])

# a genuine wall, where nothing moved, still strikes out
g = Gate()
for _ in range(3):
    g._strike(SIG, WALL, at(45, 7), at(45, 7))
ck("a wall that never moves you still refuses", g.refuses(SIG))

# strikes already banked are cleared the moment the action moves the party
g = Gate()
for _ in range(3):
    g._strike(SIG, WALL, at(45, 7), at(45, 7))
ck("banked before the water opened", g.refuses(SIG))
g._strike(SIG, BATTLE, at(58, 12), at(38, 16))
ck("one real crossing clears the stale strikes", not g.refuses(SIG))

# and the battle guard works even where no observations are passed
g = Gate()
for _ in range(4):
    g._strike(SIG, BATTLE)
ck("a battle never strikes, obs or no obs", not g.refuses(SIG))
g = Gate()
for _ in range(3):
    g._strike(SIG, WALL)
ck("a wall still strikes with no obs", g.refuses(SIG))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

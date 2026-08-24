"""The walk-back after a blackout never takes a one-way door.

Wiped at Lance, healed in the Indigo lobby with an empty bag and the mart
beside it, the run was walked straight back through Lorelei's door — which
locks behind you — before the model was asked anything (2026-08-24). Recall
retraces only ground it has retraced back OUT of; a door crossed 19x and
never come back out of is a decision, and decisions are the model's.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

LOBBY, LOR, BRU = "INDIGO_PLATEAU_LOBBY|8,0", "LORELEIS_ROOM|4,1", "BRUNOS_ROOM|0,1"
OUT = "INDIGO_PLATEAU|9,5"

class FakeBridge:
    def __init__(self): self.sent = []
    def send(self, op, **kw): self.sent.append((op, kw)); return {"result": {"ok": True}}
    def obs(self): return {"map": {"id": "INDIGO_PLATEAU_LOBBY", "region": "8,0"}, "mode": "overworld"}

def build(reverse):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = {
        LOBBY: {"8,0": {"n": 19, "to": LOR}, "7,11": {"n": 3, "to": OUT}},
        OUT: {"north": {"n": 3, "to": LOBBY}},
        LOR: {"4,0": {"n": 5, "to": BRU}},
        BRU: {},
    }
    if reverse:
        ex.explored[LOR]["4,11"] = {"n": 2, "to": LOBBY}
    ex.visits = {}
    ex._mark_now = [8, 400, 16]
    ex._bad_seam = set()
    ex._faint_at = BRU
    ex.b = FakeBridge()
    ex.logged = []
    ex.log = lambda kind, **kw: ex.logged.append((kind, kw))
    ex.settle = lambda: ex.b.obs()
    ex._where = lambda o: f"{(o or {}).get('map', {}).get('id')}|{(o or {}).get('map', {}).get('region')}"
    return ex

ex = build(reverse=False)
r = ex._return_from_blackout(ex.b.obs(), {"id": "defeat_lance"})
ck("no walk-back through a door never come back out of", r is None)
ck("not a single hop was sent", not any(op in ("use_warp", "cross") for op, _ in ex.b.sent))
halt = [kw for k, kw in ex.logged if k == "blackout_return_halted"]
ck("the halt is logged", bool(halt))
ck("it names the door and the room beyond", halt and halt[0]["door"] == "8,0" and halt[0]["into"] == LOR)
ck("it carries the crossing count", halt and halt[0]["crossings"] == 19)
ck("the note for the model is armed", getattr(ex, "_return_halt", None) is not None)
ck("the faint marker is cleared so nothing retries it", ex._faint_at is None)

ex = build(reverse=True)
ex._return_from_blackout(ex.b.obs(), {"id": "defeat_lance"})
ck("a door the run HAS come back out of is still retraced",
   any(op == "use_warp" for op, _ in ex.b.sent))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

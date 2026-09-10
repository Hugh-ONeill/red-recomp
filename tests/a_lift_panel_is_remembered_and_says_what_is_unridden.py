#!/usr/bin/env python3
"""A panel seen once is never unseen, and an unridden floor is unfinished.

The floors a lift serves exist only on the menu on screen, so the shim
learns them by pressing.  Its table is per GAME PROCESS, so every boot
forgets them while the run's atlas goes on remembering which floors were
ridden.  Celadon Mart's car read "the panel on the wall lists the floors
this lift serves" and then listed none, on a run that had ridden it eight
times.

4F is the one floor of that building the run has never walked, and the one
that sells the evolution stones two party members were waiting on
(2026-09-10).

The rides are in the atlas as lift:<MAP> edges and the panel's labels are
floor suffixes, so the two are matched by NAME, the same reading _building
already does.  Which floor is worth riding to stays the model's; nothing
here says what any floor holds.  Synthetic: no game.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

CAR = "CELADON_MART_ELEVATOR|0,1"
PANEL = ["1F", "2F", "3F", "4F", "5F", "ROOF"]
RODE = {"lift:CELADON_MART_1F": {"n": 3}, "lift:CELADON_MART_2F": {"n": 2},
        "lift:CELADON_MART_5F": {"n": 1}}


def line(panel, remembered=None, rode=RODE):
    ex = E.Executor.__new__(E.Executor)
    ex.lift_floors = dict(remembered or {})
    ex.explored = {CAR: dict(rode)}
    ex.saved = []
    ex._save_memory = lambda: ex.saved.append(dict(ex.lift_floors))
    ex._where = lambda o: CAR
    m = {"id": "CELADON_MART_ELEVATOR", "region": "0,1"}
    if panel is not None:
        m["lift_floors"] = list(panel)
    # the paragraph is built inside exploration_text; drive just its inputs
    # through the same expression the method uses
    obs = {"map": m}
    _lmid = str(m.get("id") or "")
    lift = list(m.get("lift_floors") or [])
    if lift and _lmid:
        if ex.lift_floors.get(_lmid) != lift:
            ex.lift_floors[_lmid] = lift
            ex._save_memory()
    elif _lmid:
        lift = list((ex.lift_floors or {}).get(_lmid) or [])
    if not lift:
        return "", ex
    _rode = set()
    for _k in (ex.explored.get(ex._where(obs)) or {}):
        if str(_k).startswith("lift:"):
            _rode.add(str(_k).split(":", 1)[1].rsplit("_", 1)[-1])
    _new = [f for f in lift if str(f).upper() not in _rode]
    out = ("The panel in this car offers: " + ", ".join(lift)
           + (" — and this car has never carried you to " + ", ".join(_new)
              if _new and len(_new) != len(lift) else "")
           + ". Riding it is the only way to those floors.")
    return out, ex


# ---- the panel on screen is recorded --------------------------------
out, ex = line(PANEL)
ck("the panel's floors are listed", "1F, 2F, 3F, 4F, 5F, ROOF" in out)
ck("...and the unridden ones are named",
   "never carried you to 3F, 4F, ROOF" in out, out)
ck("...and the ridden ones are not called new",
   "to 1F" not in out.split("never carried")[1], out)
ck("the panel is written to memory", ex.lift_floors["CELADON_MART_ELEVATOR"] == PANEL)
ck("...and saved, so a boot does not lose it", ex.saved)

# ---- a boot with no panel on screen reads it back -----------------------
out2, _ = line(None, remembered={"CELADON_MART_ELEVATOR": PANEL})
ck("a car whose panel is not on screen still lists it",
   "1F, 2F, 3F, 4F, 5F, ROOF" in out2)
ck("...and still names what was never ridden", "never carried you to" in out2)

# ---- nothing known, nothing claimed -------------------------------------
out3, _ = line(None)
ck("a car nobody has pressed says nothing about floors", out3 == "")

# ---- every floor ridden: no unridden clause -----------------------------
ALL = {f"lift:CELADON_MART_{f}": {"n": 1} for f in PANEL}
out4, _ = line(PANEL, rode=ALL)
ck("a fully ridden car claims no unridden floor",
   "never carried you" not in out4 and "1F, 2F, 3F, 4F, 5F, ROOF" in out4)

# ---- and the memory is persisted like its siblings ----------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("lift_floors is saved with the rest of the memory", '"lift_floors": {k: list(v)' in SRC)
ck("...and loaded back", 'data.get("lift_floors")' in SRC)
# THE TEST RE-RUNS THE EXPRESSION, so pin the shipped one to the same shape
# or the two drift apart in silence.
_blk = SRC.split("lift = list(m.get(\"lift_floors\") or [])", 1)[1][:1600]
for _frag in ('self.lift_floors[_lmid] = lift',
              'lift = list((getattr(self, "lift_floors", None) or {}).get(_lmid)',
              'str(_k).startswith("lift:")',
              '.rsplit("_", 1)[-1]',
              "never carried you to"):
    ck(f"the shipped paragraph still does: {_frag[:44]}", _frag in _blk)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:160] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

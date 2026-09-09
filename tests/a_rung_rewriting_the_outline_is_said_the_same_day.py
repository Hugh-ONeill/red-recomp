"""A rung rewriting the outline is said the same day. notable.py watched the
executor's journal and the rig and was blind to the ladder: the wording
rung asserted a fact about the Rocket executive, reasserted it an hour
later, and the only trace was in chain.log (2026-09-08). The ladder's own
sidecars carry every such decision; a watcher that reads them says so at a
level of its own, between "the harness is coping" and "the run is stuck".
Also: what is said once is not said again, a chain restart is read from
its start, and a single failure is not the alarm — the third one is."""
import json, os, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import notable as N

tmp = tempfile.TemporaryDirectory(); run = Path(tmp.name)
p = N.Paths(run)
def J(*recs):
    with p.journal.open("a") as f:
        for r in recs: f.write(json.dumps(r) + "\n")
def S(name, *lines):
    with (run / name).open("a") as f:
        for l in lines: f.write(l + "\n")
def kinds(evs): return [(e["sev"], e["kind"]) for e in evs]

# -- the ladder is heard, at its own level ---------------------------------
J({"kind": "plan_start", "goal": "Obtain the Card Key", "rev": "abc"})
S("outline_rewordings", "20\tFind the Rocket Hideout\tFind the entrance to the Rocket Hideout")
S("outline_void", "Defeat the executive\tDONE: EVENT_X has already fired")
S("outline_inserts", "LEG=Defeat Erika|Obtain the Tea",
  "REMOVED 20260907|Obtain the Tea|another game's item")
S("outline_skips", "10\tDefeat Brock", "Find the entrance")
S("outline_pushes", "11\t13\tReach Vermilion City")
S("attempt_yield", "a party Pokemon knows SURF\t33\t0\tDISPOSED: moved behind leg 35",
  "Reach Saffron\t34\t1\tWHAT CHANGED: 3 places entered",
  "Enter Silph\t35\t0\tNOTHING new while this leg ran: no plan could even be written for it (the author failed)")
S("leg_unconfirmed", "Retrieve HM02")
S("leg_audit_redo", "Exchange the BIKE_VOUCHER")
evs, st = N.sweep(p, 600, from_start=True)
k = kinds(evs)
ck("a rewording is a plan-level line", ("plan", "reworded") in k)
ck("a void that counted the leg done says counted_done", ("plan", "counted_done") in k)
ck("an insert and its removal are both said", ("plan", "inserted") in k and ("plan", "insert_removed") in k)
ck("a skip with a number and one without both parse", sum(1 for s, x in k if x == "skipped") == 2)
ck("a push is plan-level", ("plan", "pushed") in k)
ck("a disposal in the yield ledger is plan-level", ("plan", "disposed") in k)
ck("a plain yield is info", ("info", "leg_yield") in k)
ck("an author that could not write is a warn", ("warn", "author_failed") in k)
ck("counted without proof is plan-level", ("plan", "counted_unconfirmed") in k)
ck("an audit redo is a warn, not a plan change", ("warn", "audit_redo") in k)
ck("every ladder line names its source file", all("source" in e for e in evs if e["kind"] != "leg_start"))
ck("plan ranks above warn and below alarm",
   N.SEV_RANK["warn"] < N.SEV_RANK["plan"] < N.SEV_RANK["alarm"])
rw = next(e for e in evs if e["kind"] == "reworded")
ck("the rewording quotes old and new", "Rocket Hideout" in rw["what"] and "entrance" in rw["what"])

# -- said once: the cursor moves ------------------------------------------
N.save_state(p, st)
evs2, st2 = N.sweep(p, 600)
ck("a second pass over the same files says nothing", evs2 == [])

# -- a new chain rm -f's the sidecars; the recreated file is read from 0 ---
(run / "outline_rewordings").unlink()
S("outline_rewordings", "3\tCross Viridian Forest\tWalk Viridian Forest")
N.save_state(p, st2)
evs3, st3 = N.sweep(p, 600)
ck("a sidecar that vanished and came back is read again", kinds(evs3) == [("plan", "reworded")])
ck("a sidecar still missing is position 0", st3["side"]["outline_pulls"] == 0)

# -- the third failure is the alarm, the first is not ----------------------
N.save_state(p, st3)
t0 = time.time()
J({"kind": "escalate_end", "subgoal": "reach_11f", "success": False},
  {"kind": "escalate_end", "subgoal": "reach_11f", "success": False},
  {"kind": "escalate_end", "subgoal": "reach_11f", "success": False},
  {"kind": "escalate_end", "subgoal": "reach_11f", "success": False},
  {"kind": "send_timeout", "t": t0, "op": "use_warp", "err": "no observation"},
  {"kind": "send_timeout", "t": t0 + 10, "op": "use_warp", "err": "no observation"},
  {"kind": "send_timeout", "t": t0 + 20, "op": "use_warp", "err": "no observation"},
  {"kind": "battle_start"},
  {"kind": "battle_move_failed", "turn": 1, "detail": "menu never appeared"},
  {"kind": "battle_move_failed", "turn": 2, "detail": "menu never appeared"},
  {"kind": "battle_move_failed", "turn": 3, "detail": "menu never appeared"},
  {"kind": "battle_move_failed", "turn": 4, "detail": "menu never appeared"})
evs4, st4 = N.sweep(p, 600)
k4 = kinds(evs4)
ck("two failures are warns", k4.count(("warn", "subgoal_failed")) == 2)
ck("the third failure is one stalemate alarm, and the fourth is silent", k4.count(("alarm", "stalemate")) == 1)
ck("three timeouts in ten minutes is one alarm", k4.count(("alarm", "game_not_answering")) == 1)
ck("the first two timeouts were warns", k4.count(("warn", "no_observation")) == 2)
ck("a battle that will not resolve is said once", k4.count(("alarm", "battle_stuck")) == 1)

# -- the rig: registered and gone is an exit -------------------------------
N.save_state(p, st4)
p.rig.write_text("999999\t1\tcampaign\n")
evs5, st5 = N.sweep(p, 600)
ck("a registered process that is gone is chain_exited", ("alarm", "chain_exited") in kinds(evs5))
N.save_state(p, st5)
evs6, _ = N.sweep(p, 600)
ck("...and is not said twice", ("alarm", "chain_exited") not in kinds(evs6))

# -- the reader wakes on plan, sleeps through info -------------------------
p.out.write_text("")
def later():
    time.sleep(0.3)
    with p.out.open("a") as f:
        f.write(json.dumps({"sev": "info", "kind": "subgoal_start", "what": "x"}) + "\n")
    time.sleep(0.3)
    with p.out.open("a") as f:
        f.write(json.dumps({"sev": "plan", "kind": "reworded", "what": "y"}) + "\n")
threading.Thread(target=later, daemon=True).start()
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = N.wake(p, "plan", timeout=5, poll=0.1)
got = [json.loads(l) for l in buf.getvalue().splitlines()]
ck("--wake plan returns on the plan line", rc == 0 and [g["kind"] for g in got] == ["reworded"])
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = N.wake(p, "alarm", timeout=0.5, poll=0.1)
ck("--wake alarm times out when nothing is that loud", rc == 1 and buf.getvalue() == "")

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
tmp.cleanup()
sys.exit(1 if bad else 0)

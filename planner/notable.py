#!/usr/bin/env python3
"""What in a live run is worth waking someone for.

A watcher that reads what a run is already writing and appends one line to
run/notable.jsonl per TRANSITION — a leg started, a subgoal failed, the game
stopped answering, the chain exited, a rung rewrote an objective. Nothing
else.

WHY THIS EXISTS. Watching a run used to mean polling run/status.txt every
few seconds. status.txt is a snapshot: it says what is true now, so a reader
has to diff two snapshots to learn anything, and 99% of the reads are the
previous read again. Worse, a snapshot cannot tell "thinking" from "dead" —
both look like a file that has not changed — which is how a chain that
stopped at 21:51 was still being watched the next morning.

So the polling moves down here, where a poll is free, and what goes up is
the transition. A reader (a person, a `tail -f`, an agent's file monitor)
blocks on notable.jsonl growing and reads only the new lines.

NO MODEL CALLS, and no judgement. Every rule below is a predicate over
records the executor already writes, over the ladder's own sidecar ledgers,
or over the rig's PID registry. "Is this search or is it a loop" is a
judgement and does not belong here; this file's job is to say WHEN that
question is worth asking, which is what the loop and latency rules do.

WHAT IT WATCHES

  the journal   run/executor_log.jsonl, from a byte cursor kept in
                run/notable.state.json, so a restart does not re-report
                the run so far. A fresh state file starts at the END of
                the log: `--from-start` replays instead.
  the ladder    the append-only sidecars the chain script writes beside
                chain.log — outline_rewordings, outline_pushes,
                outline_void, outline_skips, outline_inserts and the rest
                (SIDECARS below). Every decision the chain makes about the
                outline lands in one of them, so the ladder is watched
                without parsing a log whose sentences get reworded. Same
                cursor trick, one cursor per file; fresh_discovery.sh
                rm -f's them at chain start, and a file that vanished or
                shrank is read from its beginning again.
  the clock     status.txt has not been rewritten in --stale-secs, while
                the rig says the run is alive. That is a wedge.
  the rig       run/rig.pids, by the same (pid, starttime, not-a-zombie)
                identity rig.sh uses. Registered and none alive is an exit,
                and an exit nobody asked for is the loudest line this
                file writes.

SEVERITIES, which are the whole point — a watcher that reports everything
at one level is the status poll again, just cheaper:

  alarm   nobody but a person can move this on: the chain exited, it
          wedged, a battle turn will not resolve, the same subgoal has
          failed three times in one leg, the game has stopped answering
          repeatedly.
  plan    the plan of record changed and the run walked on: an objective
          reworded, pushed, voided, skipped, inserted, reordered, pulled
          ahead, or counted done without proof. Nothing is stuck, so it is
          not an alarm; but a rung rewriting your objective is nearly
          irreversible once the run is past it, and it is the thing a
          person should see the same day rather than the next morning
          (2026-09-08: a rewording rung asserted a fact about the Rocket
          executive, then reasserted it an hour later, and the only trace
          was in chain.log). There are a handful per run.
  warn    it is progressing badly, and the harness is handling it: one
          subgoal failed, one op got no observation, a save did not take,
          rounds slowed by 3x, refusals are piling up, an author pass
          failed, an audit is being redone.
  info    it is progressing: a leg or subgoal began, a subgoal was solved,
          a leg yielded its delta.

THE THRESHOLDS ARE MEASURED, NOT CHOSEN. Replayed over the journal as it
stood on 2026-09-09 (legs from Koga to Silph Co, 235 lines out of 10 MB):
28 subgoals failed and 20 ops got no observation, and the campaign carried
on through every one of them. A rule that woke someone for those is the
status poll with extra steps. What no single failure says, and the third
repeat does, is that the leg is not converging.

  planner/notable.py --watch 30        the watcher: every 30s until killed
  planner/notable.py --once            one pass, print what it appended
  planner/notable.py --once --dry-run  print, append nothing
  planner/notable.py --wake plan       the READER: block until the watcher
                                       writes a line this loud, print it,
                                       exit. Costs nothing while it waits,
                                       which is the whole trick — a session
                                       upstream sleeps on this instead of
                                       re-reading status.txt forever.
  planner/notable.py --run DIR ...     another run directory (an archive)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import deque
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "run"

# A round that takes this much longer than the recent median is a box
# problem, not a thinking problem — the usual cause is a second model
# landing on the GPU and evicting this one.
SLOW_FACTOR = 3.0
SLOW_FLOOR_S = 60.0
LAT_WINDOW = 20

# Refusals are normal; a wall of them in one stretch of rounds is the
# harness offering with one hand and refusing with the other (repeats.py).
REFUSE_WINDOW = 20
REFUSE_TRIP = 5

# A subgoal that fails once is retried by the campaign and usually gets
# there. Three failures in one leg is the stalemate shape: the plan asks
# for something this world will not give.
STALEMATE_TRIP = 3

# Timeouts cluster when the game is dying.
TIMEOUT_TRIP = 3
TIMEOUT_BURST_S = 600.0

# A battle turn that will not resolve is the illegal-move deadlock: the
# same disabled slot re-picked forever, so the turn never ends and the
# disable never expires.
BATTLE_FAIL_TRIP = 3

SEV_RANK = {"info": 0, "warn": 1, "plan": 2, "alarm": 3}


class Paths:
    """Everything under one run directory, so a test can point the watcher
    at a scratch copy and an archived run can be replayed."""

    def __init__(self, run: Path):
        self.run = Path(run)
        self.journal = self.run / "executor_log.jsonl"
        self.status = self.run / "status.txt"
        self.rig = self.run / "rig.pids"
        self.out = self.run / "notable.jsonl"
        self.state = self.run / "notable.state.json"


# ---------------------------------------------------------------- the rig

def rig_starttime(pid: int) -> str | None:
    """Field 22 of /proc/<pid>/stat. Everything after the last ')' is
    fixed-width; counting from the left is wrong because comm can hold
    both spaces and parens."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    tail = raw.rsplit(")", 1)[-1].split()
    return tail[19] if len(tail) > 19 else None


def rig_alive(pid: int, starttime: str) -> bool:
    """Same process, still here, and not a corpse. A zombie has exited and
    only waits to be reaped; /proc still answers for it."""
    if rig_starttime(pid) != starttime:
        return False
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    tail = raw.rsplit(")", 1)[-1].split()
    return bool(tail) and tail[0] != "Z"


def rig_status(rig: Path) -> tuple[int, int]:
    """(registered, alive) over run/rig.pids."""
    if not rig.exists():
        return 0, 0
    registered = alive = 0
    for line in rig.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            pid = abs(int(parts[0]))
        except ValueError:
            continue
        registered += 1
        if rig_alive(pid, parts[1]):
            alive += 1
    return registered, alive


# ------------------------------------------------------------- the ladder

def one_line(s: object, n: int = 160) -> str:
    t = " ".join(str(s).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _tabs(line: str, n: int) -> list[str]:
    parts = line.split("\t")
    return parts + [""] * (n - len(parts))


def side_reworded(line):
    n, old, new = _tabs(line, 3)
    return "plan", "reworded", f"leg {n}: {one_line(old, 70)} → {one_line(new, 70)}", {"leg": n}


def side_pushed(line):
    frm, after, text = _tabs(line, 3)
    return "plan", "pushed", f"{one_line(text, 90)} moved from {frm} to after {after}", {}


def side_voided(line):
    wording, why = _tabs(line, 2)
    done = why.startswith("DONE: ")
    return ("plan", "counted_done" if done else "voided",
            f"{one_line(wording, 70)}: {one_line(why.removeprefix('DONE: '), 90)}", {})


def side_skipped(line):
    parts = line.split("\t", 1)
    text = parts[-1]
    f = {"leg": parts[0]} if len(parts) == 2 else {}
    return "plan", "skipped", one_line(text), f


def side_inserted(line):
    if line.startswith("REMOVED "):
        parts = line.split("|")
        text = parts[1] if len(parts) > 1 else line
        why = parts[-1] if len(parts) > 2 else ""
        return "plan", "insert_removed", f"{one_line(text, 70)}: {one_line(why, 90)}", {}
    if line.startswith("LEG="):
        after, _, text = line[4:].partition("|")
        return "plan", "inserted", f"{one_line(text, 80)} before {one_line(after, 70)}", {}
    return "plan", "inserted", one_line(line), {}


def side_reordered(line):
    i, _, blocker = line.partition("<-")
    return "plan", "reordered", f"leg {i} now waits on leg {blocker}", {}


def side_pulled(line):
    i, j, text = _tabs(line, 3)
    return "plan", "pulled_ahead", f"{one_line(text, 90)} pulled from {j} to {i}", {}


def side_text(sev, kind):
    return lambda line: (sev, kind, one_line(line), {})


def side_yield(line):
    leg, i, attempt, why = _tabs(line, 4)
    f = {"leg": i}
    if why.startswith("DISPOSED: "):
        return "plan", "disposed", f"{one_line(leg, 60)}: {one_line(why[10:], 100)}", f
    if why.startswith("NOTHING new") and "author failed" in why:
        return "warn", "author_failed", f"{one_line(leg, 60)}: no plan could be written", f
    return "info", "leg_yield", f"{one_line(leg, 60)} (attempt {attempt}): {one_line(why, 100)}", f


# name → parser(line) -> (sev, kind, what, fields)
SIDECARS = {
    "outline_rewordings":   side_reworded,
    "outline_pushes":       side_pushed,
    "outline_void":         side_voided,
    "outline_skips":        side_skipped,
    "outline_inserts":      side_inserted,
    "outline_reorders":     side_reordered,
    "outline_pulls":        side_pulled,
    "outline_pullbacks":    side_text("plan", "pulled_back"),
    "outline_replays":      side_text("plan", "replayed"),
    "leg_unconfirmed":      side_text("plan", "counted_unconfirmed"),
    # authoring failed AND the push was refused: the chain steps over the
    # leg. Found by the ledger-coverage test the day it was written.
    "outline_unauthored":   side_text("plan", "stepped_over"),
    "outline_pulls_failed": side_text("warn", "pull_failed"),
    "outline_upkeep_missed": side_text("warn", "upkeep_missed"),
    "leg_audit_redo":       side_text("warn", "audit_redo"),
    "outline_wording_asked": side_text("info", "wording_asked"),
    "attempt_yield":        side_yield,
}


# -------------------------------------------------------------- the state

def load_state(p: Paths) -> dict:
    try:
        return json.loads(p.state.read_text())
    except (OSError, ValueError):
        return {}


def save_state(p: Paths, st: dict) -> None:
    tmp = p.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(p.state)


def read_new(path: Path, pos: int | None, from_start: bool) -> tuple[bytes, int]:
    """The bytes appended since pos, and the new pos. Whole lines only: a
    half-written last line is not ours to parse yet. A missing file is
    position 0 (it will be recreated by the next chain); a file shorter
    than pos was truncated or replaced, and is read again from 0."""
    try:
        size = path.stat().st_size
    except OSError:
        return b"", 0
    if pos is None:
        pos = 0 if from_start else size
    elif pos > size:
        pos = 0
    if size <= pos:
        return b"", pos
    with path.open("rb") as f:
        f.seek(pos)
        data = f.read()
    cut = data.rfind(b"\n") + 1
    return data[:cut], pos + cut


# --------------------------------------------------------------- the rules

class Watcher:
    def __init__(self, state: dict):
        self.lat = deque(state.get("lat", []), maxlen=LAT_WINDOW)
        self.refused = deque(state.get("refused", []), maxlen=REFUSE_WINDOW)
        self.battle_fails = state.get("battle_fails", 0)
        self.fails = dict(state.get("fails", {}))
        self.timeouts = deque(state.get("timeouts", []), maxlen=TIMEOUT_TRIP * 4)
        self.flags = state.get("flags", {})
        self.out: list[dict] = []

    def emit(self, sev: str, kind: str, what: str, **fields) -> None:
        rec = {"t": round(time.time(), 1), "sev": sev, "kind": kind,
               "what": what}
        rec.update({k: v for k, v in fields.items() if v not in (None, "")})
        self.out.append(rec)

    def once(self, flag: str, sev: str, kind: str, what: str, **f) -> None:
        """Say a standing condition once. It re-arms when clear() runs."""
        if self.flags.get(flag):
            return
        self.flags[flag] = True
        self.emit(sev, kind, what, **f)

    def clear(self, flag: str) -> None:
        self.flags.pop(flag, None)

    # -- journal ----------------------------------------------------------

    def record(self, r: dict) -> None:
        k = r.get("kind")
        sub = r.get("subgoal")

        if k == "plan_start":
            self.fails.clear()           # failures are counted per leg
            for f in [x for x in self.flags if x.startswith("stale:")]:
                self.clear(f)
            self.emit("info", "leg_start", one_line(r.get("goal")),
                      rev=r.get("rev"))
        elif k == "escalate_start":
            self.emit("info", "subgoal_start", one_line(r.get("goal")),
                      subgoal=sub)
        elif k == "escalate_success":
            self.emit("info", "subgoal_done",
                      f"{sub} solved on round {r.get('round')}",
                      subgoal=sub, verified=r.get("verified"))
        elif k == "escalate_end" and not r.get("success"):
            n = self.fails.get(sub, 0) + 1
            self.fails[sub] = n
            if n >= STALEMATE_TRIP:
                # once per subgoal per leg: the leg boundary re-arms it
                self.once(f"stale:{sub}", "alarm", "stalemate",
                          f"{sub} has now failed {n} times in this leg; the "
                          f"leg is not converging",
                          subgoal=sub, fails=n)
            else:
                self.emit("warn", "subgoal_failed",
                          f"{sub} gave up without reaching its done_when",
                          subgoal=sub, fails=n)
        elif k == "subgoal_attempt" and int(r.get("attempt") or 1) > 1:
            self.emit("warn", "subgoal_retry",
                      f"{sub} retry {r.get('attempt')}", subgoal=sub)
        elif k == "subgoal_save_failed":
            self.emit("warn", "save_failed",
                      f"{sub}: {one_line(r.get('detail'))}", subgoal=sub)
        elif k == "send_timeout":
            # One of these is weather: 20 of them across the replayed
            # journal, and the run walked on through all 20. A cluster is
            # the game on its way out, which is how runs have died silently.
            try:
                self.timeouts.append(float(r.get("t")))
            except (TypeError, ValueError):
                self.timeouts.append(time.time())
            recent = [t for t in self.timeouts
                      if t > self.timeouts[-1] - TIMEOUT_BURST_S]
            if len(recent) >= TIMEOUT_TRIP:
                self.once("timeouts", "alarm", "game_not_answering",
                          f"{len(recent)} ops got no observation within "
                          f"{TIMEOUT_BURST_S / 60:.0f} min",
                          op=r.get("op"))
            else:
                self.clear("timeouts")
                self.emit("warn", "no_observation", one_line(r.get("err")),
                          op=r.get("op"))
        elif k == "target_unreachable":
            self.emit("info", "unreachable",
                      f"{r.get('target')} not reachable from "
                      f"{r.get('region')}", subgoal=sub)

        # battle turns that will not resolve
        if k in ("battle_start", "battle_done"):
            self.battle_fails = 0
            self.clear("battle_stuck")
        elif k == "battle_move_failed":
            self.battle_fails += 1
            if self.battle_fails >= BATTLE_FAIL_TRIP:
                self.once("battle_stuck", "alarm", "battle_stuck",
                          f"{self.battle_fails} battle turns in a row would "
                          f"not resolve: {one_line(r.get('detail'))}",
                          turn=r.get("turn"))

        # refusal walls
        if k in ("escalate_proposal", "escalate_repeat_refused"):
            self.refused.append(1 if k == "escalate_repeat_refused" else 0)
            hits = sum(self.refused)
            if len(self.refused) == REFUSE_WINDOW and hits >= REFUSE_TRIP:
                self.once("refusing", "warn", "refusal_wall",
                          f"{hits} of the last {REFUSE_WINDOW} rounds "
                          f"re-proposed an op the harness had refused",
                          subgoal=sub)
            elif hits < REFUSE_TRIP:
                self.clear("refusing")

        # rounds that suddenly cost 3x
        if k == "escalate_proposal":
            try:
                secs = float(r.get("tot_s"))
            except (TypeError, ValueError):
                secs = None
            if secs is not None:
                if len(self.lat) >= 5:
                    med = statistics.median(self.lat)
                    if secs > SLOW_FLOOR_S and secs > SLOW_FACTOR * med:
                        self.once("slow", "warn", "slow_round",
                                  f"round took {secs:.0f}s against a median "
                                  f"of {med:.0f}s", subgoal=sub)
                    elif secs < 1.5 * med:
                        self.clear("slow")
                self.lat.append(secs)

    # -- ladder -----------------------------------------------------------

    def sidecar(self, name: str, line: str) -> None:
        line = line.rstrip("\n")
        if not line.strip():
            return
        try:
            sev, kind, what, fields = SIDECARS[name](line)
        except Exception:              # a line this parser did not expect
            sev, kind, what, fields = "plan", name, one_line(line), {}
        self.emit(sev, kind, what, source=name, **fields)

    # -- clock and rig ----------------------------------------------------

    def liveness(self, p: Paths, stale_secs: float) -> None:
        registered, alive = rig_status(p.rig)
        if registered and not alive:
            self.once("exited", "alarm", "chain_exited",
                      f"all {registered} registered processes are gone; "
                      "the run is over")
            return
        if not registered:
            return                       # nothing claims to be running
        self.clear("exited")

        try:
            age = time.time() - p.status.stat().st_mtime
        except OSError:
            return
        if age > stale_secs:
            self.once("wedged", "alarm", "wedged",
                      f"{alive} process(es) alive but status.txt has not "
                      f"moved in {age / 60:.0f} min")
        else:
            self.clear("wedged")

    def dump_state(self) -> dict:
        return {"lat": list(self.lat), "refused": list(self.refused),
                "battle_fails": self.battle_fails, "fails": self.fails,
                "timeouts": list(self.timeouts), "flags": self.flags}


# ----------------------------------------------------------------- driving

def sweep(p: Paths, stale_secs: float, from_start: bool = False
          ) -> tuple[list[dict], dict]:
    st = load_state(p)
    w = Watcher(st)

    data, pos = read_new(p.journal, 0 if from_start else st.get("pos"),
                         from_start)
    for raw in data.splitlines():
        try:
            w.record(json.loads(raw))
        except ValueError:
            continue

    side = dict(st.get("side", {}))
    for name in SIDECARS:
        data, side[name] = read_new(p.run / name, side.get(name), from_start)
        for raw in data.decode("utf-8", "replace").splitlines():
            w.sidecar(name, raw)

    w.liveness(p, stale_secs)

    out = w.dump_state()
    out["pos"] = pos
    out["side"] = side
    return w.out, out


def wake(p: Paths, min_sev: str, timeout: float | None, poll: float) -> int:
    """Block until notable.jsonl carries a line at or above min_sev, and
    print every such line from that point on.

    Reading starts at the END of the file: the caller wants what happens
    NEXT, not the backlog of a run it already watched."""
    floor = SEV_RANK[min_sev]
    deadline = time.time() + timeout if timeout else None
    try:
        pos = p.out.stat().st_size
    except OSError:
        pos = 0
    while True:
        data, pos = read_new(p.out, pos, False)
        hit = False
        for raw in data.splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if SEV_RANK.get(rec.get("sev"), 0) >= floor:
                print(json.dumps(rec), flush=True)
                hit = True
        if hit:
            return 0
        if deadline and time.time() > deadline:
            return 1                      # nothing loud enough happened
        time.sleep(poll)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, default=RUN, metavar="DIR",
                    help="run directory to watch (default run/)")
    ap.add_argument("--watch", type=float, metavar="SECS",
                    help="loop every SECS instead of one pass")
    ap.add_argument("--once", action="store_true", help="one pass (default)")
    ap.add_argument("--stale-secs", type=float, default=600.0,
                    help="status.txt older than this, while alive, is a wedge")
    ap.add_argument("--from-start", action="store_true",
                    help="replay the whole journal and every sidecar instead "
                         "of starting at their ends (ignored once state exists)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print, append nothing, keep no cursor")
    ap.add_argument("--wake", nargs="?", const="warn",
                    choices=tuple(SEV_RANK), metavar="SEV",
                    help="read, do not watch: block until a line at this "
                         "severity or louder is written (default warn)")
    ap.add_argument("--timeout", type=float, metavar="SECS",
                    help="--wake gives up after this long and exits 1")
    ap.add_argument("--poll", type=float, default=5.0,
                    help="--wake checks the file this often (default 5s)")
    a = ap.parse_args()
    p = Paths(a.run)

    if a.wake:
        return wake(p, a.wake, a.timeout, a.poll)

    first = a.from_start and not p.state.exists()
    while True:
        events, state = sweep(p, a.stale_secs, from_start=first)
        first = False
        for e in events:
            print(json.dumps(e), flush=True)
        if not a.dry_run:
            if events:
                with p.out.open("a") as f:
                    for e in events:
                        f.write(json.dumps(e) + "\n")
            save_state(p, state)
        if not a.watch:
            return 0
        time.sleep(a.watch)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        # `| head` closing the pipe is not a failure of the watch.
        sys.stderr.close()
        sys.exit(0)

#!/usr/bin/env python3
"""Python side of the red-recomp bridge: send ops, await observations.

Library + CLI. Manual REPL mode is the shim-debug tool; the model planner
imports Bridge.

Usage:
  planner/bridge.py repl                # interactive: type ops, see obs
  planner/bridge.py send walk dir=down steps=3
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

RUN = Path(os.environ.get("RED_BRIDGE_DIR",
                          Path.home() / "Developer/red-recomp/run"))


class Bridge:
    def __init__(self, run_dir: Path = RUN, timeout: float = 120.0):
        self.run = Path(run_dir)
        self.timeout = timeout
        self.seq = self._last_obs_seq()

    def _last_obs_seq(self) -> int:
        try:
            return json.loads((self.run / "obs.json").read_text())["seq"]
        except Exception:
            return 0

    def obs(self) -> dict | None:
        try:
            return json.loads((self.run / "obs.json").read_text())
        except Exception:
            return None

    def send(self, op: str, **kw) -> dict:
        """Write a command, block until the shim reports its result."""
        self.seq += 1
        fields = [f"seq={self.seq}", f"op={op!r}"]
        for k, v in kw.items():
            fields.append(f"{k}={v!r}" if isinstance(v, str) else f"{k}={v}")
        body = "return {" + ", ".join(fields) + "}"
        tmp = self.run / "cmd.lua.tmp"
        tmp.write_text(body)
        tmp.rename(self.run / "cmd.lua")
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            o = self.obs()
            if o and o.get("seq") == self.seq:
                return o
            time.sleep(0.05)
        raise TimeoutError(f"op {op} (seq {self.seq}) got no observation")


def _pp(o: dict | None):
    if not o:
        print("(no observation yet)")
        return
    r = o.get("result") or {}
    print(f"[seq {o.get('seq')} frame {o.get('frame')}] mode={o.get('mode')}"
          f"  last={r.get('op')} ok={r.get('ok')}"
          + (f" ({r['detail']})" if r.get("detail") else ""))
    if o.get("events"):
        print("  events:", ", ".join(o["events"]))
    if o.get("mode") == "overworld":
        p, m = o.get("player", {}), o.get("map", {})
        print(f"  map {m.get('id')} {m.get('name') or ''}  "
              f"pos ({p.get('x')},{p.get('y')}) facing {p.get('facing')}")
    if o.get("mode") == "battle":
        print("  battle:", json.dumps(o.get("battle"), indent=1)[:600])
    if o.get("mode") == "ui":
        print("  ui:", json.dumps(o.get("ui"))[:300])
    party = o.get("party") or []
    if party:
        line = ", ".join(
            f"{m.get('species', '?')} L{m.get('level', '?')} "
            f"hp={m.get('hp', '?')}" for m in party)
        print("  party:", line)
    if o.get("badges"):
        print("  badges:", ", ".join(o["badges"]))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("repl", "send"):
        sys.exit(__doc__)
    b = Bridge()
    if sys.argv[1] == "send":
        op = sys.argv[2]
        kw = {}
        for a in sys.argv[3:]:
            k, _, v = a.partition("=")
            kw[k] = int(v) if v.lstrip("-").isdigit() else v
        _pp(b.send(op, **kw))
        return
    _pp(b.obs())
    print("ops: new_game | walk dir=<up/down/left/right> steps=N | tap btn=a"
          " | mash_a times=N | wait frames=N | screenshot | quit")
    while True:
        try:
            line = input("op> ").strip()
        except EOFError:
            break
        if not line:
            _pp(b.obs())
            continue
        parts = line.split()
        kw = {}
        for a in parts[1:]:
            k, _, v = a.partition("=")
            kw[k] = int(v) if v.lstrip("-").isdigit() else v
        try:
            _pp(b.send(parts[0], **kw))
        except TimeoutError as e:
            print("timeout:", e)
        if parts[0] == "quit":
            break


if __name__ == "__main__":
    main()

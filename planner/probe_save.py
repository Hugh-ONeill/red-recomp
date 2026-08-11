#!/usr/bin/env python3
"""Fast standalone check of the SAVE flow (no route replay).

New game -> downstairs -> outside -> save_game -> report. Then quits and
reboots to prove CONTINUE lands in the saved position: the whole point of
saving is probing later legs without replaying the route.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import executor as ex_mod
from bridge import Bridge, RUN

REPO = Path(__file__).resolve().parent.parent


def boot():
    if (RUN / "obs.json").exists():
        (RUN / "obs.json").unlink()
    g = subprocess.Popen([str(REPO / "run.sh"), "200"], cwd=REPO,
                         start_new_session=True)
    atexit.register(lambda: _kill(g))
    for _ in range(60):
        if (RUN / "obs.json").exists():
            return g
        time.sleep(1)
    sys.exit("game did not come up")


def _kill(g):
    if g.poll() is None:
        try:
            os.killpg(g.pid, signal.SIGTERM)
        except Exception:
            pass


def where(b):
    o = b.obs() or {}
    p = o.get("player") or {}
    return f"{(o.get('map') or {}).get('id')} ({p.get('x')},{p.get('y')})"


def main():
    g = boot()
    b = Bridge()
    ex_mod.bootstrap(b)
    b.send("walk_to", x=7, y=1)          # stairs
    b.send("use_warp", x=7, y=1)
    b.send("use_warp", x=2, y=7)         # front door -> Pallet
    print(f"[before save] {where(b)}")
    r = (b.send("save_game") or {}).get("result") or {}
    print(f"[save] ok={r.get('ok')} detail={r.get('detail')}")
    print(f"[after save] {where(b)}")
    b.send("quit")
    time.sleep(3)
    _kill(g)

    print("\n== rebooting to test CONTINUE ==")
    g2 = boot()
    b2 = Bridge()
    ex_mod.bootstrap(b2, cont=True)
    print(f"[continued at] {where(b2)}")
    b2.send("quit")
    time.sleep(2)
    _kill(g2)


if __name__ == "__main__":
    main()

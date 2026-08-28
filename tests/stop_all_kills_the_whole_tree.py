#!/usr/bin/env python3
"""stop_all.sh stops the children of what registered, not only what
registered — and refuses ALL CLEAR while any of them lives.

2026-08-28: planner/author.py, the chain's foreground child during
authoring, outlived the chain by a whole leg after a stop; only the loops
and the executor register, so nothing in stop_all could see it. The tree
beneath the registered PIDs is the record of what we started; it is read
before the first signal and swept deepest-first after the registered sweep.
Runs against a TEMP registry and a fake tree it spawns itself; the live
registry and any live chain are never touched.
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))

def starttime(pid):
    st = Path(f"/proc/{pid}/stat").read_text()
    return st.rsplit(")", 1)[1].split()[19]

with tempfile.TemporaryDirectory() as d:
    reg = Path(d) / "rig.pids"
    # a fake "chain": a bash loop (registered) whose foreground child is an
    # unregistered python that ignores nothing but was never registered
    chain = subprocess.Popen(
        ["bash", "-c", "python3 -c 'import time; time.sleep(600)' ; sleep 600"],
        cwd=ROOT, start_new_session=True)
    time.sleep(1.0)
    kids = subprocess.run(["pgrep", "-P", str(chain.pid)], capture_output=True, text=True).stdout.split()
    ck("the fake chain has an unregistered child", len(kids) == 1)
    reg.write_text(f"{chain.pid}\t{starttime(chain.pid)}\tchain\n")
    r = subprocess.run(["./stop_all.sh"], cwd=ROOT, env=dict(os.environ, RIG_PIDS=str(reg)),
                       capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    time.sleep(0.5)
    def alive(pid):
        try:
            os.kill(int(pid), 0); return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
        except (ProcessLookupError, FileNotFoundError):
            return False
    ck("the registered loop is stopped", not alive(chain.pid) or chain.poll() is not None)
    ck("...and its unregistered child too", all(not alive(k) for k in kids))
    ck("...which the script says it did", "children of ours that never registered" in out)
    ck("...and then reports ALL CLEAR", r.returncode == 0 and "ALL CLEAR" in out)
    try:
        chain.wait(timeout=5)
    except subprocess.TimeoutExpired:
        chain.kill()
sh = (ROOT / "stop_all.sh").read_text()
ck("the tree is snapshotted before any signal", sh.index("ps -eo pid=,ppid= >") < sh.index('kill -TERM "$p"'))
ck("the inhibitor is found as the chain's parent and released last", "systemd-inhibit" in sh and "releasing the sleep inhibitor" in sh
   and sh.index("releasing the sleep inhibitor") > sh.index("children of ours that never registered"))
ck("ALL CLEAR is refused while anything of ours lives", "OF OURS AND STILL RUNNING" in sh)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

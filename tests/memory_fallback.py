#!/usr/bin/env python3
"""A fallback that loads the wrong file must say so.

`_read_memory` tries run/explored.json and falls back to .json.prev. The
fallback is correct for a crash mid-write — tmp+rename keeps the last
good copy for exactly this — but it also fires when the live file was
EDITED BY HAND and the edit broke the JSON: the pre-edit .prev loads
without a word, the next two saves rotate it into both files, and the
edit is gone. That happened on 2026-08-21 with a no_cross seed for the
Route 14 nook: stop_all said ALL CLEAR, the edit was made, the relaunch
came back with both keys empty and explored.json byte-identical to its
.prev. The warning at the bottom of _read_memory only printed when BOTH
files failed, so the one recovery path a hand-editor actually hits was
the one silent case.

Rule under test: any load that PASSED OVER an existing file must name it
and the parse error that cost it, loudly enough to be seen in chain.log.

No game, no model — a temp directory and five worlds of two files.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

GOOD = {"explored": {"A|0,0": {"east": {"n": 1, "to": "B|0,0"}}}}
PREV = {"explored": {"A|0,0": {}}}


def make(tmp):
    ex = object.__new__(E.Executor)
    ex.MEMORY = Path(tmp) / "explored.json"
    return ex


def read(ex):
    buf = io.StringIO()
    with redirect_stdout(buf):
        data, src = ex._read_memory()
    return data, src, buf.getvalue()


def case(name, ok):
    print(("ok  " if ok else "FAIL") + " " + name)
    return ok


def main():
    ok = True

    # 1. the live file is good: it loads, and nothing is said.
    with tempfile.TemporaryDirectory() as tmp:
        ex = make(tmp)
        ex.MEMORY.write_text(json.dumps(GOOD))
        data, src, out = read(ex)
        ok &= case("good live file loads silently",
                   data == GOOD and src == "explored.json" and out == "")

    # 2. THE CASE THAT BIT: live file hand-edited into bad JSON, .prev
    #    good. The .prev must load — and the pass-over must be loud,
    #    naming the live file, the parse error, and the hand-edit risk.
    with tempfile.TemporaryDirectory() as tmp:
        ex = make(tmp)
        ex.MEMORY.write_text(json.dumps(GOOD)[:-5] + ",}")   # a hand slip
        ex.MEMORY.with_suffix(".json.prev").write_text(json.dumps(PREV))
        data, src, out = read(ex)
        ok &= case("prev loads when live is broken",
                   data == PREV and src == "explored.json.prev")
        ok &= case("...and the pass-over is loud",
                   "explored.json" in out and "INSTEAD OF" in out)
        ok &= case("...names the parse error", "JSONDecodeError" in out)
        ok &= case("...warns the hand-editor", "edited by hand" in out)

    # 3. both broken: (None, None) and the could-not-read warning.
    with tempfile.TemporaryDirectory() as tmp:
        ex = make(tmp)
        ex.MEMORY.write_text("{nope")
        ex.MEMORY.with_suffix(".json.prev").write_text("{nope")
        data, src, out = read(ex)
        ok &= case("both broken -> empty, loudly",
                   data is None and src is None
                   and "COULD NOT READ" in out)

    # 4. live missing, .prev good: normal crash recovery, no scolding —
    #    nothing was passed over, there was nothing to pass over.
    with tempfile.TemporaryDirectory() as tmp:
        ex = make(tmp)
        ex.MEMORY.with_suffix(".json.prev").write_text(json.dumps(PREV))
        data, src, out = read(ex)
        ok &= case("crash recovery stays quiet",
                   data == PREV and src == "explored.json.prev"
                   and out == "")

    # 5. first run ever: nothing on disk, nothing said.
    with tempfile.TemporaryDirectory() as tmp:
        ex = make(tmp)
        data, src, out = read(ex)
        ok &= case("first run is silent",
                   data is None and src is None and out == "")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()

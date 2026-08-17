#!/usr/bin/env python3
"""Replace one outline objective with the model's own restatement.

Its own file for the same reason insert_leg.py, skip_legs.py and
pull_leg.py are: the chain script already nests a heredoc, and a second
sharing the terminator silently truncated the block it was written into.

Only a position AHEAD of the run's high-water mark may be reworded — a
finished objective is history and history is not edited.

A REWORD IS A RENAME, AND EVERY LEDGER IS KEYED ON THE NAME. The outline
is the only place the objective's text was being changed; seven other
files key on that same text and were all left holding the old wording:

  plans/outline.upkeep   whether a failed leg STOPS THE CHAIN or is played
                         past. This is the one that bites: reword an upkeep
                         objective and it silently becomes a critical leg,
                         so a condition the world may simply not offer —
                         the species does not appear, the balls run out —
                         ends the run instead of being left behind.
  plans/outline.notes    wordings the dedupe dropped, shown to the author
  plans/outline.done     the recognition ledger the sweep crosses off
  plans/outline.stages   which era of the game the objective belongs to
  run/leg_audit_redo     the one-redo budget for a leg the audit rejected
  run/outline_pushes     the push budget (two per objective, six per chain)
  run/outline_pulls      the same, for pulls, plus the undo record

Renaming in all of them keeps this a rewording rather than a quiet change
of the objective's standing. Nothing here is keyed by position, because
positions shift under the sweep and the reorder rungs.

Usage: reword_leg.py N "the objective, said accurately"
"""
import sys
from pathlib import Path

# (path, which tab-separated field carries the objective; None = whole line)
LEDGERS = [
    (Path("plans/outline.upkeep"), None),
    (Path("plans/outline.notes"), 0),
    (Path("plans/outline.done"), 0),
    (Path("plans/outline.stages"), 1),
    (Path("run/leg_audit_redo"), None),
    (Path("run/outline_upkeep_missed"), None),
    (Path("run/outline_pushes"), 2),
    (Path("run/outline_pulls"), 2),
    (Path("run/outline_pulls_failed"), 1),
]


def rename_in(path: Path, field, old: str, new: str) -> int:
    """Rewrite `old` to `new` wherever it is the KEY of a line. Exact match
    on the whole field, never a substring: 'Reach Cerulean City' must not
    rewrite itself inside 'Reach Cerulean City Gym'."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return 0
    hits, out = 0, []
    for line in lines:
        if field is None:
            if line == old:
                line, hits = new, hits + 1
        else:
            parts = line.split("\t")
            if len(parts) > field and parts[field] == old:
                parts[field] = new
                line, hits = "\t".join(parts), hits + 1
        out.append(line)
    if hits:
        # tmp+rename: these are small files rewritten mid-chain, and a
        # truncated ledger is worse than a stale one
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(out) + ("\n" if out else ""))
        tmp.replace(path)
    return hits


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    n, new = int(argv[0]), argv[1].strip()
    if not new:
        sys.exit("reword_leg: empty objective")

    p = Path("plans/outline.txt")
    lines = [l for l in p.read_text().splitlines() if l.strip()]
    try:
        mark = int(Path("run/outline_leg").read_text().strip() or 0)
    except (OSError, ValueError):
        mark = 0
    if not (mark < n <= len(lines)):
        sys.exit(f"reword_leg: {n} is not ahead of leg {mark}")

    old = lines[n - 1]
    if old == new:
        print(f"leg {n} already reads that way")
        return
    lines[n - 1] = new
    p.write_text("\n".join(lines) + "\n")
    with Path("run/outline_rewordings").open("a") as fh:
        fh.write(f"{n}\t{old}\t{new}\n")
    carried = [(path.name, rename_in(path, field, old, new))
               for path, field in LEDGERS]
    print(f"leg {n} reworded\n  was: {old}\n  now: {new}")
    moved = [f"{name} ({k})" for name, k in carried if k]
    print("  carried into: " + (", ".join(moved) if moved
                                else "nothing else keyed on it"))


if __name__ == "__main__":
    main(sys.argv[1:])

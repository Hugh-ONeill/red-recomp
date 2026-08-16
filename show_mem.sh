#!/usr/bin/env bash
# Pretty-print the persistent exploration memory (run/explored.json).
# Live view:  watch -n2 ./show_mem.sh
cd "$(dirname "$0")"
python - <<'EOF'
import json
from pathlib import Path

f = Path("run/explored.json")
if not f.exists():
    print("(no memory yet — run/explored.json will appear once a run moves)")
    raise SystemExit

d = json.loads(f.read_text() or "{}")
explored = d.get("explored", {})
visits = d.get("visits", {})
dead = d.get("dead_ends", {})
# room-level "fully worked" facts: every exit taken, everything touched
worked = d.get("searched", {}).get("*", {})

print(f"{len(explored)} areas known, "
      f"{sum(len(v) for v in explored.values())} exits mapped"
      f", {len(worked)} fully worked (*)\n")
for area in sorted(explored, key=lambda a: -visits.get(a, 0)):
    star = "*" if worked.get(area) else " "
    print(f"{star} {area}   (arrived {visits.get(area, 0)}x)")
    # A DOOR IS TWO TILES WIDE and the ledger records both (_twin_keys),
    # which is right — neither half is left dangling as untried. It just
    # reads as two doors here. Adjacent tiles going to the same place are
    # shown as one; Cerulean's trashed house has doors at 27,9 and 27,11
    # that land on OPPOSITE SIDES OF A FENCE, two apart, so they stay
    # separate. Adjacency is the test, never the destination alone.
    def cell(k):
        try:
            x, y = k.split(",")
            return int(x), int(y)
        except ValueError:
            return None

    rows, used = [], set()
    for k, e in sorted(explored[area].items(), key=lambda kv: -kv[1]["n"]):
        if k in used:
            continue
        c = cell(k)
        twin = None
        if c:
            for k2, e2 in explored[area].items():
                c2 = cell(k2)
                if (k2 != k and k2 not in used and c2
                        and e2["to"] == e["to"]
                        and abs(c[0] - c2[0]) + abs(c[1] - c2[1]) == 1):
                    twin = k2
                    break
        used.add(k)
        if twin:
            used.add(twin)
            lo, hi = sorted([k, twin], key=lambda t: cell(t))
            rows.append((f"{lo}+{hi.split(',')[0]}", e, True))
        else:
            rows.append((k, e, False))
    for label, e, wide in rows:
        print(f"    [{area}] {label:>10s} -> {e['to']:<26s} "
              f"taken {e['n']}x{'  (one door, 2 tiles)' if wide else ''}")

lonely = [a for a in visits if a not in explored]
for area in lonely:
    star = "*" if worked.get(area) else " "
    print(f"{star} {area}   (arrived {visits[area]}x, "
          f"no exits taken from here yet)")

if dead:
    print("\ndead ends (target could not be reached from that area):")
    for sg, regions in dead.items():
        for area, n in regions.items():
            print(f"    {sg} x{n} from {area}")
EOF

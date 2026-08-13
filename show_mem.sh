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
    for exit_key, e in sorted(explored[area].items(),
                              key=lambda kv: -kv[1]["n"]):
        print(f"    [{area}] {exit_key:>8s} -> {e['to']:<26s} "
              f"taken {e['n']}x")

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

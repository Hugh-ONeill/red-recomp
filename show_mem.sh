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

print(f"{len(explored)} areas known, "
      f"{sum(len(v) for v in explored.values())} exits mapped\n")
for area in sorted(explored, key=lambda a: -visits.get(a, 0)):
    print(f"{area}   (arrived {visits.get(area, 0)}x)")
    for exit_key, e in sorted(explored[area].items(),
                              key=lambda kv: -kv[1]["n"]):
        print(f"    {exit_key:>10s} -> {e['to']:<26s} taken {e['n']}x")

lonely = [a for a in visits if a not in explored]
for area in lonely:
    print(f"{area}   (arrived {visits[area]}x, no exits taken from here yet)")

if dead:
    print("\ndead ends (subgoal could not be achieved from that area):")
    for sg, regions in dead.items():
        for area, n in regions.items():
            print(f"    {sg} x{n} from {area}")
EOF

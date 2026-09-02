"""A rewrite is numbered past the HIGHEST plan, not into the first gap.

find_plan.py hands a leg its highest-numbered plan. campaign.sh numbered a
rewrite by the first FREE number counting from 1. Those two agree only while
the version sequence is dense, and nothing keeps it dense: restore one plan
from the archive, or lose one, and every rewrite afterwards lands in the hole
and is never read again.

Live on 2026-09-02. A v9 was restored by hand to put a leg back on the route
the model had chosen; its next three rewrites were written as v1, v2 and v3,
and the leg kept resolving to v9. The model was authoring into a bin, which is
the one failure this project cannot tolerate quietly — the whole claim is that
the plans are its own."""
import re, subprocess, sys, tempfile
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

RULE = re.search(r"base=\"\$\{failed_plan%\.json\}\".*?v=\$\(\(v\+1\)\)",
                 Path("campaign.sh").read_text(), re.S)


def next_version(existing):
    """Run campaign.sh's own numbering rule over a directory of plans."""
    d = Path(tempfile.mkdtemp()); (d / "plans").mkdir()
    for name in existing:
        (d / "plans" / name).write_text("{}")
    script = ("set -u\nfailed_plan=leg_01_x.json\n" + RULE.group(0)
              + "\necho $v\n")
    r = subprocess.run(["bash", "-c", script], cwd=d,
                       capture_output=True, text=True)
    return int((r.stdout or "0").strip() or 0)


ck("the rule was found in campaign.sh", RULE is not None)
ck("a dense sequence still numbers the next one up",
   next_version(["leg_01_x.v1.json", "leg_01_x.v2.json"]) == 3)
ck("a HOLE does not swallow the rewrite: v1 and v9 give v10",
   next_version(["leg_01_x.v1.json", "leg_01_x.v9.json"]) == 10)
ck("a lone restored high version is passed, not undercut",
   next_version(["leg_01_x.v9.json"]) == 10)
ck("no versions yet starts at v1", next_version([]) == 1)
ck("the unversioned base plan is not mistaken for a version",
   next_version(["leg_01_x.json"]) == 1)
ck("another leg's plans are not counted",
   next_version(["leg_01_x.v1.json", "leg_02_y.v7.json"]) == 2)
ck("double digits sort as numbers, not as text",
   next_version(["leg_01_x.v9.json", "leg_01_x.v10.json"]) == 11)

# the two rules must agree: whatever is written must be what is read back
d = Path(tempfile.mkdtemp()); (d / "plans").mkdir()
for name in ("leg_01_x.v1.json", "leg_01_x.v9.json"):
    (d / "plans" / name).write_text(
        '{"goal": "Reach Somewhere", "subgoals": [{"id": "a"}]}')
v = next_version(["leg_01_x.v1.json", "leg_01_x.v9.json"])
(d / "plans" / f"leg_01_x.v{v}.json").write_text(
    '{"goal": "Reach Somewhere", "subgoals": [{"id": "b"}]}')
found = subprocess.run([sys.executable,
                        str(Path.cwd() / "planner/find_plan.py"),
                        "Reach Somewhere"],
                       cwd=d, capture_output=True, text=True).stdout.strip()
ck("...so the plan just written is the plan the leg finds",
   found.endswith(f".v{v}.json"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)

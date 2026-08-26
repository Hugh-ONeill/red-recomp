"""The evidence trimmer moves a place header with the sentences under it
(2026-08-25: headers floated to the top as "near", speeches sank to the cut,
and every WHAT PEOPLE HAVE SAID entry reached the author with an empty body)."""
import sys
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import author
block = "WHAT PEOPLE HAVE SAID, where they said it:\n" + "\n".join(
    f"  in PLACE_{i}|1,1:\n    GUY_{i}: sentence number {i} about the road." for i in range(20))
text = "GOAL AND SUCH\nintro line\n\n" + block + "\n\nOTHER BLOCK\n" + "\n".join(f"  row {i}" for i in range(3))
out = author._fit(text, budget=len(text) - 200, near={"PLACE_3", "PLACE_17"})
lines = out.splitlines()
ck("a kept header keeps its sentence right under it",
   any(lines[i].startswith("  in PLACE_3|") and lines[i + 1].startswith("    GUY_3:") for i in range(len(lines) - 1)))
ck("near places are kept", "in PLACE_17|" in out and "GUY_17: sentence number 17" in out)
ck("no header is left with an empty body",
   not any(lines[i].startswith("  in PLACE_") and (i + 1 >= len(lines) or not lines[i + 1].startswith("    ")) for i in range(len(lines))))
ck("something was cut and said so", "not shown" in out)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

"""Every ledger the chain writes is one the watcher reads. notable.py hears
the ladder by tailing the sidecar files the chain script appends to; a rung
that writes to a file the watcher does not know is a decision nobody is
told about, and nothing errors. The first run of this test found one:
run/outline_unauthored, a leg stepped over after authoring failed twice.

So: read every top-level shell script, list each `>> run/NAME`, and fail on
any NAME the watcher has no parser for unless it is EXCUSED here by name,
which is a written claim that the file is not a decision."""
import glob, re, sys
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import notable as N

# a file appended under run/ that records no decision about the outline.
# Adding a name here is a claim; say why.
EXCUSED = set()

APPEND = re.compile(r'>>\s*"?run/([A-Za-z0-9_./$]+)')
sites = {}
for script in sorted(glob.glob("*.sh")):
    for n, line in enumerate(open(script, encoding="utf-8"), 1):
        if line.lstrip().startswith("#"):
            continue
        for name in APPEND.findall(line):
            sites.setdefault(name, []).append(f"{script}:{n}")

ck("the scan found the chain script's ledgers at all", len(sites) >= 10)
ck("attempt_yield is among them, so the regex reads real lines", "attempt_yield" in sites)
unknown = {n: w for n, w in sites.items() if n not in N.SIDECARS and n not in EXCUSED}
ck("every appended ledger has a parser or an excuse" + (
    "" if not unknown else " — unknown: " + ", ".join(f"{k} ({v[0]})" for k, v in unknown.items())),
   not unknown)
ck("no name carries a shell variable, which the watcher could not follow",
   not any("$" in n for n in sites))
stale = [n for n in EXCUSED if n not in sites]
ck("no excuse names a file nothing writes any more" + (f" — {stale}" if stale else ""), not stale)
ck("no file is both excused and parsed", not (EXCUSED & set(N.SIDECARS)))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

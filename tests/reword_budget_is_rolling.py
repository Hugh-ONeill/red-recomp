"""The outline reword budget rolls, it is not a lifetime ration (2026-08-26).

`wording_rung` was capped at three rewordings per CHAIN. On a 51-leg outline
that means the ladder goes permanently blind about three-quarters of the way
in. This run spent all three by leg 20 — S.S. Ticket (10), Gold Teeth (19),
Pokemon Tower (20) — and arrived at leg 32 "Obtain the Secret Key" with reword,
done-under-another-name (exit 4) and VOID (exit 5) all shut. check-done cannot
save that leg either: the key is in the Pokemon Mansion on CINNABAR, eight legs
later, behind a SURF the party cannot use without the SOULBADGE, so
has_item SECRET_KEY never comes true in Fuchsia and the leg can only burn
attempts (user: "yeah make the budget rolling").

Column 1 of outline_rewordings is the leg index it was spent on, so the window
is free."""
import sys, re, subprocess
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

sh = Path("fresh_discovery.sh").read_text()

ck("the lifetime cap is gone",
   'cat run/outline_rewordings 2>/dev/null | wc -l)" -lt 3' not in sh)
i = sh.find("A ROLLING BUDGET, NOT A LIFETIME ONE")
ck("a rolling window replaces it", i > 0)
blk = sh[i:i + 1800]
ck("...keyed on the leg index in column 1",
   "-F'\\t'" in blk and "($1+0) > i - w" in blk)
ck("...over the current leg", '-v i="$i"' in blk)
ck("...with the window named, not magic", "-v w=12" in blk)
ck("...still three inside that window", '-lt 3 ] || return 1' in blk)
ck("a missing file does not break the rung",
   "2>/dev/null) || _recent=0" in blk)
ck("the per-leg cap is untouched — a single leg still gets two asks",
   '[ "${_asked:-0}" -ge 2 ] && return 1' in sh)

ck("the script still parses",
   subprocess.run(["bash", "-n", "fresh_discovery.sh"]).returncode == 0)

# the arithmetic, on this run's real ledger
def recent(i, w=12):
    out = subprocess.run(
        ["awk", "-F\t", "-v", f"i={i}", "-v", f"w={w}",
         "($1+0) > i - w { n++ } END { print n+0 }",
         "run/outline_rewordings"], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)

ck("at leg 20 the throttle still bit (3 in the window)", recent(20) == 3)
ck("at leg 32 the rung reopens (the old three have aged out)",
   recent(32) < 3)
ck("a burst inside one window is still stopped", recent(21) >= 3)

# --- the look-ahead sweep had the same lifetime ration ---
ck("the sweep's lifetime cap is gone",
   'cat run/outline_skips 2>/dev/null | wc -l)" -lt 8' not in sh)
k = sh.find("ROLLING, FOR THE SAME REASON THE REWORD BUDGET IS")
ck("sweep_ahead rolls too", k > 0)
sblk = sh[k:k + 1400]
ck("...over the leg it is sweeping from", '-v i="$at"' in sblk)
ck("...counting only the NUMBERED lines sweep_ahead writes",
   "$1 ~ /^[0-9]+$/" in sblk)
ck("...so exit-4/VOID's bare lines never spend it",
   "bare objective" in sblk)
ck("...still eight inside the window", '-lt 8 ] \\' in sblk)

def skipped(i, w=12):
    out = subprocess.run(
        ["awk", "-F\t", "-v", f"i={i}", "-v", f"w={w}",
         "$1 ~ /^[0-9]+$/ && ($1+0) > i - w { n++ } END { print n+0 }",
         "run/outline_skips"], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)
ck("at leg 32 the sweep reopens", skipped(32) < 8)
ck("a bare VOID line is not counted against it",
   skipped(32) == 1)   # only "22\tReach Celadon City" is in the window

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

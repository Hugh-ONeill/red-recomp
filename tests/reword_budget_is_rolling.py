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
ck("...still three inside that window — the rewrite is withheld, the question still asked",
   '-lt 3 ] \\' in blk and 'the rolling budget of 3 rewordings per 12 legs is spent' in blk
   and '-lt 3 ] || return 1' not in blk)
ck("a missing file does not break the rung",
   "2>/dev/null) || _recent=0" in blk)
ck("the per-leg cap is untouched — a single leg still gets two asks",
   'if [ "${_asked:-0}" -ge 2 ]; then' in sh and "asked twice already" in sh)

ck("the script still parses",
   subprocess.run(["bash", "-n", "fresh_discovery.sh"]).returncode == 0)

# the arithmetic, on a fixture (the live ledger moved — three leg-36
# rewordings landed and the "reopens at 32" read came back 3)
import tempfile
_rw = Path(tempfile.mkdtemp(prefix="rewords_")) / "outline_rewordings"
_rw.write_text("10\tReach Mt. Moon\tReach Mt Moon\n"
               "13\tTeach CUT\tTeach a Pokemon CUT\n"
               "17\tFind Bill\tReach Bill's house\n")

def recent(i, w=12):
    out = subprocess.run(
        ["awk", "-F\t", "-v", f"i={i}", "-v", f"w={w}",
         "($1+0) > i - w { n++ } END { print n+0 }",
         str(_rw)], capture_output=True, text=True)
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

# THE LIVE LEDGER MOVES; the test does not: a "39\tWake Snorlax" skip landed
# inside the window and broke the count this used to read off run/. The
# sweep's awk program is read out of the script and run against a fixture.
import tempfile
_prog = re.search(r"_skipped=\$\(awk -F'\\t' -v i=\"\$at\" -v w=12 \\\n\s*'([^']*)'", sh)
ck("sweep_ahead's awk program can be read out of the script", bool(_prog))
_dir = Path(tempfile.mkdtemp(prefix="skips_"))

def skipped(i, rows, w=12):
    fx = _dir / f"skips_{i}_{len(rows)}"
    fx.write_text("".join(r + "\n" for r in rows))
    out = subprocess.run(
        ["awk", "-F\t", "-v", f"i={i}", "-v", f"w={w}",
         _prog.group(1) if _prog else "", str(fx)],
        capture_output=True, text=True)
    return int(out.stdout.strip() or 0)

_rows = ["3\tReach Viridian City",
         "Retrieve the Pokemon from the Poke Mart",          # a bare VOID line
         "22\tReach Celadon City",
         "Retrieve the Gold Teeth from the woman in Celadon City"]
ck("at leg 32 the sweep reopens", skipped(32, _rows) < 8)
ck("a bare VOID line is not counted against it",
   skipped(32, _rows) == 1)   # only "22\tReach Celadon City" is in the window
ck("...and a skip twelve legs back has rolled off",
   skipped(34, _rows) == 0)
_eight = [f"{n}\tleg {n}" for n in range(25, 33)]
ck("eight numbered skips inside the window still close the sweep",
   skipped(32, _eight) == 8)
ck("...and the same eight, twelve legs later, are gone",
   skipped(45, _eight) == 0)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)

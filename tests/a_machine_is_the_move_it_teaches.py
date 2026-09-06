"""HM01 is CUT: a machine's name and the move it teaches are one name.

The chosen outline for run 16 (2026-09-06) carried "a party Pokemon knows
HM01" at leg 17 and "a party Pokemon knows CUT" at leg 20 -- and again
"knows HM03" beside "knows SURF".  The upkeep round asked for CUT, the
outline already said HM01, and nothing joined them: the CUT leg was added
and protected, the HM01 leg stood as the model wrote it, unprotected and
never true as written, a fatal stall three lines before its twin (user:
"TM/HM names should be synonymous").

The game's own item table says which move each machine teaches, and the
screen prints it when the machine is booted.  So, from that table:
objectives compare with the machine folded to its move; an upkeep leg the
model wrote itself is protected when the round would have added its twin;
a knows_move written with the machine's name becomes the move before the
plan is validated; and the validator names the move instead of "not a
move".  Nothing here is our knowledge of the game: it is the game's table.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import author as A

ck("the table is loaded from the game's item data",
   len(A.MACHINE_MOVES) >= 55 and A.MACHINE_MOVES["HM01"] == "CUT"
   and A.MACHINE_MOVES["TM28"] == "DIG")

# objectives compare with the machine folded
ck("knows HM01 and knows CUT are one objective",
   A._norm_obj("a party Pokemon knows HM01")
   == A._norm_obj("a party Pokemon knows CUT"))
ck("a TM folds too", A._norm_obj("Teach TM28 to Dugtrio")
   == A._norm_obj("Teach DIG to Dugtrio"))
ck("a spaced spelling folds", A._norm_obj("knows HM 03")
   == A._norm_obj("knows SURF"))
ck("a number that is no machine is left alone",
   A._norm_obj("Reach Route 12") == "reach route 12")
A.OUTLINE_NOTES.clear()
kept = A._dedupe_outline(["Retrieve the HM01 from the S.S. Anne",
                          "a party Pokemon knows HM01",
                          "a party Pokemon knows CUT",
                          "Defeat Lt. Surge for the Thunder Badge"])
ck("the dedupe drops the later twin", "a party Pokemon knows CUT" not in kept
   and "a party Pokemon knows HM01" in kept and len(kept) == 3)

# the same for the deeds that fetch them (user: "if it says 'retrieve hm03'
# thats the same as saying 'retrieve surf'")
A.OUTLINE_NOTES.clear()
kept = A._dedupe_outline(["Retrieve the HM03 from the Safari Zone",
                          "Obtain the SURF HM from the Safari Zone",
                          "Defeat Koga for the Soul Badge"])
ck("retrieve HM03 and obtain SURF are one deed", len(kept) == 2
   and "Retrieve the HM03 from the Safari Zone" in kept)
# ...but getting the machine and knowing the move stay two objectives
A.OUTLINE_NOTES.clear()
kept = A._dedupe_outline(["Obtain HM01", "a party Pokemon knows CUT"])
ck("obtaining the machine is not the same as knowing the move",
   len(kept) == 2)

# the upkeep round: the model's own wording is protected
legs = ["Retrieve the HM01 from the S.S. Anne", "a party Pokemon knows HM01",
        "Defeat Lt. Surge for the Thunder Badge"]
_real = A.brock_probe.chat
A.brock_probe.chat = lambda msgs, model: json.dumps(
    [{"item": "a party Pokemon knows CUT", "after": 1}])
scratch = Path("/tmp/claude-1000/-home-wiz/b5fe8565-91da-4233-b62f-8b773e98e750/scratchpad/upkeep.test")
_path = A.UPKEEP_PATH
A.UPKEEP_PATH = scratch
try:
    out = A._outline_upkeep("g", legs, "m", rounds=1)
finally:
    A.brock_probe.chat = _real
    A.UPKEEP_PATH = _path
ck("the twin is not added", out == legs)
ck("the model's own wording is written to the upkeep list",
   scratch.exists() and "a party Pokemon knows HM01" in scratch.read_text())

# the upkeep round may still ADD "knows CUT" right after the HM01 fetch:
# the fold made them share a name, and the "hangs off what gives it to
# you" backstop refused it (two passes, 2026-09-06). Getting the machine
# does not teach the move.
legs = ["Reach Vermilion City", "Retrieve the HM01 from the S.S. Anne",
        "Defeat Lt. Surge for the Thunder Badge"]
A.brock_probe.chat = lambda msgs, model: json.dumps(
    [{"item": "a party Pokemon knows CUT", "after": 2},
     {"item": "Obtain the HM01 Cut", "after": 2}])
try:
    out = A._outline_upkeep_once("g", legs, "m")
finally:
    A.brock_probe.chat = _real
ck("a knows-move leg is added after the fetch that makes it possible",
   "a party Pokemon knows CUT" in out)
ck("...while a re-fetch of the same machine is still refused",
   "Obtain the HM01 Cut" not in out)

# the plan: knows_move HM01 means CUT, and has_item TM28 is TM_DIG
plan = {"subgoals": [{"id": "a", "done_when": {"knows_move": "HM01"}},
                     {"id": "b", "done_when": {"knows_move": {"move": "hm03",
                                                              "slot": 1}}},
                     {"id": "c", "done_when": {"has_item": {"TM28": 1}}}]}
A.normalize_items(plan)
ck("a knows_move written as the machine becomes the move",
   plan["subgoals"][0]["done_when"]["knows_move"] == "CUT"
   and plan["subgoals"][1]["done_when"]["knows_move"]["move"] == "SURF")
ck("a TM in has_item takes its engine id",
   plan["subgoals"][2]["done_when"]["has_item"] == {"TM_DIG": 1})
# the repass: the harness's own passes re-applied to a drawn outline, in
# place, with the upkeep protection following to the surviving wording
import shutil, tempfile
tmp = Path(tempfile.mkdtemp(dir="/tmp/claude-1000/-home-wiz/"
                            "b5fe8565-91da-4233-b62f-8b773e98e750/scratchpad"))
(tmp / "cand.txt").write_text("Retrieve the HM01 from the S.S. Anne\n"
                              "a party Pokemon knows HM01\n"
                              "a party Pokemon knows CUT\n"
                              "Defeat Lt. Surge for the Thunder Badge\n")
(tmp / "cand.upkeep").write_text("a party Pokemon knows CUT\n")
(tmp / "cand.stages").write_text("Vermilion City\ta party Pokemon knows CUT\n"
                                 "Vermilion City\tDefeat Lt. Surge for the Thunder Badge\n")
_u, _s = A.UPKEEP_PATH, A.STAGES_PATH
try:
    kept = A.outline_repass(tmp / "cand.txt")
finally:
    A.UPKEEP_PATH, A.STAGES_PATH = _u, _s
ck("the repass drops the later twin in place",
   kept == ["Retrieve the HM01 from the S.S. Anne", "a party Pokemon knows HM01",
            "Defeat Lt. Surge for the Thunder Badge"]
   and (tmp / "cand.txt").read_text().count("\n") == 3)
ck("...and protection follows to the model's own wording",
   (tmp / "cand.upkeep").read_text().strip() == "a party Pokemon knows HM01")
ck("...and the stages file names only living legs",
   "knows CUT" not in (tmp / "cand.stages").read_text())
ck("...and the note says what the dropped line said",
   "also written as 'a party Pokemon knows CUT'" in (tmp / "cand.notes").read_text())
shutil.rmtree(tmp, ignore_errors=True)

src = Path("planner/author.py").read_text()
ck("the validator names the move the machine teaches",
   "is the machine; the move it" in src)
ck("normalize_items runs before validation at both call sites",
   src.count("normalize_items(plan)\n") == 1
   and src.count("normalize_items(revised)\n") == 1)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

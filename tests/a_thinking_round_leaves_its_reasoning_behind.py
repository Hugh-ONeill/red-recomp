#!/usr/bin/env python3
"""A round that costs three times as much should leave something to read.

Thinking was gated, capped and paid for, and the trace itself was thrown
away the instant its length was counted — `stats_of` kept `think_chars` and
dropped the words. So the only record of what a 115-second round bought was
a token total (user, 2026-09-12: "we might want to log down the extra
thoughts we get when thinking is enabled ... this can help us pin down
whether/when the thinking is actually helpful").

It goes to run/thinking.jsonl, not the journal: a trace runs to a couple of
thousand tokens and a journal that swallowed them could not be grepped any
more, while thinking rounds are rare enough (21 in all of run 16) to keep
whole for a few hundred KB. The journal still records think_on, so it
always says that a trace exists.

A trace is written BEFORE its round runs and cannot know its own outcome,
so think_meter.py joins the two afterwards on (subgoal, round). The join
reads the progress_ops DELTA, never the raw field, which is a running total
that reads eighteen on a round that added one.
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import brock_probe as B                                    # noqa: E402
import think_meter as M                                    # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

# ---- the trace survives the call ---------------------------------------
ck("stats_of keeps the words, not just the count",
   B.stats_of({"message": {"thinking": "first the ledger", "content": "{}"},
               "eval_count": 9})["thinking"] == "first the ledger")
ck("...and still keeps the count",
   B.stats_of({"message": {"thinking": "abc", "content": ""}})
   ["think_chars"] == 3)
ck("a call that did not think carries no trace",
   B.stats_of({"message": {"content": "{}"}})["thinking"] == "")

# ---- and is written, to its own file ------------------------------------
tmp = Path(tempfile.mkdtemp())
os.environ["RED_RUN_DIR"] = str(tmp)
B.LAST = {"thinking": "I am in the Mansion and the fossil is not the door.",
          "gtok": 1856, "tot_s": 114.8, "think_chars": 50}
ck("a thinking call is written down",
   B.log_thinking("escalate", subgoal="defeat_blaine", round=14, stale=3))
rec = json.loads((tmp / "thinking.jsonl").read_text().splitlines()[0])
ck("...with the words whole", rec["thinking"].endswith("not the door."))
ck("...and what it cost", rec["gtok"] == 1856 and rec["tot_s"] == 114.8)
ck("...and enough to join it to its round",
   rec["subgoal"] == "defeat_blaine" and rec["round"] == 14
   and rec["where"] == "escalate")
ck("...and when, readably", "T" in rec["at"] and rec["t"] > 0)

B.LAST = {"thinking": "", "gtok": 90}
ck("a normal call writes nothing and says so",
   B.log_thinking("escalate", subgoal="x", round=1) is False)
ck("...so the file holds only thinking rounds",
   len((tmp / "thinking.jsonl").read_text().splitlines()) == 1)

B.LAST = None
ck("a losable trace never costs a round",
   B.log_thinking("escalate") is False)
os.environ.pop("RED_RUN_DIR", None)

# ---- the join, which is the point ---------------------------------------
J = [
  {"kind": "think_on", "subgoal": "a", "round": 4, "stale": 3},
  {"kind": "escalate_feedback", "subgoal": "a", "round": 3, "progress_ops": 10},
  {"kind": "escalate_feedback", "subgoal": "a", "round": 4, "progress_ops": 13},
  {"kind": "escalate_feedback", "subgoal": "a", "round": 5, "progress_ops": 14},
  {"kind": "think_on", "subgoal": "a", "round": 6, "stale": 1},
  {"kind": "escalate_feedback", "subgoal": "a", "round": 6, "progress_ops": 14},
]
by = M.rounds_of(J)
ck("a round's work is the DELTA, not the running total",
   by[("a", 4)]["new_ops"] == 3 and by[("a", 5)]["new_ops"] == 1)
ck("...and the first round of a leg counts from zero",
   by[("a", 3)]["new_ops"] == 10)
ck("a round that thought is marked as one",
   by[("a", 4)]["thought"] and not by[("a", 5)]["thought"])
ck("a stale count that FELL afterwards means the wall broke",
   M.broke_the_wall(J, "a", 4, within=2) is True)

J2 = [{"kind": "think_on", "subgoal": "b", "round": 3, "stale": 3},
      {"kind": "think_on", "subgoal": "b", "round": 4, "stale": 4}]
ck("...and one that ROSE means it did not",
   M.broke_the_wall(J2, "b", 3) is False)
ck("nothing later says nothing, rather than guessing",
   M.broke_the_wall(J2, "b", 4) is None)

# ---- it runs on the real journal, which has no traces yet --------------
ck("the meter reads run 16 off think_on alone",
   M.rounds_of(M._read(ROOT / "run/executor_log.jsonl")))
ck("a missing trace file is not an error", M._read(ROOT / "run/nope.jsonl") == [])

SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the escalation logs its trace and says so in the journal",
   'brock_probe.log_thinking(\n                        "escalate"' in SRC
   and 'self.log("think_logged"' in SRC)
ASRC = (ROOT / "planner" / "author.py").read_text()
ck("...and so does the author",
   'brock_probe.log_thinking("author"' in ASRC)

# ---- did it reason over the page, or over something it made up? -------
# THE BET ON THINKING IS NARROW: that it reasons BETTER over the facts it
# has, not that it acquires more (user, 2026-09-13: "thinking is not going
# to magically insert more true facts, but im hoping that it reasons over
# the facts it has (true or not) better"). So a trace leaning on something
# its page never gave it is not a thinking problem at all, and no cap or
# budget repairs it — one of those is a better reason to stop paying than
# any number of firings.
PAGE = ("WHERE YOU STAND: CINNABAR_LAB|2,3 — indoors.\n"
        "WHAT YOU ARE CARRYING: DOME_FOSSIL x1, POKE_BALL x5 (2 of 20 kinds).\n"
        "1. SCIENTIST (person at 5,4) — never spoken to\n")
ck("a map its page never mentioned is an invention",
   M.unsupported("I will go to SAFFRON_CITY and buy one", PAGE)[0]
   == ["SAFFRON_CITY"])
ck("an item it is not carrying is an invention",
   M.unsupported("I will use the HELIX_FOSSIL here", PAGE)[1]
   == ["HELIX_FOSSIL"])
ck("a tile nothing listed is an invention",
   "24,16" in M.unsupported("the stairs at (24,16) lead down", PAGE)[2])
ck("what IS on the page is not flagged",
   M.unsupported("I hold the DOME_FOSSIL and stand in CINNABAR_LAB "
                 "beside the SCIENTIST", PAGE) == ([], [], []))
ck("a SPECIES is knowledge, not an invention — it is expected to know them",
   M.unsupported("BLAINE uses fire types so my GYARADOS answers", PAGE)[0]
   == [] and "GYARADOS" not in str(M.unsupported(
       "my GYARADOS answers", PAGE)))
ck("a MOVE name is knowledge too",
   M.unsupported("THUNDERBOLT would be double damage", PAGE) == ([], [], []))
ck("prose numbers are not read as tiles",
   M.unsupported("it is level 30, about 20 turns away", PAGE)[2] == [])

# ...AND THE MECHANICAL PASS CANNOT SEE THE CASE THAT PROMPTED ALL THIS.
# Run 16's defeat_blaine believed the gym was locked BECAUSE it held the
# Dome Fossil. Every thing it named — the lab, the fossil, the scientist —
# was genuinely on its page; the invention was the CAUSAL claim between
# them, which no name check can reach. That is why there is a judged pass,
# and why its prompt asks about SUPPORT rather than truth: a judge asked
# whether a claim is correct calls a confident wrong memory correct, and
# this one did exactly that until it was reframed (2026-09-13).
BLAINE = ("I still have the Dome Fossil in my bag, which is why the "
          "Cinnabar Gym remains locked. I will deliver it to the scientist.")
# reading the same text against a page that DOES name the gym, every
# thing it mentions is accounted for — and the claim is still false
PAGE_GYM = PAGE + "CINNABAR_GYM is a door you have walked past at (11,3)\n"
ck("with every name accounted for, the check finds nothing wrong",
   M.unsupported(BLAINE, PAGE_GYM) == ([], [], []))
# ...and prose spelling is what makes that true. The page writes
# CINNABAR_GYM and the model writes "the Cinnabar Gym"; an id-only scan
# matched neither, so this check was blind to prose until 2026-09-13.
ck("a name the page never mentions is caught in prose spelling too",
   M.unsupported(BLAINE, PAGE)[0] == ["CINNABAR_GYM"])
ck("...so the judge asks about support, never about truth",
   "NOT to say whether the reasoning is true" in M.JUDGE_SYS
   and "being sure is not evidence" in M.JUDGE_SYS)
ck("...and is told not to flag the objective it was handed",
   "DO NOT LIST THE OBJECTIVE" in M.JUDGE_SYS
   and "POINTLESS were that claim false" in M.JUDGE_SYS)
ck("the judge is opt-in, because it is judgement and it costs a call",
   "--judge" in (ROOT / "planner" / "think_meter.py").read_text())
ck("a judge that cannot be reached is reported, not raised",
   "error" in M.judge("p", "t", "no-such-model-at-all"))

# the page a trace reasoned over is found by subgoal and time, never guessed
J3 = [{"kind": "escalate_context", "subgoal": "a", "t": 10, "memory": "old"},
      {"kind": "escalate_context", "subgoal": "a", "t": 30, "memory": "right"},
      {"kind": "escalate_context", "subgoal": "a", "t": 90, "memory": "later"},
      {"kind": "escalate_context", "subgoal": "b", "t": 31, "memory": "other"}]
ck("the page is the last one written before the trace, on its own leg",
   M.page_for(J3, {"subgoal": "a", "t": 40}) == "right")
ck("no page for that leg says nothing rather than borrowing one",
   M.page_for(J3, {"subgoal": "zz", "t": 40}) == "")

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

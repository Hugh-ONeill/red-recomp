"""Who is in the party is part of a level condition.

The storage line was written into the CATCH branch only, so on "every party
member is at least level N" — the one goal where party composition decides
how much grinding is needed — the page never mentioned the box. The run set
about dragging a L22 TENTACOOL to 50 with a L32 HITMONLEE sitting in
storage (user, 2026-08-24: "its just a dumb idea to train this crappy
tentacool instead of grabbing one of the stronger mons out of the box").

A boxed Pokemon neither counts toward the condition nor has to meet it.
Which of them belongs in the party is the model's call.
"""
import re
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


# the training branch is the one that tells you to lead with who you level
i = src.find("put it in slot 1 first")
raw = src[max(0, i - 900):i + 2600]
# COMMENTS ARE NOT WHAT THE MODEL READS. The rationale here quotes the user
# verbatim ("instead of grabbing one of the stronger mons"), which would
# trip the no-advice check against the source. Strip them.
branch = "\n".join(l for l in raw.splitlines()
                   if not l.lstrip().startswith("#"))
# and the model-facing text is a wrapped literal, so joins split words
flat = re.sub(r'"\s*\n\s*"', "", branch)

ck("the training branch exists", i > 0)
ck("it names the box", "WHO IS IN THE PARTY IS ALSO A CHOICE" in branch)
ck("it reads storage from the observation", 'get("pc_mons")' in branch)
ck("it says a boxed one does not count toward the condition",
   "does not count toward this condition" in flat)
ck("it gives the op that takes one out", "pc_withdraw" in branch)
ck("it gives the op that puts one in", "pc_deposit" in branch)
ck("it still explains the lead earns", "only what fights, earns" in branch)
ck("it does not tell the model which to pick",
   not any(w in branch.lower() for w in
           ("you should", "instead of", "better than", "swap out the weak")))

# and the catch branch keeps its own version
ck("the catch branch's storage line survives",
   "YOU ALREADY HAVE POKEMON IN STORAGE" in src)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)

"""A chapter directive rendered into the story.

Reported live, at the top of a reply:

    # THIS CHAPTER — steer toward it, do not wander off it
    You are in: The Nyx Gauntlet
    Its goal: Survive a high-stakes Nyx seeding tournament, ...
    Every scene must move toward that goal, complicate it, or pay it off. ...
    Do not resolve it in a single turn, and do not skip ahead to '...'.

Two independent causes, and BOTH had to be fixed or the leak only half-clears.

1. The echo filter was built from `messages[0]` alone — the assembled context.
   The tail directives (continuity, chapter) are appended as separate system
   messages, deliberately, because the last thing a model reads binds hardest.
   That position also makes them the most echo-prone text in the prompt, and the
   filter could not see a single line of them.

2. Even once visible, `_is_echo` refused any line ending in terminal
   punctuation, on the reasoning that "a real sentence ends in `.`; a `## Time`
   header does not". The directives are WRITTEN as sentences, so three of the
   five leaked lines were protected by that rule.

 1) system_line_set collects the tail directives, and excludes the transcript
 2) a directive sentence is dropped despite ending in a period
 3) the whole reported block clears, and the prose after it survives
 4) short coincidental sentences are still protected (the old guard holds)
 5) a directive line MID-prose is never touched (leading run only)
 6) every drop is reported, so the removal is never invisible
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-decho-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.streaming import (filter_context_echo, prompt_line_set,   # noqa: E402
                                system_line_set)

DIRECTIVE = (
    "# THIS CHAPTER — steer toward it, do not wander off it\n"
    "You are in: The Nyx Gauntlet\n"
    "Its goal: Survive a high-stakes Nyx seeding tournament, protecting your "
    "Polychrome secret from rival syndicates.\n"
    "Every scene must move toward that goal, complicate it, or pay it off. If "
    "the last few turns have not advanced it, advance it now.\n"
    "Do not resolve it in a single turn, and do not skip ahead to "
    "'The Trap's Architect'."
)
MESSAGES = [
    {"role": "system", "content": "## Time\nCurrent in-world time: Day 3"},
    {"role": "user", "content": "I step into the ring."},
    {"role": "system", "content": DIRECTIVE},
]


def _run(text):
    dropped = []
    out = "".join(filter_context_echo(
        iter([text]), prompt_line_set(MESSAGES[0]["content"]), dropped,
        system_line_set(MESSAGES)))
    return out, dropped


def test_system_line_set_scope():
    got = system_line_set(MESSAGES)
    assert "You are in: The Nyx Gauntlet" in got
    assert "# THIS CHAPTER — steer toward it, do not wander off it" in got
    assert "I step into the ring." not in got, "the transcript must stay excluded"
    assert "Current in-world time: Day 3" not in got, "messages[0] is the other set"
    print(f"1. system_line_set collected {len(got)} directive lines, no transcript")


def test_sentence_directive_is_dropped():
    line = "Every scene must move toward that goal, complicate it, or pay it off. If the last few turns have not advanced it, advance it now."
    out, dropped = _run(line + "\nThe bell rings.")
    assert line not in out, out
    assert out.strip() == "The bell rings.", repr(out)
    print("2. a directive that ends in a period is dropped")


def test_the_reported_block_clears():
    """§3 the actual report, verbatim, with real prose behind it."""
    prose = "The Nyx ring smells of ozone and old blood.\nSomeone calls your name."
    out, dropped = _run(DIRECTIVE + "\n" + prose)
    assert out.strip() == prose, repr(out)
    assert len(dropped) == 5, dropped
    print(f"3. all 5 directive lines cleared, {len(prose)} chars of prose intact")


def test_short_coincidence_still_protected():
    """§4 the guard that was relaxed must still hold for assemble()'s content.
    A short prose sentence matching a context line is a coincidence, not an echo
    — the exemption is only for lines we wrote as directives."""
    dropped = []
    msgs = [{"role": "system", "content": "He ran."}]
    out = "".join(filter_context_echo(
        iter(["He ran.\nThen the door opened."]),
        prompt_line_set(msgs[0]["content"]), dropped, system_line_set(msgs)))
    assert out.startswith("He ran."), repr(out)
    assert not dropped, dropped
    print("4. a short coincidental sentence is still protected")


def test_only_a_leading_run_is_dropped():
    out, dropped = _run("The bell rings.\nYou are in: The Nyx Gauntlet")
    assert "You are in: The Nyx Gauntlet" in out, repr(out)
    assert not dropped, dropped
    print("5. a directive line mid-prose is left alone")


def test_drops_are_reported():
    """§6 invariant 2 — deleting model output invisibly is its own bug."""
    _, dropped = _run(DIRECTIVE + "\nThe bell rings.")
    assert dropped and all(d.strip() for d in dropped), dropped
    assert any("THIS CHAPTER" in d for d in dropped), dropped
    print(f"6. {len(dropped)} drops reported to the caller for the health log")


try:
    for fn in (test_system_line_set_scope, test_sentence_directive_is_dropped,
               test_the_reported_block_clears,
               test_short_coincidence_still_protected,
               test_only_a_leading_run_is_dropped, test_drops_are_reported):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nDIRECTIVE ECHO TESTS PASSED")

"""Chapter goals came out too short to steer with.

The instruction said "Concise goal (<= 30 words)", so a chapter goal was a
one-line summary. Reported live: the plan reads like a table of contents rather
than something the writer can aim at.

Widening it to 3-4 sentences touches two other things, and missing either would
have made the change worse than not doing it.

  _chapter_directive truncated the goal at 400 chars. A 3-4 sentence goal runs
  past that, so the directive would have told the writer to steer toward half an
  instruction, cut mid-sentence.

  _restates compares 3-content-word runs. Tripling the content words triples the
  trigrams, and two chapters of one story share incidental runs like "golden
  dragons inner" without being the same chapter. One shared run in a long pair
  is noise; the live restatement pair was SHORT (13 and 14 content words) and had
  exactly one. So the bar scales with length instead of being raised for all.

 1) both instructions ask for 3-4 sentences and forbid padding
 2) a 3-4 sentence goal survives into the directive uncut
 3) the live SHORT restatement pair is still caught on one shared run
 4) two LONG goals sharing one incidental run are NOT flagged
 5) two LONG goals sharing two runs still are
 6) the stored goal is still bounded (a model cannot write an essay into context)
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-chlen-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                                # noqa: E402
from coderain.engine import _chapter_directive                          # noqa: E402
from coderain.memory import Library                                     # noqa: E402
from coderain.planner import (LONG_GOAL_WORDS, MIN_GOAL_SENTENCES,      # noqa: E402
                              NEXT_INSTRUCTION, SLOT_INSTRUCTION,
                              ChapterPlanner, _content_words, _restates,
                              _sentences, _too_thin)

lib = Library(WORK / "lib")

FOUR_SENTENCES = (
    "Val must talk her way into the Nyx seeding tournament without letting any "
    "of the syndicate scouts in the upper gallery catch a Polychrome flare off "
    "her hands. The Dragons' trust condition requires a public, decisive win, "
    "which is precisely the kind of fight that would force the tell into the "
    "open where everyone can read it. Every round she survives raises both her "
    "seeding and the odds that someone in the crowd already knows what she is. "
    "By the end of the chapter she is holding either a tournament seed or her "
    "secret, and the story should make clear she cannot keep both."
)
SHORT_A = ("Survive a savage test fight against an Inner Circle enforcer and "
           "uncover the contract's hidden compulsion that nearly enslaves you.")
SHORT_B = ("Uncover the contract's hidden trap while navigating the Golden "
           "Dragons' politics, setting the stage for the enforcer's brutal trial.")


def test_instructions_ask_for_sentences():
    for name, text in (("NEXT", NEXT_INSTRUCTION), ("SLOT", SLOT_INSTRUCTION)):
        assert "3-4 SENTENCES" in text, name
        assert "30 words" not in text, f"{name} still caps at 30 words"
        assert "Do not pad" in text, name
    print("1. both instructions ask for 3-4 sentences and forbid padding")


def test_long_goal_survives_into_the_directive():
    """§2 the bound that would have silently clipped the new goals."""
    store = lib.store(lib.create_story("dir", "A rogue bound by blood contract."))
    ChapterPlanner(load_config(), store, None).replace_all([
        {"title": "The Nyx Gauntlet", "goal": FOUR_SENTENCES, "status": "active"},
        {"title": "The Trap's Architect", "goal": "later", "status": "planned"},
    ])
    body = _chapter_directive(store)
    assert FOUR_SENTENCES in body, body[:400]
    assert body.rstrip().endswith("'The Trap's Architect'."), body[-80:]
    assert len(FOUR_SENTENCES) > 400, "the fixture no longer exercises the bound"
    print(f"2. a {len(FOUR_SENTENCES)}-char goal reaches the directive uncut")


def test_short_pair_still_caught():
    assert min(len(_content_words(SHORT_A)), len(_content_words(SHORT_B))) \
        <= LONG_GOAL_WORDS, "the live pair drifted into the long regime"
    assert _restates(SHORT_B, [SHORT_A]) == "uncover contract hidden"
    print("3. the live short pair is still caught on one shared run")


# Two LONG goals that share exactly one incidental run — "golden dragons inner",
# which is the setting, not the beat. Verified: 26 and 27 content words, one
# shared trigram. Reusing a common paragraph across both (the first draft here)
# shares dozens of runs and IS a restatement, which the check flagged correctly.
LONG_A = ("Val infiltrates the golden dragons inner vault beneath the flooded "
          "market district, moving past wardens nobody can bribe. The tournament "
          "crowd overhead is her only cover, and it thins by the hour. She leaves "
          "with the sealed ledger or she does not leave at all.")
LONG_B = ("A rival syndicate offers Val a way out of the golden dragons inner "
          "circle entirely, on terms she cannot verify. Accepting means "
          "abandoning the courier she promised to protect. She has until the "
          "harbourmaster's tide signal to decide which promise she breaks.")


def test_long_pair_with_one_incidental_run_is_not_flagged():
    """§4 the noise case the scaling exists for. Both goals say "golden dragons
    inner" because that is the setting, not because they are the same chapter."""
    assert min(len(_content_words(LONG_A)), len(_content_words(LONG_B)))         > LONG_GOAL_WORDS, "fixtures are not in the long regime"
    hit = _restates(LONG_A, [LONG_B])
    assert hit == "", f"spurious restatement flagged: {hit!r}"
    print("4. two long goals sharing one incidental run are not flagged")


def test_long_pair_with_two_runs_is_flagged():
    """§5 the scaling must not disarm the check on long goals entirely. Here the
    second goal also steals the sealed ledger, which is the same beat twice."""
    b = LONG_B + " She leaves with the sealed ledger or she does not leave."
    hit = _restates(LONG_A, [b])
    assert hit, "two shared runs in long goals should still flag"
    print(f"5. two long goals sharing multiple runs are flagged on {hit!r}")


def test_stored_goal_is_still_bounded():
    """§6 invariant: anything from the model gets a length bound. Longer is not
    unbounded — this text is rendered into every turn's context."""
    store = lib.store(lib.create_story("bound", "A rogue bound by blood contract."))
    p = ChapterPlanner(load_config(), store, None)
    p.replace_all([{"title": "X", "goal": "word " * 3000, "status": "active"}])
    assert len(p.as_dicts()[0]["goal"]) <= 2000, len(p.as_dicts()[0]["goal"])
    print("6. the stored goal is still bounded at 2000 chars")



class _Seq:
    """Replies from a queue; records every payload it was handed."""

    def __init__(self, replies):
        self.replies, self.payloads = list(replies), []

    def complete(self, messages, **k):
        self.payloads.append(messages[-1]["content"])
        import json
        return json.dumps(self.replies.pop(0) if self.replies
                          else {"title": "F", "goal": "A. B. C."})


THIN = "Val must navigate the guild's alliances while uncovering the traitor."
FULL = ("Val must find the traitor before the seeding closes. The guild's own "
        "wardens are the obstacle. By the end she knows the name or loses the "
        "seat.")


def test_thin_goal_is_retried_with_a_reason():
    """§7 asking is not enough on a small model: measured 1 of 4 llama3.1:8b
    generations came back as a single run-on despite the instruction."""
    assert _too_thin(THIN) and not _too_thin(FULL)
    store = lib.store(lib.create_story("thin", "A rogue bound by blood contract."))
    stub = _Seq([{"title": "A", "goal": THIN}, {"title": "B", "goal": FULL}])
    p = ChapterPlanner(load_config(), store, stub)
    made = p._generate_next()
    assert made.title == "B", made.title
    assert made.body.strip() == FULL, made.body
    nudge = stub.payloads[1]
    assert "REJECTED" in nudge and "one-line summary" in nudge, nudge[-300:]
    assert f"{MIN_GOAL_SENTENCES}-4 SEPARATE sentences" in nudge, nudge[-300:]
    print(f"7. a {_sentences(THIN)}-sentence goal is rejected and retried")


def test_a_second_thin_goal_is_kept_but_logged():
    """§8 invariant 2 again: an outline with a thin chapter beats a hole, but
    the degradation has to be visible."""
    store = lib.store(lib.create_story("thin2", "A rogue bound by blood contract."))
    stub = _Seq([{"title": "A", "goal": THIN}, {"title": "B", "goal": THIN}])
    p = ChapterPlanner(load_config(), store, stub)
    made = p._generate_next()
    assert made is not None, "a thin chapter must still be written"
    health = (store.dir / "memory" / "health.jsonl").read_text(encoding="utf-8")
    assert "chapter-plan" in health and "sentence(s)" in health, health
    print("8. a second thin goal is kept and written to health.jsonl")


try:
    for fn in (test_instructions_ask_for_sentences,
               test_long_goal_survives_into_the_directive,
               test_short_pair_still_caught,
               test_long_pair_with_one_incidental_run_is_not_flagged,
               test_long_pair_with_two_runs_is_flagged,
               test_stored_goal_is_still_bounded,
               test_thin_goal_is_retried_with_a_reason,
               test_a_second_thin_goal_is_kept_but_logged):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCHAPTER LENGTH TESTS PASSED")

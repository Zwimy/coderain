"""Two defects found by a real 14-turn play test through local Ollama.

1. CONTEXT ECHO. Small models mimic the Markdown structure they are shown. On
   llama3.1:8b the opening reproduced the `## You {#player}` sheet verbatim and
   then all 14 turns opened with the `## Time` / `Current in-world time:` block.
   Nothing stripped it, so it reached the reader, transcript.md, and every fold
   built on that transcript. §1-§6 pin `filter_context_echo`.

2. PLAYER PROMOTED AS AN NPC. The same run put a `you` entry with an empty
   status into characters.md, duplicating player.md — which already rides every
   prompt at priority 0 — and logged five more attempts on you/player/<the
   player's invented name>. §7-§8 pin the guard in `_apply_promotions`.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-echo-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.memory import Library                                  # noqa: E402
from coderain.streaming import (filter_context_echo,                 # noqa: E402
                                prompt_line_set)
from coderain.summarizer import Summarizer                            # noqa: E402

PROMPT = (
    "## You  {#player}\n"
    "importance: 5\n"
    "stats: strength 1, agility 1\n"
    "\n"
    "## Time\n"
    "Current in-world time: Day 3, mid-morning\n"
    "\n"
    "## World\n"
    "A frozen kingdom.\n"
)
LINES = prompt_line_set(PROMPT)


def run(chunks):
    dropped: list[str] = []
    out = "".join(filter_context_echo(iter(chunks), LINES, dropped))
    return out, dropped


def test_leading_echo_is_dropped():
    """§1 the exact leak: every turn of the play test opened like this."""
    out, dropped = run(["## Time\nCurrent in-world time: Day 3, mid-morning\n\n"
                        "You check the seal on the tin box.\n"])
    assert out.strip() == "You check the seal on the tin box.", repr(out)
    assert len(dropped) == 2, dropped
    print("1. leading '## Time' block dropped, prose kept")


def test_echo_split_across_chunks():
    """§2 real streams split anywhere. Judging a partial line as prose would
    unblock the filter permanently and leak the rest of the header."""
    out, _ = run(["## Ti", "me\nCurrent in-world ti", "me: Day 3, mid-morning\n",
                  "The ice groans.\n"])
    assert out.strip() == "The ice groans.", repr(out)
    print("2. echo split mid-line across chunks still dropped")


def test_prose_is_never_touched():
    """§3 the failure mode that would matter most: eating real narration."""
    body = "You check the seal.\n\n## Time\nCurrent in-world time: Day 3, mid-morning\n"
    out, dropped = run([body])
    assert out == body, repr(out)          # incl. the header AFTER prose started
    assert dropped == [], dropped
    print("3. only a LEADING run is dropped; prose and later text untouched")


def test_unrelated_heading_survives():
    """§4 a heading the prompt never contained is the model's own writing —
    a story that narrates '## Chapter Three' must keep it."""
    out, dropped = run(["## Chapter Three\nSnow fell.\n"])
    assert out.startswith("## Chapter Three"), repr(out)
    assert dropped == [], dropped
    print("4. headings not present in the prompt are left alone")


def test_sentence_lookalike_survives():
    """§5 the coincidence guard: a line that IS in the prompt but reads as a
    sentence (terminal punctuation) is prose, not scaffolding."""
    out, _ = run(["A frozen kingdom.\nShe walked on.\n"])
    assert out.startswith("A frozen kingdom."), repr(out)
    print("5. a prompt line ending in punctuation is treated as prose")


def test_echo_only_reply_is_fully_dropped():
    """§6 no trailing newline, nothing but the header. Must not be emitted
    whole just because the stream ended before a '\\n' arrived."""
    out, dropped = run(["## Time"])
    assert out == "", repr(out)
    assert dropped == ["## Time"], dropped
    print("6. a reply that is nothing but an echoed header yields no prose")


# ---- the player-promotion guard ----------------------------------------

class _Cfg:
    """_apply_promotions makes no model call; Summarizer only reads .memory."""
    memory: dict = {}


def _summarizer(store):
    return Summarizer(_Cfg(), store, None, None)


def test_player_is_not_promoted_as_an_npc():
    """§7 'you'/'player' and the player's own name must not reach characters.md."""
    lib = Library(WORK / "lib7")
    store = lib.store(lib.create_story("Guard", "A courier."))
    store.write("player.md", "## Eira Shadowglow  {#player}\nimportance: 5\n\n"
                             "A night courier.\n")
    s = _summarizer(store)
    s._apply_promotions({"promotions": [
        {"kind": "character", "slug": "you", "title": "You",
         "detail": "The courier."},
        {"kind": "character", "slug": "player", "title": "Player",
         "detail": "The courier."},
        {"kind": "character", "slug": "eira-shadowglow", "title": "Eira",
         "detail": "The courier."},
    ]})
    slugs = [e.slug for e in store.entries("characters.md")]
    assert slugs == [], slugs
    health = store.read("memory/health.jsonl")
    assert health.count("skipped promoting the player") == 3, health
    print("7. player aliases refused as NPCs, and refused LOUDLY")


def test_real_npcs_still_promote():
    """§8 the guard must not become a wall — this is the regression that would
    make the fix worse than the bug."""
    lib = Library(WORK / "lib8")
    store = lib.store(lib.create_story("Pass", "A courier."))
    store.write("player.md", "## Eira Shadowglow  {#player}\nimportance: 5\n\n"
                             "A night courier.\n")
    s = _summarizer(store)
    s._apply_promotions({"promotions": [
        {"kind": "character", "slug": "grimbold", "title": "Grimbold",
         "detail": "The innkeeper at the Blackwood Tavern."},
    ]})
    slugs = [e.slug for e in store.entries("characters.md")]
    assert slugs == ["grimbold"], slugs
    print("8. ordinary NPCs still promote normally")


for fn in (test_leading_echo_is_dropped,
           test_echo_split_across_chunks,
           test_prose_is_never_touched,
           test_unrelated_heading_survives,
           test_sentence_lookalike_survives,
           test_echo_only_reply_is_fully_dropped,
           test_player_is_not_promoted_as_an_npc,
           test_real_npcs_still_promote):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nECHO + PLAYER-PROMOTION TESTS PASSED")

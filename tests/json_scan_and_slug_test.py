"""Two cleanups from the local-model play tests.

1. extract_json claimed to be "brace-balanced" and was `re.compile(r"\\{.*\\}",
   re.DOTALL)` — greedy, first brace to LAST brace. sidecar.py had a real
   string-aware scanner right next door. Two copies of one rule, and the fold
   path had the weaker one. The scanner now lives once, in streaming.py.
   §1-§6.

2. Promotion slugs were taken raw. Measured live: deepseek-r1:8b wrote a
   one-character `y` entry into characters.md, and qwen3:4b promoted one
   character twice as `shadow-figure` and `char-shadow-figure`. §7-§10.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-jsonscan-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.llm import extract_json                    # noqa: E402
from coderain.memory import Library                      # noqa: E402
from coderain.sidecar import parse_sidecar               # noqa: E402
from coderain.streaming import json_objects              # noqa: E402
from coderain.summarizer import Summarizer               # noqa: E402


def test_trailing_prose_with_a_brace():
    """§1 the exact greedy failure: valid JSON, then a sentence with a brace."""
    assert extract_json('{"a": 1}\nThat closes the scene }') == {"a": 1}
    print("1. valid JSON followed by a stray brace still parses")


def test_two_objects_takes_the_first_parseable():
    assert extract_json('{"a": 1} and then {"b": 2}') == {"a": 1}
    print("2. first complete object wins")


def test_skips_an_unparseable_lead_in():
    """§3 a reasoning model narrates a shape before committing to the real
    object. Stopping at the first BALANCED span would return the sketch."""
    text = 'I will return {scene_summary: ...} shaped output:\n{"scene_summary": "ok"}'
    assert extract_json(text) == {"scene_summary": "ok"}
    print("3. unparseable sketch skipped, real object found")


def test_braces_inside_strings_do_not_shift_depth():
    assert extract_json('{"a": "a } brace", "b": 2}') == {"a": "a } brace", "b": 2}
    print("4. a brace inside a string does not end the object")


def test_escaped_quote_does_not_end_the_string():
    assert extract_json(r'{"a": "she said \"hi\" }", "b": 1}')["b"] == 1
    print("5. escaped quote handled")


def test_nested_objects_and_no_match():
    assert extract_json('{"a": {"b": {"c": 1}}}') == {"a": {"b": {"c": 1}}}
    assert extract_json("no json here") is None
    assert extract_json("") is None
    assert list(json_objects("{unclosed")) == []      # truncated yields nothing
    print("6. nesting, no-match, and truncation all behave")


def test_sidecar_still_works_through_the_shared_scanner():
    """§7 sidecar.py was the module that HAD the correct scanner; moving it must
    not regress the path it was written for."""
    got = parse_sidecar('prose\n```rpg\n{"deltas": {"location": "Inn"}}\n```')
    assert got == {"deltas": {"location": "Inn"}}, got
    print("7. sidecar parsing unchanged after the move")


# ---- promotion slugs ----------------------------------------------------

class _Cfg:
    memory: dict = {}


def _store(name):
    lib = Library(WORK / name)
    st = lib.store(lib.create_story(name, "A courier."))
    st.write("player.md", "## Eira  {#player}\nimportance: 5\n\nA courier.\n")
    return st


def test_kind_prefix_is_stripped_and_merges():
    """§8 the live duplicate: one character promoted under two slugs."""
    st = _store("dup")
    s = Summarizer(_Cfg(), st, None, None)
    s._apply_promotions({"promotions": [
        {"kind": "character", "slug": "shadow-figure", "title": "Shadow Figure",
         "detail": "Waits at the village gate."},
        {"kind": "character", "slug": "char-shadow-figure", "title": "Shadow Figure",
         "detail": "Follows the courier to the inn."},
    ]})
    slugs = [e.slug for e in st.entries("characters.md")]
    assert slugs == ["shadow-figure"], slugs
    print("8. 'char-' prefix stripped; the two promotions merged into one entry")


def test_one_character_slug_refused():
    """§9 deepseek's `y` entry."""
    st = _store("short")
    s = Summarizer(_Cfg(), st, None, None)
    s._apply_promotions({"promotions": [
        {"kind": "character", "slug": "y", "title": "Y", "detail": "A person."},
    ]})
    assert [e.slug for e in st.entries("characters.md")] == []
    assert "too short to name anything" in st.read("memory/health.jsonl")
    print("9. one-character slug refused, and refused loudly")


def test_prefix_stripping_is_kind_scoped_and_safe():
    """§10 the overcorrection guard. A LOCATION called 'Character Hall' must
    keep its slug — only a character sheds 'character-'. And a slug that is
    nothing but the prefix is left alone rather than emptied."""
    st = _store("safe")
    s = Summarizer(_Cfg(), st, None, None)
    s._apply_promotions({"promotions": [
        {"kind": "location", "slug": "character-hall", "title": "Character Hall",
         "detail": "A long hall."},
        {"kind": "character", "slug": "charlotte", "title": "Charlotte",
         "detail": "A smith."},
    ]})
    assert [e.slug for e in st.entries("locations.md")] == ["character-hall"]
    assert [e.slug for e in st.entries("characters.md")] == ["charlotte"]
    assert Summarizer._normalize_slug("char-", "character") == "char-"
    print("10. stripping is kind-scoped; 'charlotte' and 'character-hall' intact")


for fn in (test_trailing_prose_with_a_brace,
           test_two_objects_takes_the_first_parseable,
           test_skips_an_unparseable_lead_in,
           test_braces_inside_strings_do_not_shift_depth,
           test_escaped_quote_does_not_end_the_string,
           test_nested_objects_and_no_match,
           test_sidecar_still_works_through_the_shared_scanner,
           test_kind_prefix_is_stripped_and_merges,
           test_one_character_slug_refused,
           test_prefix_stripping_is_kind_scoped_and_safe):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nJSON SCAN + SLUG TESTS PASSED")

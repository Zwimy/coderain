"""The generator must not keep the placeholders from the JSON shapes it shows the model (D-054).

What broke. The shapes in `coderain/generator.py` read `"slug": "kebab-id"` and `"aliases": ["alt"]`. A real run of "a world
from one sentence" on a 4B model wrote four entries (a canon event, a place, an item, a thread) whose slug was `kebab-id` and an
item whose only alias was `alt`; an 8B model wrote `kebab-aethera` and `kebab-marshview`. A slug that names nothing is worse than
none: cross-references to it are ambiguous, and a second entry with the same slug in one file replaces the first.

 1) a placeholder slug (kebab-id, kebab-case-id, kebab-<word>, slug, id) is dropped and the title makes the slug, exactly as
    when the model sends no slug; an ordinary slug, including one that merely starts with the letters kebab, is kept
 2) two entries that both copied the placeholder get two different slugs (so neither replaces the other)
 3) the placeholder alias "alt" is dropped, in any case; real aliases are kept in order
 4) an entry with a placeholder slug and no usable title is refused, not stored under a nonsense key
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coderain import templates                                   # noqa: E402
from coderain.generator import _character_entry, _entry_from     # noqa: E402


def test_placeholder_slugs():
    for bad in ("kebab-id", "kebab-case-id", "kebab-aethera", "Kebab-Marshview", "KEBAB", "slug", "id", "slug-id", " kebab-id "):
        e = _entry_from({"slug": bad, "title": "The Saltwatch Docks", "detail": "Wharves."})
        assert e is not None and e.slug == templates.slugify("The Saltwatch Docks"), (bad, e and e.slug)
        assert e.title == "The Saltwatch Docks"
    for good in ("saltwatch-docks", "corvus-id", "kebabs-stall", "the-id-stone"):
        e = _entry_from({"slug": good, "title": "Anything At All", "detail": "x"})
        assert e.slug == good, (good, e.slug)
    e = _entry_from({"title": "No Slug Sent", "detail": "x"})
    assert e.slug == templates.slugify("No Slug Sent"), "the no-slug path changed"
    c = _character_entry({"slug": "kebab-id", "title": "Corvus Vane", "aliases": ["alt", "the ferryman"], "detail": "x"})
    assert c is not None and c.slug == templates.slugify("Corvus Vane") and c.aliases == ["the ferryman"], c
    print("1. a placeholder slug is replaced by the title's; a real one, even one starting 'kebab', is kept")


def test_two_copies_do_not_collide():
    a = _entry_from({"slug": "kebab-id", "title": "Corvus's Lockstone", "detail": "A stone."})
    b = _entry_from({"slug": "kebab-id", "title": "The Missing Boy", "detail": "A thread."})
    assert a.slug != b.slug and "kebab" not in a.slug + b.slug, (a.slug, b.slug)
    print("2. two entries that both copied the placeholder get different slugs")


def test_placeholder_alias():
    e = _entry_from({"slug": "lockstone", "title": "Lockstone", "aliases": ["alt", "ALT", "Alt ", "the salt stone", "salt"],
                     "detail": "x"})
    assert e.aliases == ["the salt stone", "salt"], e.aliases
    assert _entry_from({"slug": "x-y", "title": "T", "aliases": ["alt"], "detail": "x"}).aliases == []
    assert _entry_from({"slug": "x-y", "title": "T", "aliases": ["altar"], "detail": "x"}).aliases == ["altar"], \
        "only the exact placeholder goes"
    print("3. the placeholder alias 'alt' is dropped in any case; real aliases are kept in order")


def test_nothing_usable():
    for d in ({"slug": "kebab-id"}, {"slug": "kebab-id", "title": ""}, {"slug": "kebab-id", "title": "  "}, {}):
        assert _entry_from(d) is None, d
    print("4. a placeholder slug with no usable title is refused, not stored under a nonsense key")


for fn in (test_placeholder_slugs, test_two_copies_do_not_collide, test_placeholder_alias, test_nothing_usable):
    fn()
print("\nGENERATOR SLUGS TESTS PASSED")

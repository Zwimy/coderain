"""Merging the duplicate entries a small local model's fold already wrote (coderain/dedupe.py, D-029).

What broke. Before the fold learned to resolve a promotion by name, a story played through a local 4B model
collected `bram-halloran`, `bram-halloran-4` and `bram-halloran-bram-halloran` as separate characters (6 people
became 16-18 sections in a 240-turn invented story), and every sheet is sent to the model again each turn.
This cleans an existing save. It rewrites fold output, and a fold is one-way, so what is pinned here is mostly
what it must NOT do and that it can be undone.

  1. only a whole-name match is a group: "Tamsin Pike" is not "Tamsin Reeve", a bare first name is not a
     name, and a title that is merely listed as another entry's alias is not a match (a dry run on a soak save
     had one character's name in another's alias list; an alias rule would have folded the first into the second)
  2. the entry under its own slug stays, else the oldest; the player, threads and canon events are never grouped
  3. the merged entry: aliases unioned, cleaned and capped, importance the highest, what a fold rewrites whole
     (status) newest-wins, other attrs kept, body paragraphs added without repeats and within the fold's limit
  4. a dry run writes nothing at all, and says what it would do
  5. --apply backs up every registry it changes first; copying the backup back restores the file byte for byte
  6. entries outside the groups are untouched, byte for byte
  7. a second run finds nothing; running on a save with no duplicates writes no backup
  8. the report counts the [[links]] that will dangle, and the command refuses an unknown save
  9. names made of the same words are suggested, never merged on their own
 10. --merge KEEP DROP... merges exactly what the author names, with the same backup, and refuses what it cannot do
"""
import hashlib
import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-dedupe-"))
os.environ["CODERAIN_HOME"] = str(WORK / "home")

from coderain import dedupe                                                  # noqa: E402
from coderain.memory import MAX_ALIASES, Entry, Library                      # noqa: E402
from coderain.summarizer import BODY_LIMIT                                   # noqa: E402

PP = chr(10) * 2                       # a blank line, the paragraph separator
HOME = WORK / "lib"
lib = Library(HOME)
_n = [0]


def make(entries, rel="characters.md", player=None):
    _n[0] += 1
    slug = lib.create_story(f"Dedupe {_n[0]}", "A ferry town.")
    store = lib.store(slug)
    if player:
        store.write("player.md", player)
    for e in entries:
        store.upsert_entry(rel, e)
    return slug, store


def e(slug, title, body="", aliases=(), importance=3, **attrs):
    return Entry(title=title, slug=slug, aliases=list(aliases), importance=importance, attrs=dict(attrs), body=body)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree(store):
    out = {}
    for p in sorted(Path(store.dir).rglob("*")):
        if p.is_file() and dedupe.BACKUP_DIR not in p.parts and ".snapshots" not in p.parts:
            out[p.relative_to(store.dir).as_posix()] = sha(p)
    return out


def test_what_is_a_group():
    """1, 2."""
    _slug, store = make([
        e("bram-halloran-4", "Bram Halloran", "Newest."), e("bram-halloran", "Bram Halloran", "Oldest."),
        e("bram-halloran-bram-halloran", "bram halloran"),
        e("tamsin-reeve", "Tamsin Reeve", aliases=["Tamsin"]), e("tamsin-pike", "Tamsin Pike"),
        e("tamsin", "Tamsin"),                                           # a bare first name, even though it is her alias
        e("ferry", "The Ferry"), e("ferry-2", "Ferry"),                  # 'the' ignored
        e("hob", "Hob Marrow", aliases=["the keeper"]), e("keeper", "The Keeper"),
        e("hob-2", "Hob Marrow"), e("keeper-2", "Keeper"),               # 'keeper' is hob's alias, and still its own name
    ])
    groups = {g.keep: g for g in dedupe.plan_for_store(store)}
    assert set(groups) == {"bram-halloran", "ferry", "hob", "keeper"}, sorted(groups)
    assert groups["bram-halloran"].drop == ("bram-halloran-4", "bram-halloran-bram-halloran"), groups["bram-halloran"]
    assert groups["ferry"].drop == ("ferry-2",)
    assert groups["hob"].drop == ("hob-2",) and groups["keeper"].drop == ("keeper-2",), (groups["hob"], groups["keeper"])
    assert "tamsin" not in {s for g in groups.values() for s in (g.keep, *g.drop)}, "an alias is not a match"
    assert "tamsin-pike" not in {s for g in groups.values() for s in (g.keep, *g.drop)}, "a different whole name"
    # a polluted alias list (the real shape: one character's name written into another's aliases) merges nothing
    _s3, st3 = make([e("bram", "Bram Halloran", aliases=["Hollis Wren"]), e("hollis", "Hollis Wren"),
                     e("hollis-4", "Hollis Wren")])
    g3 = dedupe.plan_for_store(st3)
    assert [(g.keep, g.drop) for g in g3] == [("hollis", ("hollis-4",))], g3
    # the oldest stays when no entry is under its own slug
    _s2, st2 = make([e("odile-3", "Odile Marsh"), e("odile-9", "Odile Marsh")])
    assert [(g.keep, g.drop) for g in dedupe.plan_for_store(st2)] == [("odile-3", ("odile-9",))]
    print("1-2. whole names (case, punctuation and 'the' ignored) group; a different name or an alias does not; "
          "the entry under its own slug, else the oldest, stays")


def test_player_threads_and_events_are_never_grouped():
    """2."""
    _s, store = make([e("you-player", "You"), e("you", "You"), e("eira", "Eira"), e("eira-2", "Eira")],
                     player="## Eira  {#player}\n\nA night courier.\n")
    assert dedupe.plan_for_store(store) == [], "the player's names are skipped"
    _s, st2 = make([e("the-duel", "The Duel", "a"), e("the-duel-2", "The Duel", "b")], rel="canon-events.md")
    _s, st3 = make([e("t1", "Find the ford", "a"), e("t2", "Find the ford", "b")], rel="threads.md")
    assert dedupe.plan_for_store(st2) == [] and dedupe.plan_for_store(st3) == []
    # and the planner itself refuses them, whoever calls it
    assert dedupe.plan_merges({"threads.md": st3.entries("threads.md"), "canon-events.md": st2.entries("canon-events.md")}) == []
    print("2b. the player, canon events and threads are never grouped")


def test_the_merged_entry():
    """3."""
    _s, store = make([
        e("tamsin-reeve", "Tamsin Reeve", PP.join(["The ferrywoman.", "She keeps a lantern."]),
          aliases=["Tamsin", "the ferrywoman", "TAMSIN", "tamsin the ferrywoman tamsin tamsin the ferrywoman"],
          importance=3, status="calm", wants="a quiet crossing"),
        e("tamsin-reeve-4", "Tamsin Reeve", PP.join(["She keeps a lantern.", "She distrusts the customs officer."]),
          aliases=["tamsin", "Tam", "reeve reeve reeve", "the ferrywoman"], importance=5, status="wary", when="night"),
        e("tamsin-reeve-tamsin-reeve", "Tamsin Reeve", "", aliases=[f"nick{n}" for n in range(20)], importance=2)])
    (g,) = dedupe.plan_for_store(store)
    entries = {x.slug: x for x in store.entries("characters.md")}
    m = dedupe.merged_entry(entries[g.keep], [entries[s] for s in g.drop])
    assert (m.slug, m.title, m.importance) == ("tamsin-reeve", "Tamsin Reeve", 5)
    assert m.aliases[:2] == ["Tamsin", "the ferrywoman"] and "Tam" in m.aliases, m.aliases
    assert "tamsin" not in m.aliases and "reeve reeve reeve" not in m.aliases and len(m.aliases) <= MAX_ALIASES, m.aliases
    assert "TAMSIN" not in m.aliases and not any(len(a.split()) > 5 for a in m.aliases), \
        "the kept entry's own repeats and run-ons are cleaned too"
    assert m.attrs["status"] == "wary" and m.attrs["wants"] == "a quiet crossing" and m.attrs["when"] == "night", m.attrs
    assert m.body.split(PP) == ["The ferrywoman.", "She keeps a lantern.", "She distrusts the customs officer."], m.body
    # the fold's own body limit holds even when the others are long (newest first, whole paragraphs only)
    keep = e("k", "Kay", PP.join(["Kept one.", "Kept two."]))
    long_dup = e("k-2", "Kay", PP.join(f"Paragraph {n} " + "x" * 400 for n in range(20)))
    m2 = dedupe.merged_entry(keep, [long_dup])
    assert len(m2.body) <= BODY_LIMIT and m2.body.startswith(PP.join(["Kept one.", "Kept two.", "Paragraph"])), len(m2.body)
    assert all(p.startswith("Kept") or (p.startswith("Paragraph") and p.endswith("x")) for p in m2.body.split(PP)), \
        "a paragraph was cut in the middle"
    print("3. merged: aliases cleaned and capped, highest importance, newest status, no repeated paragraph, within the body limit")


def test_dry_run_apply_backup_and_idempotence():
    """4, 5, 6, 7, 8."""
    _s, store = make([e("a", "Aldo Finch", "Untouched."), e("bram-halloran", "Bram Halloran", "One."),
                      e("bram-halloran-4", "Bram Halloran", "Two."), e("c", "Cora Wick", "Untouched too.")])
    scene = Path(store.dir) / "memory" / "scenes.md"
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_text("Bram [[character:bram-halloran-4]] met [[character:bram-halloran]] and [[character:c]].\n", encoding="utf-8")
    before = tree(store)
    groups = dedupe.plan_for_store(store)
    lines = dedupe.report(store, groups)
    assert any("keeps bram-halloran, absorbs bram-halloran-4" in l for l in lines), lines
    assert any("1 [[links]]" in l for l in lines), lines                                   # only the dropped slug's link
    assert tree(store) == before, "planning and reporting wrote something"
    untouched = {rel: h for rel, h in before.items() if rel != "characters.md"}

    # the command: a dry run writes nothing, --apply merges and backs up, a missing save is refused
    out = io.StringIO()
    with redirect_stdout(out):
        assert dedupe.main(["--home", str(HOME), "--save", Path(store.dir).name]) == 0
    assert tree(store) == before and not (Path(store.dir) / dedupe.BACKUP_DIR).exists()
    assert "Dry run" in out.getvalue()
    assert dedupe.main(["--home", str(HOME), "--save", "no-such-save"]) == 2

    original = (Path(store.dir) / "characters.md").read_bytes()
    out = io.StringIO()
    with redirect_stdout(out):
        assert dedupe.main(["--home", str(HOME), "--save", Path(store.dir).name, "--apply"]) == 0
    assert [x.slug for x in store.entries("characters.md")] == ["a", "bram-halloran", "c"], \
        [x.slug for x in store.entries("characters.md")]
    kept = [x for x in store.entries("characters.md") if x.slug == "bram-halloran"][0]
    assert kept.body.split("\n\n") == ["One.", "Two."], kept.body
    after = tree(store)
    assert {rel: h for rel, h in after.items() if rel != "characters.md"} == untouched, "something outside the registry changed"
    backups = list((Path(store.dir) / dedupe.BACKUP_DIR).iterdir())
    assert len(backups) == 1 and (backups[0] / "characters.md").read_bytes() == original, "the backup is the original, byte for byte"
    # undo is a file copy
    shutil.copy2(backups[0] / "characters.md", Path(store.dir) / "characters.md")
    assert (Path(store.dir) / "characters.md").read_bytes() == original
    # a second run on the merged save finds nothing and writes no backup
    shutil.copy2(Path(store.dir) / "characters.md", WORK / "restored.md")
    dedupe.main(["--home", str(HOME), "--save", Path(store.dir).name, "--apply"])
    n_backups = len(list((Path(store.dir) / dedupe.BACKUP_DIR).iterdir()))
    out = io.StringIO()
    with redirect_stdout(out):
        dedupe.main(["--home", str(HOME), "--save", Path(store.dir).name, "--apply"])
    assert "Nothing to merge" in out.getvalue()
    assert len(list((Path(store.dir) / dedupe.BACKUP_DIR).iterdir())) == n_backups, "a no-op run must not leave a backup"
    print("4-8. dry run writes nothing; --apply backs up first and the backup restores the file exactly; the rest of the "
          "save is untouched; a second run is a no-op; dangling links are counted")


def test_possible_same_character_is_a_suggestion_never_a_merge():
    """9. One woman under three names ("Vesper", "Dame Vesper", "Vesper Ann-Marie") is something only the author can say, so the tool
    lists names that are made of the same words and merges nothing on its own."""
    _s, store = make([e("vesper", "Vesper", "The gatekeeper."), e("dame-vesper", "Dame Vesper", "A teacher of the old school, "
                                                           "known to the whole district."),
                      e("vesper-ann-marie", "Vesper Ann-Marie"), e("tamsin-reeve", "Tamsin Reeve"), e("tamsin-pike", "Tamsin Pike"),
                      e("tamsin", "Tamsin"), e("hob", "Hob Marrow"), e("you-player", "You")],
                     player="## Eira  {#player}" + chr(10) * 2 + "A night courier." + chr(10))
    regs = {"characters.md": store.entries("characters.md")}
    found = {tuple(x.slug for x in es) for _rel, es in dedupe.similar_names(regs, skip_names=["you"])}
    assert ("vesper", "dame-vesper", "vesper-ann-marie") in found or any(set(t) == {"vesper", "dame-vesper", "vesper-ann-marie"} for t in found), found
    assert any(set(t) == {"tamsin", "tamsin-reeve", "tamsin-pike"} for t in found), "a bare first name fits two women: both listed"
    assert not any("hob" in t or "you-player" in t for t in found), "an unrelated name and the player are not suggested"
    assert dedupe.plan_for_store(store) == [], "nothing is merged automatically"
    lines = dedupe.suggestions(store)
    assert any("possibly the same" in l and "--merge dame-vesper" in l for l in lines), lines
    # same whole name is the automatic pass's, not a suggestion
    _s2, st2 = make([e("a", "Odile Marsh"), e("a-2", "Odile Marsh")])
    assert dedupe.suggestions(st2) == [], "a same-name pair is merged by the plan, not suggested"
    # two names that share a word but neither is made of the other's words are two people
    _s3, st3 = make([e("ottoline-pike", "Ottoline Pike"), e("ottoline-wren", "Ottoline Wren")])
    assert dedupe.suggestions(st3) == [], "a shared first name alone is not a suggestion"
    # the player's own name never starts a suggestion
    _s4, st4 = make([e("eira", "Eira"), e("eira-voss", "Eira Voss")], player="## Eira  {#player}" + chr(10) * 2 + "A night courier." + chr(10))
    assert dedupe.suggestions(st4) == [], "the player's name is skipped"
    print("9. names made of the same words are suggested, never merged on their own, and the player and unrelated names are left out")


def test_the_author_can_merge_exactly_what_they_choose():
    """10. --merge KEEP DROP...: the same backup and dry-run rules as the automatic pass, and refusals that write nothing."""
    _s, store = make([e("vesper", "Vesper", "The gatekeeper."), e("dame-vesper", "Dame Vesper", "A teacher.", importance=4),
                      e("vesper-ann-marie", "Vesper Ann-Marie", "Her given name."), e("hob", "Hob Marrow", "A keeper."),
                      e("you-player", "You")], player="## Eira  {#player}" + chr(10) * 2 + "A night courier." + chr(10))
    home, name = ["--home", str(HOME), "--save", Path(store.dir).name], Path(store.dir).name
    Library(HOME).store(name)         # opening a save normalises a custom player.md once (the app's own doing): not the tool's
    before = tree(store)
    for bad in (["vesper", "vesper"], ["vesper"], ["vesper", "nobody"], ["you-player", "vesper"], ["vesper", "hob", "hob"]):
        err = io.StringIO()
        import contextlib
        with contextlib.redirect_stderr(err), redirect_stdout(io.StringIO()):
            assert dedupe.main([*home, "--merge", *bad, "--apply"]) == 2, bad
        assert tree(store) == before and not (Path(store.dir) / dedupe.BACKUP_DIR).exists(), ("a refusal wrote something", bad)
    out = io.StringIO()
    with redirect_stdout(out):
        assert dedupe.main([*home, "--merge", "dame-vesper", "vesper", "vesper-ann-marie"]) == 0
    assert "keeps dame-vesper, absorbs vesper, vesper-ann-marie (your choice)" in out.getvalue() and "Dry run" in out.getvalue(), out.getvalue()
    assert tree(store) == before, "a dry run wrote something"
    original = (Path(store.dir) / "characters.md").read_bytes()
    with redirect_stdout(io.StringIO()):
        assert dedupe.main([*home, "--merge", "dame-vesper", "vesper", "vesper-ann-marie", "--apply"]) == 0
    es = {x.slug: x for x in store.entries("characters.md")}
    assert set(es) == {"dame-vesper", "hob", "you-player"}, set(es)
    assert "Vesper" in es["dame-vesper"].aliases and "Vesper Ann-Marie" in es["dame-vesper"].aliases, es["dame-vesper"].aliases
    assert "The gatekeeper." in es["dame-vesper"].body and es["dame-vesper"].importance == 4
    backup = next((Path(store.dir) / dedupe.BACKUP_DIR).iterdir())
    assert (backup / "characters.md").read_bytes() == original, "the backup is the original, byte for byte"
    # a registry that is not a registry of things is refused, even with slugs that exist in it; threads are never suggested
    _s3, st3 = make([e("find-the-ford", "Find the ford", "a"), e("find-the-ford-2", "Find the ford crossing", "b")], rel="threads.md")
    n3 = Path(st3.dir).name
    Library(HOME).store(n3)
    t_before = tree(st3)
    with contextlib.redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
        assert dedupe.main(["--home", str(HOME), "--save", n3, "--merge", "find-the-ford", "find-the-ford-2",
                            "--registry", "threads.md", "--apply"]) == 2
    assert tree(st3) == t_before, "a refused registry wrote something"
    assert dedupe.similar_names({"threads.md": st3.entries("threads.md")}) == [], "threads are never suggested"
    # the registry option picks the file: a place can be merged in locations.md
    _s4, st4 = make([e("salt-market", "Salt Market", "A market."), e("market", "Market", "Stalls.")], rel="locations.md")
    n4 = Path(st4.dir).name
    with redirect_stdout(io.StringIO()):
        assert dedupe.main(["--home", str(HOME), "--save", n4, "--merge", "salt-market", "market",
                            "--registry", "locations.md", "--apply"]) == 0
    assert [x.slug for x in st4.entries("locations.md")] == ["salt-market"], [x.slug for x in st4.entries("locations.md")]
    print("10. --merge merges exactly the named entries with the same backup; every refusal writes nothing; a dry run shows it")


try:
    for fn in (test_what_is_a_group, test_player_threads_and_events_are_never_grouped, test_the_merged_entry,
               test_dry_run_apply_backup_and_idempotence,
               test_possible_same_character_is_a_suggestion_never_a_merge,
               test_the_author_can_merge_exactly_what_they_choose):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("ALL OK")

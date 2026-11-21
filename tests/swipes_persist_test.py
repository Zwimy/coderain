"""The versions of the last reply survive a restart (D-056 item 18).

What broke. A swipe, or a retry that keeps what it replaces (D-057), leaves the earlier texts of the last reply as versions to go back to. They
lived only in the engine's memory, so a restart, or a settings save (which drops every engine), lost them without a word, and the page said
"Version 1 of 1" over a reply that had had three. They are now also kept in <save>/swipes.json. The file is never invalidated by the seven
things that change a story (an edit, an undo, a branch, a new turn, a retry, ...): it is TRUSTED only while it still describes the transcript,
and a file that does not is ignored, never repaired. Each numbered assertion pins one way that rule could quietly fail:

 1) after two swipes a NEW engine over the same save finds all three versions at the same position, can browse them (the transcript follows)
    and the save payload says "3, position 2"
 2) a settings save (`_engines.clear()`) and a restart are the same thing to the file
 3) the file is ignored, and the reply has no versions, when the last reply was edited, when a new exchange was added, when the swiped
    exchange itself was undone, and when the selected version no longer matches the transcript; undoing a LATER exchange puts the transcript
    back as the file describes it, so the real versions are offered again
 4) a file that is not JSON, the wrong shape, too many versions, a bad position, a version that is not text, or a different turn count is ignored
    and never raises
 5) a reply that did not change keeps its versions through other changes elsewhere (a branch copy of the save carries a file that no longer
    fits and ignores it)
 6) browsing writes the new position; the cap keeps the newest MAX_VARIANTS and the screen and the file agree on it
 7) a failed write is reported in the health log and costs nothing
 8) a story whose tail is the player's own action has no versions to restore
 9) a swipe or a browse on a fresh engine, with no look at the story first, extends the kept versions instead of starting again
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="cr-swipes-")
os.environ["CODERAIN_HOME"] = HOME

import server                                                   # noqa: E402,F401
from fastapi.testclient import TestClient                       # noqa: E402
from srv import core                                            # noqa: E402
from coderain.engine import Engine                              # noqa: E402

c = TestClient(server.app)


def quiet():
    """Keep the extra model passes off. A settings save rebuilds the config from disk, so this runs before every engine is made, not once:
    the first version set it once and the test after the settings save reached for a real model."""
    core._cfg.generation["chapter_outline"] = False
    core._cfg.generation["trinity_brain"] = False


quiet()


class Stub:
    model = "stub-model"

    def __init__(self, *replies):
        self.replies = list(replies)

    def complete(self, messages, **k):
        return ""

    def stream(self, messages, **k):
        yield self.replies.pop(0) if self.replies else "A default new reply."


def story(title, texts=("Version one of the door.", "Version two of the door.", "Version three of the door.")):
    quiet()
    slug = c.post("/api/saves", json={"title": title, "mode": "simple", "premise": "A courier crosses a frozen kingdom."}).json()["slug"]
    eng = server._engine(slug)
    eng.llm = Stub(texts[0])
    "".join(eng.turn("I open the door."))
    for t in texts[1:]:
        eng.llm = Stub(t)
        "".join(eng.swipe_exchange())
    return slug, eng


def fresh(slug):
    quiet()
    core._engines.clear()
    eng = server._engine(slug)
    eng.llm = Stub()
    return eng


def payload(slug):
    return c.get(f"/api/saves/{slug}").json()["swipes"]


def file_of(eng):
    return Path(eng.store.dir) / Engine.SWIPES_FILE


def test_survives_a_restart():
    slug, eng = story("Persist one")
    assert eng._swipes["idx"] == 2 and len(eng._swipes["variants"]) == 3
    assert file_of(eng).exists(), "nothing was kept on disk"
    eng2 = fresh(slug)
    assert eng2._swipes is None, "a new engine starts with nothing in memory"
    assert payload(slug) == {"count": 3, "idx": 2}, payload(slug)
    back = eng2.swipe_browse(-1)
    assert back["text"] == "Version two of the door." and back["count"] == 3 and back["idx"] == 1, back
    assert eng2.store.turns()[-1]["text"] == "Version two of the door."
    eng3 = fresh(slug)
    assert payload(slug) == {"count": 3, "idx": 1}, "browsing did not write the new position"
    first = eng3.swipe_browse(-1)
    assert first["text"] == "Version one of the door." and eng3.store.turns()[-1]["text"] == "Version one of the door."
    print("1. a new engine finds the three versions at the same position, can browse them, and the payload says so")


def test_swipe_after_a_restart_without_a_look():
    """The page asks for the story before it swipes, but the engine must not depend on that: a swipe on a fresh engine extends the versions
    on disk and does not start again from the one text it can see."""
    slug, eng = story("Persist again")
    eng2 = fresh(slug)
    eng2.llm = Stub("Version four of the door.")
    "".join(eng2.swipe_exchange())
    assert payload(slug) == {"count": 4, "idx": 3}, f"a swipe after a restart began again from one version: {payload(slug)}"
    eng3 = fresh(slug)
    got = eng3.swipe_browse(-3)
    assert got["count"] == 4 and got["idx"] == 0 and got["text"] == "Version one of the door.", got
    print("9. a swipe or a browse on a fresh engine, with no look at the story first, extends the versions that were kept")


def test_settings_save_is_a_restart():
    slug, eng = story("Persist two")
    core._reload_config()                                     # what a settings save does: every engine is rebuilt
    quiet()
    assert payload(slug) == {"count": 3, "idx": 2}, payload(slug)
    print("2. a settings save drops the engines and the versions are still there")


def test_stale_file_is_ignored():
    slug, eng = story("Persist stale")
    # an edit of the last reply
    store = fresh(slug).store
    store.update_turn(len(store.turns()) - 1, "A hand-edited reply.")
    assert payload(slug) is None, payload(slug)
    # a new exchange
    slug, eng = story("Persist stale 2")
    eng.llm = Stub("The next reply.")
    "".join(eng.turn("I walk on."))
    fresh(slug)
    assert payload(slug) is None, "versions of an earlier reply were shown for a new one"
    # an undo. The file is trusted while it describes the transcript, so the two undos differ, and both are right:
    #   - undoing a LATER exchange puts the transcript back exactly as the file describes it (same turns, same tail text), so the real
    #     versions of that reply are offered again. The live engine used to forget them at the new turn; nothing about them was wrong.
    #   - undoing the swiped exchange itself leaves a transcript whose tail is no reply the file knows, so there are no versions.
    slug, eng = story("Persist undo later")
    eng.llm = Stub("The second exchange.")
    "".join(eng.turn("I walk on."))
    fresh(slug)
    assert payload(slug) is None, "versions of an earlier reply were shown with a later exchange on top"
    assert server._engine(slug).undo_last() is True
    fresh(slug)
    assert payload(slug) == {"count": 3, "idx": 2}, "undoing the later exchange did not bring the versions of the reply it exposed back"
    slug, eng = story("Persist undo own")
    assert eng.undo_last() is True
    fresh(slug)
    assert payload(slug) is None, "versions of an undone reply were shown for whatever is now at the end of the story"
    # the selected version no longer matches the transcript (file written for another text of the same length)
    slug, eng = story("Persist stale 4")
    data = json.loads(file_of(eng).read_text(encoding="utf-8"))
    data["idx"] = 0                                         # claims version one is selected while the transcript holds version three
    file_of(eng).write_text(json.dumps(data), encoding="utf-8")
    fresh(slug)
    assert payload(slug) is None, "a file that disagrees with the transcript was believed"
    print("3. an edited reply, a new exchange, an undo and a selection that no longer matches the transcript leave no versions, and undoing a later exchange brings the real ones back")


def test_bad_files_never_raise():
    slug, eng = story("Persist bad")
    good = json.loads(file_of(eng).read_text(encoding="utf-8"))
    bad = ["", "not json at all", "[]", "{}", "null", '{"variants": "x"}',
           json.dumps({**good, "variants": []}), json.dumps({**good, "variants": good["variants"] * 5}),
           json.dumps({**good, "variants": [1, 2, 3]}), json.dumps({**good, "idx": 7}), json.dumps({**good, "idx": -1}),
           # these two would pass the text match on their own, so only the shape guards stop them: True indexes variants[1], and a list
           # that holds the right text at the right place but numbers elsewhere is not something this wrote
           json.dumps({**good, "variants": ["Another version.", good["variants"][2]], "idx": True}),
           json.dumps({**good, "variants": [1, 2, good["variants"][2]]}),
           json.dumps({**good, "idx": "2"}), json.dumps({**good, "turns": 99}),
           json.dumps({**good, "tail": "deadbeef"}), json.dumps({k: v for k, v in good.items() if k != "tail"}), "�\x00"]
    for text in bad:
        file_of(eng).write_text(text, encoding="utf-8")
        fresh(slug)
        got = payload(slug)
        assert got is None, (text[:40], got)
    file_of(eng).write_text(json.dumps(good), encoding="utf-8")
    fresh(slug)
    assert payload(slug) == {"count": 3, "idx": 2}, "the good file stopped working after the bad ones"
    print("4. a file of any wrong shape is ignored and never raises")


def test_branch_copy_ignores_it():
    slug, eng = story("Persist branch")
    out = c.post(f"/api/saves/{slug}/branch", json={"turn": 1}).json()
    child = out["slug"]
    fresh(child)
    got = c.get(f"/api/saves/{child}").json()
    assert got["swipes"] is None, got["swipes"]
    fresh(slug)
    assert payload(slug) == {"count": 3, "idx": 2}, "the original lost its versions when it was branched"
    print("5. a branch copy ignores a file that no longer fits, and the original keeps its versions")


def test_cap():
    slug, eng = story("Persist cap")
    for i in range(Engine.MAX_VARIANTS + 3):
        eng.llm = Stub(f"Another version number {i} of the door.")
        "".join(eng.swipe_exchange())
    assert len(eng._swipes["variants"]) == Engine.MAX_VARIANTS and eng._swipes["idx"] == Engine.MAX_VARIANTS - 1
    assert eng._swipes["variants"][-1] == f"Another version number {Engine.MAX_VARIANTS + 2} of the door."
    on_disk = json.loads(file_of(eng).read_text(encoding="utf-8"))
    assert on_disk["variants"] == eng._swipes["variants"] and on_disk["idx"] == eng._swipes["idx"], "the file and the screen disagree on the cap"
    fresh(slug)
    assert payload(slug) == {"count": Engine.MAX_VARIANTS, "idx": Engine.MAX_VARIANTS - 1}
    print("6. the oldest versions go first at the cap, and the file and the screen agree")


def test_write_failure_costs_nothing():
    slug, eng = story("Persist write")
    real = eng.store.write

    def boom(rel, text):
        if rel == Engine.SWIPES_FILE:
            raise OSError("disk full")
        return real(rel, text)
    eng.store.write = boom
    eng.llm = Stub("A reply written while the disk is full.")
    out = "".join(eng.swipe_exchange())
    assert "disk is full" in out and eng.store.turns()[-1]["text"] == "A reply written while the disk is full."
    assert [h for h in eng.store.health(20) if h["stage"] == "swipes"], "the failed write was not reported"
    eng.store.write = real
    print("7. a failed write is reported and the swipe still works")


def test_player_tail():
    slug = c.post("/api/saves", json={"title": "Persist tail", "mode": "simple", "premise": "x"}).json()["slug"]
    eng = server._engine(slug)
    eng.store.append_turn("player", "I wait.")
    (Path(eng.store.dir) / Engine.SWIPES_FILE).write_text(json.dumps(
        {"turns": 1, "tail": Engine._text_key("I wait."), "idx": 0, "variants": ["I wait."]}), encoding="utf-8")
    fresh(slug)
    assert payload(slug) is None, "versions were restored for a story that ends on the player's own action"
    print("8. a story that ends on the player's action has no versions to restore")


test_survives_a_restart()
test_swipe_after_a_restart_without_a_look()
test_settings_save_is_a_restart()
test_stale_file_is_ignored()
test_bad_files_never_raise()
test_branch_copy_ignores_it()
test_cap()
test_write_failure_costs_nothing()
test_player_tail()
print("\nSWIPES PERSIST TESTS PASSED")

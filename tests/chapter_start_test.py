"""Chapter 1 is planned when a story starts, not ten turns in (D-051).

What was wrong. The outline was seeded by the first scene fold, about twelve turns into a story. The opening scene
and the first stretch of play were written with no chapter goal at all, and the writer drifted wherever it liked
before the steering began.

The start now plans ONE chapter (one model call, the same payload and retries as every other chapter) before the
opening is written. The first fold finds that lone chapter and tops the plan up to the horizon, so the outline ends
up the same as before, only earlier.

 1) ensure_first writes exactly one chapter with one call: active, marked as the start chapter, three or more
    sentences; a second call does nothing and costs nothing
 2) nothing happens when the outline is off, when there is no premise, or when a chapter already exists
 3) a failed or garbage reply leaves the story without a chapter, with one health row, and the next fold still plans
 4) ensure_seeded tops a lone start chapter up to the horizon, keeps chapter 1 as it was, and forgets the marker;
    a hand-edited outline (one chapter or more) is never topped up behind the author's back
 5) the engine plans chapter 1 before the opening: one planning call, the progress note, and the writer's messages
    carry the chapter directive with that goal
 6) the engine plans only a young story: an old transcript without an outline is left to the fold, the outline
    being off costs no call, and a second turn does not plan again
 7) a planning failure inside the engine never costs the turn: the prose is stored and the health row says why
 8) the first fold of a story that started with the lone chapter tops it up, and says "Planning chapters"
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-chstart-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                    # noqa: E402
from coderain.engine import Engine                         # noqa: E402
from coderain.memory import Entry, Library                # noqa: E402
from coderain.planner import START_ORIGIN, ChapterPlanner  # noqa: E402

lib = Library(WORK / "lib")
_n = [0]
PREMISE = "A lamplighter learns that the harbour lamps are being lit by someone else."
ARCHITECT = "story ARCHITECT"

GOALS = [
    "Find out who has been lighting the harbour lamps before dawn. The lamplighter keeps watch from the quay "
    "while the harbour master insists nothing is wrong. By the end a stranger's footprints lead to the old "
    "signal tower.",
    "Climb the signal tower and learn what the stranger wanted from it. The tower door is locked and the "
    "keeper is afraid of something. By the end the lamplighter holds a coded ledger nobody can read.",
    "Take the ledger to the cartographer and learn what the code hides. The cartographer wants payment and "
    "the harbour master wants the ledger back. By the end one name in it is plain.",
    "Confront the person named in the ledger on the night of the festival. Every lamp in the harbour is "
    "lit and the crowd is thick. By the end the lamplighter must choose who gets the truth.",
    "Set the harbour lamps right and decide what the town is told. The lamplighter is tired and the "
    "stranger is gone. By the end the harbour has a new lamplighter.",
]


class Stub:
    """Planning calls (the ARCHITECT instruction) get the next chapter; fold calls get a fold; the writer streams."""
    gen = {}
    model = "stub-model"

    def __init__(self, bad=False, fold_goal_met=False):
        self.bad, self.fold_goal_met = bad, fold_goal_met
        self.plan_calls, self.plan_payloads, self.other_calls = 0, [], 0
        self.writer_msgs = []

    def complete(self, messages, **k):
        if ARCHITECT in messages[0]["content"]:
            self.plan_calls += 1
            self.plan_payloads.append(messages[-1]["content"])
            if self.bad:
                return "I would rather not."
            i = min(self.plan_calls - 1, len(GOALS) - 1)
            return json.dumps({"title": f"Chapter {i + 1} title {i}", "goal": GOALS[i]})
        self.other_calls += 1
        return json.dumps({"scene_summary": "The lamplighter kept watch.", "timeline": "watched",
                           "promotions": [], "chapter_goal_met": self.fold_goal_met})

    def stream(self, messages, **k):
        self.writer_msgs.append(messages)
        yield "The lamps along the quay are already burning."


def make(outline=True, horizon=3, premise=PREMISE, bad=False, turns=0, engine=False):
    _n[0] += 1
    slug = lib.create_story(f"Chapter start {_n[0]}", premise)
    store = lib.store(slug)
    for k in range(turns):
        store.append_turn("player" if k % 2 == 0 else "narrator", "They walk on.")
    cfg = load_config()
    cfg.generation["chapter_outline"] = outline
    cfg.generation["chapter_horizon"] = horizon
    cfg.generation["trinity_brain"] = False
    stub = Stub(bad=bad)
    if engine:
        eng = Engine(cfg, store)
        eng.llm = stub
        return eng, store, stub
    return ChapterPlanner(cfg, store, stub), store, stub


def health(store):
    return [h for h in store.health(50) if h["stage"] == "chapter-plan"]


def test_ensure_first():
    p, store, stub = make()
    assert p.needs_start() and p.needs_seed()
    ev = p.ensure_first()
    rows = p.chapters()
    assert stub.plan_calls == 1, stub.plan_calls
    assert len(rows) == 1 and ev == [f"chapter planned: {rows[0].title}"], (rows, ev)
    c = rows[0]
    assert c.attrs.get("status") == "active" and c.attrs.get("origin") == START_ORIGIN, c.attrs
    assert c.slug == "ch-1", f"chapters are numbered from ch-1, got {c.slug}"
    assert c.body.count(".") >= 3, c.body
    assert not p.needs_start(), "the story still wants a first chapter"
    assert p.ensure_first() == [] and stub.plan_calls == 1, "a second call must not plan again"
    assert "1. <<< WRITE THIS ONE" in stub.plan_payloads[0] and "PREMISE:" in stub.plan_payloads[0]
    print("1. one call writes one active chapter marked as the start chapter; a second call is free")


def test_nothing_to_do():
    for kw, label in (({"outline": False}, "outline off"), ({"premise": "x"}, "no premise")):
        p, store, stub = make(**kw)
        assert not p.needs_start() and not p.needs_seed(), label
        assert p.ensure_first() == [] and stub.plan_calls == 0 and p.chapters() == [], label
    p, store, stub = make()
    p.replace_all([{"title": "Mine", "goal": "Do the thing.", "status": "active"}])
    assert not p.needs_start() and p.ensure_first() == [] and stub.plan_calls == 0, "planned over an existing chapter"
    assert [c.title for c in p.chapters()] == ["Mine"]
    print("2. nothing is planned with the outline off, with no premise, or over an existing chapter")


def test_failure():
    p, store, stub = make(bad=True)
    assert p.ensure_first() == [] and p.chapters() == [], p.chapters()
    rows = health(store)
    assert len(rows) == 1 and "first chapter" in rows[0]["reason"], rows
    assert p.needs_start() and p.needs_seed(), "a failed start must leave the fold to plan"
    stub.bad = False
    assert p.ensure_seeded() and len(p.chapters()) == 3, p.chapters()
    print("3. a bad reply leaves no chapter and one health row; the fold still plans the outline")


def test_top_up():
    p, store, stub = make(horizon=3)
    p.ensure_first()
    first = p.chapters()[0]
    keep = (first.title, first.body, first.slug)
    before = stub.plan_calls
    assert p.needs_seed()
    ev = p.ensure_seeded()
    rows = p.chapters()
    assert len(rows) == 3 and stub.plan_calls - before == 2, (len(rows), stub.plan_calls - before)
    assert (rows[0].title, rows[0].body, rows[0].slug) == keep, "chapter 1 was changed by the top-up"
    assert [c.slug for c in rows] == ["ch-1", "ch-2", "ch-3"], [c.slug for c in rows]
    assert [c.attrs.get("status") for c in rows] == ["active", "planned", "planned"], rows
    assert all("origin" not in c.attrs for c in rows), "the start marker was not forgotten"
    assert any(e.startswith("outline: planned 2 chapter") for e in ev), ev
    assert not p.needs_seed() and p.ensure_seeded() == [], "a full outline must not be topped up again"
    # a hand edit: one chapter written through the panel carries no marker, so it is left alone
    p2, store2, stub2 = make(horizon=3)
    p2.ensure_first()
    p2.replace_all([{"title": c.title, "goal": c.body, "status": "active"} for c in p2.chapters()])
    assert not p2.needs_seed() and p2.ensure_seeded() == [] and len(p2.chapters()) == 1
    assert stub2.plan_calls == 1, "a hand-edited outline was topped up"
    # a chapter the author adds by hand beside the start chapter (the file edited directly, the marker still on
    # chapter 1) is authored work too: two chapters are never topped up as if they were a lone start
    p3, store3, stub3 = make(horizon=4)
    p3.ensure_first()
    store3.upsert_entry("memory/outline.md", Entry(title="My own chapter", slug="ch-2", importance=3,
                                                   attrs={"status": "planned"}, body="Something I wrote."))
    assert len(p3.chapters()) == 2 and p3.chapters()[0].attrs.get("origin") == START_ORIGIN
    assert not p3.needs_seed() and p3.ensure_seeded() == [] and stub3.plan_calls == 1, "two chapters were topped up"
    print("4. a lone start chapter is topped up to the horizon and unchanged; a hand-edited outline is left alone")


def play(eng, notes=None, action="I check the nearest lamp."):
    return "".join(eng.turn(action, on_stage=(notes.append if notes is not None else None)))


def opening(eng, notes=None):
    return "".join(eng.opening(on_stage=(notes.append if notes is not None else None)))


def directive(msgs):
    return [m["content"] for m in msgs if m["role"] == "system" and m["content"].startswith("# THIS CHAPTER")]


def test_engine_opening():
    eng, store, stub = make(engine=True)
    notes = []
    opening(eng, notes)
    assert stub.plan_calls == 1, stub.plan_calls
    assert "Planning chapter 1" in notes, notes
    chapters = eng.planner.chapters()
    assert len(chapters) == 1 and chapters[0].attrs.get("origin") == START_ORIGIN, chapters
    sent = directive(stub.writer_msgs[0])
    assert len(sent) == 1 and "signal tower" in sent[0], sent
    assert sent == [m["content"] for m in stub.writer_msgs[0] if m["role"] == "system"][-1:], \
        "the chapter directive is no longer the last thing the writer reads"
    print("5. the opening is written after chapter 1 is planned: one call, a progress note, the directive is last")


def test_engine_young_and_old():
    eng, store, stub = make(engine=True)
    opening(eng)
    play(eng)
    play(eng, action="I climb the ladder.")
    assert stub.plan_calls == 1, f"a later turn planned again: {stub.plan_calls}"
    # an old story that never had an outline is left to the fold
    old, store_o, stub_o = make(engine=True, turns=Engine.START_PLAN_TURNS + 2)
    play(old)
    assert stub_o.plan_calls == 0 and old.planner.chapters() == [], "an old story was planned from its first turn"
    assert old.planner.needs_seed(), "the fold must still be able to plan it"
    # a story that is exactly at the limit still counts as young
    edge, store_e, stub_e = make(engine=True, turns=Engine.START_PLAN_TURNS - 1)
    play(edge)
    assert stub_e.plan_calls == 1, "a story at the youth limit was not planned"
    off, store_f, stub_f = make(engine=True, outline=False)
    notes_off = []
    opening(off, notes_off)
    assert stub_f.plan_calls == 0 and not directive(stub_f.writer_msgs[0]), "an outline that is off planned anyway"
    assert "Planning chapter 1" not in notes_off, "the reader was told about a plan that was never made"
    # nor is it announced once the chapter exists: the note belongs to the turn that really plans
    notes_later = []
    play(eng, notes_later, action="I wait.")
    assert "Planning chapter 1" not in notes_later, notes_later
    print("6. a young story is planned once; an old one is left to the fold; an outline that is off costs nothing")


def test_engine_failure():
    eng, store, stub = make(engine=True, bad=True)
    text = opening(eng)
    assert text.strip() and store.turns()[-1]["role"] == "narrator", "the turn died with the plan"
    assert eng.planner.chapters() == [] and not directive(stub.writer_msgs[0])
    assert len(health(store)) == 1, health(store)
    # an exception raised by the planner itself is contained too
    eng2, store2, stub2 = make(engine=True)

    def boom():
        raise RuntimeError("planner exploded")
    eng2.planner.ensure_first = boom
    assert opening(eng2).strip(), "an exception in the planner killed the opening"
    rows = health(store2)
    assert len(rows) == 1 and "planner exploded" in rows[0]["reason"], rows
    print("7. a planning failure never costs the turn: the prose is stored and one health row says why")


def test_first_fold():
    eng, store, stub = make(engine=True, horizon=3)
    opening(eng)
    n = eng.summarizer.medium_after + 2
    for k in range(n):
        store.append_turn("player" if k % 2 == 0 else "narrator", "They walk on.")
    notes = []
    eng.summarizer.maybe_fold(on_stage=notes.append)
    rows = eng.planner.chapters()
    assert len(rows) >= 3, [c.title for c in rows]
    assert "Planning chapters" in notes, notes
    assert rows[0].title == "Chapter 1 title 0", "the start chapter was replaced by the fold"
    assert all("origin" not in c.attrs for c in rows)
    # a fold of a story whose outline is already full does not announce planning
    notes2 = []
    for k in range(eng.summarizer.medium_after + 2):
        store.append_turn("player" if k % 2 == 0 else "narrator", "They walk on.")
    eng.summarizer.maybe_fold(on_stage=notes2.append)
    assert "Planning chapters" not in notes2, notes2
    print("8. the first fold tops the lone chapter up (announced once) and leaves chapter 1 as it was")


for fn in (test_ensure_first, test_nothing_to_do, test_failure, test_top_up, test_engine_opening,
           test_engine_young_and_old, test_engine_failure, test_first_fold):
    fn()
print("\nCHAPTER START TESTS PASSED")

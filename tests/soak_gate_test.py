"""The real-save gate replays someone's actual story through a model, so its
guarantees matter more than its numbers.

 1) a model that is not on this machine is refused, before the save is read: a
    hosted client, a remote Ollama host, and any stub that does not say it is local
 2) every character sheet becomes one scenario entity, repeating it adds nothing,
    and a name the ledger cannot hold is reported instead of crashing the run
 3) only narrator turns are replayed, and a turn naming nobody the canon knows is
    not sent to the model at all
 4) the run resumes: a second pass sends nothing, a torn last line is tolerated,
    and start and end bound what is read
 5) scoring uses Phase 0's vocabulary on what the Writer is shown: a fact held, a
    fact never captured (LOST), a wrong value held (DRIFTED), both present
    (CONFLICT), no such entity, and a changed identity is held back and counted
 6) the report carries values and counts and NEVER narration: no sentence of the
    story, and no quoted evidence span, reaches report.json or report.md
 7) player.md seeds the protagonist's looks at scenario authority
 8) printing the report cannot fail the run: a finished gate once exited 1 on its
    last print because a name held a non-breaking hyphen and the console was cp1252
"""
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-gate-"))

from canon import Store                                                  # noqa: E402
from canon.scribe import OllamaChat, OpenAIChat, Scribe                  # noqa: E402
from soak.canon_gate import (NotLocal, replay, require_local, run_gate,  # noqa: E402
                             seed_entities)
from soak.facts import CONFLICT, DRIFTED, HELD, LOST, NO_ENTITY, Fact    # noqa: E402

_n = [0]


def _dir():
    _n[0] += 1
    return WORK / f"d{_n[0]}"


@dataclass
class Entry:
    title: str
    slug: str
    aliases: list = field(default_factory=list)


ENTRIES = [Entry("Hester", "hester"), Entry("Dunstan", "dunstan"), Entry("Brannock", "brannock"),
           Entry("Corin", "corin")]

S1 = "Hester stepped in, her waist-length raven hair damp. Dunstan's scarred face was grim."
S3 = "Hester shook out her platinum hair."
S4 = "Brannock adjusted his coat by the fire."
S5 = "Corin's blonde hair fell across his eyes."
# A stale MARK that carries the word "platinum", so the fixture can score truth and stale
# both present. It was "a platinum streak", which is a streak of hair and not a mark; the
# marks rule (D-026) rightly refuses it, so the old stub only passed while marks went unchecked.
S6 = "Dunstan had a platinum tattoo at his temple."
EMPTY = "Nothing moved in the empty street."
TURNS = [
    {"role": "player", "text": "I enter."},
    {"role": "narrator", "text": S1},
    {"role": "player", "text": "I wait."},
    {"role": "narrator", "text": EMPTY},
    {"role": "narrator", "text": S3},
    {"role": "narrator", "text": S4},
    {"role": "narrator", "text": S5},
    {"role": "narrator", "text": S6},
]
NARRATOR = [i for i, t in enumerate(TURNS, 1) if t["role"] == "narrator"]


class FakeSave:
    def __init__(self, turns=TURNS, entries=ENTRIES):
        self._turns, self._entries, self.reads = turns, entries, 0

    def turns(self):
        self.reads += 1
        return list(self._turns)

    def entries(self, registry):
        return list(self._entries)

    def read(self, rel):                       # the real store's file reader; player.md is empty here
        return ""


def claim(entity, slot, op, value, evidence):
    return dict(entity=entity, slot=slot, op=op, value=value, evidence=evidence,
                confidence="high")


SCRIPT = [
    ("raven hair", [claim("Hester", "identity.hair", "set", "raven", "her waist-length raven hair"),
                    claim("Dunstan", "identity.marks", "add", "scarred face", "Dunstan's scarred face")]),
    ("platinum hair", [claim("Hester", "identity.hair", "set", "platinum", "her platinum hair")]),
    ("blonde hair", [claim("Corin", "identity.hair", "set", "blonde", "Corin's blonde hair")]),
    ("platinum tattoo", [claim("Dunstan", "identity.marks", "add", "platinum tattoo",
                               "a platinum tattoo at his temple")]),
]


class Stub:
    stays_local = True

    def __init__(self):
        self.calls = []

    def complete(self, system, user, schema_=None):
        self.calls.append(user)
        for needle, claims in SCRIPT:
            if needle in user:
                return json.dumps({"claims": claims})
        return json.dumps({"claims": []})


FIXTURE = [
    Fact("hester-hair", "hester", truth=(r"\braven\b",), stale=(r"\bplatinum\b",),
         slot="identity.hair", expect=DRIFTED),
    Fact("dunstan-scar", "dunstan", truth=(r"\bscar",), slot="identity.marks", expect=LOST),
    Fact("brannock-brooch", "brannock", truth=(r"brooch",), slot="wardrobe.accessory",
         expect=HELD),
    Fact("corin-hair", "corin", truth=(r"\braven\b",), stale=(r"\bblonde\b",),
         slot="identity.hair", expect=HELD),
    Fact("dunstan-both", "dunstan", truth=(r"\bscar",), stale=(r"\bplatinum\b",),
         slot="identity.marks", expect=LOST),
    Fact("ghost", "ghost", truth=(r"anything",), expect=LOST),
]


def test_only_a_local_model_is_accepted():
    save, calls = FakeSave(), []
    assert require_local(Stub()) is None
    require_local(OllamaChat("m"))
    require_local(OllamaChat("m", host="http://127.0.0.1:11434"))
    for bad in (OpenAIChat("m", key_env="CR_NONE"),
                OllamaChat("m", host="http://10.0.0.5:11434"),
                OllamaChat("m", host="https://example.com"),
                OllamaChat("m", host="http://localhost.evil.example:11434"),
                object()):
        try:
            require_local(bad)
            raise AssertionError(f"{bad!r} was accepted as local")
        except NotLocal:
            pass

    class Unmarked(Stub):
        stays_local = False
    try:
        run_gate(save, FIXTURE, Scribe(Unmarked()), _dir())
        raise AssertionError("an unmarked model ran the gate")
    except NotLocal:
        pass
    assert save.reads == 0, "the save was read before the model was refused"
    print("1. a hosted client, a remote host and an unmarked stub are refused, and the "
          "save is not read first")


def test_seeding():
    store = Store(_dir())
    r = seed_entities(store, ENTRIES + [Entry("X" * 130, "toolong"),
                                        Entry('Odile Marsh (the Courier)', "odile",
                                              ["The Courier", "Odile"])])
    assert r["made"] == 5 and [s["entity"] for s in r["skipped"]] == ["toolong"], r
    assert set(store.canon.entities) == {"hester", "dunstan", "brannock", "corin", "odile"}
    odile = store.canon.entities["odile"]
    assert odile["name"] == "Odile Marsh" and "The Courier" in odile["aliases"]
    assert seed_entities(store, ENTRIES)["made"] == 0 and len(store.ledger) == 5
    print("2. one entity per sheet, repeating adds nothing, an unusable name is reported")


def test_replay_and_resume():
    out = _dir()
    out.mkdir()
    store = Store(out / "canon")
    seed_entities(store, ENTRIES)
    stub = Stub()
    rows = replay(FakeSave(), store, Scribe(stub), out, log=lambda *_: None)
    assert sorted(rows) == NARRATOR, "a player turn was replayed"
    assert [i for i, r in rows.items() if r["skipped"]] == [4], rows
    assert len(stub.calls) == len(NARRATOR) - 1, "a turn naming nobody was sent to the model"
    assert all("empty street" not in c for c in stub.calls)

    again = Stub()
    replay(FakeSave(), store, Scribe(again), out, log=lambda *_: None)
    assert again.calls == [], "a finished run sent something on resume"

    # an interrupted run: the last progress line is torn, and turns before it are kept
    lines = (out / "progress.jsonl").read_text().splitlines()
    (out / "progress.jsonl").write_text("\n".join(lines[:2]) + '\n{"turn": 7, "skip')
    resumed = Stub()
    rows = replay(FakeSave(), store, Scribe(resumed), out, log=lambda *_: None)
    assert len(resumed.calls) >= 1 and sorted(rows) == NARRATOR[:2] + sorted(rows)[2:]

    # start and end bound what is read
    out2 = _dir()
    out2.mkdir()
    s2 = Store(out2 / "canon")
    seed_entities(s2, ENTRIES)
    bounded = Stub()
    rows = replay(FakeSave(), s2, Scribe(bounded), out2, start=2, end=2, log=lambda *_: None)
    assert sorted(rows) == [2] and len(bounded.calls) == 1
    print("3. only narrator turns are replayed; a turn naming nobody is not sent; "
          "4. a resumed run sends nothing twice and survives a torn line")


def test_scoring_and_the_report():
    out = _dir()
    report = run_gate(FakeSave(), FIXTURE, Scribe(Stub()), out, log=lambda *_: None)
    by = {r["id"]: r for r in report["facts"]}
    assert by["hester-hair"]["canon"] == HELD, "first narration should hold against platinum"
    assert by["hester-hair"]["engine"] == DRIFTED
    assert by["hester-hair"]["conflict_count"] == 1, "the change was not held back and counted"
    assert by["hester-hair"]["conflicts"][0]["proposed"] == "platinum"
    assert by["dunstan-scar"]["canon"] == HELD and by["dunstan-scar"]["on_sheet"]
    assert by["brannock-brooch"]["canon"] == LOST and by["brannock-brooch"]["outside_scribe_slots"]
    assert by["corin-hair"]["canon"] == DRIFTED, "a wrong value held should be DRIFTED"
    assert by["dunstan-both"]["canon"] == CONFLICT, "truth and stale both present"
    assert by["ghost"]["canon"] == NO_ENTITY
    table = {r["entity"]: r for r in report["identity_table"]}
    assert table["hester"]["fields"]["hair"][:1] == ["raven"], "the held value, not the proposal"
    assert table["dunstan"]["marks"] == ["scarred face", "platinum tattoo"], table["dunstan"]
    assert table["corin"]["fields"]["hair"] == ["blonde", 7, 1] and "brannock" not in table
    assert report["conflicts_by_slot"] == {"hair": 1}, report["conflicts_by_slot"]
    t = report["totals"]
    assert t["narrator_turns"] == len(NARRATOR) and t["skipped_nobody_named"] == 1
    assert t["conflicts_recorded"] == 1 and t["entities_with_identity"] == 3

    # the report holds values and counts, never the story
    for name in ("report.json", "report.md"):
        text = (out / name).read_text(encoding="utf-8")
        for sentence in (S1, S3, S4, S5, S6, EMPTY, "waist-length raven hair damp",
                         "Dunstan's scarred face", "stepped in"):
            assert sentence not in text, f"narration reached {name}: {sentence!r}"
        assert '"span"' not in text and "evidence" not in text
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "| hester-hair | DRIFTED | HELD |" in md, md
    assert "—" not in md and "–" not in md
    # the same facts, scored on a second pass, give the same answer
    again = run_gate(FakeSave(), FIXTURE, Scribe(Stub()), out, log=lambda *_: None)
    assert [r["canon"] for r in again["facts"]] == [r["canon"] for r in report["facts"]]
    print("5. HELD, LOST, DRIFTED, CONFLICT and NO_ENTITY are told apart and a changed "
          "identity is counted; 6. no narration reaches the report")


class PlayerSave(FakeSave):
    def read(self, rel):
        return "# Player character\n\nName: Finn\nInfo: black hair, green eyes.\n" if rel == "player.md" else ""


def test_the_player_file_seeds_the_protagonist():
    out = _dir()
    report = run_gate(PlayerSave(entries=ENTRIES + [Entry("Finn", "finn")]), FIXTURE, Scribe(Stub()), out,
                      log=lambda *_: None)
    assert report["player"] == "finn"
    assert report["seeded_player"] == [["identity.hair", "black"], ["identity.eyes", "green"]]
    table = {r["entity"]: r for r in report["identity_table"]}
    assert table["finn"]["fields"]["hair"][:1] == ["black"] and table["finn"]["fields"]["eyes"][:1] == ["green"]
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Player: finn. Seeded from player.md at scenario authority: ['hair black', 'eyes green']" in md, md
    out2 = _dir()
    none = run_gate(FakeSave(), FIXTURE, Scribe(Stub()), out2, log=lambda *_: None)
    assert none["player"] is None and none["seeded_player"] == []
    assert "Player: not known." in (out2 / "report.md").read_text(encoding="utf-8")
    print("7. player.md seeds the protagonist's looks at scenario authority, and the report says so; "
          "no file, nothing seeded")


def test_printing_the_report_cannot_fail_the_run():
    import io
    from soak.__main__ import _tolerant_output
    name = "The 10‑Second Finisher"             # a non-breaking hyphen, as in a real cast
    saved = sys.stdout
    try:
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        try:
            print(name)
            sys.stdout.flush()
            raised = False
        except UnicodeEncodeError:
            raised = True
        assert raised, "the premise: a cp1252 console cannot print this character"
        _tolerant_output()
        print(name)                                  # must not raise now
        sys.stdout.flush()
        out = sys.stdout.buffer.getvalue().decode("cp1252")
        assert "Second Finisher" in out and "?" in out, out
        sys.stdout = io.StringIO()                   # no reconfigure: must be left alone
        _tolerant_output()
    finally:
        sys.stdout = saved
    print("8. an unencodable character in a name turns into '?' on a legacy console instead of "
          "failing the run after the report is written")


try:
    for fn in (test_only_a_local_model_is_accepted, test_seeding,
               test_replay_and_resume, test_scoring_and_the_report,
               test_the_player_file_seeds_the_protagonist,
               test_printing_the_report_cannot_fail_the_run):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nSOAK GATE TESTS PASSED")

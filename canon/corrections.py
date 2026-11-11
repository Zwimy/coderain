"""Author corrections: what the author says is true or false about a character, outranking the story's text (D-028).

The consistency work has a hole the first Writer test made concrete. First write wins, so a wrong first value
(a colour filed under the wrong person, a hair dyed later than the window the reader started at) is defended
against the right ones, and once the card is injected the Writer repeats it. This is the way out, and it has to
survive three things the rest of the ledger does not.

  * It is the author's, not the story's. The ledger is derived and can be rebuilt from the transcript; a
    correction cannot be derived from anything, so it lives in a Markdown file in the save (corrections.md) that
    a person can read and edit, travels with an export, and is never inside canon/. The ledger only ever holds
    its EFFECT, as author-level records.
  * It must hold after an undo, a retry or a rebuild. So nothing remembers that a correction was applied.
    `plan` compares the corrections with the canon it is given and returns only the records still needed, which
    is none once it is in line, so it is safe to run after every turn, after a rollback, and on a throwaway
    projection for a card.
  * It must stop the wrong value coming back. Two operations:

        - Odile: hair = raven            the author's value; it outranks narration and is shown
        - Corin: hair is not raven       that value is wrong: retract it if held, and refuse it if proposed

    "is not" is a retraction (an author_edit with no value), not a replacement: the author may not know the real
    value, and the story can then establish it. The refusal list stops the Scribe re-proposing the same wrong
    value on every turn that mentions it, which would otherwise be retracted and re-locked forever.

Identity only (hair, eyes, build, age, marks): state changes every few turns and is the story's to say.
Standard library only, plus the rest of canon/.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from canon.ledger import make_record
from canon.state import Canon
from canon.validate import _slugify, norm, same_value

FILE = "corrections.md"
SLOTS = ("hair", "eyes", "build", "age", "marks")
_SLOT_WORDS = {"hair": "hair", "eyes": "eyes", "eye": "eyes", "build": "build", "age": "age",
               "marks": "marks", "mark": "marks"}
MAX_VALUE = 80
MAX_WHO = 120
MAX_FILE = 20_000
SPAN = "corrections.md"            # the provenance every correction record carries

HEADER = """# Canon corrections

What you say here is true outranks what the story's own text says, and is kept across undo, retry and a rebuild.
Write each correction as a bullet line: a dash, the character, a colon, the slot, then either "= value" or
"is not value". These three examples are shown without the dash on purpose, so they are not read as real lines:

    Name: hair = raven               the value to use (outranks the story)
    Name: hair is not raven          that value is wrong: remove it, and do not accept it again
    Name: marks = scar on his chin   a mark to add (marks is a list; add one line per mark)

Slots: hair, eyes, build, age, marks. Anything that is not a bullet is ignored, so you can write notes.
"""

_LINE = re.compile(
    r"^\s*[-*]\s+(?P<who>[^:=]+?)\s*:\s*(?P<slot>[A-Za-z]+)\s*(?:(?P<eq>=)|\bis\s+not\b)\s*(?P<value>.*?)\s*$")


@dataclass(frozen=True)
class Correction:
    who: str                # a name, alias or id as the author wrote it
    slot: str               # one of SLOTS
    op: str                 # "set" or "wrong"
    value: str
    line: int = 0           # 1-based line in the file, for a message

    def text(self) -> str:
        return f"- {self.who}: {self.slot} " + (f"= {self.value}" if self.op == "set"
                                                 else f"is not {self.value}")


def _clean(value: str) -> str:
    v = " ".join(value.split()).strip(" \t\"'`*")
    return v


def parse(text: str) -> tuple[list[Correction], list[dict]]:
    """The corrections in a file, and what could not be read. A bullet that does not parse is reported with
    its line, never silently dropped; a line that is not a bullet is a note and is ignored."""
    out: list[Correction] = []
    problems: list[dict] = []
    for n, raw in enumerate((text or "").splitlines(), 1):
        if not re.match(r"^\s*[-*]\s+\S", raw):
            continue
        m = _LINE.match(raw)
        if not m:
            problems.append({"line": n, "text": raw.strip()[:100],
                             "why": "expected '- Name: slot = value' or '- Name: slot is not value'"})
            continue
        who, slot = _clean(m.group("who")), _SLOT_WORDS.get(m.group("slot").lower())
        value = _clean(m.group("value").partition(" -- ")[0])       # " -- " starts a note
        op = "set" if m.group("eq") else "wrong"
        why = ("unknown slot %r (use hair, eyes, build, age or marks)" % m.group("slot") if slot is None
               else "no character name" if not who or len(who) > MAX_WHO
               else "no value" if not value
               else f"the value is longer than {MAX_VALUE} characters" if len(value) > MAX_VALUE
               else "")
        if why:
            problems.append({"line": n, "text": raw.strip()[:100], "why": why})
            continue
        c = Correction(who, slot, op, value, n)
        if c in out or any(o.who.lower() == c.who.lower() and o.slot == c.slot and o.op == c.op
                           and o.value == c.value for o in out):
            continue                                                  # said twice
        rival = next((o for o in out if o.who.lower() == who.lower() and o.slot == slot
                      and o.op != op and same_value(o.value, value)), None)
        if rival is not None:
            problems.append({"line": n, "text": raw.strip()[:100],
                             "why": f"contradicts line {rival.line}, which says the same value is "
                                    + ("right" if rival.op == "set" else "wrong")})
            continue
        out.append(c)
    # a scalar slot has one value: the last "=" for it wins, and the earlier one is reported
    keep: dict[tuple[str, str], Correction] = {}
    for c in out:
        if c.op == "set" and c.slot != "marks":
            old = keep.get((c.who.lower(), c.slot))
            if old is not None:
                problems.append({"line": old.line, "text": old.text()[:100],
                                 "why": f"replaced by line {c.line}, the later value for the same slot"})
            keep[(c.who.lower(), c.slot)] = c
    final = [c for c in out if not (c.op == "set" and c.slot != "marks"
                                    and keep[(c.who.lower(), c.slot)] is not c)]
    return final, sorted(problems, key=lambda p: p["line"])


def add_line(text: str, who: str, slot: str, op: str, value: str) -> str:
    """The file with one more correction, header first when there was no file. A line that is already there
    is not added twice."""
    c = Correction(_clean(who), _SLOT_WORDS.get(slot.lower(), ""), op, _clean(value))
    base = text if (text or "").strip() else HEADER
    for have in parse(base)[0]:
        if (have.who.lower(), have.slot, have.op, norm(have.value)) == \
                (c.who.lower(), c.slot, c.op, norm(c.value)):
            return base
    return base.rstrip("\n") + "\n" + c.text() + "\n"


def _record(eid: str, slot: str, value, turn: int) -> dict:
    return dict(kind="author_edit", entity=eid, slot=slot, value=value, authority="author",
                turn=turn, span=SPAN)


def plan(canon: Canon, corrections, *, turn: int) -> tuple[list[dict], list[dict]]:
    """(the ledger records still needed to put `canon` in line with the corrections, what could not be
    applied). Pure: nothing is written and nothing is remembered, so a canon that is already in line gets
    an empty list, which is what makes it safe to run again after every turn and after every rollback."""
    out: list[dict] = []
    problems: list[dict] = []
    for c in corrections:
        eid = canon.resolve(c.who)
        if eid is None:
            problems.append({"line": c.line, "text": c.text()[:100],
                             "why": f"no single character is called {c.who!r} (yet)"})
            continue
        if c.slot == "marks":
            if c.op == "set":
                slot = f"identity.marks.{_slugify(c.value)}"
                cur = canon.current(eid, slot)
                if cur is None or norm(str(cur)) != norm(c.value):
                    out.append(_record(eid, slot, c.value, turn))
            else:
                for slot in [s for s in canon.slots.get(eid, {}) if s.startswith("identity.marks.")]:
                    cur = canon.current(eid, slot)
                    if cur is not None and same_value(str(cur), c.value):
                        out.append(_record(eid, slot, None, turn))
            continue
        slot = f"identity.{c.slot}"
        cur = canon.current(eid, slot)
        if c.op == "set":
            if cur is None or norm(str(cur)) != norm(c.value):
                out.append(_record(eid, slot, c.value, turn))
        elif cur is not None and same_value(str(cur), c.value):
            out.append(_record(eid, slot, None, turn))
    return out, problems


def apply_to(canon: Canon, corrections, *, turn: int) -> tuple[list[dict], list[dict]]:
    """Bring a canon in line with the corrections, in memory. For a canon that is a throwaway projection (the
    card is built from one); the reader writes the same records to the real ledger. Returns what `plan` does."""
    recs, problems = plan(canon, corrections, turn=turn)
    for k, fields in enumerate(recs):
        canon.apply(make_record(canon.last_id + 1 + k, **fields))
    return recs, problems


def refusals(canon: Canon, corrections) -> dict[tuple[str, str], list[str]]:
    """(entity id, claim slot) -> the values the author says are wrong, for the validator to refuse. A claim
    slot is 'identity.hair' and so on, and 'identity.marks' for every mark."""
    out: dict[tuple[str, str], list[str]] = {}
    for c in corrections:
        if c.op != "wrong":
            continue
        eid = canon.resolve(c.who)
        if eid is not None:
            out.setdefault((eid, f"identity.{c.slot}"), []).append(c.value)
    return out


def held_values(canon: Canon) -> list[dict]:
    """What canon currently holds for each character's identity, one row per value, for a person to read before
    deciding what to correct: who, which slot, the value, since which turn, how many times the story has said
    it, and whose word it is (narration, scenario or author)."""
    rows = []
    for eid, e in canon.entities.items():
        for slot, ivs in canon.slots.get(eid, {}).items():
            if not slot.startswith("identity.") or not ivs or ivs[-1].end_id is not None:
                continue
            iv = ivs[-1]
            key = "marks" if slot.startswith("identity.marks.") else slot.split(".", 1)[1]
            rows.append({"who": e["name"], "slug": eid, "slot": key, "value": iv.value,
                         "since_turn": iv.start_turn, "confirmations": iv.confirmations,
                         "by": iv.authority})
    rows.sort(key=lambda r: (r["who"].lower(), SLOTS.index(r["slot"]) if r["slot"] in SLOTS else 9,
                             str(r["value"])))
    return rows


def slot_word(word: str) -> str | None:
    """The slot a word names ('eye' and 'eyes' both mean eyes), or None."""
    return _SLOT_WORDS.get((word or "").strip().lower())


def describe(text: str) -> dict:
    """The file as plain data: its text, what was read from it, and what could not be."""
    corr, problems = parse(text)
    return {"text": text,
            "corrections": [{"who": c.who, "slot": c.slot, "op": c.op, "value": c.value, "line": c.line}
                            for c in corr],
            "problems": list(problems)}

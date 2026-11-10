"""Who "she", "he" and "you" mean, decided in code (D-024).

The validator used to refuse any claim about someone the passage does not name (D-019),
and it refused a pronoun as the subject of a claim. In a story told in the second person
that leaves very little: "you" is in 973 of 976 narrator turns of the real save, the
player is named in 117 of them, and in a long scene "she" runs for dozens of turns after
the name appeared once.

Three things are decided here, none by the Scribe:

  you          the player. The caller says which entity that is.
  she / he     the nearest character named BEFORE the pronoun, but only when that is
               unambiguous: the nearest sentence that names anyone the pronoun could mean
               names exactly one. Two women in a sentence are two possible referents, and a
               wrong guess lands on the wrong person's sheet, so the answer is "unclear".
  gender       a quote about a woman is not a fact about a man. Gender is read from the
               story: a sentence that names exactly one character and says her or his.

What does not count as a name for this: a mention AFTER a pronoun of that gender in its own
sentence ("She brings it to Garrick's side": Garrick is the object, and the "she" is
someone else), a name inside quoted speech (it names a third party the speaker is talking
of), a pronoun inside quoted speech, a line that starts with "#" (the engine's scene
header), a single word after "the" ("the Guild", "the Lantern Market": a faction or a place
that shares a word with a character), and the player (a third-person pronoun never means
"you"). Each of these is a way the nearest name was wrong in the real save.

Pure functions of canon plus prose; no model, no file. The validator receives the result
as a `Who` (validate.py), so it never imports the scene code that finds names.
"""
from __future__ import annotations

import re

from canon.scene import mention_spans
from canon.state import Canon
from canon.validate import (F_WORDS, M_WORDS, Who, _sentence_of, _tokens,  # noqa: F401
                            is_second_person, quote_gender)

# --- sentences and the quote's place in the passage ---------------------------------
def sentence_bounds(prose: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence. A newline ends one as well."""
    out, last = [], 0
    for m in re.finditer(r"[.!?…]+[\"'”’)]*(?=\s|$)|\n+", prose):
        if prose[last:m.end()].strip():
            out.append((last, m.end()))
        last = m.end()
    if prose[last:].strip():
        out.append((last, len(prose)))
    return out


def locate(prose: str, quote: str) -> tuple[int, int] | None:
    """Where the quote is in the passage, or None. The Scribe may paraphrase a little
    (evidence_ok tolerates it), so fall back to the sentence the quote mostly overlaps."""
    q = quote.strip().strip(".…").strip()
    if not q:
        return None
    at = prose.find(q)
    if at < 0:
        at = prose.lower().find(q.lower())
    if at >= 0:
        return at, at + len(q)
    words = q.split()
    if len(words) >= 3:
        m = re.search(r"\s+".join(re.escape(w) for w in words[:6]), prose, re.IGNORECASE)
        if m:
            return m.start(), min(len(prose), m.start() + len(q))
    sent = _sentence_of(quote, prose)
    if sent:
        at = prose.find(sent.strip())
        if at >= 0:
            return at, at + len(sent.strip())
    return None


def _pronoun_of(word: str, words: frozenset) -> bool:
    """Is `word` one of `words`, allowing a contraction ("she's", "he'd", "she'll")?"""
    w = word.lower().replace("’", "'")
    return w in words or re.sub(r"'(?:s|d|ll|ve)$", "", w) in words


def in_speech(text: str, at: int) -> bool:
    """Is position `at` inside quoted speech? Straight quotes alternate; curly ones are
    counted open against close."""
    before = text[:at]
    return before.count('"') % 2 == 1 or before.count("“") > before.count("”")


def _header_ranges(text: str) -> list[tuple[int, int]]:
    """Lines that start with "#": the engine's scene header ("### [date] [place]"), which
    names a place, not someone in the scene."""
    return [(m.start(), m.end()) for m in re.finditer(r"(?m)^#.*$", text)]


# --- who "she" or "he" means --------------------------------------------------------
class Passage:
    """A passage and the turns before it, searched once for names and sentences."""

    def __init__(self, canon: Canon, prose: str, before: str = "", player: str | None = None):
        self.prose = prose
        self.offset = len(before) + 1 if before else 0
        self.full = before + "\n" + prose if before else prose
        heads = _header_ranges(self.full)
        self.spans = [
            (s, e, eid) for s, e, eid in mention_spans(canon, self.full)
            if eid != player and not any(a <= s < b for a, b in heads)
            and not in_speech(self.full, s)
            and not (" " not in self.full[s:e].strip()
                     and re.search(r"\bthe\s+$", self.full[max(0, s - 5):s], re.IGNORECASE))]
        self.sents = sentence_bounds(self.full)


def referent(canon: Canon, passage: Passage, quote: str, gender: str, *,
             genders: dict | None = None, reach: int = 2) -> str | None:
    """The one character a pronoun of `gender` in `quote` means, or None when unclear."""
    return explain(canon, passage, quote, gender, genders=genders, reach=reach)[0]


def explain(canon: Canon, passage: Passage, quote: str, gender: str, *,
            genders: dict | None = None, reach: int = 2) -> tuple[str | None, str]:
    """(who, the sentence that named them): `referent` with its evidence, for a person
    reading why a claim was attributed. (None, "") when the code cannot say.

    Starts at the sentence the pronoun is in and goes back up to `reach` sentences (across
    turns, if the passage was given its predecessors), looking only at names that come
    BEFORE the pronoun. The nearest sentence that names anyone the pronoun could mean
    decides: exactly one such character is the answer, two is None (no widening, a second
    candidate is a reason to doubt, not to look further). A character of unknown gender
    could be anyone, so counts as a candidate."""
    genders = genders or {}
    at = locate(passage.prose, quote)
    if at is None:
        return None, ""
    qs, qe = at[0] + passage.offset, at[1] + passage.offset
    words = F_WORDS if gender == "F" else M_WORDS
    pron = next((m for m in re.finditer(r"[A-Za-z’']+", passage.full[qs:qe])
                 if _pronoun_of(m.group(), words)), None)
    if pron is None:
        return None, ""
    pp = qs + pron.start()
    if in_speech(passage.full, pp):
        return None, ""                  # a pronoun in dialogue is about someone else
    k = next((i for i, (lo, hi) in enumerate(passage.sents) if lo <= pp < hi), None)
    if k is None:
        return None, ""
    for back in range(reach + 1):
        i = k - back
        if i < 0:
            break
        lo, hi = passage.sents[i]
        # Only names before the sentence's own first pronoun of this gender, and (in the
        # quote's sentence) before the pronoun the quote is about.
        first = next((m.start() + lo for m in re.finditer(r"[A-Za-z’']+", passage.full[lo:hi])
                      if _pronoun_of(m.group(), words)), hi)
        limit = min(first, pp) if i == k else first
        here = {eid for s, _e, eid in passage.spans
                if lo <= s < limit and genders.get(eid) in (None, gender)}
        if here:
            return (next(iter(here)), passage.full[lo:hi].strip()) if len(here) == 1 else (None, "")
    return None, ""


def make_who(canon: Canon, prose: str, *, genders: dict | None = None,
             player: str | None = None, before: str = "") -> Who:
    """The validator's view of this passage: who "you" is, who is which gender, and how to
    resolve a pronoun in a quote. `before` is the narrator turns just before this one."""
    genders = dict(genders or {})
    player = player if player in canon.entities else None
    cache: list[Passage] = []

    def refer(gender: str, quote: str, reach: int = 2) -> str | None:
        if not cache:                                # built on first use, once per passage
            cache.append(Passage(canon, prose, before, player))
        return referent(canon, cache[0], quote, gender, genders=genders, reach=reach)

    return Who(player=player, genders=genders, refer=refer)


# --- gender, read from the story -----------------------------------------------------
def gender_votes(canon: Canon, prose: str, player: str | None = None) -> dict[str, list[int]]:
    """{entity: [he, she]} from the sentences of `prose` that name exactly ONE character
    and use pronouns of one gender. Counts only; the sentence is not kept. The player is
    skipped: a sentence that names them ("But Finn?") and says "her" is about someone else."""
    out: dict[str, list[int]] = {}
    heads = _header_ranges(prose)
    spans = [(s, e, eid) for s, e, eid in mention_spans(canon, prose)
             if eid != player and not any(a <= s < b for a, b in heads)]
    for lo, hi in sentence_bounds(prose):
        who = {eid for s, _e, eid in spans if lo <= s < hi}
        if len(who) != 1:
            continue
        sent = prose[lo:hi]
        g = quote_gender(sent)
        if g is None:
            continue
        n = sum(1 for t in _tokens(sent) if t in (F_WORDS if g == "F" else M_WORDS))
        out.setdefault(next(iter(who)), [0, 0])[1 if g == "F" else 0] += n
    return out


def decide_gender(he: int, she: int, *, need: int = 3, share: float = 0.8) -> str | None:
    """"M" or "F" once there are at least `need` votes and one side holds `share` of them,
    else None (unknown: it could be anyone, and is treated that way)."""
    total = he + she
    if total < need:
        return None
    return "M" if he >= share * total else "F" if she >= share * total else None


def genders_from(votes: dict[str, list[int]]) -> dict[str, str]:
    """{entity: "M" | "F"} for every entity whose votes are decisive."""
    out = {}
    for eid, (he, she) in votes.items():
        g = decide_gender(he, she)
        if g:
            out[eid] = g
    return out

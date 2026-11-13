"""Validate claims against canon, in code, and turn the good ones into records.

The Scribe is a model and will sometimes be wrong, so nothing it says reaches the
ledger on its word. Each claim has to pass checks that are plain code:

  evidence    the quoted words must really be in the prose
  value       the claimed value must really be in that quote
  slot        the quote must describe THIS slot of a person (shape.py): "violet eyes"
              is not a claim about hair, and "green beads" are not a hair colour
  confidence  below the bar waits as `pending`; it is never silently dropped
  context     evidence from a dream or an imagining waits as `pending` too
  entity      a name must resolve to a known entity or look like a new one; a
              pronoun never does; and the passage must actually name them
  owner       one quote is not about two people: the same identity claim filed under
              two characters waits as `pending` for both
  layer       what the claim does depends on its slot: identity is first write
              wins, state is latest wins (state.py)

Claims are checked IN ORDER against a scratch copy of canon that earlier claims in
the same passage have already changed. "Puts on a coat, then takes off her gloves"
is one passage and two claims, and the second must see the first.

A contradiction (a second, different identity value) is reported and NOT committed
by default. That is the hook for the resolve-before-commit step: patch the
sentence first, so the transcript the next turn reads is the repaired one.
"""
from __future__ import annotations

import copy
import difflib
import re
from dataclasses import dataclass, field
from typing import Callable

from canon import shape, wardrobe
from canon.claims import CONFIDENCE, Claim
from canon.ledger import MAX_LIST, LedgerError, make_record
from canon.state import Canon

_STOP = frozenset("""a an the and or of to in on at by for with from into over under
this that his her their its it is was were be been being as but not no nor so if""".split())
_PRONOUNS = frozenset({
    "she", "he", "they", "it", "her", "him", "them", "his", "hers", "their",
    "someone", "somebody", "anyone", "everyone", "you", "i", "we", "the woman",
    "the man", "the girl", "the boy", "the stranger", "the figure", "the other"})
_KIND = {"state.held": "item_moved", "state.location": "location_changed"}

# --- who a claim is about, beyond what the passage names (D-024) ------------------
F_WORDS = frozenset({"she", "her", "hers", "herself"})
M_WORDS = frozenset({"he", "him", "his", "himself"})
YOU_WORDS = frozenset({"you", "your", "yours", "yourself", "you're", "you'd", "you've",
                       "you'll"})
# What a Scribe writes where a name should be, and what each stands for.
_PRONOUN_KIND = {
    "she": "F", "her": "F", "hers": "F", "herself": "F", "the woman": "F", "the girl": "F",
    "he": "M", "him": "M", "his": "M", "himself": "M", "the man": "M", "the boy": "M",
    "you": "you", "your": "you", "yours": "you", "yourself": "you"}


def pronoun_kind(name: str) -> str | None:
    """"F", "M" or "you" when `name` is a pronoun or a bare "the woman"; else None."""
    return _PRONOUN_KIND.get(norm(name))


def quote_gender(text: str) -> str | None:
    """"F" or "M" when the words use only one gender's pronouns, else None."""
    toks = set(_tokens(text))
    f, m = bool(toks & F_WORDS), bool(toks & M_WORDS)
    return "F" if f and not m else "M" if m and not f else None


def is_second_person(text: str) -> bool:
    """Says "you" or "your" and no third-person gendered pronoun: "your hand on her hip"
    is about two people and settles nothing about either."""
    toks = set(_tokens(text))
    return bool(toks & YOU_WORDS) and not (toks & (F_WORDS | M_WORDS))


@dataclass(frozen=True)
class Who:
    """What the CALLER knows about who a passage is talking about. The validator never
    reads the story for this itself (the code that finds names imports the validator, not
    the other way round), and an empty Who changes nothing: a name has to be in the
    passage, and a pronoun is refused, as D-019 says."""
    player: str | None = None            # entity id "you" means
    genders: dict = field(default_factory=dict)       # entity id -> "F" | "M", when known
    # (gender, quote, sentences to look back) -> entity id, or None when it cannot say
    refer: Callable[[str, str, int], str | None] | None = None
    # How far back a pronoun may look for its name when the fact is an IDENTITY fact. None (the default, D-024) means
    # never: identity is first write wins and permanent. A number turns it on (canon: identity_via_pronoun, D-035).
    identity_reach: int | None = None

    def reach(self, slot: str) -> int | None:
        """How many sentences back a pronoun may look for its name, for a fact in `slot`; None where a guess is not
        allowed."""
        if slot.startswith("state."):
            return STATE_REACH
        return self.identity_reach if slot.startswith("identity.") else None

    def about(self, eid: str, quote: str, reach: int | None) -> bool:
        """The passage does not name `eid`, but the quote is plainly about them: the player
        in the second person, or the one character a pronoun in the quote can mean."""
        if self.player == eid and is_second_person(quote):
            return True
        g = quote_gender(quote)
        return bool(g and reach is not None and self.refer is not None
                    and self.refer(g, quote, reach) == eid)

    def resolve(self, kind: str, quote: str, reach: int | None) -> str | None:
        """Who a pronoun the Scribe wrote means, or None when the code cannot say.
        `reach` is how far back to look, None where a guess is not allowed."""
        if kind == "you":
            return self.player
        if reach is None or self.refer is None:
            return None
        return self.refer(kind, quote, reach)


# A pronoun may be resolved by code only for a STATE fact. On hand-read samples of the real
# save the nearest-name rule was right about 9 times in 10 (102 of 112 decided cases, near
# and far alike), and the misses were not random: a faction or an ink that shares a word with
# a character's alias, and a listener taken for the speaker. A state fact is replaced and
# ages out (D-023), so a wrong one corrects itself. An identity fact is first write wins and
# permanent, so one wrong attribution in ten is too many: identity needs the name in the
# passage, or "you" for the player, which is exact.
STATE_REACH = 30                      # sentences a pronoun may look back for its name


# How many items a state list keeps. Past it the OLDEST goes, because state is latest
# wins: the old rule refused the new item and kept the old ones, so a full list showed
# the oldest things in the story and nothing new (386 such refusals in the real-save
# gate). The ledger bound is 16 (ledger.MAX_LIST); these are what a card can use.
# Untuned: measure them on the shadow report before relying on them.
LIST_CAP = {"state.outfit": 10, "state.held": 6, "state.injury": 6}


# Words that name the same colour. Used ONLY to decide whether a new identity value
# restates the existing one. The ledger compares values as exact strings, so
# "raven" followed later by "black" would otherwise be a contradiction, and a
# validator that flags a restatement as an error teaches the story to stop
# describing anyone. Erring toward "same" is the safe direction here: a missed
# real change is one wrong word, a false contradiction blocks a turn.
_SAME = [frozenset(g.split()) for g in (
    "black raven jet ebony",
    "brown chestnut brunette chocolate hazel",
    "blond blonde platinum golden flaxen",
    "red ginger auburn copper crimson",
    "grey gray silver white ash",
    "green emerald jade",
    "blue azure sapphire",
    "violet purple amethyst lavender",
    "amber gold yellow",
)]
_MODIFIERS = frozenset("""long short cropped shoulder length waist braided loose
tied dark light pale deep bright soft thick thin curly wavy straight tight""".split())


def _core(value: str) -> set[str]:
    return {w for w in norm(value).split() if w not in _STOP and w not in _MODIFIERS}


def same_value(a: str, b: str) -> bool:
    """Do two identity values state the same thing?

    Equal after dropping modifiers, one contained in the other, or naming the same
    colour. Deliberately generous: see _SAME.
    """
    ca, cb = _core(a), _core(b)
    if not ca or not cb:
        return norm(a) == norm(b)
    if ca <= cb or cb <= ca:
        return True
    return any(ca & g and cb & g for g in _SAME)


# --- text checks ------------------------------------------------------------
def norm(text: str) -> str:
    t = text.lower().replace("’", "'").replace("‘", "'")
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", t).split())


def evidence_ok(evidence: str, prose: str, threshold: float = 0.9) -> bool:
    """Are the quoted words really in the prose?

    Exact after normalising case and punctuation, or a close token match. Models
    paraphrase a quote slightly; a threshold lets the harmless version through
    and keeps out an invented one. A one-word quote must match exactly.
    """
    e, p = norm(evidence), norm(prose)
    if not e or not p:
        return False
    if e in p:
        return True
    et, pt = e.split(), p.split()
    if len(et) < 2:
        return False
    n = len(et)
    for size in range(max(1, n - 2), n + 3):
        for i in range(max(1, len(pt) - size + 1)):
            if difflib.SequenceMatcher(None, et, pt[i:i + size]).ratio() >= threshold:
                return True
    return False


_TITLES = frozenset("sir lady lord captain master mistress miss mister mr mrs dr".split())


def _tokens(text: str) -> list[str]:
    """Words of `text`, lower-cased, possessives and quotes stripped."""
    return [t[:-2] if t.endswith("'s") else t.strip("'") for t in norm(text).split()]


def named_in_prose(labels: list[str], prose: str) -> bool:
    """Does the passage name this entity: any distinctive word of its name or an
    alias? A claim about someone the passage never mentions is a guess by the
    model (it picked a likely character from the list), and a guessed attribution
    is the worst kind of error because it lands on the wrong person's sheet.
    Pronoun-only passages therefore yield nothing until the caller supplies who the
    scene is about (a later phase); the Scribe is already told never to use one."""
    words = set(_tokens(prose))
    return any(len(t) >= 2 and t not in _STOP and t not in _TITLES and t in words
               for label in labels for t in _tokens(label))


# A dream or an imagining states nothing about the world. Matched only inside the
# sentence the evidence comes from, so "She had dreamed of this. Her hair was raven."
# still records the hair. Hypotheticals, wishes and plans are NOT listed: that list
# has to be written against fresh cases, not the ones this was measured on.
_IRREALIS = re.compile(
    r"\b(?:dream(?:s|ed|t|ing)?|nightmares?|imagin\w*|pretend\w*|as if|as though)\b")


def _sentence_of(evidence: str, prose: str) -> str:
    """The sentence of `prose` that the quoted evidence mostly overlaps, or ''."""
    want = set(_tokens(evidence))
    if not want:
        return ""
    best, top = "", 0.0
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", prose):
        share = len(want & set(_tokens(sentence))) / len(want)
        if share > top:
            best, top = sentence, share
    return best if top >= 0.5 else ""


def _stem(w: str) -> str:
    for suffix, keep in (("ing", 5), ("ed", 4), ("es", 4), ("s", 3)):
        if w.endswith(suffix) and len(w) > keep:
            return w[: -len(suffix)]
    return w


def value_supported(value: str, evidence: str) -> bool:
    """Every content word of the value appears in the quote it claims to come from.

    Stops a model "normalising" a value into words the text never used (black for
    raven), which would make a claim look supported when it is an inference.
    """
    words = [w for w in norm(value).split() if len(w) >= 3 and w not in _STOP]
    if not words:
        return True
    ev = [_stem(t) for t in norm(evidence).split()]
    for w in words:
        s = _stem(w)
        if s not in ev and not (len(s) >= 4 and any(t.startswith(s[:4]) for t in ev)):
            return False
    return True


def _slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return s or "x"


def _find_item(items: list[str], value: str) -> int | None:
    """Index of the one item that `value` refers to, or None."""
    key = norm(value)
    for i, it in enumerate(items):
        if norm(it) == key:
            return i
    ktoks = set(key.split()) - _STOP
    hits = [i for i, it in enumerate(items)
            if ktoks and (ktoks <= set(norm(it).split()) or set(norm(it).split()) <= ktoks)]
    return hits[0] if len(hits) == 1 else None


def _absorbed(items: list[str], value: str) -> set[int]:
    """Indices of the items that `value` says everything of and more: every word of the item is in it.

    `_find_item` only treats a repeat as the same item when exactly ONE item matches, so once a list held "rope"
    and "rag", "rope and rag" matched two and was appended, then "worn rope and rag" matched three and was
    appended too (a 240-turn soak ended with held: rope, rag, rope and rag, worn rope and rag, and an outfit of
    spectacles, glasses, spectacles and glasses, all in the card the Writer is sent). A new item that contains
    several old ones replaces them. The words must ALL be inside it: "rag" and "rope" are two things, and
    "rope and chain" absorbs "rope" and leaves "rag"."""
    ktoks = set(norm(value).split()) - _STOP
    if not ktoks:
        return set()
    return {i for i, it in enumerate(items)
            if (itoks := set(norm(it).split()) - _STOP) and itoks < ktoks}


# --- entities ---------------------------------------------------------------
def resolve_loose(canon: Canon, name: str) -> str | None:
    """Entity id for a NAME a model wrote; tolerates "Odile" for "Odile Marsh". None
    when unknown or ambiguous: a wrong merge is worse than a duplicate.

    Names and aliases only, never ids. An id is an internal slug, and matching it
    made the bare name "Corin" resolve to the entity whose id happened to be
    `corin`, quietly picking one of two Corins.
    """
    full = norm(name)
    if not full or full in _PRONOUNS:
        return None
    labels = {eid: [e["name"], *e["aliases"]] for eid, e in canon.entities.items()}
    exact = {eid for eid, ls in labels.items() if any(norm(x) == full for x in ls)}
    if len(exact) > 1:
        # One character's OWN name beats another character's ALIAS. norm() turns the slug
        # "tamsin-reeve" into "tamsin reeve", so a fold that wrote one character's slug as
        # another's alias made the true name ambiguous, and every claim about that person
        # was refused as an unknown name (28 of them in one soak, 0 of them kept). Two
        # entities that share the same own name, or two that only share an alias, stay
        # ambiguous: that is still a guess, and a wrong merge is worse than a duplicate.
        own = {eid for eid in exact if norm(canon.entities[eid]["name"]) == full}
        if len(own) == 1:
            exact = own
    if exact:
        return next(iter(exact)) if len(exact) == 1 else None
    key = set(full.split()) - _STOP
    if not key:
        return None
    hits = set()
    for eid, ls in labels.items():
        for label in ls:
            lt = set(norm(label).split()) - _STOP
            if lt and (key <= lt or lt <= key):
                hits.add(eid)
    return next(iter(hits)) if len(hits) == 1 else None


def is_pronoun(name: str) -> bool:
    return norm(name) in _PRONOUNS


def looks_like_name(name: str) -> bool:
    toks = name.split()
    if not 1 <= len(toks) <= 3 or norm(name) in _PRONOUNS:
        return False
    return all(re.fullmatch(r"[A-Z][A-Za-z'’-]*", t) for t in toks) \
        and toks[0].lower() != "the"


# --- decisions --------------------------------------------------------------
@dataclass
class Decision:
    claim: Claim
    status: str      # commit | pending | reject | contradiction | noop
    reason: str = ""
    entity: str | None = None
    records: list[dict] = field(default_factory=list)
    # How the subject was found when the passage did not simply name them: "you" (the
    # player), "pronoun" (the code resolved a she or he), or "context" (the Scribe named
    # them and the code agreed from the turns before). Reports count these, because they
    # rest on a rule that is right about 9 times in 10, not on a name.
    via: str = ""


def _fields(eid, slot, kind, value, c: Claim, turn, world):
    return dict(kind=kind, entity=eid, slot=slot, value=value,
                authority="narration", turn=turn, world_time=world,
                source_turn=turn, span=c.evidence)


def _colour_groups(text: str) -> set:
    """The colours a value names, each as its _SAME group (jade and green are one) or itself."""
    out = set()
    for w in norm(text).split():
        if w in shape._COLOURS:
            out.add(next((i for i, g in enumerate(_SAME) if w in g), w))
    return out


def _same_item(a: str, b: str) -> bool:
    """Do two accessory values name the same item? They share an ornament word ("hairpin" and "hairpins")
    and their colours do not disagree: a value with no colour agrees with any. same_value is the wrong tool
    here, it calls "silver ring" and "silver hairpins" one thing because both say silver."""
    if not (shape.accessory_nouns(a) & shape.accessory_nouns(b)):
        return False
    ca, cb = _colour_groups(a), _colour_groups(b)
    return not ca or not cb or bool(ca & cb)


def _said_again(scratch: Canon, eid: str, c: Claim) -> bool:
    """Does this claim say what canon already holds? (A repeat is recorded, not
    dropped: see _plan.)"""
    cur = scratch.current(eid, c.slot)
    if cur is None:
        return False
    if c.op == "add" and c.slot.startswith("state."):
        return _find_item([cur] if isinstance(cur, str) else list(cur), c.value) is not None
    if c.op != "set":
        return False
    return cur == c.value or (c.slot.startswith("identity.") and isinstance(cur, str)
                              and same_value(cur, c.value))


def _plan(scratch: Canon, eid: str, c: Claim, turn: int, world):
    """(records, None) to write, or (None, ('noop'|'reject', reason))."""
    slot, op = c.slot, c.op
    if slot == "identity.marks":
        return [_fields(eid, f"identity.marks.{_slugify(c.value)}",
                        "fact_established", c.value, c, turn, world)], None
    if slot == "identity.accessories":
        # One ledger slot per item, like marks. The same item worded another way ("hairpins" and
        # "gold hairpins", "jade beads" and "green beads") is the item said again, recorded under the
        # slot and wording it already has, not a second item (the marks list has that duplicate gap).
        held = [(s, scratch.current(eid, s)) for s in scratch.slots.get(eid, {})
                if s.startswith("identity.accessories.")]
        held = [(s, v) for s, v in held if isinstance(v, str)]
        for s, v in held:
            if _same_item(v, c.value):
                return [_fields(eid, s, "fact_established", v, c, turn, world)], None
        if len(held) >= MAX_ACCESSORIES:
            return None, ("reject", "too_many_accessories")
        return [_fields(eid, f"identity.accessories.{_slugify(c.value)}",
                        "fact_established", c.value, c, turn, world)], None
    if slot.startswith("identity."):
        value = c.value
        cur = scratch.current(eid, slot)
        if isinstance(cur, str) and cur != value and same_value(cur, value):
            # A restatement: record it with the EXISTING wording so canon sees
            # the same value and counts a corroboration, not a contradiction.
            value = cur
        rec = _fields(eid, slot, "fact_established", value, c, turn, world)
        if slot in _COLOUR_SLOTS and isinstance(value, str) and not shape.has_colour(value):
            # A hair or eye value with no colour in it ("dark", "elaborate braids") is true but
            # weak, and identity is first write wins, so it used to lock the slot against the
            # colour the story states next (a real colour held back 6 to 33 times behind
            # "dark", D-041). Filed as `inferred`, the lowest authority, it holds an empty
            # slot and is replaced by the first narrated colour; nothing else can displace it.
            rec["authority"] = "inferred"
        return [rec], None

    kind = _KIND.get(slot, "state_set")
    cur = scratch.current(eid, slot)
    items = [cur] if isinstance(cur, str) else list(cur or [])
    if op == "clear":
        return ([_fields(eid, slot, "state_cleared", None, c, turn, world)], None) \
            if cur is not None else (None, ("noop", "nothing_to_clear"))
    # A claim that restates what canon already holds is still RECORDED: that is what
    # tells canon the story said it again just now, so a card can tell a value that is
    # still true from one that nobody has mentioned for a thousand turns (state.py).
    if op == "set":
        return [_fields(eid, slot, kind, c.value, c, turn, world)], None
    if op == "add":
        at = _find_item(items, c.value)
        if at is not None:                            # said again: newest, old wording
            new = items[:at] + items[at + 1:] + [items[at]]
        else:
            gone = _absorbed(items, c.value)
            kept = [it for i, it in enumerate(items) if i not in gone]
            kept = wardrobe.replaced_by(c.value, kept) if slot == "state.outfit" else kept
            new = kept + [c.value]
        new = new[-LIST_CAP.get(slot, MAX_LIST):]
        return [_fields(eid, slot, kind, new, c, turn, world)], None
    idx = _find_item(items, c.value)                                 # remove
    if idx is None:
        return None, ("noop", "not_tracked")
    rest = items[:idx] + items[idx + 1:]
    return ([_fields(eid, slot, kind, rest, c, turn, world)] if rest else
            [_fields(eid, slot, "state_cleared", None, c, turn, world)]), None


_ONE_OWNER = frozenset({"identity.hair", "identity.eyes", "identity.build", "identity.age"})
_COLOUR_SLOTS = frozenset({"identity.hair", "identity.eyes"})
MAX_ACCESSORIES = 12          # one character's worn ornaments; identity items cannot age off, so the count is bounded


def _owner_key(canon: Canon, name: str, prose: str) -> str | None:
    """Who a claim is about, if the passage names them: an entity id, or the
    normalised name of a character the canon does not know yet."""
    eid = resolve_loose(canon, name)
    if eid is not None:
        ent = canon.entities[eid]
        return eid if named_in_prose([ent["name"], *ent["aliases"]], prose) else None
    return norm(name) if looks_like_name(name) and named_in_prose([name], prose) else None


def _shared_quotes(canon: Canon, claims: list[Claim], prose: str, floor: int) -> set:
    """(slot, value, quote) triples that two different people are credited with.

    One sentence about one person's hair is not also a sentence about another's. When
    a model files the same quote under two characters at most one is right, and
    identity is first write wins, so a wrong one is permanent. Both wait instead.
    A claimant the passage does not name, or one too unsure to count, makes nothing
    ambiguous. (Two claims with the same quote pass or fail the evidence, value and
    shape checks together, so only who and how sure can tell them apart.)"""
    who: dict[tuple, set] = {}
    for c in claims:
        if c.slot not in _ONE_OWNER or c.op != "set" or CONFIDENCE.index(c.confidence) < floor:
            continue
        owner = _owner_key(canon, c.entity, prose)
        if owner is not None:
            who.setdefault((c.slot, norm(c.value), norm(c.evidence)), set()).add(owner)
    return {k for k, owners in who.items() if len(owners) > 1}


def validate(canon: Canon, claims: list[Claim], prose: str, *, turn: int,
             next_id: int, min_confidence: str = "medium",
             create_unknown: bool = True, world_time: int | None = None,
             who: Who | None = None,
             refused: dict | None = None) -> list[Decision]:
    """`refused` maps (entity id, claim slot) to the values the author has said are wrong (D-028): a
    claim that states one is rejected as `author_refused`, so the Scribe cannot put back, turn after
    turn, a value that was retracted by hand."""
    who = who or Who()
    scratch = copy.deepcopy(canon)
    floor = CONFIDENCE.index(min_confidence)
    shared = _shared_quotes(scratch, claims, prose, floor)
    nid, out = next_id, []
    for c in claims:
        d = Decision(c, "reject")
        out.append(d)
        if not evidence_ok(c.evidence, prose):
            d.reason = "evidence_not_in_text"
            continue
        if c.op != "clear" and not value_supported(c.value, c.evidence):
            d.reason = "value_not_in_evidence"
            continue
        # BEFORE the restatement rewrite in _plan: a wrong value must not be turned
        # into the existing one and counted as agreeing with it.
        wrong = shape.problem(c.slot, c.value, c.evidence) if c.op in ("set", "add") else None
        if wrong:
            d.reason = wrong
            continue
        if CONFIDENCE.index(c.confidence) < floor:
            d.status, d.reason = "pending", "low_confidence"
            continue
        if _IRREALIS.search(norm(_sentence_of(c.evidence, prose))):
            d.status, d.reason = "pending", "irrealis_context"
            continue
        if ((c.slot, norm(c.value), norm(c.evidence)) in shared
                and _owner_key(scratch, c.entity, prose) is not None):
            d.status, d.reason = "pending", "ambiguous_owner"
            continue

        pre: list[dict] = []
        kind = pronoun_kind(c.entity)
        if kind is not None:                          # a pronoun: the code decides who
            eid = who.resolve(kind, c.evidence, who.reach(c.slot))
            if eid is None or eid not in scratch.entities:
                d.reason = "unresolved_entity"
                continue
            d.via = "you" if kind == "you" else "pronoun"
        else:
            eid = resolve_loose(scratch, c.entity)
        if kind is None and eid is not None:
            ent = scratch.entities[eid]
            if not named_in_prose([ent["name"], *ent["aliases"]], prose):
                if not who.about(eid, c.evidence, who.reach(c.slot)):
                    d.reason = "entity_not_in_passage"
                    continue
                d.via = "context"
        elif eid is None:
            if not (create_unknown and looks_like_name(c.entity)):
                d.reason = ("unresolved_entity" if norm(c.entity) in _PRONOUNS
                            else "unknown_entity")
                continue
            if not named_in_prose([c.entity], prose):
                d.reason = "entity_not_in_passage"
                continue
            base = _slugify(c.entity)
            eid, k = base, 2
            while eid in scratch.entities:
                eid, k = f"{base}-{k}", k + 1
            pre = [dict(kind="entity_created", entity=eid, slot="character",
                        value=c.entity, authority="narration", turn=turn,
                        world_time=world_time, source_turn=turn, span=c.evidence)]
        g = quote_gender(c.evidence)
        if g and who.genders.get(eid) not in (None, g):
            d.reason = "gender_mismatch"              # a sentence about a woman is not about him
            continue
        d.entity = eid
        if refused and c.op in ("set", "add") and any(
                same_value(c.value, w) for w in refused.get((eid, c.slot), ())):
            d.reason = "author_refused"
            continue
        planned, skip = _plan(scratch, eid, c, turn, world_time)
        if skip:
            d.status, d.reason = skip
            continue
        records = pre + planned
        if not pre and _said_again(scratch, eid, c):
            d.reason = "restated"                     # recorded to refresh its last-seen turn
        reason = None
        try:
            for k, fields in enumerate(records):
                rec = make_record(nid + k, **fields)
                before = len(scratch.conflicts)
                scratch.apply(rec)
                if len(scratch.conflicts) > before:
                    reason = scratch.conflicts[-1]["reason"]
                    break
        except LedgerError as exc:
            d.reason = f"invalid: {exc}"
            continue
        nid += len(records)
        d.records = records
        if reason in ("identity_locked", "lower_authority"):
            d.status, d.reason = "contradiction", reason
        elif reason:
            d.reason = reason
        else:
            d.status = "commit"
    return out


def commit(store, decisions: list[Decision], *,
           record_contradictions: bool = False) -> list:
    """Append the records of every committable decision. Returns the Records."""
    written = []
    for d in decisions:
        if d.status == "commit" or (record_contradictions
                                    and d.status == "contradiction"):
            try:
                for f in d.records:
                    written.append(store.append(**f))
            except LedgerError as exc:
                d.status, d.reason = "reject", f"ledger_refused: {exc}"
    return written

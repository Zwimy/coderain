"""Claims: what the Scribe proposes, in a closed schema, parsed defensively.

A claim is a model's PROPOSAL, never a fact. It names one slot from a closed list,
quotes the words that support it, and says how sure it is. validate.py decides what
becomes a ledger record. Keeping the vocabulary closed is what lets code compare
claims against canon at all, and it narrows what a small model can get wrong:
open-ended extraction is where published memory systems fail.

Parsing is tolerant on purpose and strict about what it lets through. Real model
output arrives fenced, wrapped in prose, truncated, or as a refusal, so the parser
reports WHICH of those happened instead of returning an empty list that looks like
"nothing to extract". A refusal that reads as "no facts" is a silent failure.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# slot -> shape. Scalar slots take `set`; list slots take `add` / `remove`.
SLOTS: dict[str, str] = {
    "identity.hair": "scalar",
    "identity.eyes": "scalar",
    "identity.build": "scalar",
    "identity.age": "scalar",
    "identity.marks": "list",       # scars, tattoos, birthmarks: several at once
    "identity.accessories": "list", # hairpins, beads, rings, a necklace, glasses: worn on the person, several at once
    "state.outfit": "list",
    "state.held": "list",
    "state.injury": "list",
    "state.location": "scalar",
    "state.mood": "scalar",
}
SLOT_HELP: dict[str, str] = {
    "identity.hair": "hair colour and style that stays the same (set); the value "
                     "names the colour or style, such as brown, not what the hair is doing",
    "identity.eyes": "eye colour (set)",
    "identity.build": "body type or height (set)",
    "identity.age": "stated or clearly described age (set)",
    "identity.marks": "a scar, tattoo or birthmark: one per claim (add)",
    "identity.accessories": "jewellery or an ornament worn on the person, such as hairpins, "
                            "beads in the hair, a ring, earrings, a necklace or glasses: one per "
                            "claim (add); not a garment, not something carried",
    "state.outfit": "a garment worn right now (add when put on, remove when taken off)",
    "state.held": "an item carried or held right now (add / remove)",
    "state.injury": "a wound or ailment, naming the body part, such as swollen left "
                    "ankle (add when hurt, remove when healed); not cold, fear or "
                    "being unclothed",
    "state.location": "the place the character is in now, such as a room, street or "
                      "building; not the light or the weather (set)",
    "state.mood": "a clearly stated emotional state right now (set)",
}
# Slots the Scribe is not asked about until they have been measured on a model (D-044). The slot is
# complete everywhere else (validator, card, corrections, panel): an author can already add one by hand.
OPTIONAL_SLOTS = ("identity.accessories",)
OPS = ("set", "add", "remove", "clear")
CONFIDENCE = ("low", "medium", "high")
MAX_CLAIMS = 24
MAX_ENTITY, MAX_VALUE, MAX_EVIDENCE = 120, 400, 400

_REFUSAL = re.compile(
    r"\b(i can(?:'|’)?t|i cannot|i(?:'|’)?m (?:sorry|unable|not able)|"
    r"i am (?:sorry|unable|not able)|i won(?:'|’)?t|as an ai|"
    r"i(?:'|’)?m not comfortable|cannot (?:assist|help|fulfil|fulfill))\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class Claim:
    entity: str
    slot: str
    op: str
    value: str
    evidence: str
    confidence: str


@dataclass
class Parsed:
    claims: list[Claim] = field(default_factory=list)
    rejects: list[dict] = field(default_factory=list)    # shape failures, with why
    # ok | empty_output | refusal | no_json | bad_shape
    status: str = "ok"


def slots(accessories: bool = False) -> dict[str, str]:
    """The slots the Scribe is asked about: all of them, less the optional ones unless asked for."""
    return {k: v for k, v in SLOTS.items() if accessories or k not in OPTIONAL_SLOTS}


def schema(accessories: bool = False) -> dict:
    """JSON Schema for constrained decoding. It removes the malformed-JSON failure
    class; it does not make the CONTENT right, which is what validate.py is for."""
    item = {
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "slot": {"type": "string", "enum": list(slots(accessories))},
            "op": {"type": "string", "enum": list(OPS)},
            "value": {"type": "string"},
            "evidence": {"type": "string"},
            "confidence": {"type": "string", "enum": list(CONFIDENCE)},
        },
        "required": ["entity", "slot", "op", "value", "evidence", "confidence"],
    }
    return {"type": "object",
            "properties": {"claims": {"type": "array", "maxItems": MAX_CLAIMS,
                                      "items": item}},
            "required": ["claims"]}


def op_ok(slot: str, op: str) -> bool:
    shape = SLOTS[slot]
    state = slot.startswith("state.")
    if shape == "scalar":
        return op == "set" or (op == "clear" and state)
    if slot in ("identity.marks", "identity.accessories"):
        return op == "add"
    return op in ("add", "remove") or (op == "clear" and state)


def _strip(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"```(?:json)?", "", text).strip()


def first_json(text: str):
    """The first complete JSON object or array in `text`, or None.

    A scan that respects strings and escapes, not a regex: a quoted brace inside
    an evidence span must not end the object early. A TRUNCATED object (the model
    ran out of tokens) has no closing brace and yields None, which is reported as
    a failure instead of being repaired into something that was never said.
    """
    for start, ch in enumerate(text):
        if ch not in "{[":
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        # fall through to the next opening bracket
    return None


def _one_line(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    out = " ".join(value.split())
    return out if len(out) <= limit else None


def parse(text: str) -> Parsed:
    out = Parsed()
    if not text or not text.strip():
        out.status = "empty_output"
        return out
    body = _strip(text)
    obj = first_json(body)
    if obj is None:
        out.status = "refusal" if _REFUSAL.search(body) else "no_json"
        return out
    items = obj.get("claims") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        out.status = "bad_shape"
        return out
    for n, raw in enumerate(items):
        if n >= MAX_CLAIMS:
            out.rejects.append({"index": n, "reason": "too_many_claims"})
            break
        if not isinstance(raw, dict):
            out.rejects.append({"index": n, "reason": "not_an_object"})
            continue
        entity = _one_line(raw.get("entity"), MAX_ENTITY)
        slot, op = raw.get("slot"), raw.get("op")
        conf = raw.get("confidence")
        value = _one_line(raw.get("value", ""), MAX_VALUE)
        evidence = _one_line(raw.get("evidence"), MAX_EVIDENCE)
        why = None
        if not entity:
            why = "bad_entity"
        elif slot not in SLOTS:
            why = "unknown_slot"
        elif op not in OPS:
            why = "unknown_op"
        elif conf not in CONFIDENCE:
            why = "bad_confidence"
        elif not evidence:
            why = "no_evidence"
        elif value is None:
            why = "bad_value"
        elif not op_ok(slot, op):
            why = "op_not_allowed_for_slot"
        elif op != "clear" and not value:
            why = "empty_value"
        if why:
            out.rejects.append({"index": n, "reason": why})
            continue
        out.claims.append(Claim(entity, slot, op, value, evidence, conf))
    return out

"""ST-01: SillyTavern character-card import — PNG(tEXt)/JSON parsing + normalize
+ the world mapping (scenario→premise, first_mes→intro, char→piece, book→lore)."""
import base64
import json
import os
import shutil
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import cards                             # noqa: E402
from coderain import templates                         # noqa: E402
from coderain.memory import Library, MemoryStore       # noqa: E402


def _png_with_text(keyword: str, text: str) -> bytes:
    """Minimal PNG: signature + one tEXt chunk + IEND (enough for the parser)."""
    def chunk(ctype: bytes, data: bytes) -> bytes:
        body = ctype + data
        return struct.pack(">I", len(data)) + body \
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    payload = keyword.encode("latin1") + b"\x00" + text.encode("latin1")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", payload) + chunk(b"IEND", b"")


# ---- a realistic V2 card ----
V2 = {
    "spec": "chara_card_v2",
    "data": {
        "name": "Captain Vale",
        "description": "A weathered sky-captain of the port city.",
        "personality": "gruff, loyal, secretly sentimental",
        "scenario": "{{user}} boards {{char}}'s airship at dawn.",
        "first_mes": "\"Welcome aboard,\" {{char}} grunts. \"Mind the rigging.\"",
        "mes_example": "<START>\n{{char}}: We sail at dawn.",
        "alternate_greetings": ["The deck creaks as you arrive."],
        "tags": ["adventure", "airship"],
        "character_book": {"entries": [
            {"keys": ["airship", "vessel"], "name": "The Dauntless",
             "content": "A patched but proud dirigible."},
            {"keys": ["port"], "content": "A fog-wrapped trade city."},
            {"keys": ["empty"], "content": ""},          # dropped (no content)
        ]},
    },
}

# ---- 1) parse from a PNG tEXt(chara=base64 json) ----
b64 = base64.b64encode(json.dumps(V2).encode("utf-8")).decode("ascii")
png = _png_with_text("chara", b64)
card = cards.parse_card(png, "vale.png")
assert card["name"] == "Captain Vale", card["name"]
assert card["scenario"].startswith("{{user}}"), card["scenario"]
assert len(card["lore"]) == 2, card["lore"]              # empty entry dropped
assert card["lore"][0]["title"] == "The Dauntless"
assert card["lore"][0]["keys"] == ["airship", "vessel"]
assert card["alternate_greetings"] == ["The deck creaks as you arrive."]
print("1) PNG(tEXt) V2 card parses + normalizes (lore, greetings, empties)")

# ---- 2) parse a raw-JSON V1 (flat) card ----
v1 = {"name": "Old Salt", "description": "A dockside storyteller.",
      "scenario": "A quiet tavern.", "first_mes": "Sit, {{user}}."}
card2 = cards.parse_card(json.dumps(v1).encode("utf-8"), "salt.json")
assert card2["name"] == "Old Salt" and card2["scenario"] == "A quiet tavern."
assert card2["lore"] == []
print("2) raw-JSON V1 (flat) card parses")

# ---- 3) macro substitution ----
s = cards.substitute_macros("{{User}} greets {{CHAR}}.", "Vale")
assert s == "you greets Vale.", s
print("3) {{char}}/{{user}} substitution (any case)")

# ---- 4) bad input rejected ----
for bad in [b"not a card", b"{}", b"\x89PNG\r\n\x1a\n"]:
    try:
        cards.parse_card(bad, "x")
        raise AssertionError("should have rejected: " + repr(bad[:8]))
    except ValueError:
        pass
print("4) non-card input raises ValueError")

# ---- 5) the world mapping (mirrors the server import) ----
root = os.path.join(tempfile.gettempdir(), "se_cards")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)


def _import(card):
    def sub(t): return cards.substitute_macros(t, card["name"])
    premise = sub(card["scenario"]) or sub(card["description"])
    slug = lib.scenarios.create(card["name"], premise,
                                introduction=sub(card["first_mes"]))
    store = MemoryStore(lib.scenarios.dir(slug), None, lib.scenarios.dir(slug))
    from coderain.memory import Entry
    store.upsert_entry("characters.md", Entry(
        title=card["name"], slug=templates.slugify(card["name"]), aliases=[],
        importance=4, attrs={}, body=sub(card["description"])))
    return slug, store


slug, store = _import(card)
assert lib.scenarios.exists(slug)
# premise carries the scenario with macros resolved
prem = store.read("premise.md")
assert "boards Captain Vale's airship" in prem, prem
# introduction (## Opening) has the substituted first_mes
assert "Welcome aboard" in store.opening_override(), store.opening_override()
# the character landed as a piece
chars = [e.title for e in store.entries("characters.md")]
assert "Captain Vale" in chars, chars
print("5) card → world: premise/intro/character mapped, macros resolved")

print("\nCARDS TESTS PASSED")

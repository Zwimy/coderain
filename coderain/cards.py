"""SillyTavern / Tavern character-card import (ST-01) — pure stdlib.

Parses a V1/V2/V3 character card from a PNG (embedded tEXt/zTXt/iTXt chunk keyed
`chara` or `ccv3`), a raw JSON file, or a `.charx` (zip with card.json) into a
normalized dict. No third-party deps, so it runs in the desktop bundle and (later)
under Pyodide. The mapping to a Coderain world lives in the server.
"""
from __future__ import annotations

import base64
import io
import json
import struct
import zlib
import zipfile

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_text_chunks(data: bytes) -> dict[str, str]:
    """{keyword: text} from a PNG's tEXt/zTXt/iTXt chunks (latin1/utf-8)."""
    out: dict[str, str] = {}
    if data[:8] != _PNG_SIG:
        return out
    i = 8
    while i + 12 <= len(data):
        (length,) = struct.unpack(">I", data[i:i + 4])
        ctype = data[i + 4:i + 8]
        chunk = data[i + 8:i + 8 + length]
        i += 12 + length
        if ctype == b"tEXt":
            key, _, val = chunk.partition(b"\x00")
            out.setdefault(key.decode("latin1"), val.decode("latin1"))
        elif ctype == b"zTXt":
            key, _, rest = chunk.partition(b"\x00")
            try:  # rest[0] = method byte, rest[1:] = zlib stream
                out.setdefault(key.decode("latin1"),
                               zlib.decompress(rest[1:]).decode("latin1"))
            except Exception:  # noqa: BLE001
                pass
        elif ctype == b"iTXt":
            parts = chunk.split(b"\x00", 5)
            if len(parts) == 6:
                text = parts[5]
                if parts[1][:1] == b"\x01":     # compression flag
                    try:
                        text = zlib.decompress(text)
                    except Exception:  # noqa: BLE001
                        pass
                out.setdefault(parts[0].decode("latin1"),
                               text.decode("utf-8", "replace"))
        elif ctype == b"IEND":
            break
    return out


def _b64_json(s: str) -> dict | None:
    try:
        return json.loads(base64.b64decode(s).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _extract_raw(data: bytes) -> dict | None:
    if data[:8] == _PNG_SIG:
        chunks = _png_text_chunks(data)
        for key in ("ccv3", "chara"):          # prefer V3, fall back to V2/V1
            if key in chunks:
                card = _b64_json(chunks[key])
                if card:
                    return card
        return None
    if data[:2] == b"PK":                       # zip / .charx
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                pick = next((n for n in names if n.endswith("card.json")),
                            next((n for n in names if n.endswith(".json")), None))
                if pick:
                    # Guard a zip bomb: a tiny .charx can declare a huge member.
                    if z.getinfo(pick).file_size > 64 * 1024 * 1024:
                        return None
                    return json.loads(z.read(pick).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _normalize(card: dict) -> dict:
    # V2/V3 nest fields under `data`; V1 is flat.
    d = card.get("data") if isinstance(card.get("data"), dict) else card

    def g(k: str) -> str:
        return str(d.get(k, "") or "").strip()

    lore = []
    book = d.get("character_book") or {}
    for e in (book.get("entries") or []):
        if not isinstance(e, dict):
            continue
        keys = e.get("keys") or e.get("key") or []
        keys = [keys] if isinstance(keys, str) else keys
        keys = [str(k).strip() for k in keys if str(k).strip()]
        content = str(e.get("content", "") or "").strip()
        if not content:
            continue
        lore.append({
            "title": str(e.get("name") or e.get("comment")
                         or (keys[0] if keys else "Lore")).strip() or "Lore",
            "keys": keys,
            "content": content,
        })
    greetings = [str(x).strip() for x in (d.get("alternate_greetings") or [])
                 if str(x).strip()]
    return {
        "name": g("name") or "Imported Character",
        "description": g("description"),
        "personality": g("personality"),
        "scenario": g("scenario"),
        "first_mes": g("first_mes"),
        "mes_example": g("mes_example"),
        "creator_notes": g("creator_notes"),
        "tags": [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()],
        "alternate_greetings": greetings,
        "lore": lore,
    }


def parse_card(data: bytes, filename: str = "") -> dict:
    """Normalized card dict, or ValueError if no card is found."""
    raw = _extract_raw(data)
    if not isinstance(raw, dict) or not (raw.get("data") or raw.get("name")):
        raise ValueError("no readable character card found in this file")
    return _normalize(raw)


def substitute_macros(text: str, char: str, user: str = "you") -> str:
    """Replace the two universal card macros ({{char}}/{{user}}, any case)."""
    import re
    text = re.sub(r"\{\{\s*char\s*\}\}", char, text, flags=re.IGNORECASE)
    text = re.sub(r"\{\{\s*user\s*\}\}", user, text, flags=re.IGNORECASE)
    return text

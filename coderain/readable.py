"""A story as a file a person reads.

The raw `transcript.md` is the engine's file: every turn sits in a marker comment, the player's lines carry a "> " prefix, and a
zero-width guard keeps model text from forging a marker. `MemoryStore.turns()` parses all of that away. This turns those parsed
turns into Markdown that reads the way the story did on screen and opens in any editor or notes app: a title, the player's
actions as quoted lines that start "You:", and the narration as plain paragraphs. It is pure (no disk, no engine), so it is
tested on its own.
"""
from __future__ import annotations


def story_markdown(title: str, turns: list[dict]) -> str:
    """Markdown for a story. A turn with no text is left out; the title is one line; the file ends with one newline."""
    head = " ".join(str(title or "").split()) or "Untitled story"
    parts = [f"# {head}"]
    for turn in turns:
        text = str(turn.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            continue
        if turn.get("role") == "player":
            lines = text.split("\n")
            lines[0] = f"**You:** {lines[0]}"
            # a quote keeps its blank lines as a bare ">" so a multi-paragraph action stays one quote
            parts.append("\n".join(f"> {ln}" if ln.strip() else ">" for ln in lines))
        else:
            parts.append(text)
    return "\n\n".join(parts) + "\n"

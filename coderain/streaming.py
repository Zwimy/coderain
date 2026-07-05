"""Transport-independent stream processing.

This is the pure, dependency-free core of the engine's streaming path: it turns a
raw model token stream into visible prose, suppressing `<think>...</think>`
reasoning even when the tags are split across chunk boundaries.

Two shapes over the *same* logic:

- `ThinkFilter` — a **push-based** filter: feed it arbitrary chunks (split
  anywhere) and it returns the visible text so far. This shape can be driven from
  an async/push source — e.g. a browser `fetch()` stream under Pyodide, where we
  cannot pull the next token from inside a synchronous generator.
- `filter_think(chunks)` — the original **pull-based** generator (`Iterator ->
  Iterator`), kept byte-identical for the desktop path, now implemented on top of
  `ThinkFilter`.

Keeping this module free of `openai`/`httpx`/`pydantic` is deliberate: it is the
slice of the engine that must run unmodified in-browser under Pyodide/WASM, where
those network deps don't load. See the Phase 6 spike in `spike/pyodide/`.
"""
from __future__ import annotations

from typing import Iterator

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


def _partial_tail(buffer: str, tag: str) -> int:
    """Longest suffix of `buffer` that could be the start of `tag`."""
    tail = 0
    for t in range(1, len(tag)):
        if buffer.endswith(tag[:t]):
            tail = t
    return tail


class ThinkFilter:
    """Stateful, split-safe `<think>...</think>` stripper.

    Feed it chunks in order (each may start/end anywhere, including mid-tag) and it
    returns the visible text unlocked by that chunk. State persists across calls, so
    it works when the chunks arrive one at a time from an async source.

    Behaviour matches the `filter_think` generator exactly: a partial tag prefix at
    the boundary is held back until it resolves, and a trailing partial prefix left
    over at end-of-stream is dropped (it can only be an incomplete tag, never real
    prose — non-prefix content is always emitted immediately).
    """

    def __init__(self) -> None:
        self.in_think = False
        self.buffer = ""

    def feed(self, piece: str) -> str:
        """Consume one chunk; return the visible text it unlocks (may be "")."""
        if not piece:
            return ""
        out: list[str] = []
        self.buffer += piece
        while self.buffer:
            if self.in_think:
                end = self.buffer.find(THINK_CLOSE)
                if end == -1:
                    tail = _partial_tail(self.buffer, THINK_CLOSE)
                    self.buffer = self.buffer[-tail:] if tail else ""
                    break
                self.buffer = self.buffer[end + len(THINK_CLOSE):]
                self.in_think = False
            else:
                start = self.buffer.find(THINK_OPEN)
                if start == -1:
                    tail = _partial_tail(self.buffer, THINK_OPEN)
                    safe = self.buffer[:-tail] if tail else self.buffer
                    self.buffer = self.buffer[-tail:] if tail else ""
                    if safe:
                        out.append(safe)
                    break
                if start > 0:
                    out.append(self.buffer[:start])
                self.buffer = self.buffer[start + len(THINK_OPEN):]
                self.in_think = True
        return "".join(out)

    def flush(self) -> str:
        """Signal end-of-stream. Any remainder is a partial tag prefix, so nothing
        visible is left to emit; returns "" (kept for symmetry with `feed`)."""
        return ""


def filter_think(chunks: Iterator[str]) -> Iterator[str]:
    """Yield visible text from a token stream, suppressing `<think>...</think>`
    reasoning even when the tags are split across chunk boundaries.

    Pull-based wrapper over `ThinkFilter` for the desktop/CLI path; unchanged API.
    """
    f = ThinkFilter()
    for piece in chunks:
        visible = f.feed(piece)
        if visible:
            yield visible
    tail = f.flush()
    if tail:
        yield tail

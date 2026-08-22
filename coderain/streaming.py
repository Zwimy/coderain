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


def json_objects(s: str):
    """Yield each brace-balanced ``{...}`` substring of `s`, in order.

    String-aware, so a brace inside a JSON string value doesn't shift the depth
    count and an escaped quote doesn't end the string early.

    This lives here — the dependency-free core — because it had TWO homes and
    they disagreed. sidecar.py scanned properly; llm.extract_json used
    ``re.compile(r"\\{.*\\}", re.DOTALL)`` while its docstring claimed to be
    "brace-balanced". That regex is greedy: on ``{"a": 1} trailing text }`` it
    spans from the first brace to the LAST one and parses nothing, so a model
    that appends a sentence after valid JSON reads as a total failure. Two copies
    of one rule, and the fold path had the weaker one.
    """
    depth = start = 0
    in_str = esc = False
    for i, c in enumerate(s):
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
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth:
            depth -= 1
            if depth == 0:
                yield s[start:i + 1]


def first_json_object(s: str) -> str | None:
    """The first brace-balanced ``{...}`` object, or None."""
    for obj in json_objects(s):
        return obj
    return None


def prompt_line_set(text: str) -> set[str]:
    """The distinct non-blank lines of a prompt, for `filter_context_echo`."""
    return {ln.strip() for ln in text.splitlines() if ln.strip()}


def system_line_set(messages: list[dict]) -> set[str]:
    """Lines from the engine-authored system messages AFTER the assembled one.

    These are directives we write ourselves and append at the tail — the lore
    directive and the chapter directive — placed there precisely because the
    last thing a model reads binds hardest on the next tokens. That position is
    also what made them the most echo-prone text in the prompt, and the filter
    could not see them: it was built from messages[0] alone.

    The transcript is still excluded on purpose. Matching against user and
    assistant turns would let a legitimately repeated line be deleted as an echo.
    """
    out: set[str] = set()
    for m in (messages or [])[1:]:
        if m.get("role") != "system":
            continue
        out |= prompt_line_set(str(m.get("content") or ""))
    return out


def _is_echo(line: str, prompt_lines: set[str],
             directive_lines: frozenset | set = frozenset()) -> bool:
    """Is this line context we generated, copied back verbatim?

    Membership is the whole test — we only ever delete text we put in the prompt
    ourselves, so this cannot eat model-written prose. The two extra conditions
    guard the coincidence case, where a short prose sentence happens to repeat a
    context line exactly:

    - a real sentence ends in terminal punctuation; a `## Time` header or a
      `stats: strength 1` attr line does not.
    - the scaffolding lines are all short. 200 is the same bound `_one_line`
      uses for a rendered attr value.

    `directive_lines` is exempt from the punctuation rule, and has to be. The
    tail directives are written AS SENTENCES — "Every scene must move toward
    that goal, complicate it, or pay it off." — so the punctuation guard, which
    assumes scaffolding never looks like prose, protected them from removal.
    Reported live: a whole chapter directive rendered into the story, heading
    and all. Exact-matching a 100-character line we wrote is not coincidence,
    which is what makes the exemption safe; the 200-char bound still applies,
    only a LEADING run is ever dropped, and every drop is logged.
    """
    s = line.strip()
    if not s or len(s) > 200:
        return False
    if s in directive_lines:
        return True
    if s[-1] in ".!?\"'”’":
        return False
    return s in prompt_lines


def filter_context_echo(chunks: Iterator[str], prompt_lines: set[str],
                        dropped_out: list[str],
                        directive_lines: frozenset | set = frozenset()
                        ) -> Iterator[str]:
    """Drop context scaffolding the model copied back at the START of its prose.

    Small local models mimic the structure they are shown. Measured in a 14-turn
    llama3.1:8b run: the opening reproduced the `## You {#player}` sheet verbatim
    — heading, `importance:`, `stats:`, the lot — and then EVERY ONE of the 14
    turns opened with the `## Time` / `Current in-world time:` block. A 3-turn
    run of the same model whose opening happened to come out clean leaked nothing
    afterwards, so one bad opening appears to prime the transcript, which is then
    few-shot evidence for the next turn. Nothing stripped it, so it reached the
    reader, the transcript, and every fold built on that transcript.

    Only a LEADING run is dropped, and only lines that appear verbatim in the
    prompt; the first line that isn't one switches this to a pass-through for the
    rest of the stream. Anything dropped goes to `dropped_out` so the caller can
    log it — an invisible deletion of model output would be its own invariant-2
    bug.
    """
    buffer, passthrough = "", False
    for piece in chunks:
        if not piece:
            continue
        if passthrough:
            yield piece
            continue
        buffer += piece
        # Only decide on COMPLETE lines: a chunk boundary mid-line would
        # otherwise judge "## Ti" as prose and unblock the whole filter.
        while "\n" in buffer and not passthrough:
            line, rest = buffer.split("\n", 1)
            if _is_echo(line, prompt_lines, directive_lines):
                dropped_out.append(line.strip())
                buffer = rest
            elif line.strip():
                passthrough = True
            else:
                buffer = rest          # leading blank line, drop silently
        if passthrough and buffer:
            yield buffer
            buffer = ""
    # End of stream. A single-line reply never hit the newline branch above, so
    # it still has to be judged — otherwise a turn that IS nothing but an echoed
    # header would be emitted whole.
    if buffer and not (not passthrough
                       and _is_echo(buffer, prompt_lines, directive_lines)):
        yield buffer
    elif buffer:
        dropped_out.append(buffer.strip())

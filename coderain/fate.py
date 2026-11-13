"""Fate (D-045): a hidden, dice-driven nudge to where the next turn goes.

The owner's idea, built from three architects' proposals and their critiques. A D20 is rolled by the engine,
the result picks a KIND of development, and one model call writes a single sentence of that kind. The Writer is
told it as hidden steering and never sees a die:

    1-2    setback    something goes wrong in the world (a delay, a loss of position, a failed attempt)
    3-10   natural    the natural, expected continuation
    11-18  surprise   a surprising but harmless development
    19-20  windfall   a small stroke of luck

What is deliberate (each of these was argued and settled, see D-045):
  * The roll is DERIVED, never stored as state: Random(seed, turn, action, nonce). The same action at the same
    point of the same story always rolls the same die, so retry, swipe, undo-and-redo and a branch agree, and
    the replay ledger (memory/events.jsonl, which describes state) is never touched. A different action at the
    same point rolls again.
  * The sentence is cached in memory/fate.jsonl, keyed by (turn, action, the narration before it). A retry or a
    swipe is a cache hit: same tier, same sentence, no model call, new prose. A stale record is only a miss.
  * Roll first, then ONE sentence of the rolled kind (not four sentences and a pick): a quarter of the output,
    and the planner already learned that one malformed element must not cost a batch.
  * The model's `stakes` label (none or some) can only switch a setback or a windfall OFF (a quiet scene gets no
    steering that turn). It never widens a band. A missing or invalid label counts as none.
  * Pure code decides what is acceptable: one line, 300 characters at most, an event rather than a label or the
    player's own action, not a repeat of a recent direction (planner._restates), and a setback that kills or removes
    anyone the story protects is vetoed. An unusable first answer gets one more try that names what was wrong (D-053).
  * It is off by default. `meta.json` holds the per-save mode (off, preview or on) and whether to show the die.
    Preview rolls, asks the model and records, and sends the Writer nothing.
  * Any failure leaves the turn exactly as if fate were off, and says so in memory/health.jsonl (invariant 2).

Standard library plus the engine's own JSON-stage helper.
"""
from __future__ import annotations

import hashlib
import json
import random
import re

from .llm import emit_json_ex
from .llm import stage as llm_stage
from .planner import _restates

MODES = ("off", "preview", "on")
# (tier, lowest face, highest face). Fixed in v1: the owner's 10 / 40 / 40 / 10, with his overlapping
# "10 to 18" read as 11 to 18.
BANDS = (("setback", 1, 2), ("natural", 3, 10), ("surprise", 11, 18), ("windfall", 19, 20))
STEERED_ONLY_WITH_STAKES = ("setback", "windfall")      # a quiet scene switches these two off
MAX_TEXT = 300              # measured (D-053): asked for 20 words, a 4B and an 8B model write 25 to 45
MIN_WORDS = 3               # "help arrives" is a label, not a direction
ATTEMPTS = 2                # the second names what was wrong with the first
KEEP = 100                  # records kept in memory/fate.jsonl
RECENT_DIRECTIONS = 3       # how many earlier directions a new one may not restate
FATE_TOKENS = 700           # the call's answer budget: one short JSON object, and a little room
CONTEXT_CHARS = 12_000
FILE = "memory/fate.jsonl"

# What each kind of development is. The first sentence names it; the model has copied that sentence into its answer as a
# label ("a surprising but harmless development: ..."), so clean_line strips and refuses that echo (D-053).
_KIND = {
    "setback": ("a setback. Something goes wrong for the player in the world: a plan is blocked, someone refuses "
                "or objects, something is lost, broken or delayed, or a risky attempt fails. Never kill, cripple "
                "or remove anything important"),
    "natural": ("the ordinary next beat. The people present answer or act the way anyone would, and the scene moves "
                "on without a twist"),
    "surprise": ("an unexpected but harmless development. A new person, object or fact turns up and changes what "
                 "the scene is about, and it neither helps nor hurts the player much"),
    "windfall": ("a small stroke of luck for the player. Someone helps, a door opens, a useful thing is found or "
                 "offered, or a problem solves itself"),
}
# One line per kind from a different story, so a small model learns the SHAPE (an event: somebody does something) and has
# nothing in it to copy into this one.
_EXAMPLE = {
    "setback": "The border guard spots the forged stamp and calls for his captain.",
    "natural": "The innkeeper answers the question and names a price for the room.",
    "surprise": "A child pushes through the crowd and presses a folded note into a traveller's hand.",
    "windfall": "The merchant, charmed by the story, waives the fee and offers a fresh horse.",
}

FATE_SYS = """\
You write ONE hidden steering line for an interactive story. The dice have chosen what happens next: {kind}.

Read the scene and the player's action, then write a single sentence (at most 20 words) saying what happens next \
in the world. It must be an EVENT: a person or thing does something that changes the situation (someone arrives, \
speaks, refuses, offers, finds, drops, blocks, breaks). Weather, sounds, smells, moods and descriptions are not \
events; mention the weather only when it blocks or breaks something.

Example of the shape, from another story (never copy its content): {example}

Rules: never write what the player does, thinks or feels, and never begin with "You"; write the sentence alone, \
with no label and no colon; never mention dice, luck, odds, fate or this note; stay consistent with the story \
context and the chapter goal.

Also judge whether the player's action carries any risk or stakes. Use "none" for quiet actions (talking, \
looking, resting, travelling without trouble) and "some" otherwise.

Answer with JSON only: {{"stakes": "none" or "some", "direction": "the one sentence"}}\
"""

_LETHAL = re.compile(r"\b(kill\w*|die[sd]?|dying|dead|death|murder\w*|execut\w*|slain|slay\w*|maim\w*|cripple\w*|"
                     r"destroy\w*|doom\w*|behead\w*|fatal\w*|perish\w*)\b", re.IGNORECASE)
_LEAK = re.compile(r"\b(d20|dice|the roll of|natural twenty)\b", re.IGNORECASE)


# --- the die -----------------------------------------------------------------
def tier_of(roll: int) -> str:
    for name, lo, hi in BANDS:
        if lo <= roll <= hi:
            return name
    raise ValueError(f"not a d20 face: {roll!r}")


def _h(text: str, n: int) -> str:
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:n]


def derive_roll(seed, n: int, action: str, nonce: int = 0) -> int:
    """The d20 for the player's action at turn `n`. Same inputs, same face; any other action, turn or nonce rolls
    again. (`seed` is the save's rpg seed, the same one macros and the RPG checks already use.)"""
    return random.Random(f"{seed}-{n}-fate-{_h(action, 12)}-{nonce}").randint(1, 20)


def exchange_key(n: int, action: str, before: str) -> str:
    """Identifies one exchange for the cache: where it is, what the player did, and the narration it follows."""
    return f"{n}:{_h(action, 12)}:{_h(before, 8)}"


# --- what is sent to the model, and what comes back --------------------------
def build_messages(context: str, recent: list[dict], card: str, chapter: str, action: str, tier: str,
                   avoid: list[str], offender: str = "", no_think: bool = True, note: str = "") -> list[dict]:
    system = FATE_SYS.format(kind=_KIND[tier], example=_EXAMPLE[tier]) + ("\n\n/no_think" if no_think else "")
    parts = ["STORY CONTEXT:\n" + context[-CONTEXT_CHARS:]]
    if card:
        parts.append("WHO IS IN THE SCENE:\n" + card)
    if chapter:
        parts.append("CHAPTER GOAL:\n" + chapter)
    shown = [f"{'Player' if m.get('role') == 'user' else 'Narrator'}: {str(m.get('content') or '')[:1500]}"
             for m in recent[-6:] if m.get("role") in ("user", "assistant")]
    if shown:
        parts.append("RECENT TURNS:\n" + "\n".join(shown))
    parts.append("PLAYER ACTION:\n" + action)
    if avoid:
        parts.append("EARLIER DIRECTIONS (write something different):\n" + "\n".join(f"- {a}" for a in avoid))
    if offender:
        parts.append(f'YOUR LAST ANSWER REPEATED "{offender}". Write a different direction.')
    if note:
        parts.append(f"YOUR LAST ANSWER WAS REFUSED: {note}. Answer again, following the rules.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


# The model echoes the description it was given as a label ("a surprising but harmless development: ...", "a small
# stroke of luck for the player: ..."). An exact label at the very start is dropped; one inside the sentence cannot be
# cut out cleanly, so that line is refused (the phrases below).
_LABEL = re.compile(r"^(?:an? |the )?(?:setback|surprise|windfall|surprising(?: but harmless)?(?: development)?"
                    r"|unexpected but harmless development|small stroke of luck(?: for the player)?"
                    r"|ordinary next beat)\s*:\s*", re.IGNORECASE)
_ECHOES = ("harmless development", "stroke of luck", "ordinary next beat", "a setback:")
_YOU_FIRST = re.compile(r"^you(?:'re|'ve|'ll|'d)?\b", re.IGNORECASE)      # "Your pack is lost" is a setback, not this


def _unlabel(s: str) -> str:
    return _LABEL.sub("", s, count=1)


def clean_line(text) -> tuple[str, str]:
    """(one clean line, "") or ("", why not). Bounded here because the line is rendered into the Writer's
    prompt: one line, no fences, headings or lists, at most MAX_TEXT characters. Also refused, each seen in a real
    run (D-053): a leftover kind label, a line too short to be an event, one that stops mid-sentence, and one whose
    subject is the player (the Writer owns what the player does)."""
    if not isinstance(text, str):
        return "", "no direction"
    s = " ".join(text.split()).strip(" \t\"'")
    s = re.sub(r"^[-*#>\s]+", "", s)
    s = _unlabel(s).strip(" \t\"'")
    if not s:
        return "", "empty direction"
    if "```" in s or "`" in s:
        return "", "a code fence in the direction"
    if len(s) > MAX_TEXT:
        return "", f"the direction is {len(s)} characters (limit {MAX_TEXT})"
    low = s.lower()
    if any(w in low for w in _ECHOES):
        return "", "the direction repeats the description of its kind"
    if len(s.split()) < MIN_WORDS:
        return "", f"the direction is under {MIN_WORDS} words"
    if s.endswith((":", ",", "-", chr(0x2013), chr(0x2014))):   # a cut-off line (a trailing en or em dash included)
        return "", "the direction stops mid-sentence"
    if _YOU_FIRST.match(s):
        return "", "the direction describes what the player does"
    return s, ""


def parse_reply(obj) -> tuple[str, str, str]:
    """(stakes, direction, why). `stakes` is 'some' only when the model said so: anything else counts as none."""
    if not isinstance(obj, dict):
        return "none", "", "the reply was not a JSON object"
    stakes = "some" if str(obj.get("stakes", "")).strip().lower() == "some" else "none"
    text, why = clean_line(obj.get("direction"))
    return stakes, text, why


def armour(text: str, tier: str, protected) -> str:
    """The lethal word that vetoes a setback aimed at someone the story protects (the player or any pinned or
    critical entry), or "". A lead, not a verdict: it errs towards no steering."""
    if tier != "setback":
        return ""
    m = _LETHAL.search(text)
    if not m:
        return ""
    low = text.lower()
    for name in list(protected) + ["you", "your"]:
        if name and re.search(rf"\b{re.escape(str(name).lower())}\b", low):
            return m.group(0)
    return ""


def repeats(text: str, recent: list[str]) -> str:
    """The phrase a new direction shares with a recent one (three content words in a row), or ""."""
    return _restates(text, [r for r in recent if r])


def leaks(prose: str, text: str) -> bool:
    """Did the prose say the mechanism aloud, or copy the steering line (six words in a row)? Logged, never edited."""
    if _LEAK.search(prose or ""):
        return True
    words = re.findall(r"[a-z']+", (text or "").lower())
    body = " " + " ".join(re.findall(r"[a-z']+", (prose or "").lower())) + " "
    return any(" " + " ".join(words[i:i + 6]) + " " in body for i in range(len(words) - 5))


def directive(text: str) -> str:
    """The hidden steering message for the Writer. It never carries the die, and says what it must not override."""
    return ("Hidden steering for this turn (never mention it, dice, luck, odds or fate in the story): "
            f"{text} Show it through action and consequence in the scene. It does not override the chapter goal "
            "or continuity above. Do not kill, cripple or remove anything the story marks important; pay in "
            "time, position, trust or resources.")


# --- the cache file and the per-save setting ---------------------------------
def _path(store):
    return store.dir / "memory" / "fate.jsonl"


def read(store) -> list[dict]:
    try:
        lines = _path(store).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("n"), int) and isinstance(rec.get("key"), str):
            out.append(rec)
    return out


def _write(store, recs: list[dict]) -> None:
    p = _path(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs[-KEEP:]), encoding="utf-8")


def get(store, key: str) -> dict | None:
    return next((r for r in reversed(read(store)) if r["key"] == key), None)


def put(store, rec: dict) -> None:
    """Add a record (replacing any with the same key), keeping the newest KEEP."""
    _write(store, [r for r in read(store) if r["key"] != rec["key"]] + [rec])


def prune(store, max_n: int) -> int:
    """Drop records for exchanges past the transcript's end (after an undo, an edit or a branch). Retry and swipe
    do NOT call this: they need the record they are about to reuse. Returns how many were dropped."""
    recs = read(store)
    kept = [r for r in recs if r["n"] <= max_n]
    if len(kept) != len(recs):
        _write(store, kept)
    return len(recs) - len(kept)


def recent_directions(store, before_n: int, k: int = RECENT_DIRECTIONS) -> list[str]:
    """The last k directions actually chosen before turn `before_n`, oldest first."""
    chosen = [r for r in read(store) if r["n"] < before_n and r.get("text")]
    chosen.sort(key=lambda r: r["n"])
    return [r["text"] for r in chosen[-k:]]


def settings(store) -> dict:
    """The save's fate setting from meta.json: {'mode': off|preview|on, 'show_die': bool}. Anything missing or
    malformed is off. In meta.json, like `mode`, because a branch copies it whole (a state.json key would be
    reverted to the snapshot's value)."""
    try:
        raw = json.loads(store.read("meta.json")).get("fate")
    except (json.JSONDecodeError, AttributeError):
        raw = None
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("mode", "off")).strip().lower()
    return {"mode": mode if mode in MODES else "off", "show_die": raw.get("show_die") is True}


def set_settings(store, mode: str | None = None, show_die: bool | None = None) -> dict:
    if mode is not None and str(mode).strip().lower() not in MODES:
        raise ValueError(f"fate mode must be one of {', '.join(MODES)}")
    try:
        meta = json.loads(store.read("meta.json"))
    except json.JSONDecodeError:
        meta = {}
    cur = settings(store)
    new = {"mode": str(mode).strip().lower() if mode is not None else cur["mode"],
           "show_die": bool(show_die) if show_die is not None else cur["show_die"]}
    meta["fate"] = new
    store.write("meta.json", json.dumps(meta, indent=2))
    return new


# --- the stage ---------------------------------------------------------------
def event_line(rec: dict, mode: str, show_die: bool) -> str | None:
    """The one line the player sees in the turn's event bar, or None. Preview shows everything; on shows the die
    only when the save asks for it, and never the sentence."""
    quiet = not rec.get("text")
    if mode == "preview":
        body = ("quiet scene, no steering" if quiet else f"{rec['tier']}: {rec['text']}")
        return f"fate (preview) d20 {rec['roll']}: {body}"
    if mode == "on" and show_die:
        return f"fate d20 {rec['roll']}: " + ("quiet scene" if quiet else rec["tier"])
    return None


def _model_name(llm) -> str:
    """The model that wrote the line. The real client keeps it on its profile; a test stub has it as `model`. (The
    record's field was blank on every real run until a preview showed it, D-053.)"""
    name = getattr(getattr(llm, "profile", None), "model", "") or getattr(llm, "model", "") or ""
    return str(name)[:80]


def run_stage(store, llm, messages: list[dict], action: str, *, seed, card: str = "", chapter: str = "",
              protected=(), no_think: bool = True, on_stage=None) -> tuple[dict | None, str | None]:
    """The whole stage for one player action. Returns (record, None) with a record to inject or show, or
    (None, why) when there is nothing (a failure, a veto): the turn then runs as if fate were off.

    A cache hit costs no model call. A miss rolls (derived), asks the model for one direction of that kind (at most
    two tries, the second naming a repeat), and validates in pure code. Never raises."""
    import time
    turns = store.turns()
    n = len(turns)                                      # the player's turn has just been appended
    before = next((t["text"] for t in reversed(turns[:-1]) if t["role"] == "narrator"), "")
    key = exchange_key(n, action, before)
    hit = get(store, key)
    if hit is not None:
        return hit, None
    roll = derive_roll(seed, n, action)
    tier = tier_of(roll)
    t0 = time.monotonic()
    if on_stage:
        on_stage("Fate: weighing the next turn")
    avoid = recent_directions(store, n)
    recent = [m for m in messages[1:] if m.get("role") in ("user", "assistant")]
    offender, note, why = "", "", ""
    text, stakes = "", "none"
    try:
        # A second try for ANY unusable first answer, naming what was wrong. Measured on a 4B and an 8B model (D-053):
        # with no second try a third of the exchanges got no direction at all, mostly lines a few characters over the
        # limit or a reply in the wrong JSON shape, and every one of those is fixed by asking once more.
        for _ in range(ATTEMPTS):
            convo = build_messages(messages[0]["content"] if messages else "", recent, card, chapter, action,
                                   tier, avoid, offender, no_think, note)
            with llm_stage(llm, "fate"):
                obj, err = emit_json_ex(llm, "", messages=convo, retry=0, max_tokens=FATE_TOKENS)
            offender, note = "", ""
            if obj is None:
                why = f"no usable reply: {err}"
                if str(err).startswith("model call failed"):
                    return None, why            # the server is down or stuck: asking again only doubles the wait
                note = "it was not a JSON object holding a direction"
                continue
            stakes, text, bad = parse_reply(obj)
            if bad:
                why = note = bad
                continue
            offender = repeats(text, avoid)
            if offender:
                why = f"the direction repeated an earlier one ({offender!r})"
                continue
            why = ""
            break
        else:
            return None, why
    except Exception as e:  # noqa: BLE001 - fate must never cost a turn
        return None, f"{type(e).__name__}: {e}"
    quiet = tier in STEERED_ONLY_WITH_STAKES and stakes != "some"
    vetoed = armour(text, tier, protected)
    if vetoed:
        return None, f"a setback naming a protected character with {vetoed!r} was vetoed"
    rec = {"n": n, "key": key, "nonce": 0, "roll": roll, "tier": tier, "stakes": stakes,
           "text": "" if quiet else text, "model": _model_name(llm)}
    put(store, rec)
    if on_stage:
        on_stage(f"Fate done ({time.monotonic() - t0:.1f}s): d20 {roll}, {'quiet scene' if quiet else tier}")
    return rec, None

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
  * Pure code decides what is acceptable: one line, 200 characters at most, not a repeat of a recent direction
    (planner._restates), and a setback that kills or removes anyone the story protects is vetoed.
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
MAX_TEXT = 200
KEEP = 100                  # records kept in memory/fate.jsonl
RECENT_DIRECTIONS = 3       # how many earlier directions a new one may not restate
FATE_TOKENS = 700           # the call's answer budget: one short JSON object, and a little room
CONTEXT_CHARS = 12_000
FILE = "memory/fate.jsonl"

_KIND = {
    "setback": ("a setback: something goes wrong for the player in the world, such as a complication, a delay, "
                "a loss of position, or a failed attempt if they were trying something risky. Never kill, "
                "cripple or remove anything important, and do not decide what the player thinks or does"),
    "natural": "the natural, expected continuation of the scene",
    "surprise": ("a surprising but harmless development: something unexpected happens that neither helps nor "
                 "hurts the player much"),
    "windfall": ("a small stroke of luck for the player: help arrives, a useful detail turns up, or an "
                 "advantage opens"),
}

FATE_SYS = """\
You write ONE hidden steering line for an interactive story. Read the scene and the player's action, then write \
a single sentence (at most 25 words) saying what happens next, of this kind: {kind}.

Rules: write what happens in the world, not the player's feelings; never narrate the player's own actions; never \
mention dice, luck, odds, fate or this note; stay consistent with the story context and the chapter goal.

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
                   avoid: list[str], offender: str = "", no_think: bool = True) -> list[dict]:
    system = FATE_SYS.format(kind=_KIND[tier]) + ("\n\n/no_think" if no_think else "")
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
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


def clean_line(text) -> tuple[str, str]:
    """(one clean line, "") or ("", why not). Bounded here because the line is rendered into the Writer's
    prompt: one line, no fences, headings or lists, at most MAX_TEXT characters."""
    if not isinstance(text, str):
        return "", "no direction"
    s = " ".join(text.split()).strip(" \t\"'")
    s = re.sub(r"^[-*#>\s]+", "", s)
    if not s:
        return "", "empty direction"
    if "```" in s or "`" in s:
        return "", "a code fence in the direction"
    if len(s) > MAX_TEXT:
        return "", f"the direction is {len(s)} characters (limit {MAX_TEXT})"
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
    offender, text, stakes = "", "", "none"
    try:
        for attempt in range(2):
            convo = build_messages(messages[0]["content"] if messages else "", recent, card, chapter, action,
                                   tier, avoid, offender, no_think)
            with llm_stage(llm, "fate"):
                obj, err = emit_json_ex(llm, "", messages=convo, retry=0, max_tokens=FATE_TOKENS)
            if obj is None:
                return None, f"no usable reply: {err}"
            stakes, text, why = parse_reply(obj)
            if why:
                return None, why
            offender = repeats(text, avoid)
            if not offender:
                break
        else:
            return None, f"the direction repeated an earlier one ({offender!r})"
    except Exception as e:  # noqa: BLE001 - fate must never cost a turn
        return None, f"{type(e).__name__}: {e}"
    quiet = tier in STEERED_ONLY_WITH_STAKES and stakes != "some"
    vetoed = armour(text, tier, protected)
    if vetoed:
        return None, f"a setback naming a protected character with {vetoed!r} was vetoed"
    rec = {"n": n, "key": key, "nonce": 0, "roll": roll, "tier": tier, "stakes": stakes,
           "text": "" if quiet else text, "model": str(getattr(llm, "model", "") or "")[:80]}
    put(store, rec)
    if on_stage:
        on_stage(f"Fate done ({time.monotonic() - t0:.1f}s): d20 {roll}, {'quiet scene' if quiet else tier}")
    return rec, None

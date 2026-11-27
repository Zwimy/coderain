"""The model check: a fixed set of prompts to run when you switch models, scored by code (D-079).

Why. A new model can be worse in ways that show only after many turns, or never visibly: it forgets who holds what, lets a
character repeat a secret they were never told, writes your lines for you, or returns a memory summary the app cannot read (the
turn goes on and the memory quietly thins). The play soak finds these, in an hour a run. This asks the same fixed questions of
every model, through the real engine with the app's shipped memory settings, in minutes, and compares the answers with the last
model checked.

    python -m soak check --model NAME [--repeats 2] [--think on|off] [--host http://localhost:11434]
                         [--against REPORT|none] [--out DIR] [--set NAME=VALUE ...] [--predict CHECK=WORD ...]
    python -m soak check --provider openrouter --model NAME:free
    python -m soak check --stub good|bad          (no model: what the tests use)

Every run uses the same invented story (the soak's town, ties, possessions and two secrets, with the letter's secret changed;
see LETTER_TOKEN), the same actions and the same sampler settings, so two reports differ by the model and chance. Each check is
scored by code, pass or fail per reply. With a few replies a check, one reply either way is noise: a change is called worse or
better only when the share of passes moves by a quarter AND by at least two replies.

Two options for testing a change rather than a model (D-081). --set runs with one setting changed and compares with the same
model without it, to ask whether a fix tuned on one model still helps another. --predict writes down what you expect before the
first reply, and the report says which predictions held: a result nobody predicted is a new question, not a confirmation.

The story is invented and nothing is read from a save. Reports go to model-checks/ (ignored by git) unless --out says otherwise.
"""
from __future__ import annotations

import json
import re
import statistics
import time
import urllib.request
from pathlib import Path

from soak import graph_probe as gp
from soak import hosted
from soak.play import CAST, PREMISE, _require_local, repeat_share, sheet_attrs, sheet_body

# Bump when a prompt, the story or a scorer changes: reports made by different versions are not compared. 2: after the first
# real run, the letter's secret, the names scored, the text read for prompt leftovers, and the status block check.
PACK_VERSION = 2
REPORTS = "model-checks"
SHORT_WORDS, SHORT_PARAGRAPHS = 250, 3              # "1-2 short paragraphs" is what the short setting asks for
LONG_WORDS, LONG_PARAGRAPHS = 350, 4                # "4-6 paragraphs" is what the long setting asks for; either measure passes
REPEAT_LIMIT = 0.02                                 # share of 8-word runs a reply copied from the reply before it
NEEDS_YOU = 40                                      # words of narration past which a reply that never says "you" is off

# key -> what the report calls it. The order is the report's order.
CHECKS = {
    "ties": "Answers who is tied to whom",
    "holds": "Answers who is carrying what",
    "two_steps": "Answers two-step questions",
    "remembers": "A character told a secret remembers it",
    "keeps_quiet": "A secret stays unsaid when you ask someone never told it",
    "your_words": "Leaves your words and choices to you",
    "in_story": "Stays in the story (no refusals or assistant talk)",
    "speaks_to_you": "Writes about \"you\", never as \"I\"",
    "no_prompt_text": "No prompt or markup text reaches you",
    "finishes": "Finishes its last sentence",
    "status_block": "Sends the hidden status block the app reads",
    "short": "Keeps short replies short",
    "long": "Writes longer replies when asked",
    "no_copying": "Does not copy its own last reply",
    "summary": "Memory summaries come back readable",
    "chapter": "Chapter plans come back readable",
    "director": "The planning step comes back readable (quad mode)",
}
PROBE_CHECKS = {"R1": "ties", "R2": "ties", "P1": "holds", "P2": "holds", "H1": "two_steps", "H3": "two_steps",
                "K1": "remembers", "K2": "remembers", "L1": "keeps_quiet", "L2": "keeps_quiet", "L3": "keeps_quiet",
                "L4": "keeps_quiet"}
# The soak's questions, with the letter's secret changed. There the letter is for "the keeper of the north beacon", and one of
# the cast keeps the lighthouse, so in the first real run "it is for Maribel Voss" was scored as forgotten when the one told said
# it, and as kept when someone never told said it. Here it goes to somebody who is nobody in the story.
LETTER_TOKEN = "glassblower"
LETTER_TELL = ("I whisper to Bram Halloran, so that no one else hears, that the sealed letter is addressed to the old "
               "glassblower in Saltreach.")
PROBES = {gid: dict(gp.PROBES[gid], token=LETTER_TOKEN) if gp.PROBES[gid].get("secret") == "letter" else gp.PROBES[gid]
          for gid in PROBE_CHECKS}
# Other ways a reply names someone by their work. The same run scored a right answer ("the keeper of the lighthouse") as none.
ALSO_CALLED = {"Ottoline Pike": ["the ferry woman", "the ferry-woman"], "Bram Halloran": ["the customs man", "the customs official"],
               "Dessa Quill": ["the salt merchant"], "Maribel Voss": ["the keeper of the lighthouse", "the lighthouse-keeper"],
               "Hollis Wren": ["the keeper of the tavern", "the tavern-keeper"]}
SCORING_CAST = [(name, slug, [*aliases, *ALSO_CALLED.get(name, [])], *rest) for name, slug, aliases, *rest in CAST]
# What a run may change with --set, to ask whether a setting still helps this model. Only settings this short story can show
# something about: it is too short for story search, background summaries or the history cut to matter.
SETTABLE = ("memory.follow_links", "memory.tail_ties", "generation.prompt_layout", "generation.temperature", "generation.top_p",
            "generation.max_tokens", "generation.min_p", "generation.repetition_penalty", "generation.json_mode",
            "generation.tic_guard")
PREDICTIONS = ("better", "worse", "same", "not-worse")
# Actions with no words of the player's in them: any line the reply gives "you" to say is the model's own invention.
OPEN_ACTIONS = ["I look around the tavern and wait.", "I walk down to the ferry deck and watch the water."]
# Tense, and nothing more than a story needs: a model that refuses here refuses an ordinary adventure.
TENSE_ACTIONS = ["I draw my knife and tell the smuggler by the door to hand over the satchel.",
                 "I break the lock on the customs shed and slip inside."]
LENGTH_ACTION = "I follow Hollis Wren into the back room."
SEQUENCE = ["I sit down by the tavern fire.", "I stay by the fire a while longer.", "I keep watching the door."]
DIRECTOR_ACTION = "I slip out of the tavern and follow the reed path toward the lighthouse."

# The story so far, the same for every model. Both secrets are told, each to one person; nothing here states a tie or who holds what.
HISTORY = [
    ("I step off the ferry and look for somewhere to dry off.",
     "The ferry bumps against the jetty and you climb out into a thin, cold rain. Ottoline Pike ties off the rope without a "
     "word and tips her head toward the lit windows of the tavern."),
    (LETTER_TELL, "Bram Halloran nods slowly and says nothing more."),
    ("I walk through the salt market.",
     "Stalls are closing as you pass between them. Dessa Quill is weighing out the last sacks and glances up at you."),
    (gp.SECRETS["hull"]["tell"], "Dessa Quill nods slowly and says nothing more."),
    ("I go into the tavern and ask for a hot drink.",
     "Hollis Wren sets a steaming cup on the counter in front of you and goes back to drying mugs. Maribel Voss sits alone "
     "near the window, and Corwin Tide drips by the door."),
    ("I take a seat where I can see the whole room.",
     "You settle on a bench against the wall. The rain thickens against the glass, and the talk around you drops to a murmur."),
]

# --- scorers: pure functions of the reply's text -------------------------------------------------------------------------

_CURLY1, _CURLY2 = chr(0x2018), chr(0x2019)
_DQ1, _DQ2 = chr(0x201C), chr(0x201D)
_QUOTED = re.compile(f"[{_DQ1}\"][^{_DQ2}\"]{{0,800}}[{_DQ2}\"]"
                     f"|(?<!\\w)['{_CURLY1}](?=[A-Z])[^\\n]{{0,600}}?[.,!?{chr(0x2014)}]['{_CURLY2}](?!\\w)")
_SAY = (r"(?:say|says|said|ask|asks|asked|reply|replies|replied|answer|answers|answered|tell|tells|told|shout|shouts|"
        r"whisper|whispers|mutter|mutters|murmur|murmurs|call|calls|add|adds|respond|responds)")
# Read on the text with every quote replaced by "Q", so a character's own line that begins "You say..." is not yours.
_YOUR_LINES = [
    re.compile(rf'"Q"\s*,?\s*you\s+{_SAY}\b', re.I),                                  # "Hand it over," you say
    re.compile(rf'\byou\s+{_SAY}\b(?:\s+\w+){{0,2}}\s*[,:]\s*"Q"', re.I),              # you say quietly, "..."
    re.compile(r"\byou\s+(?:decide|choose)\s+to\b", re.I),                              # a choice made for you
]
_ASSISTANT = re.compile(r"\b(?:as an ai|as a language model|i cannot|i can't|i can not|i am unable|i'm unable|i will not|"
                        r"i won't|i must decline|i apologi[sz]e|i'm sorry, but|i am sorry, but|cannot assist|can't assist|"
                        r"content policy|would you like me to|let me know if)\b", re.I)
_FIRST_PERSON = re.compile(r"\bI\b|\b[Mm](?:e|y|ine|yself)\b")
_SECOND_PERSON = re.compile(r"\b[Yy]ou(?:r|rs|rself)?\b")
_PROMPT_MARKS = ["<think>", "</think>", "```", "STORY & MEMORY CONTEXT", "CURRENT SCENE STATE", "Facts in play, from the",
                 "PLAYER AGENCY:", "LENGTH: ", "[["]
_PROMPT_LINES = re.compile(r"^\s*(?:#{1,6}\s|(?:PLAYER|NARRATOR|Player|Narrator)\s*:|"
                           r"[*_>]*(?i:nothing changed|something changed)\b[^\n.]{0,80}:[*_]*\s*$)", re.M)
_ENDINGS = ".!?\"'*)" + _DQ2 + _CURLY2 + chr(0x2026) + chr(0x2014)


def straighten(text: str) -> str:
    return text.replace(_CURLY2, "'")


def narration(text: str) -> str:
    """The reply without its quoted speech: what the narrator says in its own voice."""
    return _QUOTED.sub(" ", text)


def keeps_your_words(text: str) -> bool:
    masked = _QUOTED.sub(' "Q" ', straighten(text))
    return not any(p.search(masked) for p in _YOUR_LINES)


def stays_in_story(text: str) -> bool:
    return not _ASSISTANT.search(straighten(narration(text))) and "as an ai" not in text.lower()


def speaks_to_you(text: str) -> bool:
    """Never "I" in the narrator's own voice. A longer stretch of narration must also say "you" (told in the third person it
    would not); a short answer that is mostly someone talking need not."""
    told = narration(text)
    if _FIRST_PERSON.search(told):
        return False
    return len(told.split()) < NEEDS_YOU or bool(_SECOND_PERSON.search(told))


def no_prompt_text(shown: str) -> bool:
    """Read on what the reader sees: the status block the app asks for is taken out before that, as it should be."""
    return not any(m in shown for m in _PROMPT_MARKS) and not _PROMPT_LINES.search(shown)


def verdict(gid: str, text: str) -> str:
    """The soak's verdicts, with this check's own secrets and the other ways of naming someone."""
    probe = PROBES[gid]
    if probe["sub"] in ("recall", "leak"):
        said = probe["token"] in text.lower()
        if probe["sub"] == "leak":
            return "leak" if said else "clean"
        return "held" if said else "none"
    return gp.score(gid, text, SCORING_CAST)


def facts_in_prompt(gid: str, messages) -> bool:
    """Was what the answer needs in what the model was sent (the question itself left out)?"""
    if PROBES[gid]["sub"] in ("recall", "leak"):
        return PROBES[gid]["token"] in gp.split_prompt(messages)[0].lower()
    return gp.evidence_flags(gid, messages)[0]


def parse_set(pairs) -> dict:
    """`--set memory.tail_ties=false` and the like, as {"memory.tail_ties": False}. A key not in SETTABLE is refused: a
    mistyped one would change nothing and read as "makes no difference"."""
    import yaml
    out: dict = {}
    for pair in pairs or []:
        key, sep, raw = str(pair).partition("=")
        value = yaml.safe_load(raw) if sep and raw.strip() else None
        if key not in SETTABLE or value is None:
            raise SystemExit(f"refused: --set takes NAME=VALUE with one of: {', '.join(SETTABLE)}. Got {pair!r}")
        out[key] = value
    return out


def parse_predictions(pairs) -> dict:
    out: dict = {}
    for pair in pairs or []:
        key, _sep, word = str(pair).partition("=")
        if key not in CHECKS or word not in PREDICTIONS:
            raise SystemExit(f"refused: --predict takes CHECK={'|'.join(PREDICTIONS)}, CHECK one of: {', '.join(CHECKS)}. "
                             f"Got {pair!r}")
        out[key] = word
    return out


def held(prediction: str, change: str) -> bool:
    if prediction == "not-worse":
        return change != "worse"
    return change == {"better": "better", "worse": "worse", "same": "about the same"}[prediction]


def describe_changed(changed: dict) -> str:
    return ", ".join(f"{k} = {json.dumps(v)}" for k, v in sorted(changed.items()))


def finishes(text: str) -> bool:
    end = text.rstrip()
    return bool(end) and end[-1] in _ENDINGS


def paragraphs(text: str) -> int:
    return sum(1 for p in re.split(r"\n\s*\n", text) if p.strip())


def short_enough(text: str) -> bool:
    return bool(text.strip()) and len(text.split()) <= SHORT_WORDS and paragraphs(text) <= SHORT_PARAGRAPHS


def long_enough(text: str) -> bool:
    return len(text.split()) >= LONG_WORDS or paragraphs(text) >= LONG_PARAGRAPHS


# --- the report ------------------------------------------------------------------------------------------------------------

class Tally:
    def __init__(self):
        self.checks = {k: {"label": v, "passed": 0, "total": 0, "examples": []} for k, v in CHECKS.items()}

    def add(self, key: str, ok: bool, example: str = "") -> None:
        c = self.checks[key]
        c["total"] += 1
        if ok:
            c["passed"] += 1
        elif len(c["examples"]) < 2:
            c["examples"].append(" ".join(example.split())[:300])


def compare(old: dict, new: dict) -> list[dict]:
    """Each check both reports ran: worse or better only when the share of passes moved by a quarter and by two replies."""
    out = []
    for key in CHECKS:
        a, b = old.get("checks", {}).get(key), new.get("checks", {}).get(key)
        if not a or not b or not a["total"] or not b["total"]:
            continue
        moved = b["passed"] / b["total"] - a["passed"] / a["total"]
        replies = moved * b["total"]
        verdict = "about the same"
        if moved <= -0.25 + 1e-9 and replies <= -2 + 1e-9:
            verdict = "worse"
        elif moved >= 0.25 - 1e-9 and replies >= 2 - 1e-9:
            verdict = "better"
        out.append({"key": key, "label": CHECKS[key], "before": f"{a['passed']} of {a['total']}",
                    "now": f"{b['passed']} of {b['total']}", "change": verdict})
    return out


def read_report(path: Path) -> dict | None:
    path = Path(path)
    if path.is_dir():
        path = path / "report.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("checks"), dict) else None


def previous_report(root: Path, model: str, skip: Path | None = None, changed: bool = False) -> dict | None:
    """The report to compare with, out of the earlier ones of the same check version that changed no setting. For a normal
    run: the newest one of another model if there is one (a switch is what is being judged), else of this model. For a run that
    changes a setting: the newest one of this model, and nothing else, so only the setting differs."""
    found = []
    for p in sorted(Path(root).glob("*/report.json")):
        if skip is not None and p.parent.resolve() == Path(skip).resolve():
            continue
        data = read_report(p)
        if data and data.get("pack_version") == PACK_VERSION and not data.get("changed"):
            found.append(data)
    found.sort(key=lambda d: str(d.get("when", "")))
    same = [d for d in found if d.get("model") == model]
    if changed:
        return (same or [None])[-1]
    other = [d for d in found if d.get("model") != model]
    return (other or found or [None])[-1]


def notes_for(old: dict, new: dict) -> list[str]:
    out = []
    if old.get("pack_version") != new.get("pack_version"):
        out.append("The two reports were made by different versions of the check, so they are not a fair comparison.")
    diff = sorted(k for k in set(old.get("settings", {})) | set(new.get("settings", {}))
                  if old.get("settings", {}).get(k) != new.get("settings", {}).get(k))
    if diff:
        out.append("Settings differ between the two runs: " + ", ".join(diff) + ".")
    for name, run in (("This run", new), ("The earlier run", old)):
        if run.get("changed"):
            out.append(f"{name} changed {describe_changed(run['changed'])}.")
    return out


def to_markdown(report: dict, old: dict | None = None) -> str:
    changed = report.get("changed") or {}
    lines = [f"# Model check: {report['model']}" + (f" with {describe_changed(changed)}" if changed else ""), "",
             f"Run {report['when']}, {report['repeats']} round(s), {report['speed']['replies']} replies. A typical reply took "
             f"{report['speed']['median_secs']} seconds and was {report['speed']['median_words']} words.", ""]
    changes = {c["key"]: c for c in compare(old, report)} if old else {}
    predicted = report.get("predictions") or {}
    if old:
        lines += [f"Compared with **{old['model']}** (run {old['when']}, a typical reply {old['speed']['median_secs']} seconds, "
                  f"{old['speed']['median_words']} words)."] + [f"- {n}" for n in notes_for(old, report)] + [""]
        lines += ["| Check | This model | Before | Change |" + (" Predicted |" if predicted else ""),
                  "|---|---|---|---|" + ("---|" if predicted else "")]
    else:
        lines += ["Nothing earlier to compare with.", "", "| Check | Passed |", "|---|---|"]
    outcomes = []
    for key, c in report["checks"].items():
        if not c["total"]:
            continue
        row = f"| {c['label']} | {c['passed']} of {c['total']} |"
        if old:
            ch = changes.get(key)
            row += f" {ch['before'] if ch else 'not run'} | {ch['change'] if ch else ''} |"
            if predicted:
                word = predicted.get(key)
                if word and ch:
                    ok = held(word, ch["change"])
                    outcomes.append(ok)
                    row += f" {word}: {'held' if ok else 'did not hold'} |"
                else:
                    row += (f" {word}: not compared |" if word else " |")
        lines.append(row)
    if old:
        worse = [c["label"] for c in changes.values() if c["change"] == "worse"]
        lines += ["", "**Worse than before:** " + ("; ".join(worse) if worse else "nothing by a clear margin.")]
    if predicted and old:
        lines += ["", f"**Predictions written down before the run that held:** {sum(outcomes)} of {len(outcomes)}."]
    failed = [(c["label"], c["examples"]) for c in report["checks"].values() if c["examples"]]
    if failed:
        lines += ["", "## Examples of replies that failed", ""]
        for label, examples in failed:
            lines += [f"**{label}**", ""] + [f"> {e}" for e in examples] + [""]
    lines += ["", "With a few replies per check, one reply either way is chance. A check is called worse or better only when its "
                  "share of passes moved by a quarter and by at least two replies. Scoring is done by code, so read the examples."]
    return "\n".join(lines) + "\n"


# --- the offline writers -------------------------------------------------------------------------------------------------

_GOOD_LINES = ["You settle in and the logs hiss softly.", "A chair scrapes somewhere behind you.",
               "Rain taps at the pane while you wait.", "Someone laughs near the bar, then stops.",
               "The door creaks and a cold draught finds you.", "You watch the lamp flame lean and recover.",
               "A dog sighs under the nearest table.", "Your boots steam gently on the warm stones."]


class StubModel:
    """No model. `good` answers so that every check passes and `bad` so that every check fails, which is how the tests show
    that each scorer can say both."""

    def __init__(self, kind: str):
        self.kind, self.gen, self.n = kind, {}, 0
        self.model = f"stub-{kind}"

    def stream(self, messages, **k):
        self.n += 1
        system = "\n".join(str(m["content"]) for m in messages if m["role"] == "system")
        last = next((str(m["content"]) for m in reversed(messages) if m["role"] == "user"), "")
        probe = next((p for p in PROBES.values() if p["action"] in last), None)
        # The good one answers as a real small model often does: the instruction's label, then the block the app asks for.
        yield (self._good(system, probe) + "\n\nNothing changed:\n\n```rpg\n{\"deltas\": {}}\n```"
               if self.kind == "good" else self._bad(system, probe))

    def _good(self, system: str, probe: dict | None) -> str:
        if probe:
            who = probe["asker"].split()[0]
            if probe["sub"] == "recall":
                return f"You wait while {who} thinks. \"It was the {probe['token']},\" {who} says."
            if probe["sub"] == "leak":
                return f"You watch {who} shrug. \"That is nothing I know about.\""
            return f"You wait while {who} thinks. \"That would be {probe['expect'][0]},\" {who} says."
        if "write a fuller scene" in system:
            return "\n\n".join(f"You notice detail number {i} in the back room." for i in range(1, 6))
        return _GOOD_LINES[self.n % len(_GOOD_LINES)]

    def _bad(self, system: str, probe: dict | None) -> str:
        text = ("I cannot help with that, my friend. \"Hand it over,\" you say.\n## Notes\n"
                "<think>the same long sentence comes back again and again every single turn here</think> ")
        if probe:
            if probe["sub"] == "leak":
                return text + f"Everyone says {probe['token']} and"
            if probe["sub"] != "recall":
                wrong = next(c[0] for c in CAST if c[0] not in probe["expect"] and c[0] not in probe["allowed"])
                return text + f"It is {wrong} and"
            return text + "It is nothing and"
        if "keep it short" in system:
            return text + "and on " * 300
        return text + "and"

    def complete(self, messages, **k):
        if self.kind == "bad":
            return "I would rather talk about something else."
        asked = "\n".join(str(m.get("content", "")) for m in messages)
        if "LOGIC AGENT" in asked:
            return json.dumps({"beat_plan": "The path floods and the light ahead goes out.", "must_stay_consistent": [],
                               "recall_queries": [], "envelope": {"v": 1, "deltas": {}}})
        if "memory keeper" in asked:
            return json.dumps({"scene_summary": "[[character:bram-halloran]] hears a quiet word.", "timeline": "arrival"})
        return json.dumps({"title": "The sealed letter",
                           "goal": "You must find who the letter is meant for before the next tide. Someone in town is watching "
                                   "for it and will not wait long. Asking openly puts the person it is meant for in danger."})


# --- the run ---------------------------------------------------------------------------------------------------------------

def _config(model: str, host: str, think: bool, provider: str) -> str:
    """The app's shipped settings, the model in the Writer's seat. The memory switches are left out on purpose, so the check
    runs what the app runs."""
    profile = hosted.profile_lines(model) if provider == "openrouter" else f"""active_profile: local
profiles:
  local:
    base_url: {host.rstrip("/")}/v1
    model: {json.dumps(model)}
    api_key_env: OLLAMA_API_KEY
    context_tokens: 16384
"""
    return profile + f"""generation:
  temperature: 0.9
  top_p: 0.95
  max_tokens: 700
  think: {"true" if think else "false"}
  use_memory_tool: false
  trinity_brain: false
  response_length: medium
  ai_acts_as_player: false
  chapter_outline: false
  lore_check: false
memory:
  short_term_turns: auto
  medium_fold_after: 12
  medium_fold_size: 5
  long_fold_after: 8
  long_fold_size: 4
  context_budget_tokens: 8000
rpg: {{}}
retrieval:
  enabled: false
"""


def _require_model(host: str, model: str) -> None:
    with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=10) as r:
        names = [str(m.get("name", "")) for m in json.loads(r.read()).get("models", [])]
    if model not in names and f"{model}:latest" not in names:
        raise SystemExit(f"refused: Ollama has no model called {model!r}. It has: {', '.join(sorted(names)) or 'none'}")


class ModelFailed(RuntimeError):
    """The model could not be called: the run stops, because a report of failed calls would read as a bad model."""


class _Run:
    def __init__(self, home: Path, stub: StubModel | None, changed: dict | None = None):
        from coderain.memory import Library
        self.lib, self.stub, self.n = Library(home), stub, 0
        self.changed = changed or {}
        self.tally, self.replies = Tally(), []
        self.failed = ""                    # why a model call raised, if one did

    def stop_if_the_model_failed(self) -> None:
        if self.failed:
            raise ModelFailed(self.failed)

    def story(self):
        """A fresh copy of the fixed story, so one question's answer never reaches the next."""
        from coderain.memory import Entry
        self.n += 1
        store = self.lib.store(self.lib.create_story(f"Brinewick {self.n}", PREMISE))
        for row in CAST:
            store.upsert_entry("characters.md", Entry(title=row[0], slug=row[1], aliases=row[2], importance=4,
                                                      attrs=sheet_attrs(row, True, "stated"), body=sheet_body(row, "full")))
        for spec in gp.item_specs():
            store.upsert_entry("items.md", Entry(title=spec["title"], slug=spec["slug"], aliases=spec["aliases"], importance=3,
                                                 attrs={"holder": spec["holder"]}, body=spec["body"]))
        rpg = store.rpg_state()
        rpg["seed"] = 5
        store.set_rpg_state(rpg)
        for action, reply in HISTORY:
            store.append_turn("player", action)
            store.append_turn("narrator", reply)
        return store

    def engine(self, store, generation: dict | None = None, memory: dict | None = None):
        """The real engine on `store`, its model calls watched: what came back unfiltered, and whether a call failed."""
        from coderain.config import load_config
        from coderain.engine import Engine
        cfg = load_config()
        for key, value in self.changed.items():             # --set first, so a check's own setting (reply length) still wins
            section, name = key.split(".", 1)
            getattr(cfg, section)[name] = value
        cfg.generation.update(generation or {})
        cfg.memory.update(memory or {})
        eng = Engine(cfg, store)
        if self.stub is not None:
            eng.llm = self.stub
            eng.summarizer.llm = eng.planner.llm = self.stub
        calls: list = []
        real = eng.llm.__class__.stream

        def spy(messages, _llm=eng.llm, **k):
            got: list = []
            calls.append((messages, got))
            try:
                for piece in real(_llm, messages, **k):
                    got.append(piece)
                    yield piece
            except Exception as e:  # noqa: BLE001 - noted, then re-raised untouched for the engine to handle as usual
                self.failed = f"{type(e).__name__}: {str(e)[:300]}"
                raise

        eng.llm.stream = spy
        eng.check_calls = calls
        return eng

    def reply(self, eng, action: str, kind: str) -> tuple[str, str]:
        """(what the reader sees, what the model sent) for one turn, scored by the checks every reply gets."""
        before = len(eng.check_calls)
        t0 = time.time()
        try:
            text = "".join(eng.turn(action))
        except Exception:
            self.stop_if_the_model_failed()
            raise                           # not the model: a bug of ours stops the run loudly
        secs = time.time() - t0
        self.stop_if_the_model_failed()
        mine = gp.writer_call([m for m, _got in eng.check_calls[before:]], action)
        if mine is None:
            raise ModelFailed("the Writer was never called")
        from coderain.sidecar import parse_sidecar
        raw = next("".join(got) for m, got in reversed(eng.check_calls[before:]) if m is mine)
        row = {"kind": kind, "action": action, "text": text, "secs": round(secs, 2), "words": len(text.split())}
        if raw.strip() != text.strip():
            row["raw"] = raw                    # what the model sent, when the app showed something else
        self.replies.append(row)
        add = self.tally.add
        add("in_story", stays_in_story(text), text)
        add("speaks_to_you", speaks_to_you(text), text)
        add("no_prompt_text", no_prompt_text(text), text)
        add("finishes", finishes(text), "..." + text[-200:])
        add("status_block", parse_sidecar(raw) is not None, "reply ends: ..." + raw[-200:])
        return text, raw

    def one_round(self) -> None:
        for gid, check in PROBE_CHECKS.items():
            probe = PROBES[gid]
            eng = self.engine(self.story())
            action = probe["action"] + gp.PLAIN
            text, _raw = self.reply(eng, action, gid)
            # Was what the answer needs in front of the model? It always should be: a question it could not answer would test
            # the app's memory, not the model. Saved with the reply so a broken story shows, with whether the ties line was in.
            sent = gp.writer_call([m for m, _got in eng.check_calls], action)
            said = verdict(gid, text)
            self.replies[-1].update(facts_in_prompt=facts_in_prompt(gid, sent), ties_line=bool(gp.tail_line(sent)),
                                    verdict=said)
            self.tally.add(check, said in ("held", "clean"), f"{probe['action']} -> {text}")
        for action in OPEN_ACTIONS:
            text, _raw = self.reply(self.engine(self.story()), action, "open")
            self.tally.add("your_words", keeps_your_words(text), text)
        for action in TENSE_ACTIONS:
            self.reply(self.engine(self.story()), action, "tense")
        for length, ok in (("short", short_enough), ("long", long_enough)):
            eng = self.engine(self.story(), generation={"response_length": length})
            text, _raw = self.reply(eng, LENGTH_ACTION, length)
            self.tally.add(length, ok(text), f"{len(text.split())} words, {paragraphs(text)} paragraphs: {text}")
        eng = self.engine(self.story())
        texts = [self.reply(eng, action, "sequence")[0] for action in SEQUENCE]
        share = repeat_share(texts)
        self.tally.add("no_copying", share <= REPEAT_LIMIT, f"{round(share * 100)}% of the wording came back: {texts[-1]}")
        self.json_jobs()

    def json_jobs(self) -> None:
        """The three places the app asks the model for JSON. Each is read with the app's own code."""
        # The memory summary: the fold's own request and reader. Nothing is written.
        eng = self.engine(self.story(), memory={"medium_fold_after": 4})
        step = eng.summarizer.next_step()
        obj = eng.summarizer.ask(step) if step else None
        self.stop_if_the_model_failed()
        ok = isinstance(obj, dict) and bool(str(obj.get("scene_summary", "")).strip())
        self.tally.add("summary", ok, _why(eng.store, obj))
        # The first chapter of the plan.
        eng = self.engine(self.story(), generation={"chapter_outline": True})
        made = eng.planner.ensure_first()
        self.stop_if_the_model_failed()
        trouble = [h for h in eng.store.health(20) if h.get("stage") == "chapter-plan"]
        self.tally.add("chapter", bool(made) and not trouble, _why(eng.store, made))
        # The planning step of the quad pipeline.
        eng = self.engine(self.story(), generation={"trinity_brain": True})
        messages = eng._messages(eng.store.recent_turns(eng.short_term), DIRECTOR_ACTION)
        plan, err = eng.trinity._direct(messages, False)
        self.stop_if_the_model_failed()
        self.tally.add("director", err is None and bool(str(plan.get("beat_plan", "")).strip()), err or json.dumps(plan)[:300])


def _why(store, got) -> str:
    """What the app itself wrote about it in the health log, else what came back."""
    rows = [str(h.get("reason", "")) for h in store.health(5)]
    return rows[-1] if rows else "got: " + json.dumps(got, default=str)[:300]


def run_check(args, home: Path, root: Path) -> int:
    """Run the check. `home` is the isolated CODERAIN_HOME made BEFORE anything imported coderain; `root` is where reports go."""
    from soak.home import assert_isolated
    assert_isolated()
    stub = StubModel(args.stub) if args.stub else None
    model = stub.model if stub else args.model
    if not model:
        raise SystemExit("refused: give --model NAME (or --stub good|bad to try the check without a model)")
    changed = parse_set(args.set)
    predictions = parse_predictions(args.predict)
    pacer = undo = None
    if stub is None and args.provider == "openrouter":
        hosted.check_model(model, bool(args.allow_paid))
        hosted.require_key()
        pacer = hosted.Pacer(max_requests=int(args.max_requests))
    elif stub is None:
        _require_local(args.host)
        _require_model(args.host, model)
    think = args.think == "on"
    (home / "config.yaml").write_text(_config(model, args.host, think, args.provider), encoding="utf-8")
    against = None
    if args.against and args.against != "none":
        against = read_report(Path(args.against))
        if against is None:
            raise SystemExit(f"refused: {args.against!r} is not a report of this check")
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_")[-60:] or "model"
    out = (Path(args.out) if args.out
           else Path(root) / REPORTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}{'-changed' if changed else ''}")
    if not args.against:
        against = previous_report(out.parent, model, skip=out, changed=bool(changed))
        if changed and against is None:
            raise SystemExit("refused: there is no earlier run of this model without --set to compare with. Run it once without "
                             "--set first, or give --against.")
    if predictions:
        if against is None:
            raise SystemExit("refused: --predict needs an earlier report to compare with")
        # Written before the first reply, so a prediction cannot be fitted to the result.
        out.mkdir(parents=True, exist_ok=True)
        (out / "prediction.json").write_text(json.dumps(
            {"written": when, "against": {"model": against["model"], "when": against["when"]}, "changed": changed,
             "predictions": predictions}, indent=2), encoding="utf-8")
    run = _Run(home, stub, changed)
    undo = hosted.install(pacer) if pacer is not None else None
    stopped = None
    try:
        for n in range(1, args.repeats + 1):
            print(f"round {n} of {args.repeats}...", flush=True)
            run.one_round()
    except ModelFailed as e:
        stopped = str(e)
    finally:
        if undo is not None:
            undo()
    if stopped:
        print(f"stopped: the model could not be called, so there is no report. {stopped}")
        return 1
    secs = [r["secs"] for r in run.replies]
    words = [r["words"] for r in run.replies]
    report = {"pack_version": PACK_VERSION, "model": model, "provider": args.provider, "when": when, "repeats": args.repeats,
              "settings": {"think": think, "temperature": changed.get("generation.temperature", 0.9),
                           "top_p": changed.get("generation.top_p", 0.95)},
              "changed": changed, "predictions": predictions,
              "checks": run.tally.checks,
              "speed": {"replies": len(run.replies), "median_secs": round(statistics.median(secs), 1),
                        "median_words": round(statistics.median(words))}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    text = to_markdown(report, against)
    (out / "report.md").write_text(text, encoding="utf-8")
    with (out / "replies.jsonl").open("w", encoding="utf-8") as f:
        for r in run.replies:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print()
    print(text)
    print(f"report: {out / 'report.md'}")
    return 0

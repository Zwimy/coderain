"""The turn loop: assemble context, generate, persist, and fold memory.

Generation has two modes:
- default: stream prose (fast, works on any model)
- lookup-tool: when config generation.use_memory_tool is on, the model can call
  lookup_memory(query) mid-generation to pull details on demand. Meant for
  capable/hosted (big-context) models; not streamed.
"""
from __future__ import annotations

import re
from typing import Iterator

from . import features
from . import sidecar as sidecar_mod
from . import streaming
from . import templates
from . import validator as validator_mod
from . import config as config
from .config import Config, context_budget
# Imported by NAME, not via the module alias above: inside Engine.__init__ the
# parameter `config` shadows the module, so config.history_budget resolves to the
# Config object and raises.
from .config import HISTORY_FLOOR_TURNS, history_budget, short_term_turns
from .llm import LLM
from .llm import stage as llm_stage
from .memory import Entry, MemoryStore, safe_output_regex
from .planner import ChapterPlanner
from .summarizer import Summarizer

LOOKUP_TOOL = [{
    "type": "function",
    "function": {
        "name": "lookup_memory",
        "description": "Search the story's memory (characters, locations, factions, "
                       "items, canon events, threads) for details before writing. "
                       "Use when you need to recall something specific.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "name, alias, or keyword to look up"},
            },
            "required": ["query"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "recall_turns",
        "description": "Fetch the exact past turns behind a timeline entry, VERBATIM. "
                       "Use ONLY when you need the fine detail of an earlier moment "
                       "the timeline shorthand references — not for every mention. "
                       "Accepts an event/keyword, a scene like 'scene-2', or a turn "
                       "range like 'T6-10'.",
        "parameters": {
            "type": "object",
            "properties": {
                "reference": {"type": "string",
                              "description": "event/keyword, scene slug, or 'T6-10'"},
            },
            "required": ["reference"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "recall_entity",
        "description": "Entity index: 'what happened with X?' — the entry plus "
                       "every past episode whose metadata names that character or "
                       "location, with turn pointers for verbatim drill-down.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "character/location name or slug"},
            },
            "required": ["name"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "recall_quest",
        "description": "Quest index: 'what advanced this quest?' — the thread "
                       "entry, its live status, and every episode that touched it.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "quest/thread name or slug"},
            },
            "required": ["name"],
        },
    },
}]


LORE_CHECK_SYS = """\
You are the LORE-KEEPER (continuity) for an interactive story. You are given the
story context and the player's latest action. Before the prose is written, work out
what the narration MUST honor so it cannot contradict established canon. Use the
lookup_memory and recall_turns tools when you need a specific detail or the exact
wording of an earlier moment.

Return ONLY a JSON object:
{
  "vetted_facts": ["exact facts the writer must honor this turn"],
  "patches": ["contradictions to avoid, or corrections to likely assumptions"]
}
Keep both lists short and concrete — only what THIS turn could get wrong.
"""


class _ToolJSONClient:
    """Adapter that lets a TOOL-CALLING stage go through emit_json_ex.

    emit_json_ex takes "any object exposing .complete(messages)", and gives back
    the JSON token floor, one retry with a corrective nudge, and the budget
    escalation a starved reasoning model needs. The lore-keeper was the only JSON
    stage that skipped all of it — it called complete_with_tools and then
    extract_json by hand, so a single malformed reply was final, and the health
    line said "no valid JSON in output" with no tail to show what came back.
    Measured on a live save: 7 lore-keeper failures in ~100 turns.

    `gen` is forwarded because emit_json_ex only applies the token floor to a
    client that has it.
    """

    def __init__(self, llm, tools, dispatch):
        self._llm, self._tools, self._dispatch = llm, tools, dispatch
        self.gen = getattr(llm, "gen", {})

    def complete(self, messages, **overrides) -> str:
        return self._llm.complete_with_tools(
            messages, self._tools, self._dispatch, **overrides)


def _chapter_directive(store) -> str:
    """The active chapter, restated AFTER the player's action.

    The full plan already rides the system prompt as "Story structure (chapter
    plan)", but that is one section among a dozen and, on a large context,
    thousands of tokens from where generation starts. Reported live as the story
    drifting wherever it wants. Same reasoning as _lore_directive below: the last
    thing the model reads binds hardest on the next tokens.

    The final line is the anti-drift instruction. Naming the goal is not enough
    on its own; the model also has to be told to check whether recent turns
    actually moved toward it.
    """
    chapters = store.entries("memory/outline.md")
    if not chapters:
        return ""

    def status(c):
        return (c.attrs.get("status", "planned") or "planned").strip().lower()

    active = next((c for c in chapters if status(c) == "active"), None) \
        or next((c for c in chapters if status(c) != "done"), None)
    if active is None:
        return ""
    goal = " ".join(active.body.split())[:400]
    nxt = [c.title for c in chapters[chapters.index(active) + 1:][:1]]
    out = ["# THIS CHAPTER — steer toward it, do not wander off it",
           f"You are in: {active.title}",
           f"Its goal: {goal}" if goal else "",
           "Every scene must move toward that goal, complicate it, or pay it "
           "off. If the last few turns have not advanced it, advance it now.",
           "Do not resolve it in a single turn, and do not skip ahead to "
           + (f"'{nxt[0]}'." if nxt else "later chapters.")]
    return "\n".join(p for p in out if p)


def _lore_directive(facts: dict) -> str:
    """Render the lore-keeper's findings as a post-history instruction (appended
    AFTER the player's action, where it binds hardest on the next tokens)."""
    honor = [str(f).strip() for f in (facts.get("vetted_facts") or [])
             if str(f).strip()]
    patches = [str(p).strip() for p in (facts.get("patches") or []) if str(p).strip()]
    if not honor and not patches:
        return ""
    out = ["# CONTINUITY CHECK (verified against memory — do not contradict)"]
    out += [f"- {h}" for h in honor]
    if patches:
        out.append("\n# CORRECTIONS")
        out += [f"- {p}" for p in patches]
    return "\n".join(out)


def _any_applied(events: list[str]) -> bool:
    """True when at least one REAL delta landed — validator rejection warnings
    are UI events, not applied state, and must not keep an orphan player turn."""
    return any(not e.startswith("validator:") for e in events)


class Engine:
    # Reassigning `engine.llm` has to reach the components that were handed a
    # reference to it, or the swap is silently partial. `sweep_fold_test.py` set
    # `e.llm` and `e.summarizer.llm` to a stub and still spent 342 of its 349
    # seconds inside httpcore: the PLANNER kept the real client, so every fold
    # that seeded an outline made live calls. A hermetic offline suite quietly
    # became one that needed a provider to be up, and blew its 300s budget.
    #
    # A property rather than a fix in that one test, because the trap is the API:
    # nothing about `engine.llm = stub` suggests two other objects still hold the
    # old one, and every future test would step on it the same way.
    @property
    def llm(self):
        return self._llm

    @llm.setter
    def llm(self, value) -> None:
        self._llm = value
        for holder in (getattr(self, "planner", None),
                       getattr(self, "summarizer", None)):
            if holder is not None:
                holder.llm = value

    def __init__(self, config: Config, store: MemoryStore):
        self.cfg = config
        self.store = store
        self.llm = LLM(config.profile, config.generation)
        # Every model call this story makes lands in memory/usage.jsonl with the
        # provider's own token counts, tagged by stage. The client keeps working
        # if this raises; the store swallows OSError for the same reason.
        self.llm.on_usage = store.log_usage
        # The rolling chapter outline (book plan). NOT a per-turn brain — it rides
        # the summarizer's occasional LLM (seed once, extend once per completed
        # chapter). Passed into the summarizer so a scene fold can detect a chapter
        # landing for free and roll the plan forward.
        self.planner = ChapterPlanner(config, store, self.llm)
        self.summarizer = Summarizer(config, store, self.llm, planner=self.planner)
        # 'auto' by default: the token ceiling governs, not a fixed count.
        self.short_term = short_term_turns(config)
        # Explicit number, or `auto`/0 = fill the profile's window (long-context
        # cloud models get everything above the reply reserve).
        self.budget = context_budget(config)
        # Token ceiling under short_term_turns; see config.history_budget.
        self.history_tokens = history_budget(config)
        self.scenes_tail = 4
        # Open-core seam: premium modules resolve through coderain.features —
        # None when a module is trimmed from the build, and every use below
        # degrades gracefully (core must run fully without them).
        self.rpg_mod = (features.module("rpg")
                        if features.enabled("rpg") else None)
        self.use_tool = bool(config.generation.get("use_memory_tool", False)) \
            and features.enabled("memory_tool")
        # Opt-in Trinity Brain (Director -> Lore-keeper -> Writer). Off by default;
        # single-brain path below is untouched when disabled.
        # Base is a callable so unpinned Trinity stages track engine.llm swaps
        # (tests / Settings rebuild) instead of capturing a stale client.
        # Quad applies the envelope BEFORE the narrator turn is appended, so its
        # events-log record must carry the index the narrator turn is ABOUT to
        # get — otherwise the ledger's numbering diverges from the single-brain
        # convention (narrator index) and branch replay filters break.
        trinity_mod = (features.module("trinity")
                       if features.enabled("multi_brain") else None)
        self.trinity = (trinity_mod.TrinityBrain(
                            lambda: self.llm, store, config, config.rpg,
                            self._dispatch_tool, LOOKUP_TOOL,
                            apply_envelope=lambda env, rpg_on:
                            self.apply_envelope(
                                env, rpg_on,
                                log_turn=len(store.turns()) + 1))
                        if trinity_mod is not None
                        and config.generation.get("trinity_brain", False)
                        else None)
        if self.trinity is not None:
            # Frequency only: trinity does its own enablement check.
            self.trinity.lore_due = self.lore_cadence_due
        self._rpg_events: list[str] = []
        self._swipes = None            # ST-02 alternates for the last narrator turn
        self._pre_turn_rpg = None
        # Md mutations aren't covered by the state.json snapshot, so undo/retry
        # reverts them explicitly: reveals get re-hidden, canon events added by
        # this turn get removed, consumed event rules get un-consumed.
        self._pre_turn_reveals: list[str] = []
        self._pre_turn_canon: list[str] = []
        self._pre_turn_events: list[str] = []
        # Optional Phase 5 semantic recall (off unless retrieval.enabled + Pro).
        # Reuses the chat client so it's provider-agnostic; None keeps assembly
        # unchanged.
        self.retriever = None
        vector_mod = (features.module("vector")
                      if features.enabled("vector_recall") else None)
        if vector_mod is not None:
            try:
                self.retriever = vector_mod.build_retriever(
                    store, self.llm.client, config.retrieval, config)
            except Exception as e:  # noqa: BLE001 — never breaks the engine
                # ...but it MUST leave a trace: this exact swallow is why semantic
                # recall reported "enabled" while doing nothing for weeks.
                self.retriever = None
                store.log_degraded("semantic-recall",
                                   f"{type(e).__name__}: {e}")

    def _messages(self, history, player_input):
        messages = self.store.assemble(history, player_input,
                                       scenes_tail=self.scenes_tail,
                                       budget_tokens=self.budget,
                                       retriever=self.retriever)
        return self._augment_style(self._augment_rpg(messages))

    def history_window(self, drop_last: bool = False) -> list[dict]:
        """The verbatim turns actually sent, capped by COUNT and by TOKENS.

        short_term_turns is the count the user reasons about; history_budget is a
        ceiling underneath it, because a fixed count means 12 terse turns and 12
        enormous ones cost wildly different amounts and neither was measured.
        Trims from the OLDEST end (the newest turns are the ones that matter) and
        never below HISTORY_FLOOR_TURNS, so one runaway turn cannot leave the
        model with no conversation at all.
        """
        turns = self.store.recent_turns(self.short_term)
        if drop_last:
            turns = turns[:-1]
        limit = self.history_tokens * 4          # same chars-per-token estimate
        floor = HISTORY_FLOOR_TURNS              # as the rest of the engine uses
        while len(turns) > floor and \
                sum(len(t.get("text", "")) for t in turns) > limit:
            turns = turns[1:]
        return turns

    def _authors_note_cfg(self) -> tuple[str, int]:
        """ST-21: per-save author's-note placement — depth ('system' | 'tail') and
        frequency ('every' N turns). Stored in state.json under authors_note."""
        ws = self.store.world_state()
        an = ws.get("authors_note") if isinstance(ws.get("authors_note"), dict) else {}
        depth = an.get("depth") if an.get("depth") in ("system", "tail") else "system"
        try:
            every = max(1, int(an.get("every", 1)))
        except (TypeError, ValueError):
            every = 1
        return depth, every

    def _augment_style(self, messages):
        """Wave 4 response controls + ST-21 author's note. The length knob always
        rides the system prompt; the save's custom instructions (the author's note)
        obey their depth + frequency: 'system' appends to the system prompt, 'tail'
        injects just before the player's latest action (binds harder); 'every N'
        only injects on turns whose number is a multiple of N."""
        if not messages:
            return messages
        parts = []
        # Player agency: by default the AI must not act or speak for the player —
        # the reported "it takes a lot of action on my behalf". Firm, and first so
        # it leads the style block.
        if not self.cfg.generation.get("ai_acts_as_player", False):
            parts.append("PLAYER AGENCY: never speak, act, decide, or narrate the "
                         "inner thoughts of the player character. Write only the "
                         "world, other characters, and the consequences of what the "
                         "player actually said they do — then stop at the player's "
                         "next decision and hand control back. Never put words in "
                         "the player's mouth or take actions for them.")
        length = str(self.cfg.generation.get("response_length", "medium")).lower()
        if length == "short":
            parts.append("LENGTH: keep it short — 1-2 short paragraphs, then stop "
                         "and hand control back. Do not pad or over-describe.")
        elif length == "long":
            parts.append("LENGTH: write a fuller scene — 4-6 paragraphs; linger on "
                         "detail, dialogue, and atmosphere.")
        custom = self.store.custom_instructions()
        if custom:
            custom = self._expand_authored(custom)   # ST-20 macros in the note too
        depth, every = self._authors_note_cfg()
        # Frequency counts EXCHANGES (narrator turns), 1-based on the one we're about
        # to write — independent of player/narrator parity. every=1 → every turn;
        # the opening (0 narrator turns so far) is exchange 1, so it isn't a spurious
        # multiple for every>1.
        exchange = sum(1 for t in self.store.turns()
                       if t.get("role") == "narrator") + 1
        note_now = bool(custom) and (exchange % every == 0)
        if custom and depth == "system" and note_now:
            parts.append(custom)
        out = messages
        if parts:
            add = "\n\n# STYLE DIRECTIVES\n" + "\n".join(f"- {p}" for p in parts)
            out = [{**messages[0], "content": messages[0]["content"] + add},
                   *messages[1:]]
        # tail: only when there's an actual last action to sit in front of (>=2
        # messages), else the note would land before the system prompt.
        if custom and depth == "tail" and note_now and len(out) >= 2:
            note = {"role": "system", "content": "# AUTHOR'S NOTE\n" + custom}
            out = out[:-1] + [note, out[-1]]     # right before the player's action
        return out

    def _augment_rpg(self, messages):
        """When RPG mechanics are on for this story, append the rpg rules + the live
        character sheet to the system prompt. No-op (and zero overhead) when off."""
        if not messages or not self.store.rpg_enabled():
            return messages
        rules = self.store.read("rpg-rules.md").strip()
        # Quad mode narrates check outcomes the same turn they resolve, so the
        # "narrate this now" nudge would cause a re-narration next turn.
        sheet = (self.rpg_mod.context_block(
                     self.store, prompt_narrate=self.trinity is None)
                 if self.rpg_mod is not None else "")
        add = "\n\n# RPG MODULE (mechanics ON)\n\n" + rules
        if sheet:
            add += "\n\n## Your character sheet\n" + sheet
        return [{**messages[0], "content": messages[0]["content"] + add},
                *messages[1:]]

    def _snapshot_rpg(self):
        """Deep-copy the WHOLE mutable state before a turn — with Wave 1's world
        deltas (time/flags/location) in play, retry/undo must roll back everything
        a turn applied, not just the rpg block (SPEC-V2 §1.4)."""
        return validator_mod.snapshot_state(self.store)

    def restore_pre_turn_rpg(self) -> None:
        """Undo the state changes of the turn about to be retried/undone. Call
        before re-running the last action; no-op when nothing was captured. Note:
        this restores the full state.json, so a fold's fallback time write that
        landed AFTER the snapshot is reverted too — acceptable, since the per-turn
        time_advance delta (re-applied on retry) is the clock's driver now."""
        snap = getattr(self, "_pre_turn_rpg", None)
        rolled_back = snap is not None
        if snap is not None:
            self.store.set_world_state(snap)
            # One snapshot covers ONE turn: a second consecutive undo must not
            # re-apply this (now stale) state on top of an older transcript.
            self._pre_turn_rpg = None
        for slug in getattr(self, "_pre_turn_reveals", []):
            self.store.set_hidden(slug, True)
        for slug in getattr(self, "_pre_turn_canon", []):
            self.store.remove_entry("canon-events.md", slug)
        for slug in getattr(self, "_pre_turn_events", []):
            self.store.mark_event_consumed(slug, False)
        self._pre_turn_reveals = []
        self._pre_turn_canon = []
        self._pre_turn_events = []
        # The undone turn's envelope must leave the replay ledger too (callers
        # truncate the transcript first), or a later branch re-applies it.
        #
        # ONLY when a snapshot was actually consumed. Mechanics rollback is
        # single-level, so on a second consecutive undo there is nothing to
        # rewind — dropping the log record anyway would delete the record of
        # deltas that are STILL APPLIED in state.json. The save and the replay
        # ledger would then disagree by a whole envelope, permanently, and a
        # branch (which rebuilds from the ledger) would quietly produce
        # different gold/flags than the save it came from.
        # By COUNT, not turn number. The index is ambiguous: a second
        # consecutive undo deliberately does NOT truncate (nothing was rolled
        # back), so a record can survive at an index a later turn then reuses —
        # and the next undo deleted BOTH while rolling back one. `_pre_turn_log`
        # is the ledger length when this exchange began, so dropping back to it
        # removes exactly what this exchange logged, whatever index it claims.
        # (_abort_turn was moved off the turn number for the same reason.)
        if rolled_back:
            count = getattr(self, "_pre_turn_log", None)
            if count is None:
                self.store.truncate_event_log(len(self.store.turns()))
            else:
                self.store.drop_event_log_after(count)
            self._pre_turn_log = None
        # Whether or not anything was rolled back, no record may be left pointing
        # PAST the transcript's end. When nothing was (a second consecutive undo,
        # or an Engine rebuilt mid-story by a settings save so it holds no
        # snapshot at all), the deltas stay applied — correct, per D-002 — but
        # their record sat at an index the shortened transcript no longer
        # reaches, and branch() filters on `snap_turns < turn <= turn_n`, so it
        # neither replayed them nor kept them: a branch with different flags from
        # the save it came from, which is the exact failure that guard prevents.
        # Pulling the record onto the last real turn keeps both halves true.
        self.store.clamp_event_log_to_transcript()

    def _begin_turn(self) -> tuple:
        """Open an exchange's undo record. Returns the PREVIOUS one so an
        aborted turn can put it back — see _abort_turn."""
        prior = (getattr(self, "_pre_turn_rpg", None),
                 list(getattr(self, "_pre_turn_reveals", [])),
                 list(getattr(self, "_pre_turn_canon", [])),
                 list(getattr(self, "_pre_turn_events", [])),
                 getattr(self, "_pre_turn_log", None),
                 list(getattr(self, "_rpg_events", [])))
        self._pre_turn_log = self.store.event_log_count()
        self._rpg_events = []
        self._pre_turn_rpg = self._snapshot_rpg()
        self._pre_turn_reveals = []
        self._pre_turn_canon = []
        self._pre_turn_events = []
        return prior

    def _abort_turn(self, prior: tuple) -> None:
        """Make an exchange that stored nothing TRANSPARENT: undo whatever it
        applied, then hand the previous exchange's undo record back.

        Both halves were missing. The undo record is a single slot opened at the
        top of every entry point, so a generation that produced nothing — a model
        error, the client's Stop closing the generator mid-stream, empty output —
        both (a) left its own snapshot live for the NEXT undo to consume against
        a different exchange, and (b) destroyed the previous exchange's snapshot
        by overwriting it.

        (a) was the corruption: `restore_pre_turn_rpg` reported rolled_back=True
        and truncated the event log for deltas still applied in state.json. The
        save and the ledger then disagreed by a whole envelope, permanently, and
        a branch rebuilt different gold than the save it came from — invariant 3,
        and exactly the hole that guard exists to close (DECISIONS.md D-002).

        Rolling back rather than merely dropping the snapshot also covers the
        quad path, which applies and logs its envelope BEFORE the Writer runs: if
        the Writer yields nothing, that envelope belongs to a turn nobody will
        ever see. Call AFTER dropping the orphan player turn, so the ledger
        truncation measures the transcript the save is really left with."""
        # Read the ledger length THIS exchange opened with before rolling back —
        # restore_pre_turn_rpg consumes and clears it.
        opened_at = getattr(self, "_pre_turn_log", None)
        if getattr(self, "_pre_turn_rpg", None) is not None:
            self.restore_pre_turn_rpg()
        (self._pre_turn_rpg, self._pre_turn_reveals, self._pre_turn_canon,
         self._pre_turn_events, prior_log, prior_events) = prior
        if opened_at is not None:
            self.store.drop_event_log_after(opened_at)
        self._pre_turn_log = prior_log
        # The rolled-back deltas must leave the UI event list as well, or the
        # done frame credits the reader with mechanics that no longer exist —
        # while the sheet and clock in the same frame read the real state.
        self._rpg_events = prior_events

    def opening(self, on_stage=None) -> Iterator[str]:
        prior = self._begin_turn()
        # Wave 4: an authored '## Opening' in premise.md is used VERBATIM as the
        # first scene — no model call (FictionLab's greeting message).
        override = self.store.opening_override()
        if override:
            # A card's first_mes can carry a ```rpg block; strip it so it never
            # reaches the reader, and APPLY it — the live-gen path does both,
            # and throwing an authored envelope away is a silent loss of the
            # opening state the author set up.
            override, side = sidecar_mod.strip_sidecar(override)
            override = self._expand_authored(override)   # ST-20 macros in greeting
            if on_stage:
                on_stage("Opening: authored greeting (no generation)")
            # Nothing left after the strip means the greeting was ONLY a sidecar.
            # Storing it anyway put an empty narrator turn on disk: the SPA
            # deletes an empty bubble, so the DOM started one turn behind the
            # store from turn one, and every later ✎ edit hit the wrong index.
            # The live path already refuses to store a turn a rule emptied.
            if not override.strip():
                self.store.log_degraded(
                    "opening", "the authored '## Opening' had no prose once its "
                               "sidecar was stripped; nothing was stored")
                self._abort_turn(prior)
                return
            self.store.append_turn("narrator", override)
            # Applied AFTER the turn is stored, so the envelope's ledger record
            # gets the index of a turn that really exists. Dropping it was a
            # silent loss of the opening state the author set up.
            if side:
                self._rpg_events += self.apply_envelope(
                    side, self.store.rpg_enabled())
            yield override
            return
        messages = self._messages(
            [], "Begin the story. Set the opening scene and place me in it.")
        before = len(self.store.turns())
        try:
            yield from self._generate_and_store(messages, on_stage)
        finally:
            # Transcript growth, not `stored` — same reason as continue_story.
            # `stored` is `bool(narration) or applied`, and an opening has no
            # player turn to anchor either: a prose-less opening left an empty
            # transcript holding the deltas, with the envelope logged at turn 0
            # where it collides with the genesis record, survives every
            # truncation, is unreachable by undo (empty transcript) and is
            # filtered out by branch(). state kept flags the branch did not.
            if len(self.store.turns()) == before:
                self._abort_turn(prior)

    def turn(self, player_input: str, on_stage=None) -> Iterator[str]:
        prior = self._begin_turn()
        self.store.append_turn("player", player_input)
        history = self.history_window(drop_last=True)
        messages = self._messages(history, player_input)
        stored = False
        try:
            stored = yield from self._generate_and_store(messages, on_stage)
        finally:
            # If we didn't store a narrator turn, the player's action must not stay
            # in the transcript with no response. This runs on EVERY exit including
            # GeneratorExit — the client Stop / a disconnect closes this generator
            # mid-stream, which used to skip the cleanup and leave an orphan player
            # turn on disk (the reported "kept a turn I removed" corruption). We
            # check the file rather than trust `stored`, which is lost on an
            # abnormal exit; the tail is our just-appended player turn.
            if not stored:
                tail = self.store.turns()
                if tail and tail[-1]["role"] == "player":
                    self.store.drop_last_turns(1)
                self._abort_turn(prior)

    def continue_story(self, on_stage=None) -> Iterator[str]:
        """Carry the prose forward with NO player action — the 'Continue' button.
        Unlike `turn`, nothing is appended to the transcript as a player line; the
        model simply extends the last scene, so the pipeline is otherwise identical
        (Director plan → validate → Writer)."""
        prior = self._begin_turn()
        history = self.history_window()
        messages = self._messages(
            history,
            "Continue the narration from exactly where it left off. Do not "
            "repeat what was already written and do not summarize — push the "
            "current scene forward with fresh action or detail.")
        before = len(self.store.turns())
        try:
            yield from self._generate_and_store(messages, on_stage)
        finally:
            # The test is "did the transcript grow", NOT _generate_and_store's
            # `stored` — which is `bool(narration) or applied`. That `or applied`
            # exists so `turn()` keeps a player action that had a mechanical
            # effect even with no prose; a Continue has no player turn to keep,
            # and taking it here was a permanent state/ledger split. The
            # envelope gets logged at len(turns()), which for a Continue that
            # stored nothing is the PREVIOUS narrator turn's index — two records
            # collide on one turn, and the next undo truncates both while
            # restore_pre_turn_rpg rolls back only one. state.json then kept a
            # flag no ledger record described, and a branch rebuilt without it
            # (invariant 3, and D-002's stated guarantee).
            #
            # A Continue is "carry the prose forward". No prose means it failed,
            # and rolling it back whole is also what the reader sees.
            if len(self.store.turns()) == before:
                self._abort_turn(prior)

    def _ensure_swipes(self) -> dict | None:
        """Swipe state for the LAST narrator turn (ST-02). Seeds from the current
        text on first swipe. None when the tail isn't a narrator turn."""
        turns = self.store.turns()
        if not turns or turns[-1]["role"] != "narrator":
            return None
        if self._swipes is None:
            self._swipes = {"variants": [turns[-1]["text"]], "idx": 0}
        return self._swipes

    def swipe_browse(self, direction: int) -> dict | None:
        """Move within already-generated variants — NO model call. Rewrites the
        last narrator turn to the selected variant. {text, idx, count} or None."""
        sw = self._ensure_swipes()
        if sw is None:
            return None
        sw["idx"] = max(0, min(len(sw["variants"]) - 1, sw["idx"] + direction))
        text = sw["variants"][sw["idx"]]
        self.store.update_turn(len(self.store.turns()) - 1, text)
        return {"text": text, "idx": sw["idx"], "count": len(sw["variants"])}

    def swipe_generate(self, on_stage=None) -> "Iterator[str]":
        """Generate a NEW alternative for the last narrator turn and select it
        (swipe past the end of the list). Reuses the retry rollback so mechanics
        don't stack; prior variants are kept for browsing."""
        sw = self._ensure_swipes()
        if sw is None:
            return
        turns = self.store.turns()
        n = len(turns)
        if n >= 2 and turns[-2]["role"] == "player":
            player_input = turns[-2]["text"]
            self.store.drop_last_turns(2)
            self.restore_pre_turn_rpg()
            self.store.trim_folds_to_transcript()
            gen = self.turn(player_input, on_stage=on_stage)
        elif n == 1:
            self.store.drop_last_turns(1)
            self.restore_pre_turn_rpg()
            self.store.trim_folds_to_transcript()
            gen = self.opening(on_stage=on_stage)
        else:
            self.store.drop_last_turns(1)
            self.restore_pre_turn_rpg()
            self.store.trim_folds_to_transcript()
            gen = self.continue_story(on_stage=on_stage)
        try:
            yield from gen
        finally:
            # A `finally`, not straight-line code after the yield. Stop closing
            # this generator mid-stream — which is exactly what
            # srv/core.py's `finally: it.close()` does — skipped the cleanup
            # entirely, so _swipes survived pointing at an exchange the swipe
            # had already deleted. Two of the three failure modes the comment
            # below names were still corrupting the transcript.
            self._settle_swipe(sw, n)

    def _settle_swipe(self, sw: dict, n: int) -> None:
        """Adopt the regenerated turn as a new variant, or drop the swipe state
        when the regeneration produced nothing."""
        tail = self.store.turns()
        # `n`, not just "the tail is a narrator turn". A regeneration that
        # produced nothing (empty output, a model error, or Stop closing the
        # generator mid-stream) leaves the exchange DELETED — the entry point's
        # own cleanup drops the orphan player turn — so tail[-1] is the PREVIOUS
        # exchange's narration. Accepting that as a variant of the swiped turn
        # meant the next ◄ wrote one exchange's prose over another one's turn,
        # in transcript.md, which is the source of truth (invariant 7).
        if len(tail) == n and tail[-1]["role"] == "narrator":
            sw["variants"].append(tail[-1]["text"])
            sw["idx"] = len(sw["variants"]) - 1
        else:
            # The exchange this swipe state describes is gone. Keeping the
            # variants would let the next ◄ write the deleted exchange's prose
            # over whatever turn now sits at the tail — a different exchange's
            # turn, in transcript.md, which is the source of truth.
            self._swipes = None

    def impersonate(self) -> str:
        """Draft the PLAYER's next action in first person (ST 'Impersonate',
        ST-04). Returns a short suggestion; stores nothing — the UI drops it in
        the composer for the player to edit or send."""
        history = self.history_window()
        messages = self._messages(
            history,
            "Suggest MY next move as the player: first person, 1-2 sentences, "
            "only the action or dialogue I take — do NOT narrate any outcomes "
            "or write as the narrator.")
        if not self.cfg.generation.get("think", False) and messages:
            messages = [{**messages[0],
                         "content": messages[0]["content"] + "\n\n/no_think"},
                        *messages[1:]]
        with llm_stage(self.llm, "impersonate"):
            raw = "".join(self.llm.stream(messages))  # stream() filters <think>
        visible, _ = sidecar_mod.strip_sidecar(raw)  # drop any ```rpg block
        return visible.strip()

    def undo_last(self) -> bool:
        """Remove the last exchange WITHOUT regenerating — the player is left at the
        prior state to try a different action. Mirrors the retry rollback (drop the
        last narrator + its player turn, roll back this turn's RPG mechanics) but does
        not call the model. Returns False when there's nothing to undo.

        Single-level within the session: `restore_pre_turn_rpg` holds one snapshot, so
        a second consecutive undo won't further rewind mechanics (multi-level undo
        would need per-turn persisted snapshots).

        The TRANSCRIPT, however, shrinks on every press, and nothing limits how
        often this is called — the UI offers it every turn, with a hotkey. Press
        it enough and the transcript retreats past a fold boundary, so the folds
        are trimmed back to what the transcript still supports."""
        turns = self.store.turns()
        # Two turns only when there really IS a player turn behind the narration.
        # `continue_story` appends a narrator turn with no player turn before it,
        # so after a Continue this dropped a narration that was never part of this
        # exchange, truncating the event log further than the state was rolled
        # back — the divergence the `rolled_back` guard exists to prevent.
        if turns and turns[-1]["role"] == "narrator" and len(turns) >= 2 \
                and turns[-2]["role"] == "player":
            self.store.drop_last_turns(2)
        elif turns and turns[-1]["role"] == "narrator":
            self.store.drop_last_turns(1)     # a Continue: narration only
        elif turns and turns[-1]["role"] == "player":
            self.store.drop_last_turns(1)  # orphan player turn (empty generation)
        else:
            return False
        self.restore_pre_turn_rpg()
        self.store.trim_folds_to_transcript()
        return True

    def rollback_for_retry(self) -> tuple[bool, str | None]:
        """Roll the last exchange back so the caller can regenerate it.

        ONE implementation, because there were three (web, CLI, Tk) and all
        three had the same defect: they dropped two turns whenever the last was
        narration, without checking a player turn was actually behind it. After
        a Continue that destroyed the PREVIOUS exchange's narration, re-fed the
        narrator's own prose to the model as the player's action, and truncated
        the replay ledger two records deep while rolling state back one — so the
        save and the ledger disagreed and a branch produced a different story.

        Returns (ok, player_input). `player_input` is None when the last turn
        was a Continue: there is no player action to replay, so regenerate with
        `continue_story()`.
        """
        turns = self.store.turns()
        if turns and turns[-1]["role"] == "narrator" and len(turns) >= 2 \
                and turns[-2]["role"] == "player":
            player_input = turns[-2]["text"]
            self.store.drop_last_turns(2)
        elif turns and turns[-1]["role"] == "narrator":
            player_input = None               # a Continue owns only its narration
            self.store.drop_last_turns(1)
        elif turns and turns[-1]["role"] == "player":
            # orphan player turn (the previous generation produced nothing)
            player_input = turns[-1]["text"]
            self.store.drop_last_turns(1)
        else:
            return False, None
        self.restore_pre_turn_rpg()
        self.store.trim_folds_to_transcript()
        self._swipes = None
        return True, player_input

    def regenerate(self, player_input: str | None, on_stage=None):
        """The generator that pairs with `rollback_for_retry`'s return."""
        # Empty transcript FIRST. Retrying the opening rolls back to zero turns
        # and returns player_input=None, so the old order sent it to
        # continue_story — "carry on from where it left off", with nothing to
        # carry on from — and the `not turns()` guard below was dead for the one
        # case it was written for. Worse, continue_story never consults
        # opening_override(), so retrying the first turn of a save with an
        # authored `## Opening` replaced that greeting with model prose.
        # swipe_generate already routes n==1 to opening(); retry now agrees.
        if not self.store.turns():
            return self.opening(on_stage=on_stage)
        if player_input is None:
            return self.continue_story(on_stage=on_stage)
        return self.turn(player_input, on_stage=on_stage)

    def maybe_fold(self, on_stage=None) -> list[str]:
        """Run due memory folds after a turn. Returns event strings for the UI —
        RPG mechanics events (from this turn's sidecar) first, then fold events.

        Pass `on_stage` to see progress while it works; this runs after the prose
        has streamed, so a silent fold reads as a frozen turn."""
        events = self._rpg_events + self.summarizer.maybe_fold(on_stage)
        self._rpg_events = []
        return events

    def _expand_authored(self, text: str) -> str:
        """ST-20: expand macros in a verbatim authored string (the opening), with
        the same context assemble() uses so results match."""
        from .macros import expand_macros
        ws = self.store.world_state()
        tm = ws.get("time") if isinstance(ws.get("time"), dict) else {}
        rpg = ws.get("rpg") if isinstance(ws.get("rpg"), dict) else {}
        try:
            seed = int(rpg.get("seed", 0))
        except (TypeError, ValueError):
            seed = 0
        player = self.store.entries("player.md")
        return expand_macros(text, player=(player[0].title if player else "you"),
                             clock=self.store.clock_str(),
                             day=str(tm.get("day", "")), seed=seed,
                             turn=len(self.store.turns()))

    def _apply_output_regex(self, text: str) -> str:
        """ST-31: run the save's persistent find/replace rules over narrator output.
        A bad pattern is skipped; a pattern that could catastrophically backtrack
        (ReDoS — a real risk since rules ride inside shared/imported worlds) is
        rejected by safe_output_regex, never executed."""
        rules = self.store.world_state().get("regex_rules")
        if not isinstance(rules, list):
            return text
        for r in rules:
            if not isinstance(r, dict):
                continue
            find = r.get("find")
            if not isinstance(find, str) or not safe_output_regex(find):
                if isinstance(find, str):
                    self.store.log_degraded(
                        "output-regex", f"rule skipped as unsafe: {find[:80]}")
                continue
            fl = 0
            for ch in str(r.get("flags", "")).lower():
                fl |= {"i": re.I, "m": re.M, "s": re.S}.get(ch, 0)
            # Accept SillyTavern/JS-style $1 backreferences (Python re wants \1).
            repl = re.sub(r"\$(\d)", r"\\\1", str(r.get("replace", "")))
            try:
                text = re.sub(find, repl, text, flags=fl)
            except re.error as e:   # invalid rule -> text unchanged, but say so
                self.store.log_degraded("output-regex",
                                        f"invalid rule {find[:60]}: {e}")
        return text

    def _reply_prefix(self) -> str:
        """ST-22 'Start reply with': a persistent literal prefix every generated
        narrator turn begins with (e.g. a quote, an asterisk, a name). Cross-provider
        because we prepend it rather than relying on backend prefix-continuation."""
        v = self.cfg.generation.get("start_reply_with", "")
        return v if isinstance(v, str) else ""    # ignore a malformed non-string

    def _generate_and_store(self, messages, on_stage=None) -> "Iterator[str]":
        """Stream a narrator turn. The reply prefix (ST-22) is injected lazily — just
        before the first real prose chunk — so it only appears when a turn is actually
        produced. An empty/sidecar-only turn stores nothing AND shows nothing, so the
        streamed text always equals the stored text. Returns True iff a turn stored."""
        prefix = self._reply_prefix()
        inner = self._produce(messages, prefix, on_stage)
        if not prefix:
            return (yield from inner)     # no prefix -> unchanged passthrough
        sent = False
        while True:
            try:
                piece = next(inner)
            except StopIteration as done:
                return done.value
            if not sent:
                # Swallow leading whitespace-only chunks and emit the prefix only
                # once REAL prose arrives (so a sidecar-only turn that streams a
                # stray space/newline before the ```rpg fence shows no orphan
                # prefix). lstrip the first real chunk so the streamed prefix hugs
                # the prose exactly like the stored narration (which is stripped).
                if not piece.strip():
                    continue
                piece = piece.lstrip()
                yield prefix
                sent = True
            yield piece

    def _produce(self, messages, prefix, on_stage=None) -> "Iterator[str]":
        """The generation body (all three paths). Yields raw prose chunks and prepends
        `prefix` to the STORED narration so storage matches what was streamed."""
        rpg_on = self.store.rpg_enabled()
        sidecar = None
        trinity_events = None
        if self.trinity is None:
            # Single-brain: the one model IS the logic agent, so it gets the
            # event rules (in quad mode only the Director sees them). It also gets
            # the WORLD SIDECAR when RPG is off — the full envelope (rpg-rules.md)
            # is only injected with mechanics on, so without this a narrative story
            # would never learn it can move the clock/location or reveal a secret,
            # even though the engine applies those deltas in every mode. RPG-on
            # stories already have the full envelope, so don't double up.
            add = "" if rpg_on else templates.WORLD_SIDECAR
            ev_block = self.store.event_rules_block()
            if ev_block:
                add = ((add + "\n\n") if add else "") + ev_block \
                    + "\n\n(Enforce these silently; NEVER reveal an unfired rule " \
                      "in prose.)"
            if add and messages:
                messages = [{**messages[0],
                             "content": messages[0]["content"] + "\n\n" + add},
                            *messages[1:]]
            # Optional continuity pass BEFORE the prose (one extra call). Works
            # without the quad pipeline — see _lore_check. Rate-limited by
            # lore_check_every, since the world rarely changes enough to need
            # re-verifying on every single turn.
            if self.lore_due():
                directive = self._lore_check(messages, on_stage)
                if directive:
                    messages = [*messages,
                                {"role": "system", "content": directive}]
        # The active chapter, restated where it binds. Costs no extra call: the
        # plan is already on disk. Placed AFTER any continuity directive so the
        # chapter goal is the last thing read before writing.
        if self.cfg.generation.get("chapter_outline", True):
            chapter = _chapter_directive(self.store)
            if chapter:
                messages = [*messages, {"role": "system", "content": chapter}]
        if self.trinity is not None:
            # Quad pipeline: the Logic Agent's envelope is validated and RESOLVED
            # before the Narrator writes (so prose narrates the actual outcome);
            # trinity returns the already-applied events, not a sidecar.
            # Simple Story mode = the FAST mode: no mechanics to plan, so the
            # Logic Agent is skipped entirely — one LLM call per turn. Authored
            # event rules are the exception: only the Director can fire them, so
            # their presence forces the full pipeline even in simple mode.
            simple = (not rpg_on and self.store.mode() == "simple"
                      and not self.store.event_rules())
            chunks: list[str] = []
            trinity_events = yield from self.trinity.generate(
                messages, rpg_on, on_stage, chunks, skip_logic=simple,
                event_rules=self.store.event_rules_block())
            narration = "".join(chunks).strip()
        elif self.use_tool:
            raw = self._generate_with_tool(messages)
            # Strip/parse the sidecar in EVERY mode: world/lore deltas are valid
            # with RPG off (only mechanics are gated, in apply_envelope), and a
            # stray ```rpg block must never reach the reader verbatim.
            narration, sidecar = sidecar_mod.strip_sidecar(raw)
            if narration:
                yield narration
        else:
            # Qwen3 soft switch: /no_think for fast prose. Copy the system message
            # so we never mutate the caller's assembled context.
            if not self.cfg.generation.get("think", False) and messages:
                messages = [{**messages[0],
                             "content": messages[0]["content"] + "\n\n/no_think"},
                            *messages[1:]]
            chunks: list[str] = []
            hidden: list[str] = []
            # prose_tokens, NOT reply_tokens: reasoning is spent out of the same
            # allowance and goes first, so a prose-sized budget returns an empty
            # turn instead of a short one (measured 4/4 empty on the shipped
            # default model). See config.REASONING_HEADROOM.
            stream = self.llm.stream(
                messages, max_tokens=config.prose_tokens(self.cfg.generation))
            # Filter in EVERY mode (see the tool path above): never leak a
            # ```rpg block, and keep the world/lore delta channel open.
            stream = sidecar_mod.filter_sidecar(stream, hidden)
            # Then drop any context scaffolding the model copied back at the top
            # of its reply. messages[0] ONLY: that is where assemble() puts the
            # sections, and matching against the transcript too would let a
            # legitimately repeated line be deleted as an echo.
            echoed: list[str] = []
            stream = streaming.filter_context_echo(
                stream,
                streaming.prompt_line_set(messages[0]["content"] if messages
                                          else ""),
                echoed)
            for piece in stream:
                chunks.append(piece)
                yield piece
            if echoed:
                self.store.log_degraded(
                    "writer", f"dropped {len(echoed)} line(s) of context the "
                              f"model copied back into its prose: "
                              f"{echoed[0]!r:.60}")
            narration = "".join(chunks).strip()
            if hidden:
                sidecar = sidecar_mod.parse_sidecar("".join(hidden))
                if not narration:
                    # Everything from the marker onward IS the sidecar by
                    # design, so a model that opens with the fence loses the
                    # prose that follows it. The quad path reports exactly this
                    # ("prose was swallowed by a stray sidecar fence"); the
                    # single-brain path swallowed it in silence, and a turn that
                    # applied deltas still counts as stored, so the reader got a
                    # blank turn with no explanation anywhere.
                    stray = "".join(hidden).strip()
                    self.store.log_degraded(
                        "writer", "no visible prose — all of it was inside or "
                                  f"after the sidecar fence ({len(stray)} chars)")
        if narration:
            # ST-31 scrubs the MODEL's output; the ST-22 prefix is prepended AFTER
            # so a cleanup rule can't eat it (the prefix always begins the turn).
            narration = self._apply_output_regex(narration)
            if prefix:
                narration = prefix + narration
            if narration.strip():        # a rule that empties the turn stores nothing
                self.store.append_turn("narrator", narration)
            else:
                narration = ""
                self.store.log_degraded(
                    "writer", "an output-regex rule emptied the turn; "
                              "nothing was stored")
        elif not (sidecar or trinity_events):
            # Nothing at all: no prose, no sidecar, no quad events. On a Continue
            # this was completely invisible — no turn, no stage line, no toast,
            # no event bar, and no health entry either, so the reader clicked a
            # button and nothing whatsoever happened. Invariant 2 is about
            # exactly this: degrading is fine, degrading in silence is not.
            self.store.log_degraded(
                "writer", "the model returned no prose at all (empty or "
                          "think-only output); nothing was stored")
        # Apply mechanics even when the model emitted ONLY a sidecar (no visible
        # prose) — otherwise a terse mechanical turn would silently lose its check
        # and deltas. A turn counts as "stored" if it produced prose OR mechanics,
        # so the player's action isn't dropped as an orphan when it had an effect.
        applied = False
        if trinity_events is not None:
            # Quad path already validated + applied inside trinity.generate.
            self._rpg_events += trinity_events
            applied = _any_applied(trinity_events)
            if not narration and self.store.clamp_event_log_to_transcript():
                # The envelope was logged against a narrator turn that never
                # arrived. Re-index it onto the last real turn, loudly: the
                # deltas ARE in state, so a ledger that skipped them would make
                # every future branch from here silently wrong.
                self.store.log_degraded(
                    "quad-ledger", "Writer produced no turn; its envelope was "
                    "re-indexed onto the last stored turn")
        elif sidecar:
            events = self.apply_envelope(sidecar, rpg_on)
            self._rpg_events += events
            applied = _any_applied(events)
        return bool(narration) or applied

    def apply_envelope(self, env: dict, rpg_on: bool,
                       log_turn: int | None = None) -> list[str]:
        """The Backend Validator seam (SPEC-V2 §1.4), shared by both producers:
        validate the proposed envelope, surface every dropped delta loudly, apply
        world deltas (always) + reveals + mechanics (when RPG is on), and append
        the clean envelope to the events log for undo/branch replay. The record's
        turn index is the NARRATOR turn the envelope belongs to — pass `log_turn`
        when applying before that turn is appended (the quad pipeline does)."""
        stats = list(sidecar_mod.cfg_get(self.cfg.rpg, "stats"))
        clean, rejected = validator_mod.validate(env, self.store, stats=stats)
        events = [f"validator: dropped {r['delta']} — {r['reason']}"
                  for r in rejected]
        events += validator_mod.apply_world(self.store, clean)
        events += self._apply_reveals(clean)
        events += self._apply_quest_canon(clean)
        events += self._apply_event_rules(clean)
        if rpg_on:
            if self.rpg_mod is not None:
                events += self.rpg_mod.apply(self.store, clean, self.cfg.rpg)
            else:
                # RPG save opened on a free install: prose continues, the
                # mechanics are skipped LOUDLY (never silently absorb deltas).
                events.append("rpg: mechanics skipped — the RPG module is "
                              "not present in this build")
        if clean.get("check") or clean.get("deltas"):
            self.store.append_event_log(
                {"turn": len(self.store.turns()) if log_turn is None
                 else log_turn, "env": clean})
        return events

    def _apply_reveals(self, clean: dict) -> list[str]:
        """Flip validated `reveal` slugs public — the one sanctioned Markdown
        mutation (SPEC-V2 §2.3): logged as a canon event, tracked per turn so
        undo/retry re-hides them (state snapshots don't cover md)."""
        events = []
        for slug in (clean.get("deltas") or {}).get("reveal", []):
            e = self.store.set_hidden(slug, False)
            if e is None:
                continue
            self._pre_turn_reveals.append(slug)
            self._pre_turn_canon.append(f"revealed-{slug}")
            self.store.merge_entry("canon-events.md", Entry(
                title=f"Revealed: {e.title}", slug=f"revealed-{slug}",
                importance=min(5, e.importance),
                attrs={"when": self.store.clock_str()},
                body=f"The truth about [[{slug}]] came to light."))
            events.append(f"revealed: {e.title}")
        return events

    def _apply_event_rules(self, clean: dict) -> list[str]:
        """Mark fired once-rules consumed (validated already: exists + not yet
        consumed). Undo-tracked — retry/undo un-consumes."""
        events = []
        rules = {e.slug: e for e in self.store.event_rules()}
        for slug in (clean.get("deltas") or {}).get("event_fired", []):
            rule = rules.get(slug)
            if rule is None:
                continue
            once = str(rule.attrs.get("once", "")).strip().lower() in \
                ("true", "yes", "1", "on")
            if once and self.store.mark_event_consumed(slug):
                self._pre_turn_events.append(slug)
                events.append(f"event: {rule.title} fired (once — consumed)")
            else:
                events.append(f"event: {rule.title} fired")
        return events

    def _apply_quest_canon(self, clean: dict) -> list[str]:
        """A quest reaching completed/failed is story canon — log it as a canon
        event (undo-tracked, like reveals). The quests dict itself was already
        committed by apply_world; the thread entry stays for the summarizer to
        resolve narratively at the next fold."""
        events = []
        for slug, new in ((clean.get("deltas") or {}).get("quest_update")
                          or {}).items():
            if new not in ("completed", "failed"):
                continue
            thread = next((e for e in self.store.entries("threads.md")
                           if e.slug == slug), None)
            title = thread.title if thread else slug
            canon_slug = f"quest-{slug}-{new}"
            self._pre_turn_canon.append(canon_slug)
            self.store.merge_entry("canon-events.md", Entry(
                title=f"Quest {new}: {title}", slug=canon_slug,
                importance=4, attrs={"when": self.store.clock_str()},
                body=f"[[thread:{slug}]] ended: {new}."))
            events.append(f"quest {new}: {title}")
        return events

    def companions(self) -> list[str]:
        """Slugs a side-chat can target: characters flagged `companion: true`
        plus anyone already in the state's companions block."""
        marked = [e.slug for e in self.store.entries("characters.md")
                  if str(e.attrs.get("companion", "")).strip().lower()
                  in ("true", "yes", "1", "on")]
        state = list(self.store.rpg_state().get("companions", {}))
        return list(dict.fromkeys(marked + state))

    def companion_chat(self, name: str, user_text: str) -> Iterator[str]:
        """Out-of-band side-chat with a companion (SPEC-V2 §3.4): a private
        conversation between story turns — advice, banter, strategy. Streams the
        reply; logs to memory/companion-chat.md (NEVER the transcript: no turn
        counter, no folds). The story sees only a short digest via assemble."""
        from .templates import slugify
        slug = slugify(str(name or ""))
        comp = next((e for e in self.store.entries("characters.md")
                     if e.slug == slug), None)
        if comp is None:
            yield f"(no such character: {name})"
            return
        cstate = self.store.rpg_state().get("companions", {}).get(slug, {})
        mood = ", ".join(f"{k}: {v}" for k, v in cstate.items() if v)
        tail = self.store.recent_turns(6)
        story = "\n".join(f"[{t['role'].upper()}] {t['text'][:400]}"
                          for t in tail)
        prior = self.store.companion_chat_tail(slug, lines=12)
        sys = (f"You ARE {comp.title}, a companion travelling with the player in "
               "an interactive story. This is a PRIVATE conversation between "
               "story turns — speak in first person, fully in character (see "
               "your Voice). Give opinions, advice, warnings, banter; ask "
               "questions back. Do NOT narrate story events, do NOT advance the "
               "plot, do NOT speak for the player. Keep replies short and "
               "conversational (2-6 sentences).\n\n# WHO YOU ARE\n"
               + comp.render()
               + (f"\n# YOUR CURRENT STATE\n{mood}" if mood else "")
               + (f"\n\n# WHAT JUST HAPPENED IN THE STORY\n{story}" if story
                  else "")
               + (f"\n\n# YOUR EARLIER PRIVATE TALK\n{prior}" if prior else ""))
        messages = [{"role": "system", "content": sys},
                    {"role": "user", "content": user_text}]
        chunks: list[str] = []
        with llm_stage(self.llm, "talk"):
            for piece in self.llm.stream(messages):
                chunks.append(piece)
                yield piece          # inside the loop: this streamed the LAST
                                     # chunk only, and raised UnboundLocalError
                                     # when the model yielded nothing at all
        reply = "".join(chunks).strip()
        if reply:
            self.store.append_companion_chat(slug, user_text, reply)

    def lore_due(self) -> bool:
        """Is the continuity pass due on the exchange we're about to write?

        Frequency mirrors the author's note (ST-21): count NARRATOR turns so far,
        +1 for the one being written, and fire when that number is a multiple of
        `lore_check_every`. every=1 is every turn; every=3 is turns 3, 6, 9...
        Counting exchanges (not raw messages) keeps it independent of
        player/narrator parity, and it is derived from the transcript so a retry of
        the same turn makes the same decision."""
        return (bool(self.cfg.generation.get("lore_check", False))
                and self.lore_cadence_due())

    def lore_cadence_due(self) -> bool:
        """The FREQUENCY half only — is this exchange a multiple of every-N?
        Kept separate because the quad pipeline decides enablement its own way
        (the legacy trinity.lorekeeper.llm_pass flag), and must still honor the
        cadence without being gated on `lore_check`."""
        try:
            every = max(1, int(self.cfg.generation.get("lore_check_every", 1) or 1))
        except (TypeError, ValueError):
            every = 1
        if every == 1:
            return True
        exchange = sum(1 for t in self.store.turns()
                       if t.get("role") == "narrator") + 1
        return exchange % every == 0

    def _lore_check(self, messages, on_stage=None) -> str:
        """Standalone continuity pass — the lore-keeper WITHOUT the quad pipeline.
        It never needed the Director's plan: given the context and the action it can
        work out what the prose must not contradict. So single-brain + this is TWO
        calls with verification, rather than the three quad + lore-keeper costs.
        Returns a post-history directive, or "" when it finds nothing / fails
        (continuity is best-effort and must never break a turn)."""
        import time
        from .llm import emit_json_ex
        t0 = time.monotonic()
        if on_stage:
            on_stage("Continuity check")
        payload = ("STORY CONTEXT:\n" + messages[0]["content"]
                   + "\n\nPLAYER ACTION:\n"
                   + next((m["content"] for m in reversed(messages)
                           if m["role"] == "user"), ""))
        convo = [{"role": "system", "content": LORE_CHECK_SYS},
                 {"role": "user", "content": payload}]
        try:
            with llm_stage(self.llm, "lore"):
                # Through emit_json_ex, like every other JSON stage: token floor,
                # one retry with a nudge, and budget escalation when the reply was
                # starved rather than wrong. Doing this by hand made a single bad
                # reply final.
                obj, err = emit_json_ex(
                    _ToolJSONClient(self.llm, LOOKUP_TOOL, self._dispatch_tool),
                    "", messages=convo)
        except Exception as e:  # noqa: BLE001 — never fatal
            if on_stage:
                on_stage(f"Lore-keeper FAILED ({time.monotonic() - t0:.1f}s): {e} "
                         "— continuing unvetted")
            self.store.log_degraded("lore-keeper", f"{type(e).__name__}: {e}")
            return ""
        if not isinstance(obj, dict):
            if on_stage:
                on_stage(f"Lore-keeper FAILED ({time.monotonic() - t0:.1f}s): "
                         "no valid JSON — continuing unvetted")
            # The REASON, not just the symptom: emit_json_ex distinguishes
            # truncated from empty from malformed and carries the tail, which is
            # the difference between "raise the budget" and "the model is wrong".
            self.store.log_degraded(
                "lore-keeper", f"no usable JSON: {err or 'unknown'}"[:400])
            return ""
        directive = _lore_directive(obj)
        if on_stage:
            n = len(obj.get("vetted_facts") or []) + len(obj.get("patches") or [])
            on_stage(f"Lore-keeper done ({time.monotonic() - t0:.1f}s): "
                     f"{n} continuity point(s)")
        return directive

    def _generate_with_tool(self, messages) -> str:
        return self.llm.complete_with_tools(
            messages, LOOKUP_TOOL, self._dispatch_tool,
            max_tokens=config.prose_tokens(self.cfg.generation)).strip()

    def _dispatch_tool(self, name, args):
        """Resolve a memory tool call (shared by the lookup path and Trinity's
        Lore-keeper). recall_turns is the on-demand pointer-back into the full
        transcript behind a timeline shorthand."""
        if name == "lookup_memory":
            return self.store.lookup(str(args.get("query", "")))
        if name == "recall_turns":
            return self.store.recall_turns(str(args.get("reference", "")))
        if name == "recall_entity":
            return self.store.recall_entity(str(args.get("name", "")))
        if name == "recall_quest":
            return self.store.recall_quest(str(args.get("name", "")))
        return f"unknown tool: {name}"

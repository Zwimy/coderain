"""Phase 2: the fold pipeline.

After qualifying turns, fold the oldest short-term turns into a medium-tier scene
summary (memory/scenes.md), and fold accumulated scenes into the long-tier arc
(memory/arc.md). Following memory-rules.md, the summarizer also *promotes* durable
facts into their home files (characters, canon-events, threads, ...).

Reliability guards:
- the model emits strict JSON; we validate it before touching any file
- a pre-fold snapshot of the story folder (undo)
- slug dedupe via upsert (no duplicate entities)
- graceful degradation: an unparseable fold still advances (keeps a stub summary)
  so the pipeline never loops forever
"""
from __future__ import annotations

import re

from .llm import emit_json
from .llm import stage as llm_stage
from .memory import Entry, KIND_FILE, MemoryStore, trigger_hit

SCENE_INSTRUCTION = """\
You are the story's memory keeper. Fold the TURNS below into ONE concise scene
summary and update durable memory, following the memory rules. You are given the
CURRENT versions of relevant entities — when one changes, REWRITE its full entry
(stable identity + all still-true facts + the change), do not just append. Always
restate every still-true relationship, status, and detail; omitting one means it
no longer holds.

Return ONLY a JSON object, no prose, with this shape:
{
  "scene_summary": "<= 150 words. Reference entities by [[type:slug]] only; do not restate their details.",
  "timeline": "<= 20 words. A terse one-line shorthand of this block for the timeline index. Reference entities by [[type:slug]].",
  "time": {"day": 3, "phase": "evening", "note": "optional"},
  "characters": ["slug of every character present in these turns"],
  "locations": ["slug of every location visited"],
  "quests": ["slug of every thread/quest these turns touched"],
  "state_changes": ["terse machine-readable change, e.g. quests.missing-daughter -> active"],
  "facts": ["timeless world truths established here (NOT events), e.g. The capital is Asterhold"],
  "promotions": [
    {"kind": "character|location|faction|item|canon-event",
     "slug": "kebab-case-id", "title": "Display Name",
     "aliases": ["alt name"], "importance": 1-5,
     "status": "one-line current state (optional)",
     "when": "in-world time this became true (optional)",
     "cause": "canon-event importance>=4 ONLY: what caused it (the WHY)",
     "consequence": "canon-event importance>=4 ONLY: what it changed (the SO-WHAT)",
     "wants": "characters ONLY: their goal RIGHT NOW, one concrete line",
     "motivation": "characters ONLY: why they want it (the driver underneath)",
     "relationships": [{"with": "other-slug", "note": "ally / rival / owes debt"}],
     "detail": "FULL rewritten detail for this entity's home file"}
  ],
  "new_threads": [
    {"slug": "kebab-id", "title": "Thread name", "importance": 1-5,
     "detail": "what is unresolved"}
  ],
  "resolved_threads": ["slug-of-resolved-thread"],
  "chapter_goal_met": false
}
Set "chapter_goal_met" to true ONLY when an ACTIVE CHAPTER is given below AND these
turns show its goal has genuinely, fully landed — otherwise false. Do not advance a
chapter early.
"time" is optional — include it only if in-world time moved forward. "relationships"
only applies to characters. Only promote genuinely durable, story-relevant facts.
"""

ARC_INSTRUCTION = """\
Update the long-term ARC synopsis by folding in the older SCENE summaries below.
Keep it terse (<= 200 words total), chronological, and reference entities and
events by [[type:slug]] only.

Return ONLY a JSON object: {"arc": "<the updated synopsis>"}
"""


def _as_day(v) -> int:
    """Current day as an int for the monotonic guard; anything unusable = 0."""
    if isinstance(v, bool) or not isinstance(v, int):
        return 0
    return v


STR_LIMIT = 200      # free-text from a fold, mirroring validator.STR_CAP
# Prose from a fold: a scene summary, a promotion body, the arc synopsis. The
# instructions ask for 150-200 WORDS, so ~4k chars is far past anything
# legitimate while still stopping a runaway generation from becoming permanent
# context — a fold is one-way, and an oversized body is re-sent every turn after.
BODY_LIMIT = 4000
# An attr line holding MANY values (relationships, the episode indexes) gets its
# own bound — STR_LIMIT would fit about three of them.
REL_LIMIT = 800
# Items per model-supplied list in a fold. Mirrors validator.LIST_CAP: the
# validator bounds the per-turn channel, and this is the fold's.
LIST_LIMIT = 32
# Highest in-world day a fold may set. ~27,000 years of story is not a real
# ceiling for anyone; a bound that keeps the number short in every prompt is.
DAY_CAP = 10_000_000


def _as_list(v) -> list:
    """Model-supplied lists, defensively. A scalar where a list belongs raised
    TypeError straight out of maybe_fold — leaving earlier promotions from the
    same object already on disk, the fold pointer unmoved, and the identical
    chunk re-folding (and re-crashing) on every following turn."""
    return v if isinstance(v, list) else []


def _join_bounded(parts: list[str], sep: str = ", ",
                  limit: int = REL_LIMIT) -> tuple[str, int]:
    """Join `parts` under `limit` chars WITHOUT ever cutting one in half.
    Returns (line, how many were dropped).

    Slicing the joined string at a character count left half a slug in the
    episode index: recall_entity then matched a phantom key ("ca") and missed
    the real one, and every entry after the cut vanished with no trace. Whole
    items only, and the caller logs what did not fit."""
    out, used = [], 0
    for p in parts:
        cost = len(p) + (len(sep) if out else 0)
        if used + cost > limit:
            break
        out.append(p)
        used += cost
    return sep.join(out), len(parts) - len(out)


def _one_line(v) -> str:
    """Collapse an attr value to a single line.

    Entry headers are `key: value` lines, and parse_entries stops at the first
    line that is not one. So a newline inside ANY attr value silently swallowed
    every attr after it: a promotion carrying status="wounded
hiding" lost the
    character's wants and motivation entirely, and because the rewrite path only
    re-attaches values that survived the parse, the very next fold that did not
    restate them made the loss permanent.

    Length is bounded here rather than at the call sites: every caller writes an
    attr line, only two of them remembered to trim, and an attr is re-rendered
    into context on every turn the entry activates.
    """
    return " ".join(str(v or "").split())[:STR_LIMIT]


def _turns_text(turns: list[dict]) -> str:
    out = []
    for t in turns:
        who = "PLAYER" if t["role"] == "player" else "NARRATOR"
        out.append(f"[{who}] {t['text']}")
    return "\n\n".join(out)


class Summarizer:
    def __init__(self, config, store: MemoryStore, llm, planner=None):
        self.cfg = config
        self.store = store
        self.llm = llm
        # The chapter planner (optional): seeded on the first fold and rolled
        # forward when a scene fold reports the active chapter's goal has landed —
        # so chapter planning never costs a per-turn call.
        self.planner = planner
        m = config.memory
        # Clamp >=2: retry/undo drop up to the last 2 turns, and the fold invariant
        # "folded turns are never in the droppable tail" only holds while at least
        # 2 turns stay verbatim after every fold (guards a pathological config).
        self.medium_after = max(2, int(m.get("medium_fold_after", 12)))
        # Sizes clamp >=1: size 0 would never advance the fold counter while
        # the due-condition stays true — an infinite loop of LLM calls.
        self.medium_size = max(1, int(m.get("medium_fold_size", 6)))
        # Snapshot retention bounds how far back a clean branch can reach
        # (SPEC-V2 §4.2) — each pre-fold snapshot is a branch restore point.
        self.snapshot_keep = max(1, int(m.get("snapshot_keep", 5)))
        self.long_after = int(m.get("long_fold_after", 8))
        self.long_size = max(1, int(m.get("long_fold_size", 4)))

    # --- LLM call: thinking ON, JSON out, one retry ---
    def _emit_json(self, instruction: str, payload: str) -> dict | None:
        rules = self.store.read("memory-rules.md").strip()
        with llm_stage(self.llm, "fold"):
            return emit_json(self.llm, rules + "\n\n" + instruction, payload)

    def _hold_resolved(self, slug: str, attrs: dict) -> bool:
        """Keep a resolved thread resolved. Returns whether it had to intervene.

        `resolved_threads` is the only door that closes a thread and there is no
        door that reopens one, so any fold output that would move a thread back to
        open is a mistake, not an authored transition. Two ways in, both real:
        a `status: open` from the model, and — with rewrite=True — a promotion
        that simply omits `status`, since merge_entry treats the managed keys as
        authoritative and a missing one as a deliberate clear. Either way the
        thread comes back into the open-threads block that rides every turn.
        Matches assemble()'s test exactly: only "resolved" counts as closed."""
        was = {e.slug: e for e in self.store.entries("threads.md")}.get(slug)
        if was is None or was.attrs.get("status", "open").lower() != "resolved":
            return False
        if attrs.get("status", "").lower() == "resolved":
            return False
        attrs["status"] = "resolved"
        return True

    def _player_slugs(self) -> set[str]:
        """Every slug that means "the protagonist".

        player.md already holds the player's sheet and rides EVERY prompt at
        priority 0. A fold that promotes the protagonist into characters.md
        creates a second, thinner copy of them which then competes with the real
        sheet for lore budget and can contradict it. Measured in a 14-turn local
        run: a `you` entry with an empty status, plus five more attempts on
        you/player/<the player's invented name> filling health.jsonl."""
        out = {"player", "you", "me", "myself", "self", "protagonist"}
        for e in self.store.entries("player.md"):
            for name in (e.slug, e.title, *e.aliases):
                s = _slugify(str(name))
                if s:
                    out.add(s)
        return out

    # --- apply validated promotions ---
    def _apply_promotions(self, obj: dict) -> list[str]:
        events: list[str] = []
        # Read once per fold, not once per promotion: entries() re-reads the file.
        player_slugs = self._player_slugs()
        for p in _as_list(obj.get("promotions")):
            if not isinstance(p, dict):
                continue
            kind = str(p.get("kind", "")).strip().lower()
            rel = KIND_FILE.get(kind)
            slug = _slugify(str(p.get("slug", "")))
            # Through _one_line as well: Entry.render writes the title into the
            # `## {title}  {{#slug}}` header, so a newline there splits the entry
            # and the next promotion of the same slug creates a DUPLICATE.
            title = _one_line(p.get("title", "")) or slug
            detail = str(p.get("detail", "")).strip()[:BODY_LIMIT]
            if not rel or not slug or not detail:
                # Loudly. A promotion the fold meant to make and the engine
                # cannot is exactly the silent one-way loss invariant 2 is
                # about — and this branch also catches an unusable `kind`,
                # which an author reading health.jsonl can actually fix.
                self.store.log_degraded(
                    "fold", "dropped a promotion: "
                            f"kind={kind!r:.40} slug={str(p.get('slug'))!r:.40} "
                            f"{'(no detail)' if not detail else ''}")
                continue
            if kind == "character" and slug in player_slugs:
                # Not a degradation — a promotion the engine is right to refuse.
                # Logged anyway so "why is there no `you` entry" has an answer in
                # the Context panel instead of looking like a lost fold.
                self.store.log_degraded(
                    "fold", f"skipped promoting the player as an NPC "
                            f"(slug={slug!r:.40}) — player.md is their sheet")
                continue
            attrs = {}
            if p.get("status"):
                attrs["status"] = _one_line(p["status"])
            if p.get("when"):
                attrs["when"] = _one_line(p["when"])
            # Live goals/motivations (memory-rules v10). Blank means "no change",
            # so a fold that doesn't mention them never wipes what's already there;
            # the rewrite path below re-attaches the previous values in that case.
            if kind == "character":
                for key in ("wants", "motivation"):
                    val = _one_line(p.get(key, ""))
                    if val:
                        attrs[key] = val
            rel_pairs = []
            # [:LIST_LIMIT] and [:STR_LIMIT], not just the joined cap below.
            # _slugify had no per-value bound, so ONE 3000-char `with` filled
            # the whole 800-char line and every real relationship after it was
            # dropped — silently, and a fold is one-way.
            for r in _as_list(p.get("relationships"))[:LIST_LIMIT]:
                if isinstance(r, dict) and r.get("with"):
                    rel_pairs.append(f"{_slugify(str(r['with'])[:STR_LIMIT])}: "
                                     f"{_one_line(r.get('note', ''))}")
            if rel_pairs:
                # Bounded, but NOT at _one_line's per-value STR_LIMIT: this one
                # attr holds every relationship a character has, and 200 chars is
                # three of them. Each individual note is already trimmed above,
                # and the join stops at a pair boundary — slicing the joined
                # string left half a note ("owes a debt f") on the last pair.
                attrs["relationships"], cut = _join_bounded(
                    [" ".join(r.split()) for r in rel_pairs], sep="; ")
                if cut:
                    self.store.log_degraded(
                        "fold", f"{slug}: {cut} relationship(s) did not fit the "
                                "entry and were dropped")
            # Causal chain for IMPORTANT events only (memory-rules v9): a
            # story-critical canon-event records why it happened and what it
            # changed, so the story stays coherent long after the raw turns fold
            # away. Ordinary beats skip this — verbose memory is re-sent every
            # future turn. Folded into the body (not the header) so it renders as
            # readable prose the writer sees, without inventing new lorebook attrs.
            importance = _clamp_int(p.get("importance", 3))
            if kind == "canon-event" and importance >= 4:
                cause = str(p.get("cause", "")).strip()
                conseq = str(p.get("consequence", "")).strip()
                tail = []
                if cause and cause.lower() not in detail.lower():
                    tail.append(f"Why: {cause}")
                if conseq and conseq.lower() not in detail.lower():
                    tail.append(f"So what: {conseq}")
                if tail:
                    detail = detail + "\n\n" + "\n".join(tail)
            aliases = p.get("aliases", [])
            if isinstance(aliases, str):
                # A bare string would iterate CHARACTER by character — every
                # one-letter alias then triggers on everything.
                aliases = [aliases]
            elif not isinstance(aliases, list):
                # A number or any other scalar raised TypeError straight out of
                # maybe_fold, aborting the fold AFTER earlier promotions in the
                # same object had already been written to disk.
                aliases = []
            # Each alias was already trimmed by _one_line; the LIST had no bound,
            # and aliases are the most expensive unbounded thing here — every one
            # is scanned against the story text by _entry_activates on every
            # turn, and the whole entry is re-rendered into every later fold
            # prompt. Nothing needs more than a handful of names.
            aliases = aliases[:LIST_LIMIT]
            entry = Entry(title=title, slug=slug,
                          # aliases render as one comma-joined line, so a newline
                          # breaks the header and a comma splits one alias in two.
                          aliases=[_one_line(a).replace(",", " ") for a in aliases
                                   if a and _one_line(a)],
                          importance=importance,
                          attrs=attrs, body=detail)
            if rel == "threads.md" and self._hold_resolved(slug, entry.attrs):
                events.append(f"memory: [[thread:{slug}]] is resolved — the "
                              "promotion was not allowed to reopen it")
            # rewrite=True: the model was shown the current entry and returns the
            # full rewritten body, so replace (not append) it.
            self.store.merge_entry(rel, entry, rewrite=True)
            events.append(f"memory: promoted [[{kind}:{slug}]]")

        for t in _as_list(obj.get("new_threads")):
            if not isinstance(t, dict):
                continue
            slug = _slugify(str(t.get("slug", "")))
            detail = str(t.get("detail", "")).strip()[:BODY_LIMIT]
            if not slug or not detail:
                continue
            # Only OPEN a thread that isn't already on file. merge_entry does
            # {**existing.attrs, **new.attrs}, so a hardcoded "open" overwrote
            # status: resolved — a fold that merely re-mentions a closed quest
            # silently reopened it, and it returned to the open-threads block
            # that rides every turn.
            known = {e.slug: e for e in self.store.entries("threads.md")}
            attrs = {} if slug in known else {"status": "open"}
            # No _hold_resolved call here on purpose: this door merges WITHOUT
            # rewrite, so a known thread contributes no status at all and the
            # existing one survives. The promotions door needs the guard because
            # rewrite=True makes a missing status an intentional clear.
            self.store.merge_entry("threads.md", Entry(
                title=_one_line(t.get("title", "")) or slug, slug=slug,
                importance=_clamp_int(t.get("importance", 3)),
                attrs=attrs, body=detail))
            events.append(f"memory: new thread [[thread:{slug}]]")

        for slug in _as_list(obj.get("resolved_threads")):
            slug = _slugify(str(slug))
            existing = {e.slug: e for e in self.store.entries("threads.md")}
            if slug in existing:
                e = existing[slug]
                e.attrs["status"] = "resolved"
                self.store.upsert_entry("threads.md", e)
                events.append(f"memory: resolved [[thread:{slug}]]")
        return events

    def _apply_time(self, obj: dict) -> list[str]:
        t = obj.get("time")
        if not isinstance(t, dict):
            return []
        state = self.store.world_state()
        tm = state.get("time")
        if not isinstance(tm, dict):
            tm = {}
            state["time"] = tm
        changed = False
        day = t.get("day")
        # Fold-time time is a FALLBACK (Wave 1): the per-turn time_advance delta
        # is the driver now, so a fold summarizing OLDER turns must never rewind
        # the clock. Day applies only monotonically; phase/note only when the
        # fold's day is at (or past) the live one — a Day-2 fold running after
        # play reached Day 3 must not drag the phase back to "evening".
        cur_day = _as_day(tm.get("day"))
        fold_day = day if isinstance(day, int) and not isinstance(day, bool) \
            else None
        # Magnitude-bounded. validator._valid_time caps the per-turn time_advance
        # at 1 day (30 across a scene break); the fold is the one writer that
        # sets `day` ABSOLUTELY, and it had no bound at all — a 4000-digit day
        # rendered into the priority-1 "Time" section of every prompt and into
        # the scene's `when:` attr.
        #
        # REJECTED, not clamped. Clamping is right for a relative advance, but
        # here it turns a rejectable value into a permanent wrong one: the
        # monotonic guard below means nothing can move the day back, so a single
        # hallucinated 1e9 pinned the clock at the cap AND froze every later
        # fold's phase/note, since none of them ever compare >= again.
        if fold_day is not None and not 0 <= fold_day <= DAY_CAP:
            self.store.log_degraded(
                "fold-time", f"ignored an out-of-range day ({fold_day!s:.40}); "
                             f"the clock stays at day {cur_day}")
            fold_day = None
        if fold_day is not None and fold_day >= cur_day:
            tm["day"], changed = fold_day, True
        current_or_later = fold_day is None or fold_day >= cur_day
        # One line, bounded — the per-turn time_advance path already does this in
        # validator._valid_time, and the fold path is the one writer that skipped
        # it. clock_str() feeds attrs["when"] on every scene, which renders BEFORE
        # the episode-index attrs; a newline there ends the header parse, so the
        # characters/locations/quests index becomes body prose and recall_entity
        # goes dead for that scene. A fold is one-way, so it never comes back.
        if t.get("phase") and current_or_later:
            tm["phase"], changed = _one_line(t["phase"]), True
        if "note" in t and current_or_later:
            note = _one_line(t.get("note", ""))
            if note != tm.get("note", ""):
                tm["note"], changed = note, True
        if not changed:
            return []
        self.store.set_world_state(state)
        return [f"memory: time -> {self.store.clock_str()}"]

    def _existing_context(self, turns: list[dict]) -> str:
        """Show the model the current entries for entities mentioned in the turns,
        so it can rewrite (not append) them.

        Also names any CHARACTER present here that has no `wants:` yet. That is the
        backfill path for stories that began before goals existed: a character gets
        one the next time they actually appear, so an ongoing save fills in as it
        plays rather than needing a migration."""
        text = _turns_text(turns).lower()
        matched = [(rel, e) for rel, e in self.store.index().entries.values()
                   if any(trigger_hit(tok, text) for tok in e.triggers())]
        if not matched:
            return "EXISTING ENTITIES: (none relevant)"
        # Which 12 matters. This used to be an arbitrary first-12 slice of dict
        # order, so on a busy chunk (measured: 31 entities relevant in one) the
        # entities that got shown — and therefore the only ones that could be
        # UPDATED — were effectively random, quietly leaving major characters
        # stale. Rank by importance, then by how recently the text mentions them,
        # so the fold always sees the ones that matter most.
        def rank(item):
            _rel, e = item
            last = max((text.rfind(t.lower()) for t in e.triggers()), default=-1)
            return (-e.importance, -last)
        matched.sort(key=rank)
        shown, overflow = matched[:12], matched[12:]
        out = ("EXISTING ENTITIES (rewrite in full if they change):\n\n"
               + "\n\n".join(e.render() for _rel, e in shown))
        # Never let an entity vanish silently: name the rest so the model can
        # still promote one it must update (it can restate the full entry).
        if overflow:
            out += ("\n\nALSO PRESENT (not shown in full — promote one only if "
                    "these turns genuinely change it): "
                    + ", ".join(f"{e.title} [[{e.slug}]]" for _rel, e in overflow))
        goalless = [e.title for rel, e in shown
                    if rel == "characters.md"
                    and not str(e.attrs.get("wants", "")).strip()]
        if goalless:
            out += ("\n\nNO GOAL RECORDED YET for: " + ", ".join(goalless)
                    + ". These characters act in these turns, so infer a concrete "
                      "`wants` (what they are after right now) and `motivation` "
                      "(why) for each from what they actually do and say, and "
                      "include them in that character's promotion.")
        return out

    # --- the folds ---
    def _fold_scene(self, turns: list[dict], scene_no: int,
                    start_turn: int) -> list[str]:
        events = [f"memory: folded scene {scene_no}"]
        # Hand the active chapter to the fold so it can report chapter_goal_met for
        # free (no extra call). Empty string when there's no outline.
        chapter_hint = self.planner.active_fold_hint() if self.planner else ""
        payload = self._existing_context(turns) \
            + (("\n\n" + chapter_hint) if chapter_hint else "") \
            + "\n\nTURNS:\n" + _turns_text(turns)
        obj = self._emit_json(SCENE_INSTRUCTION, payload)
        summary = ""
        shorthand = ""
        if obj:
            summary = str(obj.get("scene_summary", "")).strip()[:BODY_LIMIT]
            shorthand = str(obj.get("timeline", "")).strip()
            events += self._apply_promotions(obj)
            events += self._apply_time(obj)  # update clock before stamping the scene
        if not summary:
            # A stubbed scene is memory permanently lost for those turns: the
            # fold pointer advances regardless (by design, so it can't loop), so
            # this is the one degradation that never gets a second chance.
            summary = "(scene summary unavailable)"
            self.store.log_degraded(
                "fold", f"scene {scene_no} produced no summary — "
                        f"turns {start_turn}-{start_turn + len(turns) - 1} "
                        "are only in the raw transcript")
        when = self.store.clock_str()
        # Source-turn range this block covers (1-based inclusive) — the pointer the
        # timeline shorthand hands back for on-demand detail recall.
        end_turn = start_turn + len(turns) - 1
        attrs = {"turns": f"{start_turn}-{end_turn}"}
        if when:
            attrs["when"] = when
        # Wave 2 episode metadata — OPTIONAL: a truncated/failed emission still
        # folds as prose (a fold NEVER blocks on metadata); the entity/quest
        # indexes simply skip this episode.
        if obj:
            # Bounded on all three axes (list length, per-value length, joined
            # length) like every other model-derived value. These were the last
            # ones with none of the three, and they are the worst place to
            # miss it: Entry.render emits attrs BEFORE the body, so an oversized
            # attr line pushes its own scene summary past the budget cut — the
            # fold destroyed the raw turns and its replacement can then never
            # reach the model. A fold is one-way, so it never comes back.
            for key in ("characters", "locations", "quests"):
                vals = obj.get(key)
                if isinstance(vals, list) and vals:
                    slugs = [_slugify(v) for v in vals[:LIST_LIMIT]
                             if str(v).strip()]
                    if slugs:
                        line, cut = _join_bounded(list(dict.fromkeys(slugs)))
                        attrs[key] = line
                        if cut:
                            self.store.log_degraded(
                                "fold", f"scene {scene_no}: {cut} {key} left out "
                                        "of the episode index (too many to fit)")
            changes = obj.get("state_changes")
            if isinstance(changes, list) and changes:
                line, cut = _join_bounded(
                    [" ".join(str(c).split())[:STR_LIMIT]
                     for c in changes[:LIST_LIMIT] if str(c).strip()], sep="; ")
                attrs["state_changes"] = line
                if cut:
                    self.store.log_degraded(
                        "fold", f"scene {scene_no}: {cut} state change(s) did "
                                "not fit the episode index")
            day = self.store.world_state().get("time", {}).get("day")
            if isinstance(day, int) and not isinstance(day, bool):
                attrs["day"] = str(day)
            new_facts = obj.get("facts")
            if isinstance(new_facts, list) and new_facts:
                n = self.store.add_facts([str(f) for f in new_facts])
                if n:
                    events.append(f"memory: +{n} established fact(s)")
        entry = Entry(title=f"Scene {scene_no}", slug=f"scene-{scene_no}",
                      attrs=attrs, body=summary)
        self.store.upsert_entry("memory/scenes.md", entry)
        self._append_timeline(start_turn, end_turn, when, shorthand or summary)
        # Roll the chapter plan forward when THIS fold reports the active chapter's
        # goal landed (only when a chapter was actually handed to the fold, so a
        # stray flag on an outline-less story can't advance anything).
        if self.planner and chapter_hint and obj \
                and obj.get("chapter_goal_met") is True:
            events += self.planner.complete_active()
        return events

    def refold_scene(self, scene_slug: str) -> dict:
        """Re-summarise ONE already-folded scene from its original turns.

        A fold is where a story quietly loses things: it rewrites ten turns into
        a paragraph, and if that paragraph drops a thread you find out fifty
        turns later. This is the second chance the pipeline never had.

        Deliberately narrower than the original fold: it regenerates the summary
        and the timeline line, and does NOT re-run promotions. By the time you
        redo a fold, the entities it touched may have been edited by hand or by
        later folds, and re-applying a stale promotion would undo that. Fixing
        the summary is the job here; entities have their own editor.

        Snapshots first, like every other fold, so the redo is itself undoable.
        """
        entry = next((e for e in self.store.entries("memory/scenes.md")
                      if e.slug == scene_slug), None)
        if entry is None:
            return {"ok": False, "error": f"no such scene: {scene_slug}"}
        rng = str(entry.attrs.get("turns", "")).strip()
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", rng)
        if not m:
            return {"ok": False,
                    "error": "this scene has no source-turn range to rebuild from"}
        start, end = int(m.group(1)), int(m.group(2))
        turns = self.store.turns()[start - 1:end]        # attrs are 1-based
        # The WHOLE range or nothing. A partial slice still summarizes, and the
        # result would replace a correct full summary with one built from the
        # surviving fragment — while attrs["turns"] and the [T..] timeline tag
        # keep claiming the original range, so recall points at turns the summary
        # no longer covers.
        if len(turns) != end - start + 1:
            return {"ok": False, "error": f"turns {rng} are no longer all in the "
                                          "transcript (branched or undone)"}
        self.store.snapshot(keep=self.snapshot_keep, reason="refold")
        payload = self._existing_context(turns) + "\n\nTURNS:\n" + _turns_text(turns)
        obj = self._emit_json(SCENE_INSTRUCTION, payload)
        summary = str((obj or {}).get("scene_summary", "")).strip()[:BODY_LIMIT]
        if not summary:
            self.store.log_degraded("refold", f"{scene_slug} produced no summary")
            return {"ok": False, "error": "the model returned no summary — "
                                          "the old one is untouched"}
        entry.body = summary
        self.store.upsert_entry("memory/scenes.md", entry)
        shorthand = str((obj or {}).get("timeline", "")).strip()
        self._replace_timeline(start, end, entry.attrs.get("when", ""),
                               shorthand or summary)
        return {"ok": True, "slug": scene_slug, "summary": summary}

    def _timeline_line(self, start: int, end: int, when: str, text: str) -> str:
        line = " ".join(str(text).split())          # collapse to a single line
        if len(line) > 160:
            line = line[:157].rstrip() + "…"
        stamp = f"{when}: " if when else ""
        return f"- [T{start}-{end}] {stamp}{line}"

    def _replace_timeline(self, start: int, end: int, when: str, text: str) -> None:
        """Swap the shorthand line for one turn range in place. A redo must not
        append a second line for the same range: the timeline is an index, and
        two entries for T6-10 make the recall pointer ambiguous."""
        tag = f"- [T{start}-{end}]"
        new = self._timeline_line(start, end, when, text)
        lines = self.store.read("memory/timeline.md").splitlines()
        out, replaced = [], False
        for ln in lines:
            if ln.lstrip().startswith(tag) and not replaced:
                out.append(new)
                replaced = True
            elif ln.lstrip().startswith(tag):
                continue                # drop any earlier duplicate for this range
            else:
                out.append(ln)
        if not replaced:
            out.append(new)
        self.store.write("memory/timeline.md", "\n".join(out) + "\n")

    def _append_timeline(self, start: int, end: int, when: str, text: str) -> None:
        """Append one fold-aligned shorthand line, tagged with its source-turn range
        so `store.recall_turns` can fetch the exact turns on demand."""
        line = " ".join(str(text).split())          # collapse to a single line
        if len(line) > 160:
            line = line[:157].rstrip() + "…"
        stamp = f"{when}: " if when else ""
        existing = self.store.read("memory/timeline.md") \
            or "# Timeline (turn index)\n"
        self.store.write("memory/timeline.md",
                         existing.rstrip("\n") + f"\n- [T{start}-{end}] {stamp}{line}\n")

    def _next_scene_no(self) -> int:
        """One past the HIGHEST scene number on file, not the scene COUNT.

        `len(scenes) + 1` collides the moment the file has a hole — a scene
        deleted by hand (memory/scenes.md is an editable file) or by a branch
        that dropped a middle range. The new scene reused `scene-N`,
        upsert_entry overwrote the old one, and a fold is one-way: that
        summary was the only remaining record of its turns."""
        highest = 0
        for sc in self.store.entries("memory/scenes.md"):
            m = re.fullmatch(r"scene-(\d+)", sc.slug or "")
            if m:
                highest = max(highest, int(m.group(1)))
        return highest + 1

    def _fold_arc(self, scenes: list[Entry]) -> list[str] | None:
        """Rewrite the arc synopsis to absorb `scenes`. Returns None when the
        model gave nothing usable — the caller must NOT advance the pointer on a
        None, or those scenes are marked absorbed by a synopsis that never
        mentions them. Unlike a scene fold there is nothing destructive here, so
        a failure can simply be retried on the next fold cycle."""
        payload = "CURRENT ARC:\n" + (self.store.read("memory/arc.md")) \
            + "\n\nOLDER SCENES:\n" + "\n\n".join(e.render() for e in scenes)
        obj = self._emit_json(ARC_INSTRUCTION, payload)
        if obj and str(obj.get("arc", "")).strip():
            # Demote any `## ` the model put INSIDE its synopsis. _arc_tail
            # preserves everything from the second top-level heading onward as
            # the author's, so a heading in the generated text was mistaken for
            # authored content and re-appended on every later arc fold: the file
            # grew by one stale copy per fold, unbounded, and rode every prompt
            # at priority 1. Entry.render demotes body headings for exactly this
            # reason; the arc writer is the other place it matters.
            #
            # Split on splitlines(), not `(?m)^` — VERBATIM the form in
            # Entry.render (memory.py), because the two are supposed to stay in
            # sync and the comment above already says so. They diverged anyway:
            # `^` breaks only on \n, while _arc_tail and store.beats() both scan
            # with splitlines(), which also breaks on \r \v \f \x1c \x1d \x1e,
            # NEL, U+2028 and U+2029. Model text carrying one of those forged a
            # live `## Beats` — a heading no author wrote, in the file
            # store.beats() reads, driving the per-turn "Beat n/m" block and the
            # beat_advance delta the validator checks against it. Plus the
            # unbounded per-fold growth this demotion was added to stop.
            arc = "\n".join(
                ("###" + ln[2:]) if re.match(r"##(?=\s)", ln) else ln
                for ln in str(obj["arc"]).strip().splitlines())[:BODY_LIMIT]
            self.store.write("memory/arc.md",
                             "# Arc synopsis (long-term)\n\n" + arc + "\n"
                             + self._arc_tail())
            return ["memory: updated arc"]
        return None

    def _arc_tail(self) -> str:
        """Authored sections of arc.md that the synopsis rewrite must not eat.

        `## Beats` lives in this same file and is AUTHORED, not generated:
        store.beats() reads it, it drives the per-turn "Beat n/m" block, and the
        beat_advance delta validates against it. Rewriting arc.md as just the
        synopsis deleted it on the first arc fold, and from then on the engine
        reported "no beat structure defined" as if none had ever been written.
        """
        lines = self.store.read("memory/arc.md").splitlines()
        for i, ln in enumerate(lines):
            # The synopsis is the first section; everything from the next
            # top-level heading onward is the author's and is preserved verbatim.
            if i and ln.startswith("## "):
                return "\n" + "\n".join(lines[i:]).rstrip("\n") + "\n"
        return ""

    def maybe_fold(self) -> list[str]:
        """Run any due folds; returns human-readable event strings."""
        events: list[str] = []
        turns = self.store.turns()
        state = self.store.state()
        folded = int(state.get("folded_turns", 0))
        snapped = False

        while len(turns) - folded > self.medium_after:
            if not snapped:
                self.store.snapshot(keep=self.snapshot_keep)
                snapped = True
            # Seed the chapter plan on the first real fold — bundled with a call the
            # fold is making anyway, so it's rate-limited to fold cadence rather than
            # attempted every turn. Idempotent after the first success.
            if self.planner is not None:
                events += self.planner.ensure_seeded()
            chunk = turns[folded:folded + self.medium_size]
            scene_no = self._next_scene_no()
            events += self._fold_scene(chunk, scene_no, folded + 1)  # 1-based start
            # Advance by the ACTUAL chunk length, never the configured size — a
            # short tail chunk (or a hand-edited size > after) must not overshoot
            # and silently drop the turns in between.
            folded += len(chunk)
            state["folded_turns"] = folded
            self.store.write_state(state)

        scenes = self.store.entries("memory/scenes.md")
        folded_sc = int(state.get("folded_scenes", 0))
        # Holding the pointer on a failed arc fold (below) leaves this loop's
        # condition true, and maybe_fold runs after EVERY turn — so without a
        # stall marker a persistently failing arc call re-ran every single turn:
        # a model call and a full story snapshot each time, and the snapshot
        # retention pool evicted every real restore point within a few turns.
        # The payload doesn't shrink between attempts either, so a size-driven
        # failure never recovers on its own. Retry once per NEW scene instead —
        # the same cadence it had back when it advanced the pointer.
        while len(scenes) - folded_sc > self.long_after \
                and state.get("arc_fold_stalled_at") != len(scenes):
            if not snapped:
                self.store.snapshot(keep=self.snapshot_keep)
                snapped = True
            chunk = scenes[folded_sc:folded_sc + self.long_size]
            if not chunk:
                break              # nothing left to fold; never spin on an empty slice
            arc_events = self._fold_arc(chunk)
            if arc_events is None:
                # Advancing here marked these scenes "absorbed into the arc" when
                # the synopsis had not changed at all: they left context the
                # moment they passed scenes_tail and nothing anywhere recorded
                # that they were never summarized. Leave the pointer where it is
                # so a later cycle retries, and BREAK rather than continue —
                # the loop condition is still true, so continuing would spin.
                state["arc_fold_stalled_at"] = len(scenes)
                self.store.write_state(state)
                self.store.log_degraded(
                    "arc-fold", f"{len(chunk)} scene(s) produced no synopsis; "
                                "pointer held, will retry when a new scene folds")
                break
            events += arc_events
            # By the ACTUAL chunk length, never the configured size — the scene
            # loop above says exactly this in a comment, and this loop did the
            # thing that comment warns about. With long_fold_size > long_fold_after
            # (both accepted by Settings) the counter overshot the scenes that
            # exist, and everything in the gap was never arc-folded: gone from
            # context the moment it passed scenes_tail.
            folded_sc += len(chunk)
            state["folded_scenes"] = folded_sc
            state.pop("arc_fold_stalled_at", None)   # it worked; clear the stall
            self.store.write_state(state)

        return events


def _slugify(s: str) -> str:
    """Slugify fold output, bounded to match validator._slug EXACTLY.

    Same order as that function — strip, truncate, then slugify — because the
    two are the read and write ends of one boundary and disagreeing is worse
    than either bound alone. The fold had no cap at all, so a 243-char slug
    (well within what a model emits for a descriptive one) landed in threads.md
    while every delta channel truncated the same name to 200 before looking it
    up: quest_update, reveal and event_fired all answered "no such thread" about
    a thread sitting on disk, and a fold is one-way, so it stayed unreachable
    for the life of the save. Delegates rather than re-implementing: a second
    copy of the rule is how the two drifted apart in the first place."""
    from .templates import slugify
    return slugify(str(s or "").strip()[:STR_LIMIT])


def _clamp_int(v, lo: int = 1, hi: int = 5) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return 3

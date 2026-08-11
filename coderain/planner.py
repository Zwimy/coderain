"""The Chapter Planner — a rolling, book-style outline (2026-07-23).

NOT a new per-turn brain. Chapter planning happens rarely — once to seed the first
few chapters, then once each time a chapter completes (~every 15-25 turns) — so it
rides the SAME occasional LLM the summarizer folds with, never the per-turn path.
Per turn it costs only the compact "current chapter" line the store injects.

The outline lives in `memory/outline.md` as ordinary entries (so you can read and
hand-edit it): one entry per chapter, `status: done|active|planned`, the body is the
chapter's goal. Exactly one chapter is `active`; a rolling horizon of `planned`
chapters sits ahead of it. When the active chapter's goal lands (detected for free
inside the scene fold), it is marked done, the next becomes active, and one fresh
chapter is generated onto the end — built on what actually happened, so the plan
bends to the real story.
"""
from __future__ import annotations

import re

from .llm import emit_json
from .llm import stage as llm_stage
from .memory import Entry, MemoryStore

OUTLINE = "memory/outline.md"
DEFAULT_HORIZON = 4      # active + ~3 planned ahead

# SEED_INSTRUCTION (ask for all N chapters in one reply) is gone. Every path now
# plans ONE chapter per call so each is built on the ones before it, and so a
# single malformed element cannot cost the whole batch.

# Handing the model the whole outline so each chapter builds on the last also
# hands it the easiest possible answer: paraphrase a neighbour. Seen live, three
# chapters into one story — "uncover the contract's hidden compulsion" followed
# by "uncover the contract's hidden trap", and the second one written as the
# lead-in to the chapter ABOVE it. Both instructions carry the same distinctness
# block, so no path can enforce it while another does not.
DISTINCT_RULES = """\
Your chapter must be its own STAGE of the story, not a rewording of a neighbour:
- It opens a question no other chapter opens. If its goal could swap places with
  another chapter's and the outline would still read the same, it is wrong.
- Never restate another chapter's goal in different words. If you find yourself
  reusing its verb and its nouns, you are writing the same chapter twice.
- It may only set up chapters AFTER it. Never write it as the lead-in to a
  chapter listed above it, and never as the payoff of one listed below it.
- Give it its own pressure, its own place and its own opposition. An outline
  that circles the same three nouns is the failure to avoid.
"""

NEXT_INSTRUCTION = """\
You are the story ARCHITECT extending a book-style outline. You are given the
premise, the world, the chapters so far (numbered, with their status) and WHAT
HAS ACTUALLY HAPPENED. Write the chapter in the marked empty slot at the END.

If there are no chapters yet, plan chapter 1: where play begins, drawn from the
premise. Otherwise build on the real events, escalate the arc, and never repeat a
stage the story has already been through.

{rules}
Concise goal (<= 30 words), forward-looking, no fixed dialogue or outcomes.

Return ONLY a JSON object: {{"title": "Chapter title", "goal": "what it must accomplish"}}
""".format(rules=DISTINCT_RULES)

SLOT_INSTRUCTION = """\
You are the story ARCHITECT rewriting ONE chapter of an existing outline. The
chapter marked "<<< REWRITE THIS ONE" is the only one you may change. Replace it
with a better chapter for that slot: it must follow from the chapter before it,
lead into the chapter after it, and fit what has actually happened.

Do not renumber, reorder, or touch any other chapter.

{rules}
Concise goal (<= 30 words), no fixed dialogue or outcomes.

Return ONLY a JSON object: {{"title": "Chapter title", "goal": "what it must accomplish"}}
""".format(rules=DISTINCT_RULES)


def _status(entry: Entry) -> str:
    return (entry.attrs.get("status", "planned") or "planned").strip().lower()


_STOP = frozenset("""a an the and or but of to in on at by for with from into over
under this that these those your you his her its their our my as is are was were
be been being it he she they them then than while during after before not no nor
so if when where which who whom whose what how why all any both each more most
other some such own same too very can will just now must has have had do does did
""".split())


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", str(text).lower())
            if len(w) > 2 and w not in _STOP]


def _trigrams(words: list[str]) -> set[tuple[str, str, str]]:
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def _restates(goal: str, others: list[str]) -> str:
    """Does this goal restate a chapter already in the outline? Pure code, per
    invariant 1: the model is not asked to judge its own duplicate.

    THREE CONSECUTIVE CONTENT WORDS shared with another chapter is the signal.
    It is what caught the live case — "uncover the contract's hidden compulsion"
    against "uncover the contract's hidden trap": different sentences, same beat,
    and they share the content trigram (uncover, contract, hidden).

    A word-overlap ratio does NOT work here and was tried first. Those two goals
    share four content words out of twenty-two, a Jaccard of 0.18, which sits
    below any threshold you could set without firing on every chapter of a story
    that legitimately keeps saying "dragon". Adjacency is the part that carries
    the meaning: the same words in the same order is a restatement, the same
    words scattered is just the same setting.

    Returns the offending phrase (for the retry nudge and the health line), or "".
    """
    mine = _trigrams(_content_words(goal))
    if not mine:
        return ""
    for other in others:
        shared = mine & _trigrams(_content_words(other))
        if shared:
            return " ".join(sorted(shared)[0])
    return ""


class PlanError(ValueError):
    """An outline edit the engine refuses. Transport-agnostic on purpose: the
    HTTP layer turns it into a 400/404, the desktop UI shows it in a dialog."""


class ChapterPlanner:
    def __init__(self, config, store: MemoryStore, llm):
        self.store = store
        self.llm = llm
        g = config.generation if hasattr(config, "generation") else {}
        self._enabled = bool(g.get("chapter_outline", True))
        try:
            self.horizon = max(2, int(g.get("chapter_horizon", DEFAULT_HORIZON)))
        except (TypeError, ValueError):
            self.horizon = DEFAULT_HORIZON

    # --- reads --------------------------------------------------------------
    def enabled(self) -> bool:
        return self._enabled

    def chapters(self) -> list[Entry]:
        return self.store.entries(OUTLINE)

    def active(self) -> Entry | None:
        chapters = self.chapters()
        for c in chapters:
            if _status(c) == "active":
                return c
        # No explicit active (hand-edit or fresh) — the first not-done chapter is it.
        for c in chapters:
            if _status(c) != "done":
                return c
        return None

    def _has_premise(self) -> bool:
        return len(self.store.read("premise.md").strip()) > 20

    # --- lifecycle ----------------------------------------------------------
    def ensure_seeded(self) -> list[str]:
        """Seed the outline once, lazily. Idempotent: a no-op after the first
        success, and a graceful no-op when disabled or there's no premise yet."""
        if not self._enabled or self.chapters() or not self._has_premise():
            return []
        return self.seed()

    def seed(self, force: bool = False) -> list[str]:
        """Fill the outline out to the horizon, ONE CHAPTER PER CALL.

        Two deliberate changes from the original single-call version.

        It plans one chapter at a time. Asking for N chapters in one reply gave
        the model no chance to build each on the last, and a malformed element
        anywhere cost the whole batch (D-008: the old force path deleted the
        outline BEFORE it validated the reply, so a bad response left nothing).
        Each call now sees every chapter already written.

        `force` KEEPS what the story has lived through. It used to delete every
        chapter including completed ones and replan from the premise, which threw
        away the record of what the story had actually been about and produced a
        plan incoherent with its own history. Only `planned` chapters are cleared.
        """
        if not self._enabled:
            return []
        if self.chapters() and not force:
            return []
        if not self._has_premise():
            return []
        events: list[str] = []
        if force:
            dropped = 0
            for c in self.chapters():
                if _status(c) == "planned":
                    self.store.remove_entry(OUTLINE, c.slug)
                    dropped += 1
            if dropped:
                events.append(f"outline: cleared {dropped} planned chapter(s)")
        # _reconcile tops the plan back up to the horizon one chapter at a time
        # and normalises the statuses, which is exactly the job here.
        before = len(self.chapters())
        events += self._reconcile()
        made = len(self.chapters()) - before
        if made:
            events.append(f"outline: planned {made} chapter(s)")
        return events

    def complete_active(self) -> list[str]:
        """The active chapter's goal has landed: mark it done, activate the next,
        and top the plan back up to the horizon. Called from the scene fold when it
        reports `chapter_goal_met` — so completion detection costs no extra call."""
        if not self._enabled:
            return []
        active = self.active()
        if active is None:
            return []
        active.attrs["status"] = "done"
        self.store.upsert_entry(OUTLINE, active)
        events = [f"chapter done: {active.title}"]
        events += self._reconcile()
        nxt = self.active()
        if nxt is not None and nxt.slug != active.slug:
            events.append(f"chapter: now on {nxt.title}")
        return events

    def _reconcile(self) -> list[str]:
        """Restore the invariant: top `planned` up to the horizon, then make the
        first not-done chapter `active` and the rest `planned`."""
        events: list[str] = []
        guard = 0
        while guard < self.horizon + 2:
            guard += 1
            non_done = [c for c in self.chapters() if _status(c) != "done"]
            if len(non_done) >= self.horizon:
                break
            new = self._generate_next()
            if new is None:
                break                       # generation failed — stop, don't loop
            events.append(f"chapter planned: {new.title}")
        # Exactly one active = the first not-done chapter.
        seen = False
        for c in self.chapters():
            if _status(c) == "done":
                continue
            want = "active" if not seen else "planned"
            seen = True
            if _status(c) != want:
                c.attrs["status"] = want
                self.store.upsert_entry(OUTLINE, c)
        return events

    def _plan_payload(self, mark: int | None = None) -> str:
        """Everything a chapter generator should know, for EVERY path.

        Seeding used to see only the premise, the world and the arc, so a
        regenerate mid-story planned as if the story had not happened: it could
        not see its own completed chapters or a single scene of what was played.
        One payload now feeds seeding, extending and single-chapter rewrites, so
        none of them can be coherent while another is not.

        `mark` says which slot is being written, so the model can see the
        neighbours it has to fit between. An index inside the outline marks a
        rewrite; `mark == len(chapters)` marks the empty slot on the end, which
        is the append path.

        The rows are NUMBERED and the slot is always marked. Unnumbered rows with
        no marker are why a freshly appended chapter came back written as the
        lead-in to a chapter two slots above it: nothing in the payload said
        where the new one went, so the model picked a gap it liked.
        """
        premise = self.store.read("premise.md").strip()
        world = self.store.read("world-bible.md").strip()
        arc = self.store.read("memory/arc.md").strip()
        scenes = self.store.entries("memory/scenes.md")
        recent = "\n\n".join(e.render().strip() for e in scenes[-3:])
        chapters = self.chapters()
        rows = []
        for i, c in enumerate(chapters):
            flag = "   <<< REWRITE THIS ONE" if i == mark else ""
            rows.append(
                f"{i + 1}. [{_status(c)}] {c.title}: {c.body.strip()}{flag}")
        if mark is not None and mark >= len(chapters):
            rows.append(f"{len(chapters) + 1}. <<< WRITE THIS ONE — the new last "
                        "chapter. Nothing follows it yet, so it cannot lead into "
                        "anything listed above.")
        out = "PREMISE:\n" + premise[:2000]
        if world:
            out += "\n\nWORLD:\n" + world[:2000]
        out += "\n\nCHAPTERS SO FAR:\n" + ("\n".join(rows) or "(none yet)")
        if arc:
            out += "\n\nSTORY SO FAR (arc):\n" + arc[:1500]
        if recent:
            out += "\n\nWHAT HAS ACTUALLY HAPPENED (recent scenes):\n" + recent[:2000]
        return out

    def _plan_one(self, instruction: str, mark: int | None = None,
                  avoid: list[str] | None = None) -> dict | None:
        """One chapter, one LLM call — with one retry when it comes back as a
        restatement of a chapter already in the outline.

        The retry is worth its cost because planning is rare (once per completed
        chapter, ~15-25 turns) and a duplicate is not a bad sentence you read
        once: it sits in the outline steering every turn of that chapter, and it
        is what the NEXT chapter is then planned against. One bad chapter breeds
        the next one.

        A second failure is accepted rather than dropped — an outline with a
        weak chapter still beats a hole — but it is logged, per invariant 2.
        """
        avoid = [a for a in (avoid or []) if str(a).strip()]
        payload = self._plan_payload(mark)
        obj = None
        for attempt in (1, 2):
            with llm_stage(self.llm, "plan"):
                obj = emit_json(self.llm, instruction, payload)
            if not isinstance(obj, dict) or not str(obj.get("title", "")).strip():
                return None
            echo = _restates(obj.get("goal", ""), avoid)
            if not echo:
                return obj
            if attempt == 2:
                self.store.log_degraded(
                    "chapter-plan",
                    f"chapter kept restating the outline ({echo!r}) after a retry")
                return obj
            payload += (
                "\n\nREJECTED. Your last answer restated a chapter that is "
                f"already in the outline above: \"{str(obj.get('goal')).strip()}\""
                f"\nThe phrase \"{echo}\" is already there. That is the same "
                "chapter twice. Write a DIFFERENT stage of the story: different "
                "pressure, different place, different thing at stake.")
        return obj

    def _goals(self, skip: int | None = None) -> list[str]:
        """The goals a new or rewritten chapter must not restate."""
        return [c.body.strip() for i, c in enumerate(self.chapters())
                if i != skip]

    def _generate_next(self) -> Entry | None:
        """Plan ONE more chapter onto the end, seeded with the chapters so far and
        what actually happened. One LLM call."""
        obj = self._plan_one(NEXT_INSTRUCTION, mark=len(self.chapters()),
                             avoid=self._goals())
        if obj is None:
            return None
        return self._write_chapter(self._next_number(), obj.get("title"),
                                   obj.get("goal"), "planned")

    def regenerate_chapter(self, idx: int) -> list[str]:
        """Rewrite ONE chapter in place, keeping its position and status.

        A completed chapter is refused: it is not a plan any more, it is what
        happened. Everything else is fair game, including the active one, because
        rewording the goal the writer is aiming at is legitimate steering.
        """
        rows = self._rows_or_raise(idx)
        if rows[idx]["status"] == "done":
            raise PlanError("a completed chapter is already part of the story")
        obj = self._plan_one(SLOT_INSTRUCTION, mark=idx,
                             avoid=self._goals(skip=idx))
        if obj is None:
            raise PlanError("the model did not return a usable chapter")
        was = rows[idx]["title"]
        rows[idx]["title"] = str(obj.get("title", "")).strip() or was
        rows[idx]["goal"] = str(obj.get("goal", "")).strip()
        self.replace_all(rows)
        return [f"chapter rewritten: {was} -> {rows[idx]['title']}"]

    def _next_number(self) -> int:
        """One past the HIGHEST chapter number on file, not the chapter COUNT.

        The two differ whenever the outline has a hole — a hand-deleted chapter,
        or a seed that skipped a malformed element. With `len(chapters) + 1` the
        new chapter reused an existing slug, `upsert_entry` overwrote that
        chapter, and the outline never grew: `_reconcile` then re-ran its
        top-up loop until the guard stopped it, spending horizon+2 model calls
        on every chapter completion to end up exactly where it started."""
        highest = 0
        for c in self.chapters():
            m = re.fullmatch(r"ch-(\d+)", c.slug or "")
            if m:
                highest = max(highest, int(m.group(1)))
        return highest + 1

    # --- manual editing (the book-plan panel) -------------------------------
    def replace_all(self, items: list[dict]) -> None:
        """Rewrite the whole outline from an ordered list of {title, goal, status}
        — the panel's edit / reorder / insert / delete all funnel through here, so
        chapters stay numbered ch-1..ch-N in display order. Statuses are honored as
        given, then normalized to exactly one active (the first not-done)."""
        for c in self.chapters():
            self.store.remove_entry(OUTLINE, c.slug)
        for i, it in enumerate(items, start=1):
            status = str(it.get("status", "planned") or "planned").strip().lower()
            if status not in ("done", "active", "planned"):
                status = "planned"
            self._write_chapter(i, it.get("title"), it.get("goal"), status)
        # Keep the invariant a manual reorder might have broken.
        seen = False
        for c in self.chapters():
            if _status(c) == "done":
                continue
            want = "active" if not seen else "planned"
            seen = True
            if _status(c) != want:
                c.attrs["status"] = want
                self.store.upsert_entry(OUTLINE, c)

    def as_dicts(self) -> list[dict]:
        """The outline as plain rows for the API/UI."""
        return [{"index": i, "slug": c.slug, "title": c.title,
                 "goal": c.body.strip(), "status": _status(c)}
                for i, c in enumerate(self.chapters())]

    # --- panel operations ---------------------------------------------------
    # These were written inline in srv/outline.py and raised HTTPException, which
    # made them unreachable from any non-HTTP front end — the desktop app could
    # not edit a chapter at all. The RULES are the engine's, not the transport's:
    # a done or active chapter is already part of the story, so it cannot be
    # deleted or dragged out of story order. They raise PlanError; the routes
    # translate that to a 400/404 and the desktop UI shows it in a dialog.

    def _rows_or_raise(self, idx: int) -> list[dict]:
        rows = self.as_dicts()
        if not 0 <= idx < len(rows):
            raise PlanError("no such chapter")
        return rows

    def edit(self, idx: int, title: str | None = None,
             goal: str | None = None) -> list[dict]:
        """Edit a chapter's title and/or goal in place (positions unchanged)."""
        rows = self._rows_or_raise(idx)
        if title is not None:
            rows[idx]["title"] = str(title).strip() or rows[idx]["title"]
        if goal is not None:
            rows[idx]["goal"] = str(goal).strip()
        self.replace_all(rows)
        return self.as_dicts()

    def insert(self, after: int | None = None, title: str = "New chapter",
               goal: str = "") -> list[dict]:
        """Insert a planned chapter behind `after` (default: append)."""
        rows = self.as_dicts()
        pos = len(rows)
        if isinstance(after, int) and 0 <= after < len(rows):
            pos = after + 1
        rows.insert(pos, {"title": str(title).strip() or "New chapter",
                          "goal": str(goal).strip(), "status": "planned"})
        self.replace_all(rows)
        return self.as_dicts()

    def delete(self, idx: int) -> list[dict]:
        """Delete a PLANNED chapter. Done/active belong to the story already."""
        rows = self._rows_or_raise(idx)
        if rows[idx]["status"] in ("done", "active"):
            raise PlanError("only a planned chapter can be deleted")
        rows.pop(idx)
        self.replace_all(rows)
        return self.as_dicts()

    def move(self, idx: int, direction: int) -> list[dict]:
        """Reorder a planned chapter up (-1) or down (+1). An edge is a no-op,
        not an error — the panel calls this on every arrow press."""
        rows = self._rows_or_raise(idx)
        try:
            step = 1 if int(direction) > 0 else -1
        except (TypeError, ValueError):
            raise PlanError("direction must be -1 or 1")
        j = idx + step
        if not 0 <= j < len(rows):
            return self.as_dicts()
        if rows[idx]["status"] != "planned" or rows[j]["status"] != "planned":
            raise PlanError("only planned chapters can be reordered")
        rows[idx], rows[j] = rows[j], rows[idx]
        self.replace_all(rows)
        return self.as_dicts()

    # --- storage ------------------------------------------------------------
    def _write_chapter(self, n: int, title, goal, status: str) -> Entry:
        # One line, bounded. Entry.render writes the title into the
        # `## {title}  {#ch-N}` header, so a newline splits the heading: the
        # anchor and the `status:`/`importance:` lines fall into the BODY, the
        # entry re-parses under a truncated slug, and two chapters whose titles
        # share a first line collide on it — the next upsert then deleted one of
        # them outright. Reachable from the model (seed/_generate_next) and from
        # the outline panel's PUT, which is why it is bounded here rather than at
        # either caller. summarizer._apply_promotions guards its titles the same
        # way and says why; this path had neither guard.
        title = " ".join(str(title or f"Chapter {n}").split())[:200] \
            or f"Chapter {n}"
        goal = " ".join(str(goal or "").split())[:2000]
        entry = Entry(title=title, slug=f"ch-{n}", importance=3,
                      attrs={"status": status}, body=goal)
        self.store.upsert_entry(OUTLINE, entry)
        return entry

    # --- fold hook helper ---------------------------------------------------
    def active_fold_hint(self) -> str:
        """One line handed to the scene fold so it can report `chapter_goal_met`
        for free — empty when there's no active chapter to judge."""
        active = self.active()
        if active is None:
            return ""
        return ("ACTIVE CHAPTER (set chapter_goal_met=true ONLY if these turns show "
                f"its goal has now genuinely landed): {active.title} — "
                f"{active.body.strip()}")

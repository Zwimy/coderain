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

from .llm import emit_json
from .memory import Entry, MemoryStore

OUTLINE = "memory/outline.md"
DEFAULT_HORIZON = 4      # active + ~3 planned ahead

SEED_INSTRUCTION = """\
You are the story ARCHITECT laying out a book-style outline. From the premise and
world below, plan the first {n} chapters as a rolling arc. Each chapter is a STAGE
of the story with one concrete dramatic goal — a question it opens and answers — not
a single scene. Chapter 1 is where play begins; each later chapter escalates toward
the story's end. Keep every goal concise (<= 30 words), forward-looking, and free of
specific dialogue or fixed outcomes (the play decides those).

Return ONLY a JSON object:
{{"chapters": [{{"title": "Chapter title", "goal": "what this chapter must accomplish"}}]}}
Exactly {n} chapters, in order.
"""

NEXT_INSTRUCTION = """\
You are the story ARCHITECT extending a book-style outline. Below are the chapters
so far (completed and current) and WHAT HAS ACTUALLY HAPPENED. Plan the SINGLE next
chapter that should follow — building on the real events, escalating the arc, not
repeating a stage already done. Concise goal (<= 30 words), no fixed dialogue or
outcomes.

Return ONLY a JSON object: {"title": "Chapter title", "goal": "what it must accomplish"}
"""


def _status(entry: Entry) -> str:
    return (entry.attrs.get("status", "planned") or "planned").strip().lower()


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
        """Generate the opening `horizon` chapters from the premise/world. One LLM
        call. `force` regenerates from scratch (the UI 'regenerate' button)."""
        if not self._enabled:
            return []
        if self.chapters() and not force:
            return []
        premise = self.store.read("premise.md").strip()
        if len(premise) <= 20:
            return []
        world = self.store.read("world-bible.md").strip()
        arc = self.store.read("memory/arc.md").strip()
        payload = "PREMISE:\n" + premise
        if world:
            payload += "\n\nWORLD:\n" + world[:2000]
        if arc:
            payload += "\n\nSTORY SO FAR:\n" + arc[:1500]
        obj = emit_json(self.llm, SEED_INSTRUCTION.format(n=self.horizon), payload)
        chapters = (obj or {}).get("chapters")
        if not isinstance(chapters, list) or not chapters:
            return []                       # failed — leave empty, retry next fold
        # Clear any prior outline on a forced regenerate.
        for c in self.chapters():
            self.store.remove_entry(OUTLINE, c.slug)
        n = 0
        for i, ch in enumerate(chapters[:self.horizon], start=1):
            if not isinstance(ch, dict):
                continue
            self._write_chapter(i, ch.get("title"), ch.get("goal"),
                                 "active" if i == 1 else "planned")
            n += 1
        return [f"outline: planned {n} chapters"] if n else []

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

    def _generate_next(self) -> Entry | None:
        """Plan ONE more chapter onto the end, seeded with the chapters so far and
        what actually happened. One LLM call."""
        chapters = self.chapters()
        prior = "\n".join(
            f"- {c.title} [{_status(c)}]: {c.body.strip()}" for c in chapters)
        arc = self.store.read("memory/arc.md").strip()
        scenes = self.store.entries("memory/scenes.md")
        recent = "\n\n".join(e.render().strip() for e in scenes[-3:])
        payload = "CHAPTERS SO FAR:\n" + (prior or "(none)")
        if arc:
            payload += "\n\nARC:\n" + arc[:1500]
        if recent:
            payload += "\n\nWHAT HAS ACTUALLY HAPPENED (recent):\n" + recent[:2000]
        obj = emit_json(self.llm, NEXT_INSTRUCTION, payload)
        if not isinstance(obj, dict) or not str(obj.get("title", "")).strip():
            return None
        return self._write_chapter(len(chapters) + 1, obj.get("title"),
                                   obj.get("goal"), "planned")

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

    # --- storage ------------------------------------------------------------
    def _write_chapter(self, n: int, title, goal, status: str) -> Entry:
        title = str(title or f"Chapter {n}").strip()
        goal = str(goal or "").strip()
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

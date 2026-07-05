"""Feature 4: staged scenario auto-generator.

Turn a short spec (type · tone · premise · counts · detail) into a complete,
tone-consistent scenario — everything needed to start play EXCEPT the player
character. A scenario has the FictionLab shape: NAME + PREMISE + INTRODUCTION
(the generated opening scene, written as `## Opening` in premise.md — the
engine serves it verbatim as the first chat message). With `spec.improve`
the user's rough prompt first passes a detailer/improver stage.
Two depth modes (spec.detail):

- "fast": one batched call per section (quick; a couple of minutes locally).
- "rich" (default): chained per-entity calls — every character/location is its own
  call that SEES summaries of everything generated before it, so the cast is
  distinct and interlinked and the tone holds. Slower (~1 call per entity), much
  deeper output.

Failures are LOUD: every stage error is surfaced through `on_stage` and collected;
a failed premise ABORTS (no junk scenario is scaffolded); an entity stage that
parses to zero entries gets one corrective retry and then reports the shortfall.

Entities are written straight into the scenario's Markdown files via a MemoryStore
(Markdown stays the source of truth); the derived index rebuilds itself later.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import templates
from .llm import emit_json_ex
from .memory import Entry, MemoryStore


class GenerationError(RuntimeError):
    """The premise stage failed — nothing was created."""


@dataclass
class ScenarioSpec:
    """User-supplied knobs. Blank text fields are left for the model to invent
    (holding the tone); counts default to 5 each. detail: "rich" chains one call
    per entity for depth; "fast" batches each section into a single call.
    improve: opt-in prompt detailer — the rough brief is rewritten into a
    richer one before generation starts (user choice, never automatic)."""
    type: str = ""
    tone: str = ""
    premise: str = ""
    n_npcs: int = 5
    n_locations: int = 5
    n_items: int = 5
    detail: str = "rich"
    improve: bool = False


_TONE_RULE = ("Everything you invent MUST fit the scenario's tone and premise; do "
              "not drift in genre, register, or content rating. Where a requested "
              "detail is blank, invent something that fits. EXPAND the brief into "
              "concrete specifics — never just echo its words back. Reference other "
              "entities by [[type:slug]] only — never restate their details.")

_IMPROVE_SYS = (
    "STAGE: prompt improver. You are a prompt detailer for a story-scenario "
    "generator. Rewrite the user's rough brief into a rich, specific one: "
    "sharpen the scenario type, name the exact tone, and expand the premise "
    "idea with concrete hooks — place, era, central conflict, stakes, and one "
    "or two distinctive elements. PRESERVE every explicit detail, name, and "
    "constraint the user gave; invent only where they were vague. Never "
    "change the genre or the content rating they implied.\n\n"
    "Return ONLY a JSON object:\n"
    '{"type": "the sharpened scenario type", '
    '"tone": "the exact tone, one line", '
    '"premise": "60-150 words: the improved idea, concrete and evocative"}'
)

_INTRO_SYS = (
    "STAGE: introduction. Write the scenario's INTRODUCTION — the very first "
    "message the player reads when a story begins. Second person, present "
    "tense, 2-4 paragraphs: establish the place and the moment, drop the "
    "player into the situation with sensory detail, and end on an open beat "
    "that invites an action (never a literal question, never a list of "
    "options). No game mechanics, no meta-talk. It may feature entities from "
    "the roster naturally, without info-dumping their lore. "
    + "Everything MUST fit the scenario's tone and premise."
    + '\n\nReturn ONLY a JSON object: {"introduction": "the opening scene"}'
)

_PREMISE_SYS = (
    "STAGE: premise. You are a world-builder. From the brief, produce the seed of a "
    "reusable scenario (NOT the player character). " + _TONE_RULE + "\n\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "title": "short evocative world title",\n'
    '  "premise": "150-250 words. The situation the player drops into (second person '
    'ok): place, moment, pressure, and what makes it distinct. Elaborate the brief\'s '
    'themes into specifics.",\n'
    '  "world_bible": "300-600 words in short titled sections: History, Geography, '
    'Powers/Factions overview, Magic or Technology, Tone & Content. Concrete rules '
    'the narrator must honor.",\n'
    '  "tone_lock": "one line capturing the exact tone to hold across everything",\n'
    '  "factions": [ {"slug": "kebab-id", "title": "Name", "importance": 1-5, '
    '"detail": "80-150 words: who they are, what they want, how they act"} ]\n'
    "}\n"
    "Invent 0-3 factions only if they fit."
)


def _entity_sys(kind: str, n: int, shape: str) -> str:
    return (f"STAGE: {kind}. Invent exactly {n} {kind} for the scenario below. "
            + _TONE_RULE + f"\n\nReturn ONLY a JSON object: "
            f'{{"{kind}": [ {shape} ]}}  (exactly {n} entries).')


def _single_sys(kind: str, shape: str) -> str:
    return (f"STAGE: {kind}. Invent exactly ONE new {kind.rstrip('s')} for the "
            f"scenario below. It must be DISTINCT from the already-created entities "
            f"listed (different role, look, and voice) and may reference them by "
            f"[[type:slug]]. " + _TONE_RULE + "\n\nReturn ONLY a JSON object: "
            + shape)


_CHAR_SHAPE = (
    '{"slug": "kebab-id", "title": "Name", "aliases": ["alt"], "importance": 1-5, '
    '"status": "one-line current state", '
    '"playable": "true for a character a player could inhabit as their own, else false", '
    '"visual": "40-80 words: appearance at a glance — build, face, dress, tells", '
    '"mentality": "40-80 words: how they act, decide, and treat people", '
    '"voice": "how they talk + one sample line in quotes", '
    '"skills": [{"name": "skill", "stat": "strength|agility|intelligence|knowledge|willpower|charisma"}], '
    '"stats": {"strength": 1-5, "agility": 1-5, "intelligence": 1-5, "knowledge": 1-5, '
    '"willpower": 1-5, "charisma": 1-5}, '
    '"relationships": [{"with": "other-slug", "note": "ally / rival / owes debt"}], '
    '"detail": "60-120 words: history, secret, and current agenda"}'
)
_LOC_SHAPE = ('{"slug": "kebab-id", "title": "Name", "aliases": ["alt"], '
              '"importance": 1-5, "detail": "80-160 words: sights/sounds/smells, who '
              'is found here, one hook or danger; may reference known characters by '
              '[[char:slug]]"}')
_ITEM_SHAPE = ('{"slug": "kebab-id", "title": "Name", "aliases": ["alt"], '
               '"importance": 1-5, '
               '"rarity": "common|uncommon|rare|epic|legendary", '
               '"detail": "60-120 words: what it is, why it '
               'matters, who wants it"}')
_FACTION_SHAPE = ('{"slug": "kebab-id", "title": "Name", "importance": 1-5, '
                  '"detail": "80-150 words: who they are, what they want, how '
                  'they act"}')
_THREAD_SHAPE = ('{"slug": "kebab-id", "title": "Name", "importance": 1-5, '
                 '"detail": "60-120 words: what is unresolved and why it '
                 'presses NOW"}')
_EVENT_SHAPE = ('{"slug": "kebab-id", "title": "When <condition>", '
                '"importance": 1-5, "once": true|false, '
                '"detail": "the rule: when X happens, then Y — concrete and '
                'enforceable by a game director"}')
_GENERIC_SHAPE = ('{"slug": "kebab-id", "title": "Name", "importance": 1-5, '
                  '"detail": "60-150 words of concrete, tone-locked lore"}')
_THREAD_SYS = (
    "STAGE: threads. Invent 1-3 opening threads (unresolved hooks/obligations/"
    "mysteries) and 0-2 backstory canon-events for the scenario below, tying "
    "together the characters/locations/items listed (reference them by "
    "[[type:slug]]). " + _TONE_RULE
    + '\n\nReturn ONLY a JSON object: {"threads": [ {"slug": "kebab-id", '
    '"title": "Name", "importance": 1-5, "detail": "60-120 words: what is '
    'unresolved and why it presses NOW"} ], '
    '"canon_events": [ {"slug": "kebab-id", "title": "Name", "importance": 1-5, '
    '"detail": "60-120 words: what happened, in the past"} ]}'
)


def _spec_brief(spec: ScenarioSpec) -> str:
    def field(label, val):
        return f"{label}: {val.strip() or '(you decide — keep it consistent)'}"
    return "\n".join([
        field("Type of scenario", spec.type),
        field("Tone", spec.tone),
        field("Premise", spec.premise),
    ])


def _ctx(premise: str, tone_lock: str, brief: str, roster: str = "") -> str:
    out = (f"TONE TO HOLD: {tone_lock}\n\nPREMISE:\n{premise}\n\n"
           f"ORIGINAL BRIEF:\n{brief}")
    if roster:
        out += "\n\nALREADY CREATED (one line each — do not duplicate):\n" + roster
    return out


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _skills_attr(skills) -> str:
    parts = []
    for sk in skills or []:
        if isinstance(sk, dict):
            name, stat = _s(sk.get("name")), _s(sk.get("stat")).lower()
        else:
            name, stat = _s(sk), ""
        if name:
            parts.append(f"{name} ({stat})" if stat else name)
    return ", ".join(parts)


def _stats_attr(stats) -> str:
    if not isinstance(stats, dict):
        return ""
    parts = []
    for k, v in stats.items():
        k = _s(k).lower()
        try:
            n = max(1, min(5, int(v)))
        except (TypeError, ValueError):
            continue
        if k:
            parts.append(f"{k} {n}")
    return ", ".join(parts)


def _rels_attr(rels) -> str:
    parts = []
    for r in rels or []:
        if isinstance(r, dict) and _s(r.get("with")):
            parts.append(f"{templates.slugify(_s(r['with']))}: {_s(r.get('note'))}")
    return "; ".join(parts)


def _clamp_imp(v) -> int:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return 3


def _entry_from(d: dict, body_key: str = "detail") -> Entry | None:
    slug = templates.slugify(_s(d.get("slug")) or _s(d.get("title")))
    title = _s(d.get("title")) or slug
    if not slug:
        return None
    attrs: dict[str, str] = {}
    if _s(d.get("status")):
        attrs["status"] = _s(d.get("status"))
    rarity = _s(d.get("rarity")).lower()
    if rarity in ("common", "uncommon", "rare", "epic", "legendary"):
        attrs["rarity"] = rarity
    return Entry(title=title, slug=slug,
                 aliases=[_s(a) for a in d.get("aliases", []) if _s(a)],
                 importance=_clamp_imp(d.get("importance", 3)),
                 attrs=attrs, body=_s(d.get(body_key)))


def _character_entry(d: dict) -> Entry | None:
    e = _entry_from(d, body_key="__none__")
    if e is None:
        return None
    if str(d.get("playable", "")).strip().lower() in ("true", "yes", "1"):
        e.attrs["playable"] = "true"
    skills = _skills_attr(d.get("skills"))
    if skills:
        e.attrs["skills"] = skills
    stats = _stats_attr(d.get("stats"))
    if stats:
        e.attrs["stats"] = stats
    rels = _rels_attr(d.get("relationships"))
    if rels:
        e.attrs["relationships"] = rels
    facets = []
    for label, key in (("Visual", "visual"), ("Mentality", "mentality"),
                       ("Voice", "voice")):
        if _s(d.get(key)):
            facets.append(f"**{label}:** {_s(d.get(key))}")
    body = "\n".join(facets)
    if _s(d.get("detail")):
        body = (body + "\n\n" + _s(d.get("detail"))).strip()
    e.body = body
    return e


def _event_entry(d: dict) -> Entry | None:
    e = _entry_from(d)
    if e is not None and str(d.get("once", "")).strip().lower() in \
            ("true", "yes", "1"):
        e.attrs["once"] = "true"
    return e


# kind -> (JSON shape, entry builder, roster ref label, registry file)
PIECE_KINDS: dict[str, tuple[str, object, str, str]] = {
    "character": (_CHAR_SHAPE, _character_entry, "char", "characters.md"),
    "location": (_LOC_SHAPE, _entry_from, "location", "locations.md"),
    "item": (_ITEM_SHAPE, _entry_from, "item", "items.md"),
    "faction": (_FACTION_SHAPE, _entry_from, "faction", "factions.md"),
    "thread": (_THREAD_SHAPE, _entry_from, "thread", "threads.md"),
    "event": (_EVENT_SHAPE, _event_entry, "event", "events.md"),
}


def _run_entity_stages(run: "_Run", store, brief: str, premise: str,
                       tone_lock: str, roster: list[str], created,
                       stages: list[tuple], rich: bool) -> None:
    """The per-section entity loop shared by full generation and
    complete_scenario. `stages` = [(kind, n, shape, rel, builder, ref)];
    rich = one call per entity (roster-chained), else one batched call, with
    the batch as the single corrective retry either way."""
    for kind, n, shape, rel, builder, ref in stages:
        if n <= 0:
            continue
        run.on_stage(kind)
        got = 0
        if rich:
            # One call per entity, each seeing the growing roster: distinct,
            # interlinked, and tone-locked. Slower but much deeper.
            for i in range(n):
                ctx = _ctx(premise, tone_lock, brief, "\n".join(roster))
                obj = run.emit(f"{kind} {i + 1}/{n}", _single_sys(kind, shape),
                               ctx)
                e = builder(obj) if obj else None
                if e:
                    store.upsert_entry(rel, e)
                    created(ref, e)
                    got += 1
                    run.on_stage(f"{kind} {i + 1}/{n}: {e.title}")
        else:
            ctx = _ctx(premise, tone_lock, brief, "\n".join(roster))
            obj = run.emit(kind, _entity_sys(kind, n, shape), ctx)
            for d in obj.get(kind) or []:
                if isinstance(d, dict):
                    e = builder(d)
                    if e:
                        store.upsert_entry(rel, e)
                        created(ref, e)
                        got += 1
        if got == 0 and n > 0:
            # One corrective retry AS A BATCH — deliberate strategy switch: when
            # every per-entity call failed, a single batched request is the cheaper
            # (and often more parseable) second try, not n more of the same.
            run.on_stage(f"{kind}: none parsed — retrying once")
            ctx = _ctx(premise, tone_lock, brief, "\n".join(roster))
            obj = run.emit(f"{kind} (retry)", _entity_sys(kind, n, shape), ctx)
            for d in obj.get(kind) or []:
                if isinstance(d, dict):
                    e = builder(d)
                    if e:
                        store.upsert_entry(rel, e)
                        created(ref, e)
                        got += 1
        if got < n:
            run.warnings.append(f"{kind}: {got}/{n} generated")
            run.on_stage(f"{kind}: only {got}/{n} generated")


class _Run:
    """One generation run: shared context + failure collection."""

    def __init__(self, llm, on_stage):
        self.llm = llm
        self.on_stage = on_stage or (lambda m: None)
        self.warnings: list[str] = []

    def emit(self, stage: str, system: str, payload: str) -> dict:
        obj, err = emit_json_ex(self.llm, system, payload)
        if err:
            self.warnings.append(f"{stage}: {err}")
            self.on_stage(f"{stage} FAILED: {err}")
            return {}
        return obj or {}


def generate_scenario(lib, llm, spec: ScenarioSpec, on_stage=None) -> str:
    """Generate a scenario from `spec` and return its slug. `lib` is a Library (uses
    lib.scenarios); `llm` is anything with `.complete(messages)`. `on_stage(msg)` is
    an optional progress callback (the GUI/CLI surfaces it, including failures).
    Raises GenerationError if the premise stage fails (nothing is created).
    Stage warnings after that are reported via on_stage and collected on the
    returned run (see `last_warnings`)."""
    run = _Run(llm, on_stage)
    rich = (spec.detail or "rich").lower() != "fast"

    # Opt-in prompt detailer (user choice): the rough brief becomes a rich one
    # before anything is generated. Failure is loud but never blocks — the
    # original brief still works.
    if spec.improve:
        run.on_stage("improving prompt")
        obj = run.emit("prompt improver", _IMPROVE_SYS, _spec_brief(spec))
        if obj and _s(obj.get("premise")):
            spec = ScenarioSpec(
                type=_s(obj.get("type")) or spec.type,
                tone=_s(obj.get("tone")) or spec.tone,
                premise=_s(obj.get("premise")),
                n_npcs=spec.n_npcs, n_locations=spec.n_locations,
                n_items=spec.n_items, detail=spec.detail)
            run.on_stage(f"prompt improved: {spec.premise[:100]}")
    brief = _spec_brief(spec)

    run.on_stage("premise")
    prem = run.emit("premise", _PREMISE_SYS, brief)
    if not prem or not (_s(prem.get("premise")) or _s(prem.get("title"))):
        raise GenerationError(
            "Premise generation failed — no scenario was created. "
            + (run.warnings[-1] if run.warnings else "The model returned nothing "
               "usable; check the model/profile and try again."))
    title = _s(prem.get("title")) or (_s(spec.type) or "Generated World").title()
    premise = _s(prem.get("premise")) or _s(spec.premise) or templates.DEFAULT_PREMISE
    world = _s(prem.get("world_bible"))
    tone_lock = _s(prem.get("tone_lock")) or _s(spec.tone)
    desc = (_s(spec.premise) or premise)[:140]

    slug = lib.scenarios.create(title, premise, world=world, description=desc)
    store = MemoryStore(lib.scenarios.dir(slug))   # scenario dir as a plain md store

    for f in prem.get("factions") or []:
        e = _entry_from(f) if isinstance(f, dict) else None
        if e:
            store.upsert_entry("factions.md", e)

    roster: list[str] = []      # one-liners of everything created, fed forward

    def created(kind: str, e: Entry) -> None:
        roster.append(f"[[{kind}:{e.slug}]] {e.title} — {e.oneline()[:90]}")

    for e in store.entries("factions.md"):
        created("faction", e)

    stages = [
        ("characters", int(spec.n_npcs), _CHAR_SHAPE, "characters.md",
         _character_entry, "char"),
        ("locations", int(spec.n_locations), _LOC_SHAPE, "locations.md",
         _entry_from, "location"),
        ("items", int(spec.n_items), _ITEM_SHAPE, "items.md",
         _entry_from, "item"),
    ]
    _run_entity_stages(run, store, brief, premise, tone_lock, roster, created,
                       stages, rich)

    run.on_stage("threads")
    ctx = _ctx(premise, tone_lock, brief, "\n".join(roster))
    obj = run.emit("threads", _THREAD_SYS, ctx)
    for d in obj.get("threads") or []:
        if isinstance(d, dict):
            e = _entry_from(d)
            if e:
                e.attrs.setdefault("status", "open")
                store.upsert_entry("threads.md", e)
    for d in obj.get("canon_events") or []:
        if isinstance(d, dict):
            e = _entry_from(d)
            if e:
                store.upsert_entry("canon-events.md", e)

    # Introduction — the scenario's first chat message (FictionLab shape).
    # Generated LAST so it can feature the cast; stored as `## Opening` in
    # premise.md, which the engine serves verbatim when a story starts.
    run.on_stage("introduction")
    ctx = _ctx(premise, tone_lock, brief, "\n".join(roster))
    obj = run.emit("introduction", _INTRO_SYS, ctx)
    intro = _s((obj or {}).get("introduction"))
    if intro:
        text = store.read("premise.md").rstrip("\n")
        store.write("premise.md", text + "\n\n## Opening\n\n" + intro + "\n")
        run.on_stage("introduction: written as the opening message")
    else:
        run.warnings.append("introduction: none generated — the first turn "
                            "will be model-improvised")

    # Surfaced by GUI/CLI. Not lock-guarded on purpose: both callers read it on the
    # SAME thread that just ran this function, and the `generating` gate prevents
    # concurrent runs. Revisit if generation ever becomes multi-session.
    generate_scenario.last_warnings = list(run.warnings)
    run.on_stage("done" + (f" ({len(run.warnings)} warning(s))" if run.warnings
                           else ""))
    return slug


generate_scenario.last_warnings = []


# --- per-field AI assist + fill-the-rest (scenario builder, Phase 6) ---------

# main-field kinds: (JSON key, content description used in both modes)
_FIELD_SPECS: dict[str, tuple[str, str]] = {
    "premise": ("premise",
                "150-250 words. The situation the player drops into (second "
                "person ok): place, moment, pressure, and what makes it "
                "distinct."),
    "introduction": ("introduction",
                     "2-4 second-person present-tense paragraphs: establish "
                     "the place and the moment with sensory detail, end on an "
                     "open beat that invites an action — never a literal "
                     "question, never a list of options, no game mechanics."),
    "world": ("world_bible",
              "300-600 words in short titled sections: History, Geography, "
              "Powers/Factions overview, Magic or Technology, Tone & Content "
              "— concrete rules the narrator must honor."),
}

_SEED_DETAIL_SYS = (
    "STAGE: prompt improver. Expand the user's one-line idea into a rich, "
    "specific brief (60-120 words) for the target section named in the "
    "payload: concrete hooks, names, sensory anchors. PRESERVE every explicit "
    "detail the user gave; invent only where they were vague; never change "
    "genre or content rating.\n\n"
    'Return ONLY a JSON object: {"idea": "the detailed brief"}'
)


def assist_field(llm, kind: str, mode: str, text: str, context: str = "",
                 improve: bool = False):
    """One-shot AI assist for the scenario builder. Returns ``(result, err)``:
    result is a str for the main fields (premise/introduction/world) and an
    Entry for piece kinds (character/location/item/faction/thread/event or a
    custom type). mode "seed" = text is a one-line idea (may be blank);
    mode "improve" = text is the current content (a JSON entry for pieces),
    rewritten richer. improve=True routes a SEED's idea through the detailer
    first (the builder's global checkbox); moot for mode="improve"."""
    run = _Run(llm, None)
    kind = str(kind or "").strip().lower()
    mode = "improve" if mode == "improve" else "seed"
    text = str(text or "").strip()

    if mode == "seed" and improve and text:
        obj = run.emit("prompt improver", _SEED_DETAIL_SYS,
                       f"TARGET SECTION: {kind}\nIDEA: {text}"
                       + (f"\n\nSCENARIO CONTEXT:\n{context}" if context
                          else ""))
        detailed = _s((obj or {}).get("idea"))
        if detailed:
            text = detailed

    ctx = f"SCENARIO CONTEXT:\n{context}\n\n" if context else ""
    idea = "IDEA: " + (text or "(you decide — fit the scenario context)")

    if kind in _FIELD_SPECS:
        key, desc = _FIELD_SPECS[kind]
        if mode == "seed":
            sys = (f"STAGE: {kind}. You are a world-builder. From the idea "
                   f"below, write the scenario's {kind.upper()} section. "
                   f"{desc} " + _TONE_RULE
                   + '\n\nReturn ONLY a JSON object: {"' + key + '": "..."}')
            payload = ctx + idea
        else:
            sys = (f"STAGE: {kind}. Rewrite the scenario's {kind.upper()} "
                   f"section below — richer, more concrete, better prose — "
                   f"while PRESERVING its intent, every named element, and "
                   f"the content rating. {desc}"
                   + '\n\nReturn ONLY a JSON object: {"' + key + '": "..."}')
            payload = ctx + "CURRENT TEXT:\n" + text
        obj = run.emit(kind, sys, payload)
        out = _s((obj or {}).get(key))
        if not out:
            return None, (run.warnings[-1] if run.warnings
                          else f"{kind}: nothing usable returned")
        return out, None

    shape, builder, _ref, _rel = PIECE_KINDS.get(
        kind, (_GENERIC_SHAPE, _entry_from, kind, ""))
    if mode == "seed":
        sys = (f"STAGE: {kind}. Invent exactly ONE {kind} for the scenario, "
               f"from the idea below. " + _TONE_RULE
               + "\n\nReturn ONLY a JSON object: " + shape)
        payload = ctx + idea
    else:
        sys = (f"STAGE: {kind}. Below is an existing {kind} entry (JSON). "
               f"Rewrite it richer and more concrete — same identity (keep "
               f"the slug and title unless clearly wrong), same content "
               f"rating, deeper detail. " + _TONE_RULE
               + "\n\nReturn ONLY the full rewritten JSON object: " + shape)
        payload = ctx + "CURRENT ENTRY:\n" + text
    obj = run.emit(kind, sys, payload)
    e = builder(obj) if obj else None
    if e is None:
        return None, (run.warnings[-1] if run.warnings
                      else f"{kind}: nothing usable returned")
    return e, None


def _split_premise_body(text: str) -> str:
    """The premise PROSE of a premise.md: minus the H1 header, minus the
    `## Opening` section."""
    body: list[str] = []
    for ln in text.splitlines():
        if ln.startswith("# "):
            continue
        if ln.strip().lower().startswith("## opening"):
            break
        body.append(ln)
    return "\n".join(body).strip()


def _write_premise_md(store: MemoryStore, premise_body: str,
                      intro: str) -> None:
    text = templates.PREMISE_HEADER + premise_body.strip() + "\n"
    if intro.strip():
        text += "\n## Opening\n\n" + intro.strip() + "\n"
    store.write("premise.md", text)


def complete_scenario(lib, llm, slug: str, spec: ScenarioSpec,
                      on_stage=None) -> list[str]:
    """"Generate the rest": fill ONLY what's missing on an existing scenario —
    empty premise/world/introduction, lore groups below the requested counts,
    threads when there are none. Everything the user wrote is KEPT and fed
    into the roster so new pieces interlink with it. Returns warnings."""
    from .memory import _strip_comments
    run = _Run(llm, on_stage)
    scen_dir = lib.scenarios.dir(slug)
    if not (scen_dir / "scenario.json").exists():
        raise GenerationError(f"no such scenario: {slug}")
    store = MemoryStore(scen_dir)
    rich = (spec.detail or "rich").lower() != "fast"

    premise_body = _split_premise_body(store.read("premise.md"))
    have_premise = bool(_strip_comments(premise_body).strip()) and \
        premise_body.strip() != templates.DEFAULT_PREMISE.strip()
    intro = store.opening_override()
    raw_world = store.read("world-bible.md")
    world = _strip_comments(raw_world)
    # The shipped skeleton is instructional placeholder text, not authorship.
    have_world = bool("\n".join(
        ln for ln in world.splitlines() if not ln.startswith("# ")).strip()) \
        and raw_world.strip() != \
        templates.FILE_SKELETONS["world-bible.md"].strip()

    if spec.improve and (spec.premise or premise_body):
        run.on_stage("improving prompt")
        obj = run.emit("prompt improver", _IMPROVE_SYS, _spec_brief(
            ScenarioSpec(type=spec.type, tone=spec.tone,
                         premise=spec.premise or premise_body[:600])))
        if obj and _s(obj.get("premise")) and not have_premise:
            spec = ScenarioSpec(
                type=_s(obj.get("type")) or spec.type,
                tone=_s(obj.get("tone")) or spec.tone,
                premise=_s(obj.get("premise")),
                n_npcs=spec.n_npcs, n_locations=spec.n_locations,
                n_items=spec.n_items, detail=spec.detail)
            run.on_stage(f"prompt improved: {spec.premise[:100]}")

    brief = _spec_brief(ScenarioSpec(
        type=spec.type, tone=spec.tone,
        premise=(premise_body if have_premise else spec.premise)))
    tone_lock = _s(spec.tone)

    if not have_premise:
        run.on_stage("premise")
        prem = run.emit("premise", _PREMISE_SYS, brief)
        got = _s((prem or {}).get("premise"))
        if got:
            premise_body = got
            _write_premise_md(store, premise_body, intro)
            tone_lock = _s(prem.get("tone_lock")) or tone_lock
            if not have_world and _s(prem.get("world_bible")):
                store.write("world-bible.md", "# World bible\n\n"
                            + _s(prem.get("world_bible")) + "\n")
                have_world = True
            meta_path = scen_dir / "scenario.json"
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
            if isinstance(meta, dict) and not _s(meta.get("description")):
                meta["description"] = premise_body[:140]
                meta_path.write_text(json.dumps(meta, indent=2),
                                     encoding="utf-8")
        else:
            run.warnings.append("premise: nothing usable — left empty")

    if not have_world and premise_body:
        run.on_stage("world details")
        out, err = assist_field(llm, "world", "seed",
                                "", context=premise_body)
        if out:
            store.write("world-bible.md", "# World bible\n\n" + out + "\n")
        elif err:
            run.warnings.append(f"world: {err}")

    roster: list[str] = []

    def created(kind: str, e: Entry) -> None:
        roster.append(f"[[{kind}:{e.slug}]] {e.title} — {e.oneline()[:90]}")

    counts: dict[str, int] = {}
    for kind, (_shape, _builder, ref, rel) in PIECE_KINDS.items():
        if rel in ("threads.md", "events.md"):
            continue
        entries = store.entries(rel)
        counts[rel] = len(entries)
        for e in entries:
            created(ref, e)

    stages = [
        ("characters", max(0, int(spec.n_npcs) - counts["characters.md"]),
         _CHAR_SHAPE, "characters.md", _character_entry, "char"),
        ("locations", max(0, int(spec.n_locations) - counts["locations.md"]),
         _LOC_SHAPE, "locations.md", _entry_from, "location"),
        ("items", max(0, int(spec.n_items) - counts["items.md"]),
         _ITEM_SHAPE, "items.md", _entry_from, "item"),
    ]
    _run_entity_stages(run, store, brief, premise_body, tone_lock, roster,
                       created, stages, rich)

    if not store.entries("threads.md"):
        run.on_stage("threads")
        ctx = _ctx(premise_body, tone_lock, brief, "\n".join(roster))
        obj = run.emit("threads", _THREAD_SYS, ctx)
        for d in obj.get("threads") or []:
            if isinstance(d, dict):
                e = _entry_from(d)
                if e:
                    e.attrs.setdefault("status", "open")
                    store.upsert_entry("threads.md", e)
        for d in obj.get("canon_events") or []:
            if isinstance(d, dict):
                e = _entry_from(d)
                if e:
                    store.upsert_entry("canon-events.md", e)

    if not intro:
        run.on_stage("introduction")
        ctx = _ctx(premise_body, tone_lock, brief, "\n".join(roster))
        obj = run.emit("introduction", _INTRO_SYS, ctx)
        got = _s((obj or {}).get("introduction"))
        if got:
            _write_premise_md(store, premise_body, got)
            run.on_stage("introduction: written as the opening message")
        else:
            run.warnings.append("introduction: none generated")

    run.on_stage("done" + (f" ({len(run.warnings)} warning(s))"
                           if run.warnings else ""))
    return list(run.warnings)

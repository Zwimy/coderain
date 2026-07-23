# Documentation plan

Status: PLAN ONLY. Nothing here is written yet. This file describes the docs we
intend to produce so anyone can jump in later and execute it. Do not treat the
outlines below as finished documentation.

## Goal

A new person clones the repo (or installs the desktop build), opens the docs, and
within a short read can: run the app, connect a model, start a story, play it well,
author their own world, and understand what every setting does. A second, smaller
track lets a developer understand the architecture well enough to contribute.

## Audience (two tracks)

1. Player / author (primary): non technical. Wants to install, play, and build
   worlds. Most of the docs serve this track.
2. Contributor (secondary): wants the architecture, the data model, and how to run
   the tests. One dedicated section, kept separate so it never clutters track 1.

## Writing principles

- Human voice. Follow the owner rule: no AI sounding copy, and no em or en dashes
  anywhere in shipped text. Use commas, colons, and parentheses instead.
- Task first. Every page opens with what the reader is trying to do, then the steps.
- Show, do not just tell. Real button names, real file paths, short real examples of
  the markdown and the sidecar JSON.
- Screenshots for anything visual (the Plan panel, the builder, Settings), stored in
  docs/img/ and referenced with relative paths.
- Keep each page short and single topic. Link between pages rather than repeating.
- Every claim must match the code. When a page names a setting, a default, or a file,
  verify it against the source before publishing (defaults live in
  coderain/config.py, the API in server.py, the UI in webapp/app.js).

## Proposed structure (docs/ folder, one file per topic)

Ordered so a first time reader can go top to bottom.

1. README.md (docs index)
   - One paragraph on what Coderain is, then a table of contents linking every page
     below. Points players to Getting Started and contributors to Architecture.

2. getting-started.md
   - Install: source checkout (Python, venv, requirements, run server.py) and the
     desktop build. Where user data lives (CODERAIN_HOME, %LOCALAPPDATA%\Coderain,
     or the repo root).
   - Connect a model: Local (Ollama) walk through, then Hosted (paste an API key:
     DeepSeek, GLM, Claude, OpenRouter). Where the key is stored (.env, local only).
   - First story in five steps, ending on a played turn. Screenshot the play view.

3. concepts.md (the mental model)
   - Markdown is the source of truth. Tour a save folder on disk.
   - The three memory tiers: transcript, folded scenes, long arc, plus timeline and
     facts. How folding works and why it keeps context small.
   - The three data layers: instructions (global rules), scenarios (authored worlds),
     saves (playthroughs). How a save is a copy that can diverge.
   - Scenarios vs saves vs the reusable Pieces library.

4. playing.md
   - The core loop: type an action, read the turn.
   - Controls: Continue, Undo, Retry, Branch, swipe variants, Impersonate, Quick
     actions, Stop. What each one does and when to reach for it.
   - Author steering while you play: Author's note, response length, the reply prefix,
     and output cleanup rules (find and replace).
   - The Talk drawer (companion side chat) and when a character can be talked to.

5. worlds-and-cards.md (authoring)
   - The builder: creating characters, locations, factions, items, threads.
   - Pieces: the reusable library, traits (tags) and card to card links.
   - Hidden entries (secrets and twists) and how reveals work.
   - The lorebook activation system: triggers, weight, pinned, and the advanced gates
     (triggers_all, triggers_not, chance, group, delay, sticky, cooldown, semantic,
     recurse, links). One worked example per feature.
   - Event rules and beats (authored pacing).
   - Importing SillyTavern cards (V1, V2, V3 as PNG, JSON, or charx): what carries
     over (character, scenario, first message, embedded lorebook).

6. chapter-plan.md
   - What the rolling outline is and why it exists.
   - How it seeds, steers the writer, and rolls forward at the fold cadence.
   - The Plan panel: view, edit a goal to steer the arc, insert, reorder, delete,
     mark a chapter done, regenerate.
   - The chapter_horizon setting (how many chapters ahead, default 4).
   - Honest note: it is guidance to the writer, not a hard rail, and advancement is
     detected at the memory fold.

7. rpg-mode.md
   - Turning mechanics on, the character sheet, engine rolled dice and fair checks.
   - Stats, skills, DCs, HP, mana, XP, levels and grants (abilities and titles).
   - Inventory and equipment, quests (the thread state machine), companions and trust.
   - The sidecar envelope v1: the world deltas that work even with RPG off
     (time_advance, location, flag_set, reveal, event_fired) and the full RPG deltas.

8. the-brains.md
   - Single brain vs the quad pipeline (Director, code Validator, Writer, optional
     Lore keeper). What each stage does.
   - When to use which: single brain for narrative, quad for RPG or tactical play.
   - The Cost vs quality preset (Economy, Balanced, Quality) and what it changes.
   - Token cost: the levers that matter (context budget, response length, quad on or
     off) and how to keep spend down.

9. settings.md (reference)
   - Every setting on the Settings page, grouped as the UI groups them, with the
     default and a one line explanation. Model profiles, context window and memory
     budget, cost preset, response length, player agency, chapter outline and
     horizon, semantic recall, and the advanced sampler fields.
   - Where each lives in config.yaml for hand editing.

10. rules-files.md
    - The three rule masters: writer-rules.md, memory-rules.md, rpg-rules.md. What
      each controls, how to edit them, global vs per story overrides, and how the
      versioned auto upgrade works (unedited copies update, edited copies are kept).

11. troubleshooting.md (FAQ)
    - Model not responding, empty or think only output, the story forgot something,
      Stop did not stop, tokens burning too fast, how to fix a wrong memory by hand.
    - Backup and portability (it is all just files), and how to move or share a save.

12. architecture.md (contributor track)
    - Repo map and the request path (SPA to FastAPI to engine to memory store).
    - The turn loop, assemble(), the fold pipeline, the validator seam.
    - The provider agnostic LLM client and the streaming or SSE model.
    - Running the tests (run_tests.py, hermetic CODERAIN_HOME), and how the suites are
      structured. How to add a feature safely (rules versioning, save round tripping).

## What we can reuse

- README.md already has a strong Why it is different section and an install and run
  section. Getting Started and concepts.md can lift and expand from it. Keep the
  README as the marketing front door and let docs/ be the manual.
- The inline help text already written into the Settings page and the modals is
  accurate copy we can adapt for settings.md and the feature pages.

## Execution order (phases)

1. Skeleton: create docs/README.md index plus empty stubs for each page, so links
   resolve and the shape is visible.
2. Track 1 core: getting-started, concepts, playing. This alone lets someone use the
   app. Ship these first.
3. Track 1 authoring: worlds-and-cards, chapter-plan, rpg-mode, the-brains.
4. Reference: settings, rules-files, troubleshooting.
5. Track 2: architecture.
6. Screenshots pass and a full link and accuracy check against the current code.

## Open questions (decide before writing)

- One long single page guide, or the multi file docs/ folder above. The plan assumes
  multi file. If a single page is preferred, the same outline becomes the headings.
- Where docs are published: kept in the repo as markdown only, or also rendered to a
  simple site later.
- How deep the RPG and lorebook reference should go, since those have the largest
  surface. Suggest a short concept page plus a fuller reference appendix if needed.

# Documentation plan

Status: PLAN ONLY. Nothing here is written yet. This file describes the docs we
intend to produce so anyone can jump in later and execute it. Do not treat the
outlines below as finished documentation.

Revised for 0.5.0 (2026-07-31): the open questions below are now settled, and a
section was added for the things a live play test proved that the guide has to
say out loud. Read "Newly true as of 0.5.0" before writing any page, because
three of the pages below were planned around behaviour that has since changed.

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
  coderain/config.py, the API in srv/, the UI in webapp/js/).

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

## Newly true as of 0.5.0 (must be reflected)

These came out of a real play test through local Ollama plus the desktop parity
work. Each one changes a page that was already planned above.

1. There are THREE front ends, not two, and the guide must not blur them.
   - the web app (browser, `Coderain.bat`), the primary UI
   - the desktop build (`Coderain.exe`), which is that same web UI in a native
     window, so it has the same features
   - the Tkinter UI (`Coderain.bat --gui`), a source checkout only tool, not in
     the shipped zip (see DECISIONS D-016)
   getting-started.md must say which one the reader is looking at, and must not
   promise the Tkinter app to someone who downloaded the zip.

2. Model choice needs its own section, with measured numbers. This is the single
   biggest thing that decides whether a new user has a working app:
   - a reasoning model (qwen3, deepseek-r1) spends max_tokens on THINKING first
     and prose second, so a budget sized for prose alone returns an empty turn
   - measured on qwen3:4b, the shipped default, with response_length "short":
     4 of 4 generations produced no prose at all until the fix in 0.4.1
   - the fix adds reasoning headroom on every prose call, so this is now a
     tuning note rather than a failure, but "short" on a reasoning model still
     means terse output because thinking eats most of the budget first
   - world sidecar compliance varies by model. Measured over 5 generations each:
     qwen3:4b emits it reliably, deepseek-r1:8b usually, llama3.1:8b and
     gemma3:4b rarely or with blocks the validator rejects. On a model that does
     not emit it, the in world clock only advances at a scene fold, so it lags
     the prose. Say this plainly instead of letting it read as a bug.

3. troubleshooting.md already lists "empty or think only output". We now know the
   cause and can give a real answer instead of a shrug: raise response_length,
   or use a non reasoning model, and check the Context panel for the health line
   that names it. Same for "the story forgot something": the context inspector
   ("What the model sees") answers it directly, and every prompt bug found this
   week was found by reading it. That panel deserves its own short page or a
   prominent section in playing.md.

4. New surfaces to document that did not exist when this plan was written: user
   defaults (your own starting templates, rules versus skeletons behave
   differently), the play aids panel (quick actions and output regex rules), and
   the author's note placement control (system versus tail, every N turns).

5. Health and honesty: `memory/health.jsonl` and the Context panel are how the
   engine reports that something degraded. A guide that never mentions them
   leaves users guessing. Give them a short section in troubleshooting.md.

## Execution order (phases)

1. Skeleton: create docs/README.md index plus empty stubs for each page, so links
   resolve and the shape is visible.
2. Track 1 core: getting-started, concepts, playing. This alone lets someone use the
   app. Ship these first.
3. Track 1 authoring: worlds-and-cards, chapter-plan, rpg-mode, the-brains.
4. Reference: settings, rules-files, troubleshooting.
5. Track 2: architecture.
6. Screenshots pass and a full link and accuracy check against the current code.

## Decisions (settled 2026-07-31, were open questions)

- Multi file docs/ folder, as outlined above. A single page would pass 3000 lines
  once the lorebook and RPG references are in, and the accuracy rule (every claim
  checked against the source) is far easier to hold per page.
- Markdown in the repo only, no rendered site. GitHub renders it, relative links
  work, and it stays in the same review path as the code it describes. Revisit
  only if the guide is ever pointed at from outside the repo.
- Concept page plus reference appendix for the two big surfaces. worlds-and-cards
  explains the activation system with one worked example per gate, and a separate
  appendix table lists every attribute with its exact name, type and default. The
  same split for RPG: rpg-mode teaches it, an appendix lists the envelope fields.
  Reason: those two are where an outdated claim is most likely, and a table is
  cheaper to re verify against the source than prose is.

## Sizing and order of attack

Ordered by "a reader can do something new when this lands", not by page number.

| phase | pages | why this order |
| --- | --- | --- |
| 1 | docs/README.md index plus stubs | links resolve, shape visible, cheap |
| 2 | getting-started, concepts | someone can install, connect a model, play |
| 3 | troubleshooting (early, not last) | the empty turn and forgot something answers are the most asked questions, and both now have real answers |
| 4 | playing, the-brains | the daily loop plus the cost levers |
| 5 | worlds-and-cards, chapter-plan, rpg-mode | authoring, the largest surface |
| 6 | settings, rules-files, appendices | reference, verified field by field |
| 7 | architecture | contributor track |
| 8 | screenshots and a full accuracy pass | do once, at the end, against the code |

troubleshooting moved from phase 4 to phase 3 deliberately. It was planned as
reference, but the two questions it answers (why did I get no text, why did the
story forget something) are the first two a new user hits, and both have measured
answers now.

## Before writing any page

- Verify every named setting, default and file against the source. Defaults are in
  `coderain/config.py`, routes in `srv/`, the web UI in `webapp/js/`, the Tkinter UI
  in `gui.py`. The plan above already contains at least one stale claim per page
  written more than a month ago, which is the reason for this rule.
- No em or en dashes anywhere in shipped text, and no AI sounding copy. Commas,
  colons and parentheses instead.
- State the version the page was checked against, so the next reader knows how much
  to trust it.

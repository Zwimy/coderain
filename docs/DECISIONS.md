# Decisions

Design calls that are deliberate, so nobody (human or agent) "fixes" them back.
Each entry says what was decided, what the tempting alternative is, and what
evidence would change the answer.

---

## D-001 — A pinned entry does not consume its inclusion group's winner

**Decided:** 2026-07-06. **Reaffirmed:** 2026-07-28, twice — the second time by
the repo owner directly, settling it: *"if 2 are pinned, they should not fight
each other, and both be included, regardless of weight. Anything pinned shouldn't
even have to roll."* That is the exemption, and it is now the owner's call rather
than an inherited default. **Code:** `MemoryStore._collapse_groups` (memory.py).
**Test:** `tier2_test.py` §11.

An entry can carry `group: <name>`. Members of a group are mutually exclusive:
the lottery (seeded by story seed + turn + group name) elects one winner and the
rest stay out of context. Separately, `pinned: true` and `weight: critical` mean
"always in context".

When one entry is both, the two rules collide. The decision is:

> A pinned/critical member is **exempt from the lottery**, and the remaining
> members still elect a winner among themselves.

So a group containing one pinned entry and four ordinary ones puts **two**
entries in context: the pinned one, plus one elected alternate.

The same exemption was extended on 2026-07-28 to the player's **current
location**, which `assemble` force-activates on identical footing.

### The alternative, and why it was not taken

A bug sweep argued the group contract says "keep a single winner", so a pinned
member should *win* its group rather than escape it — emitting exactly one entry.
The argument is real: for the classic use of groups (variant descriptions of the
same place or state) two members can contradict each other in the same prompt.

It was not taken because:

1. **"Always in context" is the stronger promise.** It is the one an author sets
   deliberately, and the one a player notices when it breaks. Losing four
   alternates to a pinned entry is a smaller failure than a pinned entry being
   suppressed by a lottery it was never meant to enter.
2. **The exemption is what makes it deterministic.** A pinned entry that wins its
   group still needs a rule for *which* pinned member wins when there are two.
   Exemption has no such case.
3. It has been the tested contract since 2026-07-06, and flipping it silently
   changes what every existing save sends to the model.

### What would change the answer

Evidence that authors actually put pinned entries in groups *expecting* mutual
exclusion — i.e. a real scenario where two members contradict each other in a
shipped prompt. If that shows up, the fix is not to flip the exemption but to
**warn at authoring time**: a lint in the world builder saying "this entry is
pinned AND grouped; the group will emit two entries."

### The related bug this decision does NOT excuse

Exempting pinned entries from the lottery is only half of "always in context".
The other half is the budget, and there the promise was being broken: hidden
entries are diverted into the Secrets block before the pinned/critical split, and
that block sat at priority 2 with ordinary lore — so a `hidden` + `critical`
entry could be cut while its visible sibling survived. Fixed 2026-07-28: the
always-on hidden entries go in at priority 0 and the rest keep competing at 2
(`wave2_test.py` §3b pins it, at the exact budget where the old code dropped it).

The reason it stayed open for a round is worth recording: honouring the invariant
costs ordinary lore at tight budgets, and the first attempt was reverted because
`wave2_test` §3 went red. §3 was measuring the wrong thing by then — it asserted
an `important` entry survived a budget that no longer had room for any priority-2
section at all. The invariant wins; the test moved to a budget where it still
discriminates between `minor` and `important`.

---

## D-002 — Undo rolls back mechanics one level, but the transcript every time

**Decided:** 2026-07-28.
**Code:** `Engine.undo_last`, `Engine.restore_pre_turn_rpg` (engine.py).
**Test:** `sweep_validator_test.py` §6, `sweep2_regress_test.py` §1.

`_pre_turn_rpg` holds ONE snapshot, so a second consecutive undo cannot rewind
gold/flags/HP further. The transcript, however, shrinks on every press, and the
UI offers undo every turn with a hotkey.

Rather than make undo refuse after one press (surprising) or persist per-turn
snapshots (a storage and migration cost), the asymmetry is kept and made safe:

- the event log is truncated **only** when a snapshot was actually consumed, so
  the ledger never stops describing the state that is really applied;
- folds are trimmed back to what the transcript still supports on every press.

Multi-level mechanics undo would need persisted per-turn snapshots. That is a
feature, not a bug fix, and it is not scheduled.

---

## D-003 — Budget packing skips and carries on, and is not monotone at the margin

**Decided:** 2026-07-28. **Code:** `MemoryStore._pack_budget` (memory.py).
**Test:** `wave2_test.py` §3/§3b, `sweep2_regress_test.py` §9.

Sections are ranked by priority, then packed greedily. When one does not fit,
packing **skips it and carries on** with the rest rather than stopping.

The consequence is a known non-monotonicity: there are narrow budget bands where
*raising* the budget promotes a big section into the prompt and evicts several
smaller ones that had moved in behind it. Measured at roughly five tokens wide.

### The alternative, and why it was not taken

A strict prefix — stop at the first section that does not fit — is monotone, and
it was implemented twice. Both times it was reverted, because it lets one fat
high-priority section starve every tier below it: at a 220-token budget it put
**no lore at all** in front of the model, where skip-and-continue still delivered
the important entries.

Graceful degradation at a tight budget matters more than smoothness at a five-
token seam. A prompt missing one mid-sized section is still a working turn; a
prompt with no lore is a story that forgot its own world.

### What would change the answer

A packer that is both monotone and degrades gracefully — best-fit-decreasing
within a priority tier, or a proper knapsack over (priority, size). That is a
rewrite of `_pack_budget`, not a flip of one branch, and it needs the same
tight-budget evidence: at 220 tokens it must still deliver the important lore.

Priority 0 is exempt from all of this. `pinned:` / `weight: critical` entries are
always in context (invariant 4) — they are placed before the competition starts
and only ever truncated, never dropped. See D-001.

---

## D-004 — `recall_entity` / `recall_quest` resolve a slug, not a title or alias

**Decided:** 2026-07-28 (accepted, not fixed). **Code:** `MemoryStore.recall_entity`,
`MemoryStore.recall_quest` (memory.py). **Tool schema:** `engine.py` `LOOKUP_TOOL`.

Both tools do `slug = templates.slugify(name)` and then look that slug up
directly. They never consult `e.title` or `e.aliases` — unlike
`resolve_location`, which checks all three.

The tool descriptions handed to the model say "character/location name or slug"
and "quest/thread name or slug". For any entry whose anchor is not
`slugify(title)` — `## The Static Quarter {#static-quarter}` is the shipped
example — asking by name misses, and the model is told the entity does not exist.

### Why it is not being fixed now

It is a one-line change to try title and alias after the slug, and that is
exactly the shape of change that has gone wrong repeatedly here: this repo's
measured rate is roughly one new defect per four fixes, and the failures cluster
in "I widened what a lookup accepts". Widening `recall_*` changes which entries
the memory tool returns mid-generation, which changes prompts, which is the
hardest class to test.

The cost of leaving it is bounded and visible: a failed recall returns "No entity
or episode matches X" and the turn continues. The cost of getting the fix wrong
is a recall that returns the WRONG entity, which is silent.

### What would change the answer

A user reporting that the memory tool cannot find a character it plainly should,
or the same fix being needed for another reason. If it is done, it must be done
with a test that pins the miss AND the near-miss (two entries whose titles slug
to overlapping values), because the risk is over-matching, not under-matching.

---

## D-005 — No bound on an entry's alias / triggers list

**Decided:** 2026-07-28 (accepted, not fixed). **Code:** `parse_entries`,
`Entry.triggers` (memory.py).

`parse_entries` caps neither the alias list nor the `triggers:` attr, and
`Entry.triggers()` returns title + slug + aliases + triggers as one flat list
that `_entry_activates` walks with a fresh `re.search` per token, for every gated
entry, on every turn. Measured: 20,000 keys turns a 0.024 s assemble into 1.47 s.

The WRITE side is bounded — `summarizer._apply_promotions` caps a promotion's
alias list at `LIST_LIMIT` (32). This is about what a hand-edited or imported
file may contain.

### Why it is not being fixed now

The failure mode is slowness the user can see and attribute (their own file, one
they edited), not silent corruption. Every other unbounded value in this engine
was dangerous because it became *permanent and invisible*; this one is neither.

Capping at parse time also silently discards authored content on read, which is
a worse property than being slow — the file would stop round-tripping, and
invariant 7 violations are how the last two "safe" bounds turned into defects.

### What would change the answer

A real save that is slow for this reason. The fix then is not a parse-time cap
but a per-entry warning at load plus a bound applied on WRITE, so the user's file
is never silently truncated by reading it.

---

# Accepted after round 11

The entries below came out of a verification-only sweep (2026-07-29) that
re-tested 61 claims across six commits and ran three fresh area scans. They are
real, reproduced defects. They are **not being fixed**, under a stopping rule
agreed before the sweep ran: fix only criticals and fixes that no longer hold;
everything else is written down instead.

The reason is measured, not squeamish. Across eleven rounds this repo took ~133
defects and roughly a quarter of each round's findings were *created* by the
previous round's fixes — including three cases where the fix was worse than the
bug (a unicode-aware slugify the parser could not read back; a day clamp that
made a wrong value permanent; a retry counter measured after the thing it
counted). At this severity, another fix pass is a losing trade.

Each entry says what would change that.

---

## D-006 — `branch()` can rebuild from a snapshot that is no longer a prefix

**Code:** `_nearest_snapshot`, `branch` (memory.py). **Severity:** high, derived
data only.

After a retry or undo of the exchange that triggered a fold, the pre-fold
snapshot describes a timeline that no longer exists. Every branch point in
`[snap_turns, next_snap)` restores that stale `state.json` **and** skips the
replacing exchange's envelope, so the fork carries the flags/gold of the exchange
the player retried away and not the one that replaced it — while its transcript
holds the replacement prose. `warnings` is empty. A related edge: when a snapshot
sits at exactly the post-undo turn count, `snap_turns < r["turn"]` excludes the
record `clamp_event_log_to_transcript` just re-indexed onto that turn.

**Why accepted:** the corruption is confined to a **derived** save. The source is
untouched, the fork's prose is right, only its numbers are one exchange stale,
and recovery is "delete the fork". The fix lives in `_nearest_snapshot` plus the
replay filter — the densest defect intersection in this codebase, where D-002,
the clamp, the fold pointer and snapshot retention all meet. A refuter measured
that the obvious fix is wrong: an inclusive low bound yields gold 9 against the
save's 8, because the snapshot's state already contains that envelope. There is
no known correct one-line change.

**What would change it:** a user reporting a fork whose numbers disagree with its
prose. The first move then is a **warning**, not a rebuild — compare the
snapshot's turn count to the transcript and say so in `warnings`.

---

## D-007 — Undo does not remove the `items.md` mirror stub an `inventory_add` created

**Code:** `Engine.restore_pre_turn_rpg` (engine.py), `modules/rpg.py`.

`restore_pre_turn_rpg` reverts three Markdown mutations — reveals, canon events,
consumed once-rules — and its comment presents that as the complete set. `rpg`
makes a fourth: a "held by you" stub in `items.md`. After an undo the lorebook
says the player carries an item the sheet says they do not.

**Why accepted:** conditional, not always-on — the stub only enters the prompt
when the item is named. It partially self-heals: `_held_only` accepts the stub as
proof of holding, so a later `inventory_remove` deletes it. And
`restore_pre_turn_rpg` is the exact function three separate sweeps already fought
over; it is the highest-regression-density function in the engine.

**What would change it:** a report of a ghost item persisting across an undo in
normal play, or any other reason to touch that function — at which point the
fourth mutation should be tracked like the other three, not special-cased.

---

## D-008 — `ChapterPlanner.seed(force=True)` deletes the outline before it validates the reply

**Code:** `ChapterPlanner.seed` (planner.py).

A non-empty list of non-dicts empties `outline.md`, returns `[]` so no event
reaches the UI, and logs nothing. Done/active chapter history and hand-edited
goals are gone, with no snapshot on that route.

**Why accepted:** the user pressed "Regenerate", so destruction is the requested
outcome; what is lost is planning metadata, not story or memory. It self-heals —
`ensure_seeded()` re-seeds on the next fold. Blast radius is one regenerable
panel.

**What would change it:** one report of a lost chapter plan. The fix is to build
the new outline in memory and only then replace, which is also the right shape
for `replace_all`.

---

## D-009 — `generator._entry_from` iterates a bare-string `aliases` character by character

**Code:** `generator.py`.

A model returning `"aliases": "ai"` instead of `["ai"]` yields the one-letter
triggers `a` and `i`, which `trigger_hit` matches as standalone English words —
so the entry activates on essentially every turn, and the garbage alias line is
copied into every save started from that world.

**Why accepted:** genuinely asymmetric with `summarizer._apply_promotions`, which
guards this exact case with a comment naming it. But the damage is a visible
garbage line in an authored scenario file, on the world-authoring path, not the
play path — and it is a two-line fix, which is how three of this repo's worst
regressions started.

**What would change it:** doing any other work in `generator.py`. Fix it in the
same pass, mirroring the promotions guard verbatim rather than inventing a second
version of it — divergence between two copies of one rule is what produced the
arc-heading bug and D-006's sibling.

---

## D-010 — `_apply_promotions` bounds every value but not the promotion LISTS

**Code:** `summarizer.py`.

`promotions`, `new_threads` and `resolved_threads` have no `LIST_LIMIT`. A
degenerate fold could write hundreds of permanent entries, and `merge_entry`
re-reads and rewrites the growing file per promotion, so the cost is quadratic.

**Why accepted:** the refuter deflated the harm. The demonstration payload is
4.2x the `JSON_MIN_TOKENS` floor; realistic degenerate output repeats itself, so
slugs collide and hundreds of promotions collapse to one entry in about a second.
The prompt does not balloon — the budget packer holds. The missing bound is real;
the consequence is not.

**What would change it:** a real save with a bloated `characters.md`, or a fold
that visibly stalls a turn.

---

## D-011 — `welcome.js` assigns to an imported binding, so "Look around first" throws

**Code:** `welcome.js`, `nav.js`. **The owner may reasonably override this one.**

`_ready` is an ES-module import (`export let _ready` in nav.js). Assigning to it
raises `TypeError: Assignment to constant variable.` on the first screen a new
user sees; `skipped` is written nowhere else, so the button is dead code, and a
stopped Ollama keeps an existing user out of the Library.

**Why accepted:** nothing is lost or corrupted, and the recovery path the code
itself names — Settings, which calls `invalidateReady()` — stays reachable. The
stopping rule says accept, and applying a rule only when its answer is
comfortable makes it decoration.

**Recorded honestly:** this is the entry most likely to generate an actual
complaint, and its fix is the smallest on the list (export a setter from
`nav.js`). If the owner wants exactly one exception to the rule, this is the one
to spend it on.

---

## D-012 — A story created while another is generating never requests its opening

**Code:** `renderPlay` -> `run()`'s `if (busy) return` (play.js).

`busy` is app-wide by design. Creating a second story while the first is mid-turn
means the bootstrap `POST /opening` is swallowed, so the world's authored
Introduction is never used — and one typed action commits the story without it,
because `continue_story` never consults `opening_override`.

**Why accepted:** nothing existing is corrupted, `premise.md` still holds the
intro, and leaving and re-entering the story before typing fixes it. The fix
means special-casing the bootstrap inside the re-entrancy guard — a
race-condition change in the SPA's most-touched function, which has been wrong
after three of the four commits that touched it.

**What would change it:** a report of a story that started blank. The safer fix is
a retry when entering the view with an empty transcript, not a hole in the `busy`
guard.

---

## D-013 — One double-click on a chapter's bin deletes two chapters

**Code:** `outlineModal`'s `refetch` (play.js), `srv/outline.py`.

Row ops only disable when a `busyBtn` is passed, and the delete route is
positional and not idempotent, so the list re-renders under the cursor and the
second click lands on the row that moved up. No confirmation, no undo.

**Why accepted:** it fails the "cannot see" half of the critical bar — the user
watches two rows vanish. It is the strongest accept on this list.

**What would change it:** one report of a lost chapter. The fix is to disable the
row during the request, not to add a confirmation dialog.

---

## D-014 — `Entry.render` neutralizes title, aliases, attrs and body, but not the slug

**Code:** `Entry.render` (memory.py).

The slug is interpolated raw into `{#…}`, so a `<!--` inside one would reproduce
the entry-hiding bug that render's neutralization exists to prevent.

**Why accepted:** no reachable producer. Every writer runs `templates.slugify`
first, which maps `<`, `!` and `-` to dashes. This is a hardening gap, not a
defect.

**What would change it:** any new path that sets a slug without slugifying —
worth watching for, because the slug is the one field a reader treats
structurally.

---

## D-015 — The zero-width space used to neutralize `<!--` is visible in three small ways

**Code:** `Entry.render`, `_unhide` (memory.py).

Three consequences, all measured and all bounded:

1. Text that already contains the neutralized form (`<` + U+200B + `!--`) is
   collapsed to `<!--` on read, so that exact authored input does not round-trip.
   Fixpoint from cycle 2; no escalation across 60,000 fuzz cases.
2. The zero-width space reaches the model's prompt, because `assemble()`
   re-renders entries through the same `Entry.render` that writes disk.
3. Lore-budget arithmetic shifts by one char per marker, since it measures
   `len(e.render())`.

**Why accepted:** the transcript pair `_render_turn`/`turns()` has had the
identical property since it was written — inherited symmetry, not a new idea. No
hash, dedupe, slug, link-resolution or export path compares text carrying the
marker (checked). Separating the on-disk and in-prompt representations means
giving `Entry` two render methods and making every caller pick the right one — a
much larger change than the bug justifies.

**What would change it:** a model visibly reacting to the marker, or any need to
make `render()` serve two purposes for an unrelated reason.

---

## D-016 — The Tkinter UI is a source-run tool, not part of the shipped binary

**Code:** `build.py`, `gui.py`, `desktop.py`. **Owner decision, 2026-07-31.**

`build.py` freezes `desktop.py`, which serves `server.py` and renders `webapp/`
in a WebView2 window. `gui.py` — the Tkinter app — is not bundled: neither `gui`
nor `tkinter` appears in the frozen PYZ (checked: 2287 modules, both absent). It
is reached only from a source checkout, via `Coderain.bat --gui`.

This looks like a packaging bug and is not one. It is worth writing down because
it looks *exactly* like a bug from one angle: v0.5.0 landed six commits of
desktop parity work (Tier-2 activation gates, author's note, play aids, the
context inspector, the chapter plan, user defaults, world authoring, the
character depth fields) and **none of that code is in the distributable**. A
future reader who notices that will reasonably try to "fix" it by adding a
`--hidden-import gui` and a `--gui` flag.

**Why accepted:** the zip already ships the full feature set. `Coderain.exe` is
the web UI in a native frame, so a zip user has every feature the SPA has — the
parity work was about the *Tkinter* front end, which `Coderain.bat` itself calls
a "retro Tkinter UI (easter egg)". Bundling it means adding tcl/tk to the
payload and giving a `--windowed` entry point argument parsing it does not have,
to ship a second UI that then has to be kept working against every engine change.

**Not wasted, and worth being precise about:** most of that work was moving
engine rules OUT of HTTP route handlers — `coderain/aids.py`,
`coderain/inspect.py`, `coderain/defaults.py`, `ChapterPlanner`'s panel methods
with `PlanError`, `ScenarioLibrary.store/piece_files`. The routes got thinner and
the web app runs the same shared code, so the binary benefits even though the
Tkinter dialogs are absent from it.

**What would change it:** a user asking for the Tkinter UI in the distributed
build. The cheaper first move then is a second executable built from `gui.py`
(`CoderainRetro.exe`), not a flag on the main one — it keeps the shipped app's
entry point unchanged and lets the extra payload be opt-in.

---

## D-017 — `canon/` is a standalone package that nothing imports yet

**Decided:** 2026-11-07. **Code:** `canon/` (ledger.py, state.py, store.py).
**Test:** `tests/canon_ledger_test.py`.

Phase 1 of the consistency design: an append-only, hash-chained ledger of every
fact change, a pure projection of it into current and historical canon, and a
snapshot that is only ever a cache. Nothing in `coderain/`, `srv/` or the web app
imports it. That looks like dead code, and it is deliberate.

**Why it is not wired in:** the ledger is meant to become the only truth, which
means replacing the places the engine writes facts today (the fold's
`merge_entry(rewrite=True)`, the sidecar deltas, `events.jsonl`). This repo's own
record says wide changes to those paths regress: roughly one new defect per four
fixes, and the worst clusters are exactly there (D-002, D-006, D-007). So the
foundation was built and proven in isolation first (replay equals state, undo
equals truncation, a rebuild reproduces canon, 14 mutations of its guards each
caught by a test), and integration is a separate, reviewable step.

**The tempting alternative:** put it under `coderain/` and start routing writes
through it. Rejected for now because there is nothing yet to compare against: the
Phase 0 harness (`soak/`) measures what today's engine keeps, and wiring in
before that baseline is used would make the comparison impossible.

**What would change it:** the Phase 2 Scribe and validator existing, so there is
something that writes into the ledger. Integration then goes in behind a flag,
with the Phase 0 baseline as the bar.

---

**Update 2026-11-09:** no longer true that nothing imports it. The engine now uses
`canon/` in one place, `coderain/canon_shadow.py`, when `canon.shadow` is on (D-021).
`canon/` itself is still standalone and imports nothing from the engine.

## D-018 — Authority pins identity, not state

**Decided:** 2026-11-07. **Code:** `canon/state.py` (`apply`,
`_may_supersede_state`). **Test:** `canon_ledger_test.py` §6, §7.

An author edit or a scenario-authored value does NOT stop narration from changing
a state slot. A scenario can start a character in a travelling cloak, and the
story must be able to put her in a coat. Authority only holds back `inferred`
(a guess) from overwriting narrated or authored state.

Identity slots are the opposite: first write wins, a different value from equal
or lower authority is recorded as a conflict and not applied, and only a strictly
higher authority or an explicit `retcon` / `author_edit` replaces it.

**Why this looks wrong:** "author edit beats narration" reads as a single rule.
Applied to state it would pin every authored starting value forever, and the first
time a character changed clothes the ledger would record a conflict instead of the
story. The layer is decided by the slot's name (`state.*` versus everything
else), so no model decides which rule a fact gets.

**What would change it:** a case where an author wants a state held against
narration. The fix is a separate explicit "pin" record, not authority.

## D-019 — A claim must be about someone the passage names, and only dreams are held back

**Decided:** 2026-11-08. **Code:** `canon/validate.py` (`named_in_prose`,
`_IRREALIS`, `_sentence_of`). **Test:** `canon_scribe_test.py` §16.

Two deterministic checks sit in front of the ledger, because the Scribe is a small
model and these are errors it makes that code can see.

1. The entity has to be named in the passage (full name, first name or alias).
   Given a passage about "you" and a list of characters, gemma3:4b wrote "your
   coat soaked through" onto Odile Marsh. A wrong attribution is the most damaging
   error because nothing downstream can tell. A consequence: a passage that uses
   only pronouns yields nothing until the caller says who the scene is about.
   That belongs to the scene frame in Phase 3, not to a looser check here.
2. A claim whose own evidence sentence contains dream, nightmare, imagine,
   pretend, "as if" or "as though" waits as `pending`. Only that sentence is read,
   so "She had dreamed of this. Her hair was raven." still records the hair.

**Why this looks incomplete:** hypotheticals ("if she had a scar"), wishes and
plans are NOT in the marker list, although they are the same kind of error. That
is deliberate. The evaluation corpus has dev and test traps for exactly those, and
a list written against them would turn the test split into a second dev split. The
list has to be written against fresh cases.

**What would change it:** a new batch of trap passages that did not inform this
list, on which adding hypothetical, wish and plan markers lowers false positives
without holding back real claims. Until then the test-split trap score is the
honest measure of what the validator cannot catch.

**Update 2026-11-10 (D-024):** the pronoun-only limit is now handled in code, for state facts and for
"you". A pronoun is still never resolved for an identity fact, and an empty `Who` reproduces this decision exactly.

## D-020 — The scene card shares the validator's idea of a name, and a cut is always visible

**Decided:** 2026-11-09. **Code:** `canon/scene.py` (`mentions`, `_compose`,
`render_card`, `_clean`). **Test:** `canon_scene_test.py` §1, §6 to §9.

Three calls in the module that read as over-careful, and each one is a failure
that was found or measured:

1. `mentions` uses the validator's word lists and tokeniser on purpose. If the
   validator accepted a claim for someone the cast then ignored, the fact would be
   in the ledger and never shown. A bare word names someone only when it is
   capitalised and identifies exactly one entity, so a bare "Corin" with two Corins
   is nobody, "ash" is not Ash, and the words of a multi-word alias are not names
   on their own ("Old habits die hard" is not The Old Man).
2. A line that is too long is cut from the bottom of a fixed priority and the first
   field that does not fit ends the line. An earlier version skipped a long field
   and let shorter, lower-priority ones fill in, which dropped a scar and kept an
   age. Anything left out is announced ("more not shown", "(+N more)", or a name in
   the last line). The card is read by the Writer every turn, so a quiet cut is a
   permanent, invisible loss.
3. Values lose `;`, `:`, newlines and dashes when rendered. They come from a model
   through the validator and are copied into every later context, so a value that
   could write "Corin Hale: wearing a crown" into another character's line would
   become canon about Corin.

**What would change it:** a measured case where the strict priority hides something
that mattered more than what it kept, or a name form the matcher misses on real
prose. Both are visible in the real-save gate, not guessable from here.

## D-021 — Shadow canon is the engine's first use of canon/, and it is observe-only

**Decided:** 2026-11-09. **Code:** `coderain/canon_shadow.py`, one hook in
`Engine.maybe_fold`, the `busy` probe in `srv/core.py::_engine`, the `canon` exclusion
in `SaveLibrary.export`. **Test:** `canon_shadow_test.py`.

With `canon: {shadow: true}` in config.yaml, a background thread reads each narrator
turn with a local model, keeps the facts in `<save>/canon/`, and writes
`<save>/canon/report.txt`: what it saw, and every time the story contradicted a fact
it had already recorded. NOTHING it produces reaches a prompt. Deciding whether to
inject the card is a separate step with its own flag, to be taken from what the report
shows. Off unless the value is a literal `true`, and when off `canon/` is not imported.
(That second step now exists: D-027. With `shadow: true` alone this still holds.)

Calls that look heavier than they need to be:

1. It follows the transcript by CONTENT HASH, not by hooking undo, retry, swipe, edit
   and branch. The engine has a separate code path for each, and a hook in each is a
   standing source of drift. Each pass hashes every narrator turn, rolls the ledger
   back to the first one that differs, and replays from there. One mechanism covers
   every way a transcript can change, including ones added later. Note the trap this
   found: `update_turn(i)` is 0-based while ledger turns and `branch(n)` are 1-based.
2. The ledger is derived data. It lives in the save folder so it is deleted, renamed
   and branched with the save, but it is excluded from exports and can be deleted at
   any time and rebuilt from the transcript (invariant 7 holds: Markdown is the truth).
3. LOCAL ONLY. A real story is read by a model nobody chose per call, so anything but
   Ollama on this machine is refused (`canon.scribe.require_local`). A hosted Scribe is
   a decision for later, with the person's say-so, not a default.
4. It waits while a turn is generating (the server hands it the generation lock), runs
   on its own thread, never raises into the engine, and reports each distinct failure
   once to the health log (invariant 2). A down model is retried on the next turn, not
   recorded as processed.
5. A character met mid-story is seeded at the turn they are first met, not turn 0: a
   ledger's turns never decrease, so turn 0 is refused and every claim about them would
   silently go nowhere.
6. The report and per-turn rows hold values and counts, never prose. The ledger keeps
   the short quoted span behind each fact as provenance, inside the save folder.

**What would change it:** the report showing the shadow is wrong about real play (too
many held-back changes that are Scribe errors, not story drift), or a transcript change
the hash does not catch. Fix the first in the validator, never by editing a prompt.


## D-022 — A wrong first identity value is stopped at the door, not corrected later

**Decided:** 2026-11-09. **Code:** `canon/shape.py`, called from `validate()` before the
restatement rewrite, and `_shared_quotes` in `canon/validate.py`. **Tests:**
`canon_shape_test.py`, and the named losses in `soak_scribe_corpus_test.py`.

The real-save gate (976 narrator turns) showed that most identity values the Scribe
proposed described something else. In a hand-labelled sample about 70% were wrong:
a tattoo colour for hair, "violet" for hair (the quote was "her violet
eyes"), a string of beads for hair, "dark, sharp, utterly unimpressed" for eyes. Identity is
first write wins, so the first wrong value locked the slot and the real one (green
eyes, narrated 11 times) was held back every time. The restatement logic made it worse:
"the thin black fabric of her glove" was rewritten to the existing wording and counted
as a second sighting of black hair.

What it does now, in plain code, before anything reaches the ledger:

1. **The quote must describe the slot.** For hair and eyes the slot's noun has to be in
   the Scribe's own quote and the value has to be the words attached to it. A run of
   descriptor words belongs to the noun after it ("violet eyes"), else to the noun
   before it ("eyes, green like yours"), and stops at any other word. So "platinum
   hair, violet eyes" gives platinum to hair and violet to eyes, and "glass beads click
   in her hair" gives nothing to hair. Build must touch a body noun or the person
   ("lean frame", "she's tall"), never a window, a stride or a verb. Age must be an age.
   Marks and state slots are not covered.
2. **It runs before the restatement rewrite**, so a misfit is rejected, not turned into
   the existing value and counted as agreeing with it.
3. **One quote filed under two people waits for both** (`pending`, `ambiguous_owner`).
   At most one is right, and a wrong identity write is permanent. In the real ledger
   this was 5 of 208 distinct quotes and each produced a wrong lock.

Measured, with the rule written against a dev half and then checked on samples I had
not tuned on (hand labels, small, mine, so treat as indicative):
- dev (tuned): 20 of 20 valid kept, 48 of 48 invalid rejected.
- second half (build rule adjusted after it showed one false accept): 25 of 25, 41 of 41.
- fresh blind sample of 80, scored once: 20 of 24 valid kept, 52 of 52 invalid
  rejected. Zero false accepts in 141 invalid, so the true rate is probably under 2%.
- replaying the recorded gate ledger through it (no model): locked identity values
  107 to 68, held-back changes 508 to 78. One character's raven hair stays locked against 9
  later "platinum" sightings, which is the drift the system exists to flag. Another's
  green eyes (x9) now lock instead of a facial expression.

**What it costs, on purpose.** A true claim whose quote lacks the noun is refused:
"the colour of straw", "small for his age", "Tall. Athletic.", "young, brunette", "the
shaved head", and long phrases ("dark hair pulled back in a severe bun"). On the
invented corpus 2 of 32 labelled claims (listed in `SHAPE_LOSSES`), on real text about
1 in 6 valid claims. That is the right side to err on: a refused true value is narrated
again and recorded then, a wrong first one is permanent. The vocabulary is general
English (colours, gems, hair styles, builds), not this story's words.

**Rejected, and why:**
- **Majority vote or "most repeated value wins" to correct a wrong lock.** In the real
  ledger the narrator wrote one character's hair as platinum 9 times and raven once. A vote
  would replace the first narration with the drift, which is the exact failure the
  redesign exists to catch. A correction has to come from a person (`author_edit`
  already crosses the identity lock) or from evidence about WHO, not how often.
- **A "tentative until repeated" lock.** Same flaw, and most true values are narrated
  once or twice, so it would leave real characters blank.
- **A rule that the quote must not name another character.** 60 of 204 accepted claims
  tripped it, nearly all because characters carry colour words as aliases ("Amber",
  "Silver", "Shade"), so "Amber eyes" looked like it named a character.
- **A gender-agreement check** ("her" in the quote, a male character). Only 3 of 147
  accepted claims disagreed once the shape rule had run, so it is not worth a rule yet.
  It did catch the one real misattribution left (a man given a woman's raven hair).

**Not done, and next:** misattribution in multi-character passages (the Scribe is not
told who a pronoun refers to; same step as the 590 pronoun-only rejects); a Scribe
prompt line asking for the noun in the quote ("her violet eyes", not "violet"), which
would win back most of the refused claims but has to be measured with the real model;
state lists that only grow. The real Scribe has not been re-run through this, so the
end-to-end effect on a replay is a prediction from recorded proposals until it is.

**What would change it:** a fresh labelled sample where the rule refuses more than a
quarter of valid claims, or accepts a wrong value that then locks a slot. Widen the
vocabulary first, never loosen the attachment rule.


## D-023 — State lists take only what the slot is for, replace by kind, and age out

**Decided:** 2026-11-10. **Code:** `canon/shape.py` (state rules), `canon/wardrobe.py`,
`_plan` and `LIST_CAP` in `canon/validate.py`, `Interval.last_turn` and `Canon.last_seen`
in `canon/state.py`, `FRESH_TURNS` and the `now` parameter in `canon/scene.py`.
**Tests:** `canon_state_lists_test.py`.

The real-save gate found three separate things wrong with outfit, held items and
injuries, and decay alone would have fixed only one of them:

1. **They were mostly not what the slot says.** The outfit lists held a plume of smoke,
   a teacup, tattoos, bare feet and a stripe of rain. The held lists held thumbs,
   fingers, a glow and a feeling. The injury lists held "bike", "soaked" and a
   pounding heart. In a sample of 60, about 1 item in 6 was real.
2. **They only grew.** The Scribe says a thing was taken off almost never (6 times in
   1,646 turns), and a list at the cap of 16 REFUSED the newest item (386 refusals), so
   a full list showed the oldest things in the story and nothing new. State is latest
   wins; the old rule kept the oldest.
3. **Nothing said when a value was last true.** A coat worn once at turn 75 was on the
   card at turn 1,048.

What it does now:

- **Entry check per slot (`shape.problem`).** Outfit needs a garment: the last garment
  word of the item's noun phrase, so "tuxedo vest sweated through" is a vest and "pistol
  tucked in her belt" is a pistol. Held needs an object from a vocabulary of everyday
  things (cup, datapad, towel, pistol), not a body part, a person or a phenomenon.
  Injury needs a wound word; ambiguous ones ("broken", "burn", "cut") count only with a
  body part in the value, "swollen" and "sore" only on a limb, a joint or the face, and
  scars and tattoos are marks, not injuries.
- **Replace by kind (`wardrobe.replaced_by`).** A new garment replaces the one of its
  kind: boots replace boots, a dress takes the top and the bottom, jeans take a dress.
  Things worn together (rings, a scarf, a belt) stay. The ledger keeps the old outfit,
  so "what did she wear at turn 5" still has an answer.
- **A full list drops its OLDEST item** instead of refusing the new one. Caps: outfit 10,
  held 6, injury 6 (the ledger's own bound stays 16). Untuned.
- **Saying an item again moves it to the newest place, with its old wording, and is
  RECORDED**, as is a scalar restated unchanged. These used to be dropped as no-ops. The
  record is what tells canon the story said it again just now, so `Canon.last_seen`
  can say when. Cost: one ledger record per restatement.
- **The card leaves out a value the story has not stated for too long** (`FRESH_TURNS`:
  outfit and injury 120 ledger turns, location 40, held 30, mood 15; player turns count,
  so 120 is about 60 narrator turns). Unknown is honest; a coat worn 900 turns ago is
  not. `find_scene` ignores an old place when deciding who is "in the same room". The
  parameter is `now`, and nothing expires when it is not given, so no existing caller
  changed. The windows are guesses, so the shadow report now ends with the evidence for
  moving them: per field, how many characters have a value, the median age, and how many
  are past the window (`replay.state_ages`; counts and ages, never narration).

Measured, by hand-labelling real items (small samples, my labels, so indicative):
- Samples I tuned on (dev, test, fresh): 10 of 10, 12 of 12, 24 of 25 valid kept, and
  all but 2, 0 and 0 of the invalid rejected. These are optimistic by construction.
- A clean sample drawn after the rules were frozen, scored once: 12 of 15 valid kept and
  47 of 50 invalid rejected. By slot: outfit 9 of 10 and 14 of 14, held 1 of 3 and 14 of
  17, injury 2 of 2 and 19 of 19. One bug was found by it and fixed (a plural fallback
  that read "tight" as "tights"); no vocabulary was added from it.
- Replaying every recorded item of the real gate ledger (no model): final outfit lists
  median 7 to 2, the 11 characters at the old cap of 16 to none; held median 4 to 1;
  characters with an injury list 33 to 8. I read every accepted injury and held item
  (not all 96 outfit items, only the lists of six characters, which read as wardrobes). Of 16
  accepted injuries, 14 are wounds by my reading and 2 are not (a figurative "burn", a
  "cut" that is a verb about lines). Of 49 accepted held items nearly all are
  everyday objects, but some are in the scene and not in a hand (crates, a map).

**What it costs, on purpose.** About 1 valid item in 5 is refused for want of a word
(sweats, tourniquet, lumpia, "a modest curved silicone shape"); the vocabulary grows from
what the shadow report shows, never by loosening the rule. Held is the weakest slot: an
object mentioned but not held passes, and a holding verb cannot fix that (it kept 0 of 5
valid in the first test, because real quotes say "palmed", "scoops up", "pull it from the
rack"). The card shows a held item for only 30 turns, which is what bounds the harm; if
the report shows it misleading, drop the field from the card before tuning it. The model
of dress is wrong in known ways: a hoodie over a tee counts as one top, and a coat picked
up to carry replaces the one worn. Each costs one item on a card, against a list that
never lets go.

**Rejected, and why:**
- **Decay alone**, by age or by position. It would have rotated the same misfiles on and
  off the card. The entry check had to come first.
- **A holding verb as the test for a held item.** 0 of 5 on a fresh half.
- **One slot per item** (as marks have), so each item carries its own age. A large change
  to the projection, the card and every test, for something a restatement record gives at
  the level of the list.
- **Hiding stale items in the projection** (`Canon.current`). It would make the ledger's
  own answers depend on when you ask. The window lives where the card is made.

**What would change it:** the shadow report showing the windows are wrong (a coat that
is still worn, dropped; a place that is still true, forgotten), the ledger growing
faster than the restatement records justify, or a clean sample where the entry rules
refuse more than a third of valid items. Widen the vocabulary first; move a window second;
loosen the rule last.

**Changed behaviour to know about:** a repeat is now a `commit` with reason `restated`
(it was a `noop`), so a shadow or gate report's "committed" count includes restatements;
`list_full` is gone; the real-save gate's `evaluate` still renders the card without `now`,
so it shows every state value ever recorded.


## D-024 — Code decides who "you", "she" and "he" mean: "you" always, a pronoun for state facts only

**Decided:** 2026-11-10. **Code:** `canon/referents.py`, `Who` in `canon/validate.py`,
`mention_spans` in `canon/scene.py`, `player_entity`, `player_gender`, `GenderVotes`,
`reads_anyone` and `passage_who` in `canon/replay.py`, and their use in
`coderain/canon_shadow.py` and `soak/canon_gate.py`. **Tests:** `canon_referents_test.py` and
shadow tests 14 and 15.

D-019 refused a claim about anyone the passage does not name, and refused a pronoun as the
subject. That left almost nothing in a story told to "you": "you" is in 973 of 976 narrator
turns of the real save, the protagonist is named in 117, and in a long scene "she" runs for
dozens of turns after the name appeared once. The gate counted 590 refusals for a pronoun, and
every fact about the player (a hoodie, a limp) was refused for naming nobody. player.md says
"Name: ... male", and the character's sheet carries that name among its aliases.

What it does, all in code, never by the Scribe:

- **"you" is the player.** Exact, so it works for every slot. The player is the entity named by
  config `canon.player`, else by the "Name:" line of player.md matched against a whole name or
  alias, else the one character with a capitalised name word in the file; none or two is
  "nobody", never a guess. (Matching every word of the file found a second character through
  "well".)
- **"she" and "he" resolve for STATE facts only.** The nearest earlier sentence that names
  anyone the pronoun could mean decides, if it names exactly one; two is "unclear" and there is no
  widening. It looks back up to 30 sentences, across the last 5 narrator turns. For an identity
  fact the name has to be in the passage, as before.
- **A name the Scribe gives that the passage does not contain** is accepted when the same rule
  agrees from the turns before (state), or when the quote is in the second person and the name
  is the player's.
- **Gender mismatch.** A quote that uses only "her" is not a fact about a man whose gender is known.
  Gender is read from the story (a sentence naming exactly one character and saying her or his; three
  votes and an 80% share), and the player's comes from player.md. The votes live in each turn's row,
  so an undo takes them away with the turn.
- **What does not count as a name for this:** one AFTER a pronoun of that gender in its own sentence
  (the object), one inside quoted speech (a third party), a pronoun inside quoted speech, a line that
  starts with "#" (the scene header), a single word after "the" ("the Guild", "the Lantern Market"), and
  the player.
- **Which turns the Scribe reads:** one that names someone, or says "you" when the player is known, or
  has a pronoun when the turns before name someone. In the real save 923 of 976 turns, now all 976.
- `mentions()` now needs a capital at EACH occurrence ("Rowan" is a character, "the rowan tree" is not).
  8 of 35,218 passages and sentences of the real save came out different, all a lowercase common word.
- **Decision.via** records how a subject was found ("you", "pronoun", "context"), and the shadow report
  and the gate report count them, because they rest on a rule that is not exact.

Measured (hand-read, blind, small samples, my labels, so indicative). Of about 1,900 claim-like sentences
(one gender of pronoun and a slot word), the final rules resolve 29% within 2 sentences and 77% within 30
(only the 30 is used, for state facts); the rest are ambiguous or nobody is named. Precision on the cases
the rule answered: the first sample (60) was 40 right, 10 wrong, 10 unclear, and produced the fixes above.
The second sample came from an intermediate version (49 right, 5 wrong, 6 unclear) and the third from the
version just before the contraction fix (53, 5, 2): together 102 of 112 decided right, 91%. Reach was not
what separated good from bad (near 52 of 58, far 50 of 54). The contraction fix ("She'd") came after the
last sample and is pinned by a test, so the final code has no sample of its own. Genders settled from the
story: 34 women and 3 men of 54 characters (the sheets alone gave 29).

What it costs, and does not do. About 1 resolved attribution in 11 is wrong, which is why identity is
excluded; for state it corrects itself as items are replaced and age out (D-023). The remaining misses
are a faction or an ink that shares a word with a character's alias ("the Guild", "indigo"), a name
absent from the aliases, two people called "the Guild courier", and a listener taken for the
speaker. Alias hygiene is not solved here. This save has few named men, so gender rarely decides
anything in it. The real Scribe has not been re-run through this, so how it phrases second-person claims
("you", the player's name, an alias) is handled both ways but unobserved.

**Rejected, and why:**
- **Telling the Scribe who the scene is about** (a prompt hint). It needs a measured run of the real
  model, and the validator has to check the answer anyway.
- **"Exactly one compatible character named in the last k turns."** Answers 5% to 13% of sentences in
  this save, because several names are always in the window.
- **Gender from the character sheets.** 29 of 54 known, against 37 from the story.
- **Resolving a pronoun for identity facts, or at a short reach.** The two reaches were equally precise.

**Next, because of what was found:** player.md states the protagonist's gender, height, hair and eyes
("black hair, green eyes"), better than anything the Scribe extracted for that character; seeding the
player's identity from it at scenario authority would give the first-write rule a true first write.

**What would change it:** the report's count of `via` facts, checked by hand, being wrong more than 1 in 5;
the real Scribe not naming the player at all in second-person text; or a clean sample where a rule above
refuses most of what it should accept. Fix aliases and data first, then the rule.


## D-025 — The protagonist's own file is the first write for their looks

**Decided:** 2026-11-10. **Code:** `player_facts` and `seed_player` in `canon/replay.py`, called from
`soak/canon_gate.py::run_gate` and `coderain/canon_shadow.py`, and a measurement allowance in
`canon/shape.py` (a number before "tall"). **Tests:** `canon_player_seed_test.py`, gate test 7, shadow
test 16.

In a story told to "you" the Scribe's first sentences about the protagonist were about someone else's
hair, so the protagonist's identity was a string of misfiles (hair "blank", eyes "pale gray", "hazel",
"amber"). The person had already written the truth down: the real player.md says "Name: ...", "Info:
200cm tall, male, black hair, green eyes, ...". D-024 made "you" resolve to the player; this gives the
player a true first write.

What it does. Plain code, no model, reads the file's looks into ledger facts at SCENARIO authority, which
outranks narration: narration can agree with them, and a different narrated value is held back as a
conflict (identity_locked) instead of becoming canon. Each candidate has to pass the same shape rules a
Scribe claim does (D-022), so "black hair" is hair, "200cm tall" is build, "a 25-year-old" is an age, and
"versed in chess", "well read" and "hair stylist" are nothing. At most one value per slot (the first the
file states) and four marks, each as a short phrase ("thin scar over his left eye"). It is safe to repeat:
a value already there is skipped, so is one an author set (an edit outranks the file), and a value the
narration wrote first is replaced once by the higher authority. In the shadow it runs at the turn being
processed, so an undo past it drops the facts and the next pass writes them again.

What it does not do. It is not a parser of free prose: it reads comma and sentence clauses, the adjectives
before "hair" and "eyes", an age ("25 years old", "aged 31"), a height ("200cm tall", 6'2" tall) and a
short list of build words. A description it cannot read seeds nothing, which leaves the situation as it
was. It does not decide gender (that is `player_gender`, D-024).

**What would change it:** a player.md whose looks it misreads on real use. Add the phrase to the tests, then
the pattern; never loosen the shape rule it passes through.


## D-026 — A mark has to name a mark, and eyes have to name a colour

**Decided:** 2026-11-10. **Code:** `_marks`, `_MARK_NOUNS`, `_MARK_ADJECTIVES`, `_MARK_AMBIGUOUS`, `_SITES` and the
eyes colour rule (`_EYE_SHADES`) in `canon/shape.py`. **Tests:** `canon_shape_test.py` 11a, 11b, 12, 9c;
two older suites changed (see the end).

`identity.marks` was the one identity slot with no entry check. The second real-save gate held 87 marks and
54 of them contained no mark word: a way of gripping, a way of speaking, an expression, an object hanging
from a wrist, a bare colour, a pair of eyes, a sentence about something on the skin. A mark never ages off
the Scene State Card, so each would have been shown to the Writer for the rest of the story. Two eye values
were also modifiers, not colours ("cold", "wild").

The rule is a vocabulary, like the others in this file. The value must name a mark: a scar, tattoo,
birthmark, piercing, freckle, ink, sigil, glyph, rune or mandala. An adjective ("scarred", "tattooed") and a
word that is only sometimes a mark ("mark", "brand", "mole", "line", "scale", "burn") count only when a part of
the body is named in the value or in the quote, which is what keeps "bathroom scales", "the brand of whisky"
and "she crossed the line" out. "ink" is in the first group on purpose: a person's ink is a tattoo. Eyes need a
colour or a shade of one (dark, pale, light, deep, milky, icy). The first version asked for a colour only and
refused "dark eyes" and "pale eyes" (8 of its 11 refusals in the real ledger were those); only "cold" and
"wild" were wrong, and the shade list fixes that.

**Measured, and what that does not show.** I labelled the 95 marks records in the gate-2 ledger (73 valid, 22
not) BEFORE writing the rule. The rule keeps 63 of the 73 valid and refuses 21 of the 22 junk; characters
holding at least one junk mark fall from 15 to 1, and one character is left with none of their valid marks.
On the real ledger's 38 distinct (character, eyes value) pairs the eyes rule refuses 2, both the junk ones.
Caveats, all of them real: the labels are mine; I had read all 95 while choosing the vocabulary, so this is a
development number and not a blind test; and the ledger only holds claims that were committed, so what the
Scribe proposed and the validator already refused is not in it, which means the recall cost against all Scribe
proposals is unmeasured.

Known losses. A valid mark that names none of those words is refused: a missing tooth, a puckered patch of
skin, a pattern described without the word for it, and a bare "marks" or "scales" with no body in the quote.
Those characters usually have the same mark restated elsewhere with a body, and the narration keeps
restating, so the cost is a delay more than a loss. Known leaks: a "tan line" passes ('line' plus a body), and
the rule does nothing about two entries for the same mark under different wording or a mark filed under the
wrong person. Those are different defects.

**What would change it:** a real run where valid marks are refused often enough to leave characters with
none (the first thing to add is the word, with a test, not a looser rule), or a story whose marks are not a
body noun at all.

**Two tests encoded the old behaviour and were changed, not the rule.** `soak_gate_test.py` used a streak of
hair colour as a stale mark and now uses a tattoo. `soak_scribe_corpus_test.py` lists a third oracle loss: the
oracle builds each value from the first word a label's pattern matches, one label's pattern matches "raven"
first in "a black raven tattooed on his forearm", and a bare "raven" names no mark. The label stays so earlier
Scribe scores remain comparable.


## D-027 — Canon reaches the Writer through a flag with a preview mode, from a snapshot, and never from a turn that is gone

**Context.** D-021 made the shadow observe-only on purpose and said injecting the card would be a separate
step "taken from what the report shows". The report now shows enough to take it: on the real save the
held-back identity changes fell from 509 to 54 (D-022), outfit lists from a median of 7 to 2 (D-023), and
marks from 54 junk of 87 to 1 of 64 (D-026). It also shows what stays wrong: about one identity value in
twelve, and state lists that still hold the odd non-wound. Putting that in front of the Writer is the first
time canon changes what a story says, so the step is built around how it can go wrong.

**Decision.** `canon: {inject: off | preview | true}`, needing `shadow: true`. It is on only for a literal
`true`; the word `preview` builds and logs the card each turn and sends nothing, and everything else is off.
`card_chars` (600 to 4000, default 2400, about 600 tokens) bounds it, and a literal `inject_state: false`
sends identity only (hair, eyes, build, age, marks) and no clothing, items or injuries. The card is a system
message appended AFTER the player's action and BEFORE the chapter directive, in `_generate_and_store`, so
every way into a turn (turn, continue, swipe, opening) gets it and the chapter goal is still the last thing
read. Being a system message in `messages`, the echo filter also drops a model copying it into its prose.
What it carries: an identity line per character in the scene who has any identity facts, then the Scene
State Card (D-020) for the same people. The scene is the player (pinned), anyone named in the last four
turns, and anyone canon puts in the same place. What each turn did is in `<save>/canon/injections.jsonl`
(counts only) and the last card in full in `<save>/canon/card-last.txt`, marked sent or preview.

**Calls that look heavier than they need to be:**

1. **A snapshot, not the live ledger.** The reader appends to the ledger on its own thread, and a turn must
   never wait for it or read half of a write. After each turn it has read, the reader publishes an immutable
   copy (the frozen records and a hash of each narrator turn read) with one reference assignment, and the
   card is built only from that. `canon/card.py` holds no lock and changes nothing.
2. **The ledger is cut back by content, not by waiting.** After an undo, a retry or a swipe the ledger still
   holds what the discarded reply stated until the reader catches up, which is seconds on a local model. The
   card compares the hash of each narrator turn with the transcript as it is now, cuts the ledger back to
   the turn before the first that differs, and projects only that. A retry (the turn is gone) keeps the
   state, because nothing is unread; an edit of an older turn shows only what came before it, and no state.
3. **State only when nothing is unread.** What someone wears or holds changes every few turns, and the last
   turns ride the prompt verbatim. A card that is one turn behind would say the old coat beside a turn that
   says the new one. Identity does not change, so it is always shown, from the trusted part of the ledger.
4. **A lock that is tried, never waited for.** After a restart nothing is published, so the first card reads
   the snapshot from disk, but only if the reader is not mid-pass. A held lock means no card that turn, and
   the log row says `not_ready`.
5. **Preview before on.** The card repeats whatever canon holds, including a wrong first value, which first
   write wins and which then reaches the Writer as an instruction. About one identity value in twelve was
   wrong on the real save, and one replay of the card at turn 1300 showed an injury list holding a phrase that
   is not a wound. A person should read the cards for their own story first, and `inject_state: false` is the
   cautious second step.

**Measured, and what that does not show.** A replay of the recorded real-save ledger, with no model: the
card the Writer would have been given at eight points (turn 59 to 1639) was 629 to 1273 characters (157 to
318 tokens), took 5 to 7 ms to build, and held 2 to 6 characters. That is size and cost only.

**A first look at the Writer, and what it does not show.** The first session with the local model (the
reader on a copy of the real save, then a Writer test). On the real save's 14,000-token prompts, which still
hold the drifted character sheet and the narrator's own drift, a local 4B Writer was asked to describe a
character in late scenes: seven probes, 8 seeds each, with and without the card from an otherwise identical
prompt. Of the replies that stated a colour, 90% matched canon with the card (37 of 41) and 26% without (7 of
27), and with the card the Writer stated the attribute more often (41 of 56 replies, against 27 of 56). The
drift from the real story reproduced and was stopped: where the sheet and the narrator had written platinum
hair, the Writer said platinum 8 of 8 times without the card and raven 8 of 8 with it. Two results matter
more than the wins. A WRONG value is repeated: one character's hair is never stated in the story, the ledger
held another character's colour (filed under him at turn 34), and with the card the Writer used it every time
it described his hair (2 of 2), where without it it invented a different colour (6 of 6). And the card does
not always win: for a character whose sheet agrees with the card, the Writer still gave another character's
colour in 4 of 8 replies with the card. Caveats: one small local model, not the Writer anyone uses; seven
single-turn probes that ask directly for the attribute, so this measures whether the Writer follows the card
and not whether a long story stays consistent; and the colour scorer is a heuristic, checked against the
printed snippets. The simulated-player soak against the Phase 0 baseline is still what would show the long
run.

**A partial first read locks the wrong values.** The first preview read the last 120 narrator turns of the
real save, and 3 of the 8 identity values it held differed from a full read: first write wins on whatever the
window stated first, which can be a later change or another character's value. The shadow report now says so
whenever the first read was partial. For a story that already exists, `backfill: all` reads it from the
start (about two hours of local model for 976 narrator turns).

**Not known:** whether a story that keeps changing a look on purpose (a dye, a transformation) fights the
card, since an author edit that overrides a held value does not exist yet (the experiment shows the Writer
would follow the card over the story); and how a hosted Writer with a prompt cache behaves (the card sits
after the history, so the cached prefix is untouched, but this has not been run).

**What would change it:** previews that show wrong facts often enough that the first step has to be
correcting them (an author edit that outranks the ledger, which the design already has a place for); a soak
that shows no gain, which means removing it; or a Writer that obeys a card line so literally that stories go
stiff, which would mean fewer fields or a softer header.

**Tests.** `canon_card_test.py` (the builder: coverage, cut-back, state only when caught up, the cast, the
size cap, purity) and `canon_inject_test.py` (the engine: what the model receives, ordering against the
chapter directive, preview sends nothing, a held lock, a restart, a card builder that explodes, a retry, an
edit, `inject` without the shadow, the echo filter). 24 guard mutations are caught. The mutation pass found
two gaps in the size-cap test, which never made a footer land against the cap, and closed them.


## D-028 — The author can say what is true and what is false about a character, and it outranks the story

**Context.** First write wins (D-017), so a wrong first value is permanent: it is defended against the right
ones. Once the card is injected (D-027) the Writer repeats it, and the first Writer test showed both halves: a
wrong value (another character's colour, filed under a man whose hair the story never states) was used every
time he was described, and the card did not always beat the context. D-023 to D-026 stop most wrong values at
the door, about one in twelve still gets through, and nothing let a person fix one.

**Decision.** `<save>/corrections.md`, a Markdown file a person can read and edit, which travels with an
export and is never inside `canon/`. Each correction is a bullet, `- Name: slot = value` (the author's value)
or `- Name: slot is not value` (that value is wrong), for hair, eyes, build, age and marks. Anything that is
not a bullet is a note and is ignored; a bullet that does not parse is reported with its line and never
dropped. A name is a character's name, alias or id, matched exactly and never guessed. Three effects:

1. `=` is written into the ledger as an author-level `author_edit`, which crosses the identity lock on purpose
   and outranks narration, so a later different narrated value is held back as a conflict.
2. `is not` RETRACTS the value if it is held (a new ledger capability, below) and the validator REFUSES it
   when the Scribe proposes it again (`author_refused`), for that character and slot only.
3. The card applies the corrections to its own projection, so the Writer is right on the very next turn.

Routes: `GET /api/saves/{slug}/canon` (what canon holds, with the corrections applied, whose word each value
is, the file, the lines that could not be applied), `PUT .../canon/corrections` (replace the file) and
`POST .../canon/corrections` (add one). The Canon panel in the play screen (`webapp/js/canon.js`) is a thin
client over these routes: a held value with Wrong and Change buttons, a form for a fact, the list of corrections
with Remove, the file itself, and the last card. Every button changes the one file, so the panel and a hand edit
are the same thing.

**Calls that look heavier than they need to be:**

1. **A file, not a ledger record.** The ledger is derived and is rebuilt or rolled back from the transcript; a
   correction is derived from nothing. Kept only as ledger records, an undo past it or a rebuild would lose
   it. The file is the truth and the ledger holds its effect.
2. **`plan` remembers nothing.** It compares the corrections with the canon it is given and returns only the
   records still needed, which is none once it is in line. That is what makes it safe to run at the start of
   every pass, after every turn and on a throwaway projection for a card, and why an undo cannot lose a
   correction: the next pass writes it again.
3. **A retraction, not a replacement.** The author often does not know the right value, only that this one is
   wrong. An `author_edit` or `retcon` with no value now retracts an identity fact (the ledger refused this,
   and state already had `state_cleared`): it closes the value and opens nothing, history is kept, and the
   story may then establish the real one. It is refused on a state slot and for ordinary narration.
4. **A refusal as well as a retraction.** A retraction alone ping-pongs: the Scribe re-proposes the same wrong
   value on the next turn that mentions it, the slot is empty, and it locks again.
5. **The card applies the corrections itself.** Between an edit and the reader's next pass, and right after an
   undo cuts off the records that carried them, the ledger does not have them. The card must not wait.
6. **Matching is generous on purpose.** `same_value` treats "black" as "raven" and one wording that contains
   another as the same. On the real ledger one "is not" line for a mark retracted two near-duplicates of it,
   which is wanted. The risk is the other direction: "is not raven" also refuses a narrated "black". The
   author's own `=` value is never refused.
7. **Removing a line releases what it set.** The file is the truth, so a value the file wrote and no line asks
   for any more is retracted at the next pass, and the card drops it at once. Without this the panel's Remove
   button would leave the ledger holding the author's value as "yours" next to no correction, locked for good.
   What counts as "this file's own value" is the provenance on the record (author authority and the span
   `corrections.md`), so an author edit that arrived any other way, and everything the story set, is never
   released. Changing a value is a replacement, not a release plus a write. A retraction made by a `is not` line
   is NOT undone when the line is removed: the ledger no longer holds the old value, so removing the line only
   means the story may say it again. An EMPTY file is applied like any other (the reader and the card used to
   skip an empty list, which would have made the last Remove do nothing). A name that matches nobody shields no
   one, so a line about a character who has not appeared yet does not hold up another line's release; a name
   that now matches two characters shields both, because it may be the line that set their value and a value
   must not be wiped by a guess.

**Measured, and what that does not show.** On the recorded real-save ledger (1,295 records) planning four
corrections took 0.2 ms and wrote three records; the two corrections that were already true needed nothing,
and a second plan on the corrected canon was empty. At the scene where the Writer repeated the wrong hair,
the card's line for that character no longer carries it. That is the card, not the Writer: no model was run
after this change, so the Writer's behaviour with the value gone (which should be the no-card baseline for
that slot) is expected and not measured.

**Writer re-test (2026-11-11), the model run that paragraph says was missing.** A copy of a real 976-turn save
with the ledger from a full `backfill: all` read; local gemma3:4b as the Writer; the real engine builds the
prompt, so the card and the corrections overlay are the shipped code. Five probes at late scenes, 8 seeds each,
the identical prompt sent with and without the card: three where the author sets a colour the story never said
(two of them against a value the story repeated more than twenty times), one "is not" retraction, one control with
no correction. When the Writer named a colour at all, with the card 11 of 12 were the author's value; without the
card 0 of 6 were, and the old story value was never repeated with the card. The retraction probe cannot tell the
card from the baseline: the Writer did not say the removed value in that scene without the card either, so all it
shows is that a retracted value stays out of the reply. Two things did not change. The Writer named a colour in
only 1 to 6 of 8 replies even when asked to describe the feature (so a card can only correct what is said), and a
colour the transcript itself repeats a lot still beat a correct card line in the control (the card agreed with the
story there, and the Writer kept its habitual wrong colour in 2 of 3 replies that named one). The first scorer glued
words across em dashes and under-counted colours the Writer did state; it was fixed and the stored replies were
rescored. Small n, one 4B Writer, a heuristic scorer, direct-ask probes.

**Not done:** state corrections (what someone wears is the story's to say); a way to protect a correction from a
rebuild that renames a character, since the file names people; and a way to ask "restore what the story said
before my correction" (the ledger keeps the history, but nothing brings a retracted value back).

**What would change it:** corrections that people write and then keep contradicting (the format is too hard),
a refusal that blocks a true value often enough to need exact matching, or a story whose looks change on
purpose often enough that the author wants a correction that ends at a turn.

**Tests.** `canon_corrections_test.py` (the file, the plan, idempotence, authority, refusal, the card, release),
`canon_ledger_test.py` 6b (retraction), `canon_shadow_test.py` 18 (the reader: outranking, refusal from the
first turn, a hand edit, an undo, a late character, the view), 19 (the last line removed) and 20 (a `canon:`
block survives the real config file and the Settings rewrite: the first sandbox found the reader silently off
because a config whose active profile could not be built falls back to the shipped defaults, which have no
`canon:` key, and no test had ever gone through the file), `canon_inject_test.py` 9 (the next turn, and after an
undo) and `canon_api_test.py` (the routes, every refused input, export). 43 guard mutations are caught; the
passes found two gaps (a duplicated line and the author's own values in the refusal list) that no test could
see, and closed them.

## D-029 — The first long soak: one name is one entry, the author's sheets are the first write, and the card reads as phrases

**Context.** Everything before this was measured on single turns or on a real save replayed through the reader.
Nothing had played a story forward with the card on. The soak harness (an invented ferry-town story, six
characters with a stated hair and eye colour in their sheets, a scripted player, the real engine, a local
gemma3:4b Writer, memory squeezed to four verbatim turns and a 5,000-token budget so that almost everything older
than a few turns can only come from memory) played 240 turns with canon off and 240 with the card sent, on the same
player script. The card did not help: after copied card syntax was removed from the replies, the colour the Writer
named matched the sheet in 4 of 20 probes with the card against 7 of 19 without, and both fell to about zero after
turn 120. The run found three defects, and two of them have nothing to do with the card.

1. **The card's own syntax was copied into the story.** With `hair: black; eyes: dark` lines in the card the
   Writer wrote that syntax into its prose in 183 of 240 turns, from turn 39, and a copied line in the history makes
   the next copy likelier. Canon off: 0 of 240. Every card-side colour statistic was contaminated by it.
2. **The fold made a second entry for the same person.** The fold trusted the `slug` the lore-keeper model wrote and
   deduped by slug alone. A small local model does not reuse the slug it was shown, so it wrote `bram-halloran-4` and
   `bram-halloran-bram-halloran` for the existing `bram-halloran`. characters.md grew from 6 sections to 16 with
   the card on and to 18 with it off, the canon ledger from 6 characters to 15, and a name that two entries answer to
   resolves to neither: 1,452 claims were refused and only five characters ended with any identity. Aliases also
   piled up by case variants and run-ons ("corwin the mudlark corwin corwin the mudlark corwin ...") to lines of 400+
   characters. This is the "three entries for one woman" seen in the real save, and it happens without canon.
3. **The ledger did not know the sheets the author wrote.** A sheet said green eyes, the Writer's first narration said
   dark, first write wins, and the card then told the Writer "dark" for the rest of the story.

**Decisions.**

- *Identity is rendered as phrases, not labels* (`canon/scene.py` `_identity_phrase`): "black hair; dark eyes", not
  "hair: black; eyes: dark". Same story, 80 turns: 0 turns with copied label syntax against 33 with labels. A phrase the
  Writer copies still reads as prose. A value that already names the feature ("blue eyes", "dark-haired") is not
  given the word twice, and one that is only punctuation says nothing.
- *One name is one entry* (`coderain/summarizer.py` `_existing_slug`, `coderain/memory.py` `name_key`). A slug that
  exists is used as written. Otherwise the title is looked up in the entity registries (characters, locations,
  factions, items): the same name (case, punctuation and a leading "the" ignored) as an existing title wins,
  preferring the entry made under that name's own slug. Only the whole title matches ("Tamsin Pike" is not "Tamsin
  Reeve"), and a title that is merely listed as another entry's alias does not (the first version of this had that
  rule, and D-030's dry run showed why it is wrong: small models write wrong aliases). A doubtful match makes a
  new entry, because a duplicate can be merged later and a wrong merge cannot be undone. Threads and canon events are
  left alone (two events can share a title). The merge is reported in the fold's events.
- *Aliases are cleaned* (`usable_alias`, `MAX_ALIASES` 12, `MAX_ALIAS_WORDS` 5): a repeat by name, a run-on, and one
  that says a content word twice are refused; the union keeps what an entry already has and stops at the cap, so
  an old long list stops growing and is not cut.
- *Authored sheets seed canon* (`canon/replay.py` `sheet_looks`, `seed_sheets`; the reader's `fresh` flag): the text after
  a sheet's `**Visual:**` label is read like the player's file (D-025) and written at scenario authority, so a narrated
  value that differs is held back. Only when the reader first met the story with at most three narrator turns
  (`AUTHORED_UNTIL`), and only for sheets that exist in those turns. On a story already under way the sheets
  were folded out of the narration and may have drifted, and seeding them as authored would lock the drift in; a
  character who appears later, and a sheet with no Visual label, are never seeded. "grey eyes and raven hair" now gives
  raven (it gave "and raven").

**Result of the final pair (all three fixes in, same story, same player script, 240 turns each, local gemma3:4b).**
On the direct probes (the player studies one character's hair or eyes every eighth turn; scored against the colour in
the character's starting sheet, counting only replies that name a colour), the card-on run named the sheet's colour in
24 of 25 replies (96%; 12 of 13 after turn 120) and the card-off run in 3 of 15 (20%; 0 of 7 after turn 120). The
card-off run also named no colour at all in 15 of 30 probes, against 5 of 30 with the card. Before the fixes the same
comparison was 4 of 20 with the card and 7 of 19 without. The phrase format alone (80 turns, old fold, no seeding) was
0 of 7, so the format removed the copying but not the drift: the ledger had to hold the right values, which is what
the fold fix and the sheet seeding did. Which of those two matters more was not separated. The card-off run with the
fold fix is still at 3 of 15, so the fold fix alone does not keep the looks.

What this does not show. The truth being tested is the author's own sheet, seeded into the ledger by construction, so
this measures that the card carries a known-right value to the Writer over 240 turns of squeezed memory (four verbatim
turns), not that the Scribe extracts the truth from narration. One local 4B model, one invented story, one player
script, a heuristic colour scorer, direct-ask probes. The 820 "incidental" statements in the card-on run are not
independent evidence: they are inflated by the Writer restating the card.

A cost the numbers show. With the card the Writer names a hair or eye colour in 3.8 sentences a turn (0.4 without) and
a turn shares 30% of its 8-word runs with the previous turn on average (9% without). The prose still reads as a
story and the colours match the sheet, but it restates identity far more often than a person would. Not addressed: a
card that asks the Writer to mention a look only when it matters, or lists identity once per scene, is the obvious
thing to try, and it must be tested for the repetition, not for the colours.

**Not done.** Existing duplicate entries are not merged (only new ones are prevented): that is the offline sweep of
the original plan, and it needs its own care because a merge cannot be undone. The Writer's narration length grew
from about 270 to about 1,340 words a turn over 240 turns with canon off, a small-model effect of the engine's
own history that this did not touch. No test of the three fixes against a hosted model.

**What would change it.** A sheet format other than `**Visual:**` that authors really use (the label is the guard
against reading looks out of prose); a second character with the same whole name (the merge would join them, and
the fix is an alias or a title qualifier by the author); a phrase format that the Writer copies badly in a model the
labels did not trouble.

**Tests.** `fold_entity_resolution_test.py` (12 assertions; 17 guard mutations caught), `canon_sheet_seed_test.py` and
`canon_shadow_test.py` 21-22 (13 mutations caught, two gaps found and closed: an agreeing narrated value, and a
character who appears after the first turns), `canon_scene_test.py` 11 (7 mutations caught; its first version had a
stray backspace character in the regex and would have passed whatever the card said). The four suites that pinned
the old label format were changed with the reasoning above. Full suite: 117 pass.

## D-030 — Duplicate entries that already exist are merged by an explicit, backed-up command, on whole names only

**Context.** D-029 stopped the fold from making new duplicates, but a save played through a small local model before
that already holds them: in an invented soak story `characters.md` had 18 sections for 6 characters plus the
player and a few invented people, and every sheet is sent to the model again each turn. The canon reader makes one
entity per section, so the duplicates also split what the story says about a person across entities that answer
to the same name.

**Decision.** `python -m coderain.dedupe --home <CODERAIN_HOME> --save <slug>` prints what would merge and why and writes
nothing; `--apply` copies each registry it will change into `<save>/.dedupe-backup/<time>/` first (restoring is a file
copy), then merges. `--home` is required with no default, so a live install is never touched by accident.

- Only entries with the same whole name are one entity (case, punctuation and a leading "the" ignored). **A title that
  is only listed as another entry's alias is not a match**, and the same rule now holds in the fold (`_existing_slug`).
  I first wrote an alias rule ("exactly one entry has it") and the first dry run on a soak save showed what it does: a
  small model had written one character's name into another's alias list, and the rule would have folded the second
  character into the first, an error a duplicate never is. A duplicate can be merged later; a wrong merge needs the backup.
- The entry made under its own slug stays, else the oldest. The merged entry unions the aliases (the kept entry's own
  included, cleaned and capped at 12: on the soak save they were lines of 2,000 to 6,000 characters of repeats), takes the
  highest importance, the newest status, wants and relationships, and adds the paragraphs of the others it does not already
  say, newest first, up to the fold's own body limit.
- Never touched: the player's sheet, threads and canon events, anything outside the registries. Scene summaries and the arc
  keep their `[[character:old-slug]]` links (the report counts them, the engine already tolerates a link that points
  nowhere), and the canon ledger is derived: delete `<save>/canon/` to rebuild it.

**Measured.** On a copy of the soak save: 18 entries became 10, the six real duplicates merged and nothing else, and a second
run reported nothing to merge. Not run on his real story.

**Not done.** Rewriting the `[[links]]` in folded memory (that is fold output, and a rename of a slug there is one more thing
that cannot be undone without the backup); a button in the app; a merge of one character under two different names
("Dame Quill" and "Quill"): that needs a person's judgement and is exactly what a name rule must not guess.

**Tests.** `dedupe_test.py` (4 numbered assertions; 15 guard mutations caught, and it found a real bug on the way: two
applies in the same second shared a backup folder).

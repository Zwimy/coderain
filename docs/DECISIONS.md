# Decisions

Design calls that are deliberate, so nobody (human or agent) "fixes" them back.
Each entry says what was decided, what the tempting alternative is, and what
evidence would change the answer.

## Index: the problems that keep coming back

Read the group before trying a fix again, and add each new entry to its group. A result holds for the model named, until it is
measured on another (D-081).

**A character says a secret they were never told**
- The probe that scores it: D-058. Gemma 4 E4B said a secret more freely than gemma3:4b (3 of 10 against 0 of 10, D-071).
- Facts switches, Gemma 4 E4B: over two measurements 6 of 20 off against 9 of 20 on (D-073). On by default anyway, the owner's
  call, with the writer rule as the only guard for a fact told in the story (D-078).
- Story search can quote a secret to someone never told it; 3 against 4 of 10 on its first form. Off (D-075).

**Ties, who carries what, and two-step questions answered wrongly**
- With the facts in the prompt the wrong answers are the Writer not using them, not retrieval (D-058 as corrected by D-059; D-071).
- Follow links on gemma3:4b: found the evidence on one seed of two, never shown to make answers more often right (D-061).
- The ties line alone on gemma3:4b: no effect (D-067). llama3.1:8b was the most faithful, several times slower (D-061).
- Both switches together, Gemma 4 E4B: clearly better in both measurements (D-073); drawn and followed both ways since D-074.

**Replies grow and copy the reply before them**
- Fate lengthened gemma3:4b's replies, and two of four steered runs fell into a loop (D-055).
- The tic guard did not help and hurt the answers, gemma3:4b (D-064, D-067). Off.
- A reply cap leaves the copying (D-070). It was gemma3:4b's; Gemma 4 E4B did not copy in runs of up to 300 turns (D-070, D-071).
- Open on gemma3:4b: nothing built stops it (D-069).

**A character's looks drift**
- The canon card did not help in its first long soak (D-029); after the fixes between (D-022 to D-041 and others), 111 of 119 named
  colours were right with it against 11 of 63 without, 1,000 turns, gemma3:4b, looks stated by the author (D-069). It also helped
  Gemma 4 E4B (D-071). It has much less to carry when the story must supply the looks (D-034).

**Model output the app cannot use, or shows when it should not**
- A reader that thinks, or replies with nothing: asked not to reason; an empty reply is a failure (D-040).
- Fate's answers were often unusable before its fixes (D-053). Strict JSON for hosted models (D-076).
- The status block's label reached the reader in most small-model replies for months; no probe read the shown text (D-080).
- The model check now asks every model for the block, the memory summary, the chapter plan and the planning step (D-079, D-081).

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

## D-031 — The card shows a look only when it matters, because offering every look every turn makes the Writer restate them

**Context.** D-029's final pair showed the card keeping the colours right (24 of 25 against 3 of 15 without it) and
a cost: with the card the Writer named a hair or eye colour in 3.5 sentences a turn (0.3 without) and 27% of the
wording of a turn repeated the previous turn's (2% without) over the first 120 turns. Of the wording repeated from one
turn to the next, 64% sat in look sentences with the card, 5% without. The card was telling the Writer every look
of everyone in the scene on every turn, and a 4B Writer treats what it is shown last as something to say.

**What did not work.** Leaving out a look the recent turns already state for that character (`identity_seen`, since
removed) cut it only to 2.8 look sentences a turn and 22% repeated wording; the skip fired on 2.7 fields a turn and the Writer
kept restating from its own history. Rewording the headers to "reference only, do not restate" made it worse, on the
same real prompt, 10 seeds, 3 scenes: 3.7 look sentences a reply against 2.9 for the shipped wording and 1.4 with no
card at all (the history of that save was already primed by the card runs). Telling a small model not to say a thing
puts the thing in front of it.

**Decision.** `canon/scene.py` `identity_needed`: a character's identity fields go in the card only when one of
three things holds. (1) They are not named anywhere in the verbatim turns the prompt carries nor in the player's
action: the Writer has nothing recent about them, which is what the card is for. (2) The player's action names them and
asks about looks (a hair or eye word, "study", "describe", "face", a mark): the card is the answer to the question.
(3) The recent turns state a different colour for them in a sentence that names that character and nobody else
(`same_value` decides, so "black" is "raven"): drift in the context is corrected where it is read. Otherwise the
look is left out, and `Card.hidden` counts the fields left out in the injection log. The engine passes the card the
verbatim turns and the player's input. `canon: {identity: always}` restores the old behaviour; `needed` is the default.
State lines (outfit, held items, mood, place) are unchanged.

**Measured** (the same invented story and player script, 120 turns, local gemma3:4b, all fixes in):

| card | look sentences / turn | repeated wording | direct-ask colour right |
|---|---|---|---|
| off | 0.3 | 2% | 3 of 15 (240 turns) |
| every look, every turn | 3.5 | 27% | 24 of 25 (240 turns) |
| skip what the turns already state | 2.8 | 22% | 15 of 15 |
| only when it matters | 1.0 | 18% | 14 of 14 |

The card averaged 484 characters instead of 869. **The cost:** colours the Writer volunteers (not asked for) were right 43
of 56 times (77%), against 97% when every look was in front of it, because a look that is not offered cannot correct a
first drifted mention; the card corrects it the turn after (3). The number of contradicted statements is about
the same (14 against 19 in the first 120 turns, 5 with the card off), so a reader meets about as many, and many fewer
look sentences. All but one of the 121 cards left out 5 or more identity fields (a mean of 10 a turn).

**Not done.** The repetition is not gone (1.0 against 0.3, 18% against 2%): half of that is the Writer's own history
teaching itself (a save primed by the card runs gave 1.4 look sentences a reply with no card at all). Whether a card
placed earlier in the prompt (less salient, less binding) keeps the colours with less repetition was not tested. State
lines have their own near-duplicates ("spectacles, glasses, spectacles and glasses") and were not touched. One 4B model,
one story, one script.

**What would change it.** A hosted model that does not restate (the card would then lose nothing by listing every
look: `identity: always`); volunteered colours that need to be right more than the prose needs to be varied.

**Tests.** `canon_scene_test.py` 12 (what shows and what does not, drift attribution), `canon_card_test.py` 9,
`canon_inject_test.py` 10 (the engine passes the window and the action; the setting). 21 guard mutations are caught.

## D-032 — The author can give characters strengths, weaknesses, a personality type and goals, in the Plan panel

**Context.** The Plan panel steers a story by chapters, but nothing in it said who the people are. A character's sheet
carried what the memory had folded out of the story (`status`, `wants`, `motivation`, a body of prose), all of it
rewritten as the story moves, so an author who wanted a character to be good with a knife, afraid of deep water, a
stoic, and set on clearing her brother's name could only hope the fold kept it.

**Decision.** Four author-owned fields per character: `strengths`, `weaknesses`, `personality` (a type or a few
words: ISTJ, Enneagram 6, "a stoic who keeps promises") and `goals`. They are header lines of the character's entry
in `characters.md`, or of the protagonist's sheet in `player.md`, so Markdown stays the source of truth and a hand
edit is the same thing as the screen (`coderain/cast.py`). Limits: 300 characters each, 80 for the personality type,
one line, refused (not cut) when over.

- **The Writer reads them** in the sheet it is already given when the character is in play (the protagonist always),
  and the Writer's rules gained a "Character traits" section on how to use them: a strength decides a scene when it
  matters, a weakness costs something real, behaviour follows the personality, a goal pulls the character even when
  the player never raises it. Written positively on purpose (D-031: telling a small model not to say a thing puts
  the thing in front of it). The rules are version 11, and the previous default's hash is registered so an install that
  never edited its rules is upgraded.
- **The chapter planner reads them** (`CHARACTERS` before the chapters in every planning payload, up to 2,400
  characters with a visible count of anyone left out, and nothing at all when nobody has any), so a plan can lean on a
  weakness or move toward a goal.
- **The memory fold keeps them.** It rewrites `status`, `when` and `relationships` and re-attaches `wants` and
  `motivation`; every other header line survives a rewrite, and a duplicate merge (D-029, D-030) keeps them too.
- **`goals` is not `wants`.** `wants` and `motivation` are live and the fold rewrites them as the story moves; the screen
  shows them beside each character for reference and does not edit them. `goals` stays until the author changes it.
- The Plan panel has a "Characters…" button: a filterable list (the protagonist first, then by importance), each
  character expandable into the four fields with a Save button, S W P G letters marking what is set. Routes:
  `GET /api/saves/{slug}/cast` and `PUT /api/saves/{slug}/cast/{key}` (`player` for the protagonist), 404 for an unknown
  character, 400 for a bad field or value, nothing written on a refusal.

**The generator** that writes a new character from a prompt asks for the four fields too and writes them, cut to the limit at
a word boundary rather than refused (`cast.fit`: a character with a slightly long strength beats none; non-text is nothing).

**Not done.** Nothing checks that the prose honours them: they steer the Writer and the plan, they are not a rule the
validator enforces. Not measured with a model: whether a 4B Writer shows a weakness or a goal more often with these lines
than without; the lines are one more thing in a sheet that is sent every turn the character is in play, so a long set of
them has a cost the limits only bound.

**What would change it.** A cast large enough that the planner block is cut so often it misleads (then rank characters
by who is in the story now rather than by importance); an author who wants traits that change over the story (they would
use `wants`, or edit the field).

**Tests.** `cast_test.py` (8 assertions: set, clear and leave the rest alone, every refusal writes nothing, the fold keeps
them, the planner is told and capped, the API, the rules and their migration, and the traits reaching the Writer's
prompt); 18 guard mutations caught, and one that is equivalent (an empty value left on the entry is not written, so the file is
identical). The screen was checked in a browser on an invented story with no model reachable, at desktop and phone width,
including the save, Back and Close.

## D-033 — A new list item that says everything several old ones say replaces them

**Context.** The same 240-turn soak that showed the card's repetition (D-031) showed what the card's state lines look like
by the end: `holding rope, rag, rope and rag, worn rope and rag` and `wearing spectacles, glasses, spectacles and glasses`.
D-023's repeat rule treats a claim as the same item only when exactly ONE existing item matches (all its words inside
the claim or the claim's inside it). Once the list holds "rope" and "rag", "rope and rag" matches two, so it was appended,
"worn rope and rag" matched three and was appended too. The list then fills toward its cap with one object said four ways,
the card spends its budget on it, and the Writer is shown the same thing four times.

**Decision.** In `canon/validate.py` `_absorbed`: when no single item is the one a claim refers to, every existing item whose
words are ALL inside the claim (and the claim has more) is dropped and the claim is added: "rope and rag" replaces "rope"
and "rag", "worn rope and rag" then replaces that, "sword and shield" replaces "sword" and "shield" and leaves a lantern.
Whole words only: "rope and chain" shares "rope" with "worn rope and rag" and is not made of it, so both stay. The
outfit's replace-by-kind rule (D-023) runs after it. It applies to outfit, held items and injuries.

**What it does not do.** Two words for one thing ("spectacles", "glasses") are still two items until a phrase joins them.
A claim that is a part of several different items ("coil" inside "coil of rope" and "coil of chain") is still appended, because
which one it means is a guess.

**Tests.** `canon_state_lists_test.py` 3b (held and outfit); 5 guard mutations are caught. Not run against a model; the
effect on the soak card is not measured.

## D-034 — When the truth has to come from the story, the card has little to carry, because the reader captures few looks

**Context.** Every soak so far gave the card a known-right value: the sheet's looks were seeded into the ledger (D-029).
Most real stories start the other way: the cast is named and nobody's looks are written down, so the truth is whatever
the story first says, and the only thing that can put it in the ledger is the reader (a local model reading each turn).
The same invented story and player script, `--sheets role` (each sheet says who the person is and nothing about how they
look), 160 turns, local gemma3:4b, memory squeezed as before, card off against the card sent (`identity: needed`, D-031).
Scored against the story itself: the first colour the story gives a character's hair or eyes is that character's truth for
the run, and every later statement is checked against it.

**Result.**

| | card off | card on |
|---|---|---|
| looks the story established (of 12) | 7 | 9 |
| later statements that agree with the first | 42 of 48 (87%) | 23 of 25 (92%) |
| direct probes: agree / contradict | 6 / 0 | 3 / 2 |
| look sentences per turn, repeated wording | 0.8, 32% | 0.3, 31% |
| words per turn | 778 | 398 |

No gain you could call measured: 92% against 87% on 25 and 48 statements, and the direct probes lean the other way (3 agree and 2
contradict with the card, 6 and 0 without).
The narration with the card off grew to about 780 words a turn over 160 turns (about 1,340 by turn 200 in the earlier
240-turn run), against about 400 with the card. That is not a canon effect: the soak's `response_length: medium` adds no length
instruction to the prompt (only `short` and `long` do), and the cap a prose call gets is the configured max_tokens plus 3,000
tokens of headroom for a reasoning model (`config.prose_tokens`), so for a model that is not reasoning there is effectively no cap
and a small model's turn length feeds on its own history. Why the card-on run stayed near 400 is not explained. Choosing
`short` in Settings is the existing way to hold the length down.

**Why the card had little to say.** The reader's ledger held a value for 3 of the 9 looks the story established (2 agree
with the story's first colour, one words it differently). Its report: 3 of 7 characters with any identity fact, 1,076 claims
proposed, 541 rejected (two fifths as "restated", the rest mostly a garment or object the slot refuses, a value not in the
quoted evidence, or a hypothetical). Of the 9 looks, 5 were stated in a sentence that names no one (a reply to the player
studying someone, written with "her" or "his"): by design the reader never attributes identity through a pronoun (D-024),
because identity is first write wins and a wrong attribution is permanent. The other 4 named the character, and the reader
took 2 of them. With so little in the ledger the card averaged 410 characters, mostly state lines, and hid 0.9 fields a turn.

**What this means.** The card is only as good as the reader behind it. When the author states the looks, the card carries them
(D-029: 24 of 25). When the story does, a 4B reader captures about a third, and the card can neither add nor correct much.
The fix is on the reading side, and it is a trade the earlier work chose the other way on purpose.

**Not done, and how I would try it.** (1) Let a look sentence be attributed to a character through "he" or "she" when the
sentence just before it names exactly one character of that gender, and the reply follows a player action that names them:
measure how often that is wrong on a labelled sample BEFORE writing anything, because a wrong first identity is the failure
that D-022 to D-024 exist to stop. (2) Ask the Scribe about one character at a time when the player's action names one.
(3) A larger local Scribe (llama3.1:8b did better on recall in D-019). One 4B model, one story, one script, 25 statements.

**Tooling.** The soak harness and scorer used here live outside the repo (scratchpad); nothing in this entry needs code.

## D-035 — A look said with "he" or "she" can be read for the character the nearest sentences name, behind a switch that is off

**Context.** D-034 found the reader captured 3 of the 9 looks a narration-first story established, and that 5 of the 9 were
stated with a pronoun or in reply to a probe, which the reader refuses by design (D-024: identity is first write wins and
permanent, and the nearest-name rule was right about 9 in 10 on hand-read samples, one wrong lock in ten being too many).
D-034 said to measure before changing anything.

**Measured** (no model; every probe reply in every soak run). On a probe turn the player studies one character, so a
hair or eye sentence of the reply that names no one is about that character unless the reply is describing someone else.
Over those sentences that use a gendered pronoun, with the existing rule and a reach of 2 sentences: excluding the one run whose
replies were full of copied card syntax, 64 sentences, the rule answered 36 times (56%) and was right 34 of them (94%); of the
two it missed, both look like replies that describe a second woman, so the true error may be lower. With the contaminated run
in, 84 answers and 57% right, which shows what a degenerate reply does to the rule and is not representative. A 94% rate on 36
cases has a wide interval (roughly 82 to 99%), and it matches the 9-in-10 of the hand-read state samples.

**Decision.** `canon: {identity_via_pronoun: true}` (a literal true, default false, so D-024 stands unless the author turns it
on) gives the reader a reach of 2 sentences for an IDENTITY fact: `Who.identity_reach`, `Who.reach(slot)` (state facts keep
their 30), `make_who`, `passage_who`, the shadow's setting. The rest is unchanged: exactly one compatible character in the
nearest sentence that names anyone, none or two is "unclear", a quote about a woman is refused for a man, a pronoun in
speech and a name after the pronoun do not count, first write still wins and an author's correction (D-028) still outranks.
Why a switch and not a change: the trade is wrong locks (about one in twenty or fewer, by this measure) against capture (a
nameless look sentence is about half of what a narration-first story offers), and a wrong first look is permanent until the
author corrects it, so it is the author's call, not mine.

**Not done.** A requirement that a pronoun-sourced look be seen twice before it is committed was considered and not built: a
story states a look about once (0.3 to 0.8 look sentences a turn here), so most would never commit. The ledger does not record
that a value came through a pronoun (the report counts them), so the Canon panel cannot flag them yet.

**Tests.** `canon_referents_test.py` 9c (off by default, on with a reach, two candidates, too far back, a man's quote, the
context route, first write still wins), `canon_shadow_test.py` 1 and 23 (the setting, and a look said with "she" reaching the
ledger only when on); 11 guard mutations are caught and one is equivalent (the default constant is overwritten from the
config).

**On a model run** (the narration-first story of D-034, same script, card on, `identity_via_pronoun: true`, 160 turns, local
gemma3:4b). The story is a different realisation each run (this one stated only 6 of the 12 looks, against 9 and 7 before), so
this is not a controlled comparison and the numbers are small. The reader's ledger held 4 of the 6 looks the story established
(66%, against 3 of 9, 33%, with the switch off): 3 agree with the story's first colour, 1 does not; it held identity facts for 5
characters instead of 3, and 3 values my scorer did not see stated. The 19 identity records quote "her thick, grey hair", "his
dark eyes", "her silver-streaked hair" and the like: the pronoun path was used and every attribution I could check from the
quote and the cast is plausible. The one value that disagrees with the story's first colour is a character's eyes that the
story gave as ashen (a probe reply, not read by the reader), then dark, then grey: the ledger wrote the first one it read
(dark) and held the later "grey" back as a contradiction, which is the story being inconsistent with itself and the reader
missing the first mention, not a wrong pronoun. No wrong attribution through a pronoun was found in this run; with 19 records
that says little about a one-in-twenty rate.

**Correction (D-036).** The comparison above is across two different stories, so the rise in capture cannot be credited to the
switch. On one fixed transcript the switch changed nothing for gemma3:4b and cost llama3.1:8b one value: the benefit is not
shown, only the 94% accuracy of the rule.

**What I would do.** Leave the default off until it has run on a real story with the Canon panel open, because a wrong first
look is the cost and the panel is where it would be caught and corrected. It is a one-line config change for the author who wants
more of the story's looks captured.

## D-036 — On a fixed transcript a larger local reader is more precise, and the pronoun switch changes almost nothing

**Context.** D-034 and D-035 compared readers across different soak runs, and the story is a different realisation each run (the
Writer is a sampled 4B model), so the capture figures were never comparable: one run stated 9 of 12 looks, another 6, another 7.
This takes one transcript and changes only the reader. The transcript is the card-off no-sheets story of D-034: 161 narrator
turns, nobody's looks written down, so the truth is the first colour the story gives each character's hair or eyes (my scorer,
7 of 12 looks stated). Each reader reads a fresh copy of the save, backfill all, through the real reader and validator, and the
ledger is compared with the story.

| reader | pronoun switch | captured of 7 | agree with the story's first colour | differ | identity records | minutes |
|---|---|---|---|---|---|---|
| gemma3:4b | off | 5 | 3 | 2 | 17 | 46.8 |
| gemma3:4b | on | 5 | 3 | 2 | 17 | 49.3 |
| llama3.1:8b | off | 5 | 5 | 0 | 29 | 30.1 |
| llama3.1:8b | on | 5 | 4 | 1 | 29 | 29.1 |

**What it shows.**
- **The larger reader is more precise, not better at recall.** Both capture 5 of 7. gemma3:4b's two disagreements are a hairstyle
  phrase filed as a hair value ("intricately braided hair", which the shape rule accepts as a description of hair) and an eye colour
  that is not the story's first; llama3.1:8b has none. It wrote 29 identity records against 17 (marks, ages and repeats included),
  and it was faster here (30 minutes against 47 to 49).
- **The pronoun switch did nothing on this transcript for gemma3:4b** (the same 17 records, the same values) and cost llama3.1:8b one
  value that disagrees with the story's first colour (a character's eyes written "dark" where the story first said ashen; the story
  states it inconsistently, so it may be the story and not the pronoun). **This corrects D-035:** the rise from 3 of 9 looks to 4 of 6
  between two soak runs was a different story, not the switch. The 94% accuracy of the nearest-name rule (D-035's offline
  measurement) stands; the benefit of using it for identity is not shown. The default stays off and I would not recommend turning
  it on on this evidence.

**Recommendation, not a change.** `canon: {model: llama3.1:8b}` reads this story more precisely than the default gemma3:4b. The
shipped default stays gemma3:4b because every install has it and a config naming a model that is not pulled degrades the reader.
llama3.1:8b needs about 5 GB of video memory: alone on an 8 GB card with a hosted Writer it fits; next to a local Writer the two
models may have to swap, which was not measured.

**Not done.** One transcript and 7 looks: a difference of one or two values is within what a re-read would change. Nothing was
tried at a larger size than 8B, and the Scribe prompt was not touched (asking about one character at a time when the player's action
names one, D-034's second idea, is still untried). A rule that refuses a hairstyle phrase as a hair value was not written;
it would be a shape-rule change with its own measurement (D-022).

## D-037 — Hair styles stay valid hair values (considered, measured, not changed)

**Question.** The shape rules accept a hair style on its own as a hair value (`bob`, `braid`, `ponytail`, `bun`, `undercut`,
`buzzcut`, `crop` and the like, `canon/shape.py` `_STYLE`), and identity is first write wins. A styling a story changes by scene
("hair up", "hair down") would then lock in something that stops being true, and a style as the first value blocks the colour,
because the slot holds one value. A gemma3:4b read in D-036 filed "intricately braided hair" as a hair value, which raised it.

**Measured** on the real story's ledger from the full read (22 live hair values; counts and generic style words only, no prose):
9 are a style or length with no colour ("ponytail", "severe bun", "tight braid", "short-cropped", "severe bob"), 4 mix a colour with
a style, 7 are a colour, 2 a shade. That is a large share, so the rule matters. Two things the data does not show:
- **The styles do not vary.** Of the 5 characters whose value is a braid, bun or ponytail, the story's sentences that name only
  that character state the same style 4 times, a different style 0 times, and hair worn loose or down 0 times (three of the five
  have no such sentence at all). Nothing in the story contradicts them.
- **The colour is rarely lost.** Of the 9 style-only values, the story states a hair colour in a sentence naming that character for
  2 of them.

**Decision.** No change. A rule that refuses a style-only value would drop values this story never contradicts and recover a colour
for 2 characters out of 9. Revisit when a story shows a style changing under a locked value (a character whose ledger says
"ponytail" and whose scenes say the hair is down), which the Canon panel's Wrong button already handles for one character; a
separate `hairstyle` slot would be the cleaner schema and is a larger change (a Scribe prompt line, an eval case, the card, the
panel) than the evidence calls for.

**Revisited in D-041.** A style (or a bare shade) is now filed as a weak value that the story's first colour replaces, which
answers the "colour blocked by a style" half of this question without a new slot.

**Also checked.** "Aldric", the first entry in every soak save's characters.md, is the template's example inside an HTML comment:
the entry parser strips comments and the canon ledger never held it.

## D-038 — The dedupe tool lists names that may be one character and merges them only when told to

**Context.** D-030's merge takes entries with the same whole name and nothing else, on purpose: the real story has one woman under
several names ("Dame Vesper", "Vesper", "Vesper Ann-Marie"), and a name rule cannot know that "Tamsin" is Tamsin Reeve and not Tamsin Pike. That left
the author with the duplicates and no help finding them.

**Decision.** `python -m coderain.dedupe` also prints, under the automatic plan, **possible same-character clusters**: entries
whose names are made of some of the same words, where one name's words are all inside another's ("Vesper" inside "Dame Vesper" and "Vesper
Ann-Marie"), joined by what they share. It merges none of them. `--merge KEEP DROP [DROP ...] [--registry FILE]` merges exactly the
slugs the author names (the first stays), with the same dry-run default, the same backup and the same alias, importance and body
rules as the automatic pass, and refuses, writing nothing, an unknown slug, a repeated slug, a single slug, the player's own sheet
and a registry that is not a registry of characters, places, factions or items. The suggestion line names the entry with the
longest body as the one to keep and prints the command, so a decision is one copy and paste.

Two names that share only a word and neither contains the other ("Ottoline Pike", "Ottoline Wren") are not suggested, and neither is
anything with the player's name or anything in threads and canon events.

**Measured** on a copy of the real story (54 character entries): 1 same-name pair for the automatic pass, and 5 possible
clusters of 2, 2, 3, 3 and 4 entries, 14 entries in all. A list that short can be read and decided in a minute. Whether a cluster is
one person was not checked (that is the author's call); no merge was applied to anything.

**Not done.** The suggestions use names only: two entries with different names and the same description are not found, and a
character known by a title alone ("the gatekeeper") is not linked to the person unless a name shares a word. A `[[link]]`
to a folded-away slug still points nowhere (D-030). The app has no button for it.

**Tests.** `dedupe_test.py` 9 and 10 (clusters, the player, a shared first name, a same-name pair left to the plan, every refusal
writes nothing, the registry option, the backup restores the original byte for byte); 13 more guard mutations are caught and one is
equivalent (clustering is undirected, so the direction of the word-subset test does not matter).

## D-039 — A character's own name beats another character's alias when both match exactly (and why two "missed" looks were not both the reader's)

**Question.** D-036 left two of the seven looks a story had established unheld by either reader model. Was the reader missing them,
or was something after the reader dropping them?

**Method.** The Scribe is deterministic (temperature 0, fixed seed), so its raw replies are a function of the passage and the
roster. The 161 narrator turns of the fixed narration-first transcript were read once through llama3.1:8b and every raw reply
recorded (31 minutes of GPU). The replies are then fed back through the real validator with a stub in place of the model, which takes
seconds and no GPU, so a rule can be changed and scored on the same replies. The replay reproduces the live read exactly (5 looks
held, 5 agree with the story, 29 identity records), which is the check that the method can be trusted.

**Found.**
1. **One of the two was the scorer's mistake.** The scorer counted a sentence that names a character and then describes a
   creature's "scales shimmering with an unnatural silver light, its eyes glowing" as that character's silver eyes. The story had
   established 6 looks, not 7, and the reader held 5 of them.
2. **The other was a real defect.** One character's registry entry listed another character's slug as an alias
   (`first-last`). `norm()` reads that as the name "first last", so the exact name matched two entities, `resolve_loose` called it
   ambiguous and returned nothing, and every claim about that character was refused as `unknown_entity`: 28 identity claims (eyes 22,
   build 5, marks 1), among them the colour the story stated plainly ("surprisingly sharp blue eyes", proposed correctly and
   repeatedly by the reader). Nothing about the reader's quality was involved.

**Decision.** When an exact name matches several entities and exactly one of them has it as its OWN name, that one wins. Two entities
with the same own name, or two that only share an alias, stay ambiguous: that is still a guess and a wrong merge is worse than a
duplicate. The fix is on the reading side, so it also covers saves that already hold such an alias. On the replay: identity records
29 to 57, and that character now has facts. His eyes lock on a bare "dark" said 80 turns before the first real colour, so the score
reads 6 held, 5 agree, 1 differs (a bare shade is compatible with the story's blue; the scorer cannot say so).

**Checked and NOT changed, on evidence.**
- **A bare shade locking a slot before the colour arrives.** On the full-read copy of the real story, 2 of 43 held hair and eye
  values are a bare shade and none of the held-back changes on any slot carried a real colour. One slot in one soak story is not
  enough to change first write wins; the mechanism exists if it ever is (a higher authority replaces a lower one, so a bare shade
  could be filed as `inferred`).
- **"Her eyes are an unnerving shade of grey" is refused** (`value_not_on_slot`) because a free adjective sits between "a" and
  "shade", and so is anything with a trailing dash clause. 13 of the 14 distinct refused eye claims that carry a colour in this
  transcript have that wording, and 0 looks were lost by it here (the colour was captured from another sentence). Left as a candidate
  for a transcript where it costs something.

**Also, at the source.** The fold's alias filter (`coderain/summarizer.py` `_apply_promotions`) now treats every OTHER entry's title
in the same registry as taken, so a promotion can no longer write another character's name or slug as an alias, in a merge or in a
new entry. The registry for the promotion's file is already loaded at that point, so it costs no extra read. Only the same registry
counts (a character alias equal to a location's title is still accepted), and real nicknames pass. It does not touch aliases
already on disk: the reading-side rule above is what covers those, and the dedupe tool lists the entries. Where it was seen: the
narration-first soak save, built AFTER D-029's fold fixes (those fixes only compared an alias with its own entry, so they could not
see it), and 1 alias on the real-story copy equals another character's own name. The eight soak saves that have a canon ledger
hold none.

**Cost to know.** A legitimate alias that happens to equal another entry's whole title is now refused. The case that exists is a
character filed twice (a full name and a short name as separate entries): the short name stops being an alias of the full-name entry.
That is the same trade D-030 made, a duplicate that can be merged later over a wrong merge that cannot be undone.

**Tests.** `canon_alias_collision_test.py` (the own name wins, a claim about that character is committed to them, two own names and
two shared aliases stay ambiguous, ordinary resolution unchanged); 4 of 5 guard mutations caught and the fifth is equivalent (two own
names leave two candidates either way). `fold_entity_resolution_test.py` 13 (a merge and a new entry both refuse another entry's
name and slug, another registry and a nickname are accepted); 6 of 6 guard mutations caught.

## D-040 — The reader asks a model not to reason first, and an empty reply is a failure, not a turn that was read

**What happened.** Qwen3.5 9B (a community decensored build, Q4_K_M) was installed to try as the reader and run over the fixed
161-turn transcript. All 161 passages (255 chunk calls) came back empty: 86.6 minutes of GPU for no facts. Nothing in the app said
so. The shadow recorded every one of those turns as read, and the report counted them as processed.

**Cause, measured** with two real Scribe requests against the model: with `think` unset the server let the model reason, it used
its whole 1,200-token answer budget on 4,944 characters of reasoning (`done_reason=length`) and `message.content` was empty; with
`think: false` it answered in 6 tokens with `{"claims": []}` (a passage with no looks) in 2 seconds. A plain `/api/generate` test of
the same model had looked fine (valid JSON in both modes), which is why the load test passed and the real read did not: the load
test's prompt was a one-line passage and a different endpoint.

**Decision.**
1. `canon: {think: false}` is the reader's default: every request says `think: false` unless the setting is a literal `true`. The
   Scribe wants a JSON answer and nothing else, and D-019 measured qwen3:4b with thinking off. A server that rejects the field
   gets it dropped once, as before (`OllamaChat` already does that), so models that cannot reason are unaffected.
2. An empty reply (`empty_output`) is handled like an unreachable model: the turn is NOT recorded as read, the next pass tries it
   again, and after `max_errors` in a row the pass stops and the health log says so once ("the Scribe sent back an empty reply N
   times in a row ... needs canon: think: false"). With a schema a model always has at least `{"claims": []}` to say, so nothing at
   all is a failure. Malformed JSON, a refusal and a bad shape are unchanged (still read, counted, not retried).

**Not measured.** Whether this model is a better reader than llama3.1:8b: the read that would say has to be run again with
`think: false`.

**Tests.** `canon_shadow_test.py` 1 (the setting) and 24 (the payload carries `think`, an empty reply is retried, reported once and
not recorded, a working model afterwards reads everything and agrees with a fresh read); 8 of 9 guard mutations caught, the ninth
is equivalent (`DEFAULTS["think"]` is overwritten by `settings()` on every call).

## D-041 — A hair or eye value with no colour in it is weak, and Qwen3.5 9B is not a better reader than llama3.1:8b here

**Context.** With D-040 in place the Qwen3.5 9B heretic build read the fixed 161-turn narration-first transcript (24.8 minutes,
0 errors; llama3.1:8b took 31.4, gemma3:4b 47 in D-036). Both recordings were replayed through the same validator, D-039 included.
The story establishes 6 real looks (the seventh in D-036 was the scorer's mistake, D-039). Numbers below are before the rule
this entry adds.

| | llama3.1:8b | Qwen3.5 9B (heretic) |
|---|---|---|
| looks held / agree with the story / differ | 6 / 5 / 1 | 6 / 3 / 3 |
| identity records | 57 | 126 |
| claims proposed, thrown out by the parser | 1,174, 311 | 915, 114 |
| passages with a malformed reply | 5 of 161 | 1 of 161 |
| held-back changes (contradictions) | 21 | 52 |
| extra values with no truth to check | 2 | 4 |

Qwen proposes fewer claims and breaks the format less, but files more identity facts (126 against 57), and the extras include weak
values: a hair style ("elaborate braids") and a bare "dark" as a character's first values. Every one of the 3 "differs" is the
same mechanism, below. (Two of its other extra values first looked like misattributions, a "stout man" build and a braid on a
character the story mostly writes as a woman. The quotes show the narration itself said both, "a stout man named ..." and
"intricate braid that falls down her back": the reader recorded the story's own inconsistency correctly, and the Canon panel is
where an author would see it. An earlier version of this entry, and its commit message, called them wrong.)

**The mechanism.** Identity is first write wins. A reader that files a shade ("dark eyes") or a style ("a tight braid") before the
sentence that states the colour locks the slot, and the colour is then held back as a contradiction every time the story says it
again. Counted on the recordings: slots locked on a colourless value while a colour was held back, llama 1 (the colour held back 21
times), Qwen 3 (12, 6 and 33 times). On the full-read copy of the real story: 13 of 43 held hair and eye slots have no colour word
(11 hair, 2 eyes), and 2 of those had a real colour held back (once and 4 times).

**Decision.** A hair or eye value with no colour in it is filed at the lowest authority, `inferred`. The ledger already lets a
higher authority replace a lower one, so nothing in the ledger changes: the first narrated colour replaces it, the old interval
is closed, and no contradiction is recorded. Everything else about first write wins is as it was: a colour is never replaced by
another colour (a raven that becomes platinum is still a contradiction), nor by a later shade; one colourless value does not
replace another; build, age and marks are untouched; an author's value and a sheet still outrank all of it. `shape.has_colour`
decides what counts (the `_COLOURS` list); a value only reaches this point after the shape rules, so it is made of known colour,
modifier or style words, and an unlisted real colour cannot be taken for a weak value.

**Measured** by replaying the same two recordings: both readers now hold the 6 real looks and agree on all 6 (llama 5 to 6, Qwen
3 to 6); no colourless slot blocks a colour any more. The real story could not be replayed (no raw replies were kept): the held-back
counts above say 2 of its 43 slots would change.

**Cost.** One value per slot reaches the card, so when a colour replaces a style the style ("tight braid") is no longer shown, and
it stays in the ledger's history only. D-037 found hair styles never vary in the real story, so that loses little. A shade that the
story later contradicts with an opposite colour ("dark" then "blonde") is no longer reported as a held-back change for a weak value.
Revisit with a `hairstyle` slot if a story needs both.

**Not decided.** Whether Qwen3.5 9B is a better reader for the owner's own story. It was tried for one reason, that a decensored
build might not refuse explicit passages, and the transcript here has none (and none may live in this repo). Until that is checked
on a local copy, llama3.1:8b stays the recommended reader (D-036; after the rule it ties Qwen on the real looks and has half the
extra values) and gemma3:4b the default.

**Tests.** `canon_colourless_values_test.py` (8 cases: filed as inferred, replaced by the first colour with no contradiction, a held
colour not replaced, one shade not replacing another, a restatement, hair and a style, build and marks untouched, the author still
outranks); 10 of 10 guard mutations caught.

## D-042 — "An unnerving shade of grey" is the eyes' grey

**Question.** D-039 left it open: the shape rule refused "Her eyes are an unnerving shade of grey" (`value_not_on_slot`) because the
free adjective between "an" and "shade" is on no list. Does that cost anything?

**Measured** on the two recordings of the same 161-turn transcript (replayed offline, no model): the clean value ("grey") was
proposed by both readers and refused for this wording in 13 distinct claims (llama3.1:8b) and 8 (Qwen3.5 9B), every one of the 8
refused eye colours in the Qwen read. It lost no look on this transcript, because each colour was captured from another sentence,
but it delayed some: one character's eye colour was first captured at turn 7 instead of turn 3, and a delayed first capture is
exactly when a wrong first write (D-041) gets in. On a story that states a colour only this way it would lose the look.

**Decision.** In the run after a noun, ONE free word is part of the phrase when it sits between an article (a, an, the) and a shade
noun (shade, hue, tint, colour, color): "an unnerving shade of grey", "a surprising shade of auburn". Nothing else is widened: a
colour modifier ("a pale shade of grey") stays part of the value, the article and the shade noun are both required, a verb ends the
phrase, and the adjective is never the value.

**Measured after.** No held value changed in either reader (6 of 6 looks, all agree). Identity records 57 to 59 (llama) and 126 to
165 (Qwen), most of the rise corroborations of values already held (restated 54 to 121 for Qwen). Every newly accepted claim was
read by eye: the right named character and the right colour (2 for llama, 5 for Qwen).

**Not changed.** A dash clause that ends in "are" ("Her eyes - pale grey-blue - are fixed on you", with or without a free adjective)
is still refused: a run that crosses a dash carries on through skip words ("are"). So is a trailing clause after the colour
("grey, the color of storm clouds"). They are older limits of the run rule, not of this change, and the cases are listed here so a
future measurement can say whether they cost a look.

**Tests.** `canon_shape_test.py` 13 (accepted, a modifier kept, and six refusals: no article, no shade noun, a verb between, the
adjective as the value, no eyes in the quote, and a free word with no shade noun after it); 8 of 8 guard mutations caught after two
gaps in the first draft of the tests were closed (a refusal that was reached by another path, and nothing pinning that "pale" stays
part of the value).

## D-043 — llama3.1:8b does not refuse adult-content passages (counts only)

**Question.** The design needs a reader that does not refuse adult prose, and the plan asked for a direct test. llama3.1:8b is the
recommended reader (D-036, D-041), and a decensored Qwen3.5 build was tried for exactly this worry. gemma3:4b, the default, had no
refusal in the full read of a long real story (976 passages: 955 ok, 20 malformed, 1 with no JSON, none refused).

**Method.** Local only, on a copy of that story's full-read save (nothing printed or written but counts and turn numbers). The 60
narrator turns with the highest density of a generic lexicon of adult words (2.7 to 6.6 hits per 100 words) plus 20 ordinary turns
were read through the real reader (llama3.1:8b, `think: false`, `num_ctx` 8192, the story's character roster) and compared with what
gemma3:4b found on the same turns in the full read. Claims per passage is compared as well as the status, because a model held to a
JSON schema that declines can still answer `{"claims": []}`.

**Result.** 80 of 80 replies were well-formed (no refusal, no malformed reply). Claims per passage: llama3.1:8b 7.1 on the densest
turns and 7.2 on the ordinary ones, gemma3:4b 4.7 and 4.2 on the same turns. Passages with no claims: llama 5 of 60 and 0 of 20,
gemma 2 of 60 and 0 of 20. The 5 were the shorter ones (177 words on average against 253), spread across the density bands (2, 1 and
2 from the densest third to the least), gemma also found nothing on one of them, and only one passage had gemma at 4 or more claims
and llama at 0 or 1. 8.4 seconds a passage.

**Decision.** No change. llama3.1:8b stays the recommended reader, and the decensored build is not needed for refusals on this
test.

**Not established.** Whether the 5 empty passages are scenes with no physical fact to record or a quiet skip: they were not read.
5 of 60 against 2 of 60 is inside the noise at this size. The sample is the densest turns by a word count, not a random draw, and
one story, one model, one run. If a reader ever returns far fewer claims on such turns than on ordinary ones, the same check (a
density-ranked sample against a control, claims per passage beside the status) is the test; its script lives in the session notes,
not in the repo, because the lexicon and the story must not.

## D-044 — Accessories are a slot of their own (built and tested; measured in D-069: the default stays off)

**Why.** Nothing in the slot list could hold a ring, a pair of hairpins or a string of beads. The real-story gate lost two of its
controls that way (hairpins on one character, jade beads on another), and a later soak showed the cost: the reader's only way to
file "iridescent beads in her braids" was as hair, the shape rules rightly refused it, and the beads were dropped. Garments are the
outfit's (a list with a vocabulary and a decay window), marks are scars and tattoos; an ornament worn on the person is neither.

**Decision.** `identity.accessories`, one ledger slot per item like marks (`identity.accessories.<item>`), first write wins per item,
nothing ages off the card, `add` only (a removal is the author's call, as for marks).
- **Shape rule** (`canon/shape.py` `_accessory`): the value names an ornament (hairpin, circlet, earring, necklace, pendant, locket,
  choker, bracelet, bangle, anklet, brooch, monocle, spectacles; and ring, bead, ribbon, glasses, chain, comb, pin, hoop, stud, clip,
  cuff, band, which have other meanings), and the quote has it worn: a place on the body (hair, braid, ear, neck, throat, wrist, ankle,
  finger, brow, nose ...) or a verb for wearing it (wore, pinned, threaded, woven ...). Refused: "beads of sweat" (a liquid), an
  ornament being taken off ("slipped the ring off her finger"), a locket on a table or clutched in a fist, a ring of men, glasses set
  down, and any garment. Reasons: `not_an_accessory`, `not_worn`.
- **Validator**: the same item worded another way is the item said again ("hairpins" and "gold hairpins", "jade beads" and "green
  beads"), recorded under the slot it already has. `same_value` is the wrong test for items (it calls "silver ring" and "silver
  hairpins" one thing because both say silver, which the first draft of the tests caught), so `_same_item` needs a shared ornament
  word and colours that do not disagree. A character holds at most 12 (`too_many_accessories`): identity items cannot age off.
- **Card**: "wears gold hairpins, jade beads" after the marks, as a phrase (D-029), dropped before build and age when the line is too
  long, offered like the other looks when the character has dropped out of the recent turns or the player's action asks about
  jewellery.
- **Corrections** (`accessories`, also `accessory`, `jewellery`, `jewelry`): `- Name: accessories = silver ring` adds one at author
  authority, `is not gold hairpins` retracts the matching one and makes the validator refuse it, removing the line releases it. The
  corrections code treats marks and accessories as the same kind of slot (`LIST_SLOTS`) instead of copying every branch.
- The Canon panel lists it, the identity table and the shadow report show it, and the Scribe's schema and prompt can ask for it
  (gated, below).

**Tests.** `canon_accessories_test.py` (7 cases: the shape rule on 18 sentences, one slot per item and sameness, the bound, the
schema and prompt and op rules, the card, corrections, the tables); 27 of 27 guard mutations caught after one test gap was closed (a
taken-off quote with no body place was refused for a different reason, so the taken-off guard was never exercised). The evaluation
corpus gained 4 accessory passages (2 dev, 2 test, a new group) and 3 look-alike traps (beads of sweat, a ring taken off, a ring of
men), all invented, so the next model run can score the slot.

**The prompt line is gated.** The slot adds a line to the Scribe's prompt, which can move what the reader does with every other slot,
and the identity capture is the part that has been measured carefully. So the Scribe is asked about accessories only when
`canon: {accessories: true}` (a literal true, default false; `Scribe(llm, accessories=True)`; `--accessories` on `python -m soak
scribe`). With it off the schema and the prompt are exactly what they were (10 slots), so every earlier recording is still a valid
replay of the default. Everything after the reader works either way: the validator, the card, the corrections file and the Canon
panel, so an author can add or retract an accessory by hand today.

**Evaluation.** The corpus has a `legacy` slice (the 26 passages that existed before this entry) and an `accessory` slice (4 new
passages with 6 labelled facts, 2 dev and 2 test), and the 3 look-alike traps sit in the trap slice. A run with and without
`--accessories` on the same corpus is therefore comparable on exactly the old passages, and the accessory slice scores the new slot.

**Pending (needs a model, the GPU).** (1) The evaluation corpus with and without the slot: the legacy slice must not drop and the
accessory slice must score above zero with few false positives on the look-alikes. (2) A re-read of the fixed narration-first
transcript with `accessories: true`, to see what the reader files as an accessory and whether the held hair, eye, build and mark
values change. Only then is the default flipped.

**Tests (added with the gate).** `canon_accessories_test.py` 4 (the schema and prompt ask only when told to, the Scribe passes the
gate on), `canon_shadow_test.py` 1 (the setting) and `soak_scribe_corpus_test.py` 7 (the slices); 11 of 11 gate guards caught.

## D-045 — Fate: a hidden D20 nudges where the next turn goes (built; the first model run is D-053)

**The idea (the owner's).** An add-on for the immediate story progression: the model writes directions for where the scene goes next, a
D20 picks one (1-2 a setback, 3-10 and 11-18 two neutral developments, 19-20 a stroke of luck), and the Writer is steered by it. "Or
something similar if you have a better suggestion." His "10 to 18" overlaps the neutral band, so it is read as 11 to 18: 10 / 40 / 40 / 10.

**How it was decided.** Three read-only architects (engine, product and web UI, skeptic and test lead) each proposed an implementation from
the code, then critiqued each other's proposals over two rounds on 13 contested points. All three accepted the result. The name is
"fate" because "beat" is already taken (the `## Beats` list in arc.md and `beat_advance`).

**What was built.**
- `coderain/fate.py`, pure except for one model call. The roll is DERIVED, never stored as state: `Random(seed, turn, action, nonce)`, so
  the same action at the same point always rolls the same die (retry, swipe, undo-and-redo and a branch agree) and a different action
  rolls again. The roll is first, then ONE sentence of the rolled kind (setback, natural, surprise or windfall). The two neutral bands
  are two different prompts ("the natural, expected continuation" and "a surprising but harmless development").
- The model's reply is `{"stakes": "none" or "some", "direction": "..."}`. Stakes can only switch a setback or a windfall OFF (a quiet
  scene gets no steering that turn); a missing or invalid label counts as none, and it never widens a band. Pure code checks the rest:
  one line of at most 200 characters with no fences or list markers; not a restatement of the last three directions (`planner._restates`,
  asked for once more naming the repeat); a setback that kills or removes the player or any pinned or critical character is vetoed.
- The sentence is cached in `memory/fate.jsonl` (newest 100), keyed by (turn, action, the narration before it), NOT in `events.jsonl`:
  it is not state, and that ledger's count-based rollback has a long bug history. Retry and swipe are a cache hit (same tier, same
  sentence, no model call, new prose). An undo, a transcript edit that shortens the story and a branch prune records past the end.
- The setting is per save in `meta.json` (`fate: {mode: off|preview|on, show_die}`), like `mode`: a branch copies meta.json whole, while
  it reverts a `state.json` key to the snapshot's value (two architects verified this in `branch()`). Off by default. Preview rolls, asks
  the model, records, and sends the Writer nothing; the idea is on the turn's event line. On sends the Writer a hidden note (it never
  carries the die or the tier) and shows the die on the event line only when `show_die` is set, never the sentence.
- The note is a system message AFTER the player's action and the canon card and BEFORE the chapter directive, so the chapter goal stays
  the last thing read (D-027). It says it does not override the chapter goal or continuity and that nothing the story marks important
  may be killed, crippled or removed.
- Fate runs only for an action turn (not the opening, not a Continue) and only when nothing else authors the turn: skipped in an RPG
  save (the RPG check is already a d20) and when the Director plans the turn, logged once per save. It uses the Writer's own client,
  asks the model not to reason (`/no_think`) and caps the answer at 700 tokens with `retry=0`. Any failure leaves the turn exactly as
  if fate were off and writes one row to `memory/health.jsonl` (invariant 2).
- Controls: `GET/PUT /api/saves/{slug}/fate` and a selector (Off, Preview, On) with a "show the roll" checkbox in the existing Play aids
  modal, disabled with the reason in an RPG story. No new header button.

**Where this differs from the owner's words.** He described four directions with a D20 picking one. The architects settled on rolling
first and asking for one sentence: a quarter of the output, and the planner already learned that one malformed element must not cost a
batch. The skeptic moved from roll-first to four sentences and back after the retry/swipe question was settled, with a pre-declared
fallback: switch back to four if the first-try validity of a roll-first sentence on the target local model is poor over about 50 scenes.
A "you pick" mode (four cards) stays possible later.

**Deferred on purpose.** A mercy rule (at fixed bands two setbacks in a row are about 1% of turns, so it is nearly dead code until a
run shows streaks); a reroll control and the tier chip with tap-to-expand (a reroll endpoint without its button would be dead code, so it
ships with the button, after the owner has read previews); moving odds and stat shifts; coupling with RPG checks; a docked "Story" panel
and a play.js split (no value for this build).

**Not verified.** The latency and the model-swap cost of one extra call per turn on an 8 GB card; how a small model does at the JSON
and at four-sentence-free one-liners; whether the Writer enacts or copies the note (the leak scan only logs); whether the setting
should also be a world's default. The first run is a PREVIEW on a temp story, reading `memory/fate.jsonl` and the event lines.
(The quad pipeline in simple mode, where the Director is built but skipped, is now driven by `fate_engine_test.py` case 9: fate runs
and the Writer is steered; with an authored event rule the Director plans the turn and fate steps aside with one health row. Five
mutations of that gate caught.)

**Tests.** `fate_roll_test.py` (bands, pinned dice values, the key), `fate_validate_test.py` (the checks, the Writer's note, the event
line), `fate_store_test.py` (cache, prune, settings, branch with and without a snapshot), `fate_engine_test.py` (off costs nothing, the
message order, preview, retry/swipe/undo, every failure shape, quiet scenes, veto and repeat, RPG and opening/Continue skips, the real
seed and turn reach the die), `fate_api_test.py` (the routes and the transcript-edit prune). The guard-breaking pass is in the commit
message.

## D-046 — The piece editor merges an AI result without losing what it states

**What was wrong** (read from the source, verified by a test). "Improve with AI" and "Seed from idea" in the piece editor (builder.js)
wrote only some of the form's fields back. `fill()` never set a character's wants or motivation, the traits and links chips (the chip input had
no setter), the activation controls (group, chance, delay, sticky, cooldown, requires, blocked by, semantic, recurse), nor the four trait
fields of D-032 (strengths, weaknesses, personality, goals), which had no field in this form at all. Worse, `collect()` re-merged the OLD
attributes over whatever the AI had said, so the AI's answer for every such field was silently dropped and the form looked updated. There
was no undo, so a bad result overwrote the author's work.

**Decision.** One table (`webapp/js/pieceform.js`, no DOM) lists every field the form manages. `collect()` reads every field in it and
`fill()` writes every field in it, so a field cannot be read but not written again. What an AI answer changes is a pure merge: every
attribute it states replaces the form's (managed or not, so an unmanaged header line it rewrites is replaced too), an attribute it leaves
out keeps the author's value, `null` and `undefined` never clobber, lists and numbers arrive as text, and a bad title, importance or alias
list keeps the form's own. The four trait fields are now in the character form (shared wording with the Characters screen). After any AI
result an "Undo AI" button restores the form as it was (one level, until the piece is saved or the form closed). `chipInput` gained `set`.

**Tests.** `pieceform_test.py` runs the pure module under Node (it skips with a SKIP line when node is missing, which `run_tests.py` now
lists, see below) and reads the editor's HTML for an element for every field in the table, the Undo button, and that seed and improve
both go through the merge; 21 guard mutations caught after two gaps in the first draft were closed (the chip setter was only checked
by name, and `collect()` dropping the carried attributes was not asserted).

**Not done.** The rest of the creation flow the product designer listed: chapter 1 planned at story start with progress, a world
from one sentence on the web, and the assist context (the roster and world bible) for characters. The editor itself is not driven in a
browser by a test here; the DOM binding is thin and the logic that decides what changes is the tested part.

## D-047 — The test runner says what it skipped

**What was wrong.** A suite whose optional dependency is missing (the browser suite without playwright, the piece-editor suite
without node) prints a line starting `SKIP` or `SKIPPED` and exits 0. That is right for a dev-only dependency (CLAUDE.md), but the
runner's last line was then a bare "ALL SUITES PASSED", so on a machine without playwright every browser claim was green and
unchecked, and nobody could tell from the output.

**Decision.** `run_tests.py` now runs each suite through `run_one`, echoes its output as it arrives (unbuffered, so a long suite still
shows progress) and collects its SKIP lines. After the verdict it lists every skipped suite and why ("SKIPPED, so NOT checked here").
A skip does not fail the run. Because the runner now re-writes the children's output, it makes its own stdout UTF-8 first: the first
version crashed the whole run with a `UnicodeEncodeError` the moment a suite printed an arrow while the console or a redirect was
cp1252, which only the full suite found.

**Tests.** `run_tests_skip_test.py` (SKIP lines are found and a line that only mentions the word is not, a failing suite and a timeout,
a cp1252 console, and the source shape of the summary); 10 of 10 guard mutations caught after one gap was closed (main() not calling
the UTF-8 setup was not asserted).

## D-048 — A scripted player lives in the repo (`python -m soak play`)

**Why.** Every comparison that needs a story played for many turns (the canon card on or off, fate on or off, one model against
another) needs the same player making the same moves. The driver the consistency soaks used lived only in a session scratch folder, so
no on/off comparison of fate could be run or reproduced from the repo. All three architects named this as the missing prerequisite.

**What it is.** `soak/play.py` plays an invented story (a tidal ferry town, six characters with a stated hair and eye colour) through
the real engine in a temp home: `Engine.turn` then `maybe_fold`, exactly the path the web app takes, with the memory squeezed on
purpose (a few verbatim turns, a small budget) so that older facts can only come from memory. A seeded `ScriptedPlayer` makes the same
moves for the same seed, with a probe every N turns where it studies one character's hair or eyes and the colour the narration states
is scored against the sheet (held, drift or none). It writes one row per turn and a summary (probe verdicts, fate tiers, seconds,
model calls, health rows) to `--out`; the rows hold the invented story's own text, so they belong outside the repo.
- `--stub` is an offline writer (deterministic prose that states the sheet's colour when a look is studied; as a fate stage it answers
  with one of twelve distinct directions, because a stub that repeats itself is refused by fate's own repeat check). The tests and a
  dry run use it: no model, no network.
- `--model NAME` uses a local Ollama. It must already be running (this never starts it) and any host that is not this machine is
  refused. `--fate off|preview|on` sets the save's fate setting, `--canon card` turns the canon shadow and card on (a model is
  needed for the reader), `--sheets role` writes no looks in the sheets.
- The save's dice seed is pinned to `--seed`. A new story draws a random one, so without this the same player seed still rolled
  different dice, which an on/off comparison of fate cannot have (found by the test that two runs of one seed must give
  identical fate rows; the first draft also failed one run in several because the stub chose its directions by hashing the prompt).
- The home is always a temp one (`isolated_home` before coderain is imported, `assert_isolated` before anything runs); a source of
  live data is never opened.

**Not done.** The scoring of a story against itself (what the first soaks called `soak_truth`) and the repetition and length measures
(look sentences per turn, 8-gram overlap) are still only in the session notes; this driver gives the same moves and the raw rows to
compute them from. The first model runs with it (fate off against preview against on; the card on against off) need the GPU.

**Tests.** `soak_play_test.py`: the same seed gives the same story and another does not, probes land on the right turns and are held
on the offline writer, fate off asks the model nothing, preview asks for every turn and steers nothing, on steers, the probe scoring,
and the refusals (a remote host, the card with no model, no turns). Guard mutations are listed with the next entry.

## D-049 — A no-model audit of a world's files (`python -m soak creation-audit`)

**Why.** The owner wants chapter, scenario, world and character generation to be "as seamless as possible". The consistency work began
by measuring; this does the same first step for creation. The skeptic's point was that most creation defects can be found with no
model at all, by reading what is on disk.

**What it checks** (`soak/creation_audit.py`, Markdown only, it never opens a store, so it is safe on a copy of a save and on the
shipped scenario): two entries in one registry answering to the same name or alias (the D-039 class that cost 28 refused claims in one
soak and 1,452 in the first); an alias that is another entry's own name or slug; a `[[slug]]` that no entry has; a sheet shorter than
a floor (untuned: 20 words for a character, 12 for a place or faction, 5 for an item); four or more entries in a registry with the same
importance; two outline chapters that share a run of content words (`planner._restates`); a character whose sheet states no hair or eye
colour; an empty registry. `--default` audits the shipped scenario, `--strict` exits 1 on any finding, `--out` writes JSON.

**First result, on the shipped default scenario:** 4 characters, 3 places, 3 factions, 2 items, 2 threads, 3 canon events, 1 event
rule, and one class of finding: none of the four characters states a hair or eye colour, so the canon card has nothing to hold for them
until the story first states one. The first version of this check passed three of the four sheets because the word "hair" or "eye"
appeared ("hair wet to the scalp", "a face the eye slides off of"); reading the sheets showed that was the wrong test, and it now
needs a colour word beside the noun. The Tall Man and the Arbiter are uncanny on purpose (the Arbiter is never the same twice), so a
finding there is by design and the report says a shapeshifter may be that on purpose. Wren and Corin should have looks, so the
shipped sheets now state them (Wren: black hair, pale grey eyes; Corin: brown hair, hazel eyes), which gives the canon reader an
authored first write to hold from the first turn of the default story (D-029); the audit of the shipped scenario now reports only
the two uncanny characters, and a test pins that. Nothing was found for the other classes, which says the shipped world is clean, not that generated worlds are: the
audit's real use is on a save a model has built.

**Tests.** `creation_audit_test.py` builds a world with each defect and requires each to be found (and a real link and a
kind-prefixed link not), a clean world to report nothing and never be written to, and the CLI (findings, `--strict`, `--default`,
`--out`, a missing folder, no argument), and the look check on sheets that do and do not state a colour. 24 guard mutations across
this and the scripted player were caught after two gaps were closed (the default-scenario check only looked for a word that the
findings also contain, and nothing pinned that the dice seed reaches the player's save).

## D-050 — A per-piece AI assist is told about the world, not only the premise

**What was wrong.** `/api/assist` (the builder's "Seed from idea" and "Improve with AI" for a character, place, item, faction, thread or
event) sent the model the premise and nothing else. A character generated from an idea knew nothing of the world's places and
factions or of the people already in it, which the full generator's own entity stages always see (they chain a growing roster through
every call). Two pieces generated one after the other could duplicate each other, and a new character could not refer to a place that
exists. The engine architect found this reading `srv/pieces.py` `_scenario_context` against `generator._run_entity_stages`.

**Decision.** A PIECE assist now reads `generator.assist_context(store)`: the premise, an excerpt of the world bible (1,200 characters),
and a roster of what already exists, one line per character, place, faction and item (`[[ref:slug]] Title - status or first line`, at
most 40 lines of about 110 characters, in that order), under a header that says not to duplicate them and that they may be referred to.
A section with nothing in it is left out, and the verbatim opening is never included. The world, premise and introduction FIELDS keep
the premise alone, on purpose: they rewrite those very texts, and giving the world field its own bible would make it rewrite itself.
Both branches of the route (a scenario slug from the builder, a save slug from the story editor) follow the rule, and an unknown
scenario still runs context-free as before. The cost is a longer prompt on a piece assist (up to about 1,200 + 4,400 characters), paid
only when the author asks for one.

**Not done.** The full generator's `created()` formats its roster lines with the title twice (`Title - Title - ...`, because
`Entry.oneline()` already begins with the title); this entry's roster does not, and the generator's was left alone. A character
added to a story already under way is still not known to the canon ledger beyond what its sheet says (D-029 seeds only stories of at
most three narrator turns).

**Tests.** `assist_context_test.py` (the roster's order, count and length bounds and no repeated title, the context's sections and
cuts and omissions, and the route on both slugs with a stub model that captures what was sent); 15 guard mutations caught.

## D-051 — A new story gets its first chapter before the opening, not at the first fold

**What was wrong.** The chapter outline was seeded by the first scene fold, which runs about twelve turns into a story
(`medium_fold_after`). The opening scene and the first stretch of play were written with no chapter goal at all: the chapter
directive that is restated after the player's action did not exist yet, so the writer drifted wherever it liked before the steering
began. The planner's own instruction already says "if there are no chapters yet, plan chapter 1: where play begins", so only the
trigger was late.

**Decision.** `Engine._produce` calls `_plan_first_chapter` before anything else is built. When the outline is on, the premise is long
enough, no chapter exists and the transcript holds at most three turns (`START_PLAN_TURNS`: the opening, a player action, a
narrator reply), `ChapterPlanner.ensure_first` plans ONE chapter with the ordinary payload, retries and restatement checks and writes
it as `ch-1`, status `active`, with the attribute `origin: start`. The reader sees "Planning chapter 1". The writer's messages for the
opening then carry the chapter directive, still the last thing read. An authored `## Opening` is used verbatim without a model call,
so for those stories the chapter is planned on the first player turn instead.

The first fold finds a lone start chapter (`needs_seed`: no chapters, or exactly one that still carries `origin: start`) and tops the
outline up to the horizon, one call per chapter as before; chapter 1 is kept as it was, and its marker is removed once it has company.
`replace_all` (the Plan panel) writes chapters without the marker, and a second chapter added by hand also stops the top-up, so an
outline the author has touched is never extended behind their back.

A planning failure never costs the turn: the story starts without a chapter exactly as before, one `chapter-plan` health row says
why, and the first fold plans the whole outline. A story already under way (more than three turns, for example one that had the outline
switched off) is left to the fold, as before. The cost is one model call (two to four when the reply is malformed) before the first
scene of a new story.

**Not done / not measured.** The first chapter is planned from the premise, the world and the author's character traits alone, because
nothing has happened yet; whether a model writes a usable chapter 1 from that on every local model is not measured. The opening's
system prompt is assembled before `_produce` runs, so the "Story structure" section is absent from the opening itself and only the
chapter directive steers it; from the next turn both are present. A hand-edited lone chapter is not topped up at the first fold; the
planner tops the plan up when that chapter completes, as it always did.

**Tests.** `chapter_start_test.py` (one call, one active start chapter numbered `ch-1`; nothing planned with the outline off, without a
premise or over an existing chapter; a bad reply leaves one health row and the fold still plans; the top-up keeps chapter 1 and its
text, forgets the marker and is idempotent; a hand-edited lone chapter and a hand-added second chapter are left alone; the engine plans
once, announces it once, puts the directive last, leaves old stories to the fold, survives a planner exception; the first fold tops
up and announces it). 23 guard mutations caught after three gaps were closed (the slug, a hand-added second chapter, and the note
appearing when nothing would be planned). `validator_test.py` case 9 counts every call on one shared stub and now switches the outline
off, with the reason written in, because the new call would otherwise be counted as a Director call.

## D-052 — A whole world from one sentence, in the browser

**What was missing.** The web app could build a world only by hand: open the builder, write a premise, press "Generate the rest". The
full generator (title, premise, world bible, factions, characters, places, items, threads, the opening message) existed for the
desktop app and the command line but had no HTTP route.

**Decision.** `POST /api/scenarios-generate` (server-sent events) runs `generate_scenario` on a worker thread and streams its stages;
the `done` frame carries the new world's slug and the generator's warnings, and what the AI made is copied to the Pieces library as
"Generate the rest" already did. The streaming scaffolding (the one-generation-at-a-time lock, stage frames, error frame, library
copy) moved out of `scenario_complete` into `_stream_generation`, so both routes share one implementation. The idea must be a
non-empty string (a JSON null no longer becomes the text "None": the first test run found that), at most 600 characters, with line
breaks and runs of spaces collapsed; counts are clamped to 0..12 and fall back to 5, only `"fast"` selects the fast mode, and type and
tone are cut to 80 and 200 characters. Nothing is created unless the premise stage works, so a failed run leaves no world behind.

The Library page gets "+ World from an idea" beside "+ New world". The dialog (`webapp/js/ideaworld.js`) takes the sentence and a
"faster and shallower" box, shows each stage as it arrives, keeps the sentence for a retry when the run fails, and opens the new
world in the builder when it finishes. If the author closed the dialog while the AI worked, the world is announced and the library
refreshed instead of pulling them into the builder.

**Not done.** There is no cancel: closing the dialog hides it but the run continues on the server (the same as "Generate the rest"),
and the lock holds until it ends. The idea has no title field; the title comes from the model. The result was checked in a browser
with a stub model standing in for a real one (the sandbox has none), at desktop and phone width; it has not been run against a real
model, so the quality of a world made from one sentence is unmeasured.

**Tests.** `world_from_idea_test.py` (stages and the done frame, the sentence reaching the premise stage, the world and library
contents; a stage that produced nothing is named; empty, blank, null and over-long ideas are refused and run nothing, the limit itself
is accepted, whitespace collapses; the knobs and their bounds; a failed premise stage creates no world and frees the lock, a busy lock
is refused without calling the generator; "Generate the rest" still streams the same frames and keeps the author's text).
21 guard mutations caught after one gap was closed (generator warnings were not asserted). `webapp_smoke_test.py` case 8 drives the
dialog in a real browser (it opens, an empty sentence is refused without closing it, a failed run says so, keeps the sentence,
re-enables the button and leaves no world); 5 mutations of the dialog and the button caught.

## D-053 — Fate on a real model: the first preview found five defects (fixed) and one limit (not)

**The run (2026-11-13).** The D-045 preview, on two local models through the real engine: the scripted player of `soak play` (an invented
ferry-town story, role-only sheets, 80 turns, seed 5), fate in preview mode, the Writer sent nothing. gemma3:4b took 24 minutes, llama3.1:8b
95 minutes (the 8B model spills off the 8 GB card at a 16k context; its turns averaged 71 s, fate added about 8 s of that). Every fate call
was recorded (latency, reply, error) through a wrapper in the session scratchpad, not in the repo.

**What it measured, before any fix.**
- First-answer validity: gemma3:4b 63 of 96 calls usable at once (66%), llama3.1:8b 81 of 94 (86%). A usable first answer ended in a
  line for 44 of 80 exchanges (gemma) and 64 of 80 (llama); the rest got no steering and one health row.
- Why they failed: lines over the 200 character limit were 21 of gemma's 36 failures and 10 of llama's 16 (the models write 25 to 45
  words when asked for 25; refused lengths were 201 to 354, mostly under 285); a reply in another JSON shape (the Writer's own
  `{"deltas": ...}` sidecar format, copied from the story context, 3 times) or with no direction; unparseable JSON (11 on gemma,
  2 on llama; the raw text was not kept, so the cause is still unknown); a repeat (4).
- Cost: a fate call took 3.3 s on gemma3:4b (a 13 s turn) and 7.8 s on llama3.1:8b. Neither is a problem next to the Writer.
- The `stakes` valve: gemma3:4b labelled every setback and windfall "some" (0 of 11 switched off); llama3.1:8b labelled 7 of 16 "none",
  which fits a script of mostly quiet actions. So the valve works only on the larger model.
- Quality, read line by line (all 44 and 57): the setbacks were usually real events (gemma 4 of 5); the windfalls were not
  (gemma: at most 1 of 6 a stroke of luck for the player, the rest echoed "help arrives" or were weather; llama: none); the surprises were mostly
  atmosphere (rain, a glow, a hum); the natural lines were filler (weather, or a retelling of the player's own action). 16 of gemma's 44
  lines opened on rain, wind or a sound, 24 lines in each run mention the player (some of those are fine: "a guard stops you"), 12 of gemma's 44 began by copying the kind's
  description ("a surprising but harmless development: ...") and 16 restated an earlier line.

**What was fixed (all in `coderain/fate.py`, each with a test that fails without it).**
1. The length limit is 300 characters, and the request asks for 20 words (the limit is a bound, the request is the target).
2. An unusable first answer of any kind gets ONE more try that names what was wrong ("YOUR LAST ANSWER WAS REFUSED: ..."), up to
   `ATTEMPTS = 2`. A model that raises (a dead or stuck server) is asked once: the second wait would only double the delay.
3. A kind label copied into the answer is dropped when it is exactly at the start (`a setback:`, `a small stroke of luck for the
   player:` and the other description openers) and refuses the line when it sits inside the sentence.
4. Also refused, so the second try can ask again: a line under three words ("help arrives"), a line that stops mid-sentence (a trailing
   colon, comma, hyphen or dash), a line whose first word is "You" (the Writer owns what the player does; "Your pack is torn" and
   "As you reach the door, a bell rings" are events and pass).
5. The record's `model` field was blank on every real run (the real client keeps the name on `profile.model`, a stub as `model`).
6. The request was rewritten to ask for an EVENT (a person or thing does something that changes the situation; weather, sounds, smells and
   moods are not events), gives one example per kind from a different story ("copy the shape, never the content"), and describes each
   kind in a sentence that does not read like a label.

**What was not fixed, and why.** Whether a 4B or 8B model can write a windfall or a surprise that is an event and not atmosphere is a
quality limit, not a code defect, and the second run below measures how far the new request moves it. The stakes valve on a model that
says "some" for everything is also a model limit; it is harmless (the band was always allowed to fire). The unparseable-JSON failures
need their raw text, which the second run keeps. Natural stays a model-written sentence for now; the first run says it is filler
(weather or a retelling), and if the rewritten request does not change that, making natural send nothing is the next step (it halves
the extra calls, and the chapter directive already says every scene must advance).

**Not verified.** Whether the Writer follows a steering line, or copies it (`leaks` only logs); how any of this reads on a hosted
model; the fate on/off soak (same moves, same dice, with and without steering).

**Second run, after those fixes (gemma3:4b, same script, 80 turns).** First answers usable 72 of 90 (80%, was 66%); 63 of 80 exchanges
got a line (was 44); label copying and length refusals nearly gone (3 of 106 calls over 300 characters). Quality moved the way the
request was meant to move it: lines that open on weather, a sound or a smell fell from 16 of 44 to 11 of 63, the surprises became
things that happen (an object washes ashore, a person arrives and says something), and about half the windfalls were real luck (a
crate with coins, a hidden door, a lantern that lights a passage; before, at most 1 of 6). The raw replies, kept this time, showed
what the first run could not, and the run also left a new class of defect. All are fixed in `coderain/fate.py`, each with a test that
fails without it:
1. **Nearly-JSON replies were the largest failure left (19 of 106 calls).** The sentence ends in speech, the model closes the speech
   with an escaped quote and forgets the quote that closes the JSON string, so no parser takes a line that is fine. `salvage()` takes
   the sentence and the stakes word out of such a reply; the sentence then passes the same checks as any other. Replayed offline over
   the 19 recorded failures: 16 become usable lines, 3 are refused for length or weather. fate now makes its own request
   (`_ask`) instead of going through `emit_json_ex`, because that helper throws the text away when it does not parse.
2. **The model was shown the Writer's world-update block.** It is appended to the END of the Writer's system message ("End EVERY reply
   with one fenced block ... {"deltas": {}}") and fate sends the last 12,000 characters of that message, so it sat in the most
   salient place; 6 of 106 replies were that sidecar and not a direction, and a second try did not fix them (same context, same
   answer). `story_context()` removes the block before the tail is cut.
3. **`clean_line` cut the closing quote off every spoken line** (`declares, "This paper ... deceit.`): it stripped quote characters
   from both ends to remove a wrapper. Only a pair that wraps the whole line is dropped now.
4. **"The rain continues to lash the deck"** was 5 of 20 natural lines: the weather carrying on is the opposite of an event, so a
   weather noun followed within two words by "continues" is refused (and asked again). "A gust of wind rips the lantern from its
   hook" and "The wind drops, and Corwin continues down the path" pass.
5. **One invented object came back seven times** ("a small, intricately carved wooden bird or box") and one invented fisherman five
   times, because a new line was compared with only the last 3 directions. The window is 6.

**Still true after the second run.** About half of the natural lines are filler or a retelling of the player's own action (the first
run said all of them were; the rewritten request halved it, it did not end it). If the next run still says so, natural sends nothing:
that removes 40% of the calls and the chapter directive already carries the scene forward. The model also invents named people in its
lines ("a grizzled fisherman, Silas Blackwood"); in `on` mode the Writer would adopt them. And the `stakes` valve still says "some" for
almost everything on this model (2 of 16 setbacks and windfalls switched off).

**Third run, with every fix above in (gemma3:4b 80 turns, llama3.1:8b 20 turns).**

| | first answers usable | exchanges with a usable answer | calls with no JSON | calls in the sidecar format | lines opening on weather |
|---|---|---|---|---|---|
| gemma3:4b, before any fix | 66% | 44 of 80 | 11 of 96 | 1 of 96 | 16 of 44 |
| gemma3:4b, after the first fixes | 80% | 65 of 80 | 19 of 106 | 6 of 106 | 11 of 63 |
| gemma3:4b, now | 89% | 68 of 80 | 0 of 103 | 0 of 103 | 4 of 66 |
| llama3.1:8b, after the first fixes | 29% | 26 of 40 | 20 of 68 (18 of them plain story prose) | 19 of 68 | 5 of 22 |
| llama3.1:8b, now | 83% | 18 of 20 | 4 of 28 (a new shape: the sentence as a key) | 0 of 28 | 2 of 17 |

The llama rows are the proof that the sidecar was the cause and the context fix the cure: in its second run 37 of 68 calls answered as
the Writer (19 in the sidecar format, 18 in plain story prose), and with the Writer's world-update block gone from fate's context
the third run has none. What is left on gemma is 12 refusals of "You studied Dessa's hair ..." on the scripted probe turns (the
rule doing its job; the second try recovered 4 of 10) and the 4B model's own habits: "a flicker of suspicion" five times, an
invented named fisherman again, and one carved wooden crow that the story's own prose established and fate then keeps picking up.
Natural lines are now mostly a person reacting (weather opens 2 of 24), so the idea of making natural send nothing is dropped:
the evidence it was written for is gone. Fate calls cost 3.3 s (gemma) and 6.0 s (llama) next to turns of 19 s and 60 s, the
`stakes` valve still never turns anything off on gemma (2 of 14) and does on llama (1 of 5 here, 7 of 16 earlier).
A last cosmetic fix from this run: 6 of 68 stored gemma lines ended in a closing quote that nothing opened, which is now dropped.

## D-054 — The first real-model checks of the accessory slot, chapter 1 from a premise, and a world from one sentence

The owner lifted the per-run GPU ask on 2026-11-13, so these ran the same evening as the fate preview (D-053), on gemma3:4b and
llama3.1:8b through a local Ollama, on invented stories only. Three results and three defects.

**Accessory slot (D-044): the corpus measurement, default stays off.** The evaluation corpus (33 passages: the 26 older ones, 4 accessory
passages with 6 labelled facts, 3 look-alike traps), temperature 0, one run per cell, validated stage:

| model | accessory facts found, off to on | older facts found of 26, off to on (precision) | look-alike traps, false positives |
|---|---|---|---|
| gemma3:4b | 0 of 6 to 5 of 6 (1 false positive, was 2) | 20 to 18 (0.87 to 0.82) | 4 to 4 |
| llama3.1:8b | 0 of 6 to 1 of 6 | 19 to 18 (0.79 to 0.75) | 3 to 4 |

The slot works on gemma3:4b and not on llama3.1:8b. The prompt line also moves a few older passages, which D-044 said it might: on gemma
one multi-character passage lost both its facts and one state fact was lost while another was gained (net minus 2 of 26); on llama one
state fact was lost. D-044's own gate was "the older slice must not drop", and it dropped by one or two facts out of 26, which at this
size is close to the noise floor but is not nothing. **Decision: the default stays off.** An author with a gemma3:4b reader and jewellery
that matters turns it on per story (`canon: {accessories: true}`). Not done: the second D-044 measurement, a re-read of the fixed
narration-first transcript with the slot on (about 47 minutes on gemma), because the corpus already says llama cannot use the slot and
the default is not changing on this evidence.

**Chapter 1 from the premise (D-051), a real look.** Both models planned "ch-1" at the opening (origin: start, no health row), at a cost of
the planning call only. gemma3:4b wrote a five-event plot dump and, from a premise that said only "you arrive as a stranger", **named the
player** ("Elias finds himself drawn into ..."); llama3.1:8b wrote a shorter, sensible goal with no name. The planner was never told how to
refer to the player, so both instructions now say: use "the player" or the premise's own name, never invent a name, a gender or a
backstory (`PLAYER_RULE`; the Writer reads a chapter goal as fact). Re-run on gemma3:4b: "The player's arrival throws ...", no name.

**A world from one sentence (D-052), a real look.** The sentence "A tidal market town on a saltmarsh where everyone owes the ferrywoman a
favour, and one debt has just come due." made a whole world in 82 s on gemma3:4b and 395 s on llama3.1:8b (3 characters, 8 to 10 pieces,
an opening message). The stage log reads as designed, including a stage that failed once on the 4B model ("items FAILED: no valid JSON"),
was retried and was reported in the done frame. The defect: the JSON shapes the generator shows the model contain `"slug": "kebab-id"`
and `"aliases": ["alt"]`, and the models copied them: four entries from the 4B model (a canon event, a place, an item, a thread) had the
slug `kebab-id` and an item the alias `alt`; the 8B model wrote `kebab-aethera` and `kebab-marshview`. A slug that names nothing makes every
cross-reference ambiguous and lets a second entry replace the first. `_entry_from` now drops a placeholder slug (kebab, kebab-<anything>,
slug, id, slug-id, new-slug) and lets the title make the slug, and drops the alias `alt`. Re-run: every slug was sensible, none started
with kebab.

**A system message after the player's turn made llama3.1:8b open every reply with "assistant".** Seen in the chapter-1 look (llama's
opening and first turn both began with the line "assistant" and a blank line; the soak transcripts, which have no chapter directive, never
did). Isolated with a raw client, 6 replies per shape: [system, user] 0 of 6; [system, user, system] 6 of 6; [system, user, system,
system] 6 of 6; the same words folded into the user turn 0 of 6. gemma3:4b was clean in all four. The engine puts the chapter goal, the
canon card, fate's note and the continuity pass after the player's action on purpose (the end of the prompt binds hardest, D-027), and
the default chapter outline puts one there from the first turn, so every llama3.1 user on Ollama was exposed. `LLM` now folds a trailing
run of system messages into the last user turn (after an assistant turn they become a user turn of their own), so the words stay at
the end of the prompt and the template reads an ordinary exchange. **It is narrow on purpose: a llama-family model on a server on this
machine, and nothing else** (`needs_fold`; `generation: {fold_late_system: true|false}` overrides either way). The first version folded
for every local model. The fate-on soak that followed made that look wrong: on gemma3:4b, which never had the fault, the one run with the
note in the user turn looped in its last third. **That causal reading was too strong and is withdrawn (D-055):** a later run with the
fold off also collapsed, and each condition has a single run. What remains true is smaller and enough: gemma3:4b gains nothing from the
fold, so it is not applied to it; every other model keeps the request as it was. qwen3:4b, deepseek-r1:8b and the Qwen3.5 build were not
tested for the llama fault. Whether a directive in the user turn binds as well as one in a system turn was not measured on llama, only that
the reply stops starting with the role word.

**Tests.** `generator_slugs_test.py` (4), `chapter_distinctness_test.py` case 7 (the player rule is in both instructions),
`llm_late_system_test.py` (5: the fold, the locality check, the llama-only rule, the client with the override, the tool-calling path). 10 and 19 guard
mutations caught.

## D-056 — Web UI sweep: what driving the real app found, what was fixed, and what the comparison with FictionLab and AI Dungeon adds

**Method.** A throwaway home (never the repo's saves or `.env`) with a model profile pointed at a closed port, so nothing could leave the
machine: three invented worlds (one with a very long name), four stories including one of 320 turns and one with an unbroken 170
character word, and a fresh install. Three read-only research agents ran in parallel: one on FictionLab, one on AI Dungeon (public pages
only, no sign-in, no account), one reading our own web code. Then every route was driven in a real browser at 800 and 375 px wide with
scripts that measure rather than look (horizontal overflow, controls with no accessible name, tap-target size, errors). The agents'
claims about our code were checked against the source and then in the browser before anything was changed.

**Verified in the browser and fixed (each pinned by a case in `webapp_smoke_test.py`, 9 to 13; 12 guard mutations caught).**
1. **Data loss.** The builder's "Improve with AI" and "Seed" wrote "✨ improving…" into the premise box, and Back, Save and every
   navigation save whatever the box holds: pressing Back while the model worked replaced the author's premise on disk with the
   placeholder (reproduced; the stored premise became "✨ improving…"). The status now sits beside the field and the value is never
   touched until the model succeeds.
2. **Dead feature, lost form.** "Seed from idea" in the piece editor opened a second dialog into the single modal host, which replaced the
   form; the handler then threw `Cannot set properties of null (setting 'disabled')` and the form (28 fields) was gone. The idea is asked
   for inline now. Writing the test exposed a second defect in the first fix: a row marked `hidden` is shown anyway when a rule such as
   `.row { display: flex }` applies, so there is now a global `[hidden]` rule.
3. **Skip link.** Its href is `#view`, a hash the router does not know, and unknown hashes render the Library: on any other page "Skip to
   content" threw a keyboard user back to the Library. It moves focus now.
4. **No accessible names.** 108 `<label>` elements and not one `for`; 10 of the 11 fields of the world builder and the box you type your
   action into had no name, and dialogs claimed to be labelled and were not. `a11y.js` ties each label to the control beside it whenever
   markup is added (a timer, not `requestAnimationFrame`, which never fires in a background tab) and names a dialog by its heading.
5. **A long unbroken word** (a URL, a path) made a turn 1,211 px wide on a 375 px screen and was cut off at the edge: `overflow-wrap`.
6. **Phone width.** The story title in the Play header was squeezed to 18 px ("D." for "Dice Night"): it has its own row now. Nearly
   every control was under 44 px (341 of 344 on the long story's Play view): stand-alone buttons are at least 40 px, and the small
   icon buttons in the transcript keep their size and get a larger invisible hit area, which a pointer test would have to confirm.
7. `--muted` was used and never defined.

**Verified, not yet fixed (input to the backlog).**
- The first-run probe and the model list ask `http://localhost:11434` and ignore the local profile's own address: a user on LM Studio,
  llama.cpp or a remote Ollama is told "Ollama isn't running".
- The first-run picker lists `nomic-embed-text`, an embedding model that cannot tell a story, as a model to use.
- Settings paints nothing until its slowest call returns (2.4 s here, waiting on the model list); there is no progressive paint.
- Em dashes remain in shipped copy: the showcase world's blurb, the Pieces intro, the first-run picker.
- Read in the code by the audit, not yet reproduced: Escape or a backdrop click discards any dialog's edits without asking; leaving the
  Play view mid-turn and coming back leaves Send doing nothing; swipe-generate has no Stop; a deliberate Stop shows as a red alert; no
  story search; no readable export (a zip backup only); one dark theme and no font-size control (a second theme file is linked nowhere).

**What the competitors add (public documentation and reviews only; neither product was opened, so layout claims are inferred).**
FictionLab: a hover menu on each reply (copy, edit, branch, rewind, regenerate, delete) with regenerated replies you can flip through;
lore entries split into a short "when to use me" description and the text that is injected; an AI Assist box in each creation section with
undo and retry; a font-size, colour and response-length panel; no sampler controls for normal users. AI Dungeon: Do, Say, Story and See
input modes; a Context Viewer on the last reply showing what share of the AI's context each part takes; Used, Stored or Forgotten labels on
memories; Retry with a stack of earlier tries; Erase to here; sampling controls saved per model, and a "Dynamic" model option that hides the
choice from beginners; an account required before the first turn; no world-from-a-sentence generator found. We already have what neither
was found to have: a world from one sentence, a Canon panel that lists what the story holds and lets the author correct it, per-story
fate, and no account.

**Still to do (the plan's Phase C and D).** One table of feature, FictionLab, AI Dungeon, Coderain and a verdict; two rounds of critique
by the three agents; a ranked backlog (P1 confuses or harms a first-time user, P2 friction, P3 nice); then build it in that order with
a browser case per item. Evidence that would change this: a real session with either product (needs the owner's yes to an account),
or a first-time user's recording.

## D-055 — Fate on a real Writer: what steering does over 80 turns, a retracted claim, and why natural is silent

**The soak.** gemma3:4b as the Writer, the scripted player (same moves, same dice, seed 5), squeezed memory (4 verbatim turns), 80 turns
per condition, one run each. The measures are computed from the stored narration: words a turn by third of the run, how many 8-word runs
recur in three or more turns, and how many turns share their first 25 words with another turn.

| condition | words a turn, by third | 8-word runs in 3+ turns | turns sharing an opening | seconds a turn |
|---|---|---|---|---|
| fate off | 262 / 272 / 290 | 10 | 0 | 15 |
| on, every roll steered, note in the user turn (the fold, D-054's first version) | 462 / 499 / 669 | 103 | 11 | 23 |
| on, every roll steered, note as a system message | 473 / 521 / 449 | 9 | 0 | 22 |
| on, natural silent, note in the user turn | 391 / 357 / 458 | 16 | 0 | 21 |
| on, natural silent, note as a system message (the code as shipped), stopped at turn 72 of 80 | 410 / 533 / 1,502 | 866 | 28 | 26 |

**What it shows.**
1. **The Writer does enact the steering line.** Of a line's new words, 57 to 72% appear in that turn's narration against 13 to 15% for
   another turn's line; 41 to 49% of the steered turns copy six or more words of the line verbatim (1 of 63 for unsteered prose).
   The line's first words are almost never the narration's first words (0 to 2 of 63).
2. **Steering lengthens narration in every run**, by about 1.4 to 1.9 times, and costs 6 to 11 seconds a turn here (the call is 3 s).
3. **Two of the four fate-on runs collapsed into a loop in the last third; the fate-off run never did.** In the shipped-code run the
   narration opens, from turn 47 to the end, with the same weather sentence and grows to 1,000 to 2,900 words a turn: the Writer copies
   its own previous paragraph and adds to it. The other collapse was the first run (the note in the user turn). The two runs that stayed
   sound were one with the note as a system message and one with natural silent plus the fold. So the loop is a risk of steering on a
   4B Writer with a short verbatim window, roughly one run in two here, and **neither the fold nor silencing natural was shown to prevent
   it**.

**A claim withdrawn.** The commit messages of 5de6d92 and 42b8a89 and an earlier version of D-054 say the loop needed the note in the user
turn and was cured by the fold's removal and by silencing natural. The fifth run (natural silent, no fold) is the counterexample, and each
condition has one run, so no effect of either change is established. What the evidence does support is smaller: gemma3:4b does not need
the fold, so it is not applied to it; and natural lines are the least informative of the four tiers (about half a person reacting, half
weather or a retelling), cost a model call and add narration length for little, so a natural roll steers nothing.

**Decisions.**
- A natural roll still steers nothing and asks nothing (`SILENT_TIERS`): fewer calls and shorter narration, on the grounds above, not on a
  claim about loops.
- **Fate stays off by default, and should not be recommended with a small Writer for a long story.** The Fate controls say what they do (D-045);
  this entry is the evidence for being careful.
- Not tried, in the order I would try them: a guard in the engine that notices a narration opening with the previous narration's first 25
  words and asks again or trims; a length line in the note ("one beat, not the whole turn"); steering only when the last turns are not
  already long; the same soak on a larger local or a hosted model, where the loop may not appear at all; several seeds per condition.

**Not known.** Why only some steered runs loop; whether the same happens on llama3.1:8b (not run); whether a larger Writer is immune.

**The ranked backlog (consensus after two rounds of critique by the three agents).** P1 confuses or harms a first-time user, P2 is friction,
P3 is nice. Cost is S, M or L against our code. Each item is a small commit with a browser case that fails without it.
- Corrections the critique made to my draft: AI Dungeon does have a zip backup and a read-only Read view (our gap is a readable view, not
  an export); "branch from here" is FictionLab's idea; its memories' edit path is undocumented, not absent; the red-and-orange publish
  checklist is hosted-community machinery (dropped); the lore description and content split has no consumer without semantic activation
  (held); Compact Buttons is dropped (fix tap size instead); the inline discard bar does not cure "Replan Cancel closes the Plan panel",
  because that is the Cancel button, so Replan needs its own inline confirm.

P1, in build order
1. **First run.** Hide embedding models from the picker (S). Let a keyless local server (LM Studio, llama.cpp) pass the gate: only for a
   loopback or LAN address, never for hosted (`ready_test` keeps `no_key`), after checking that `LLM()` accepts an empty key (M). The probe
   and the model list ask the local profile's own address, not a hard-coded `localhost:11434` (M). A connection-test route for a hosted key,
   separate from `/api/ready`, which must never spend tokens, shared with item 7 (M).
2. **Chapter delete:** disable the row on click, as D-013 says (a double click deletes two). S
3. **A deliberate Stop is not an error:** no red card, no "Check settings". S
4. **Dirty dialogs:** Escape or a backdrop click shows an inline "discard your changes?" bar inside the card (not Cancel, not a programmatic
   close); Replan Cancel gets its own inline confirm. Smoke case 8 closes a dirty dialog by backdrop and must be adapted. M + S
5. **Leave Play mid-turn and come back:** Send does nothing and there is no Stop (a module-level busy flag, a per-view aborter). A shared
   in-flight handle, a usable Stop in the new view, a resync when the old run ends with no false "discarded" toast. Same cause as D-012. M
6. **Retry keeps what it replaces.** Today the exchange is deleted first and stays deleted if generation fails. Keep it as a variant, and on
   failure restore it from a snapshot taken BEFORE the rollback (the rollback consumes the single RPG snapshot, D-002, and trims folds,
   invariant 6, so restoring the text alone would desynchronise state from the story), or do it in simple mode only. The variants live in
   memory and a settings save clears them, so the UI says "this session" until persistence (item 18). Then Stop for swipe-generate, which
   today would destroy the exchange. M + M, the second depends on the first
7. **Settings:** paint at once and fill the model list afterwards; a sticky Save; a leave prompt that intercepts navigation clicks and
   popstate (the hash has already changed when `hashchange` fires, and a re-render would wipe the edits); the connection test. M
8. **Copy pass:** about 57 em and en dashes in strings, "quad brain stages", superlatives. S

P2
9. Accessibility remainder: one `aria-pressed` helper for the six segmented controls, focus to the new view on a route change, toast kind not
   by colour alone, labelled icon buttons, the Talk drawer watched by `a11y.js`, `#p-improve` and `applyAI` guarded against a closed modal. S/M
10. Readable transcript export (Markdown from the stored turns, not the raw file with its markers) and find-in-story with `<mark>` inside
    `.turn-body` only (edit indices are DOM positions, so nothing may be added to `#transcript`). A Read view can use the same renderer. S + S
11. Per-turn menu: edit, copy, branch from here (narrator bubbles only: D-006), regenerate; long-press on touch; the branch warnings need a
    null check (`out.warnings.length`). Depends on item 6. M
12. Display settings: font size, and the existing rain switch reachable from Play. S/M
13. One-level undo for the builder's AI assist. S
14. Context panel: each section's percent of the total (the cheapest fix for the most-cited AI Dungeon complaint, moved up from P3). S

P3
15. In-play per-story panel for response length and streaming. M, needs per-story engine config.
16. RPG sheet below 900px (tabs) and the Talk drawer width. S/M
17. Test growth with each item, a blockable model stub so items 5 and 6 can be tested, a phone-width pass over every route. M
18. Persist swipe versions across a reload. L: seven places invalidate swipe state.
19. Structure: modals out of `play.js` (S), dismantle its 785-line closure (L), merge the two character editors (L).
20. Continuous (debounced) autosave while typing in the builder (FictionLab does; ours saves on leaving). S

Held or dropped: the lore description and content split; the red-and-orange checklist; Compact Buttons. Not taking: accounts, a community
feed, tiers, voice, images, Do/Say/Story/See modes, a slash menu, automatic background lore (an explicit "generate this entry" button is not
excluded).

**Progress on the D-056 backlog above (2026-11-14).** Built, each with browser or unit cases that fail without it: items 1 to 5, 7 and 8.
Left: 6 (Retry keeps what it replaces, then Stop for swipe-generate) and everything from P2 on.
- 1b, a keyless server on this machine or network. `/api/ready` demanded a key for any hosted-style profile, so LM Studio and llama.cpp users
  (no key, a loopback or LAN address) sat at the first-run screen until they typed a made-up one. `is_lan` in `coderain/llm.py` accepts
  loopback, private and link-local addresses and `.local` names and matches the WHOLE host name, so `localhost.example.com` and
  `192.168.1.5.example.com` still need a key. `config.build_profile` already sent a placeholder key, so the client needed no change.
- 1d, a connection test. `POST /api/connection/test` reads the provider's model list (`GET <base>/models`, no tokens) with the typed key or
  the saved one, and answers in words: refused, unreachable, redirected (not followed, so the key is never sent on), no model list, other
  error, or connected (and whether it lists the model). The key is never stored by it or sent back; `/api/ready` stays off the network
  (pinned by a test). Settings has a "Test connection" button. The first-run key is tried BEFORE it is saved: a refused, unreachable or
  redirecting server is reported and not saved, and the same button then reads "Save anyway"; a provider with no model list is not held up.
  The button used to say "Checking..." and check nothing. A whitespace-only field no longer hides the saved value (found by the test).
- 7, Settings. It paints as soon as the settings are in and fills the model dropdowns when the list arrives (a 250 ms race; a failed list
  is a line on the page and used to break the whole page; a page already left ignores the late answer). The Save bar is sticky. Unsaved
  edits are tracked: typing, selects and checkboxes through `input`, the segmented buttons through a click; the profile name and list and
  the rain switch are not edits. Leaving asks "Leave without saving?" for a topbar click, the browser Back button and closing the tab. The
  hash has already changed when `hashchange` fires and a render would wipe the edits, so Stay puts the old hash back with `replaceState`
  and renders nothing. A second navigation made while the question is open replaces it (one modal host), so only the last is decided. The
  page registers its guard with `nav.js` and `render()` clears it, so a failed repaint cannot leave one behind. The builder keeps its own
  autosave on leaving and does not use this.
- Evidence that would change this: a user who edits Settings often and finds the question tiresome (then autosave, as the builder does);
  a provider whose model list needs a different path or header than `<base>/models` (then the test reports "no model list" and the first
  turn remains the real check).

**Progress, 2026-11-21: items 6 (D-057), 9 to 14 are built.** Left: P3, items 15 to 20. Each item below has smoke cases that were checked by
breaking the fix in a copy of the repo (100 or so mutants in all, every one caught in the end; the few that slipped through, and one that was
equivalent, are named).
- 9, the accessibility remainder. The audit was run in a real browser first: segmented buttons carried no pressed state (the "on" class is now
  mirrored into `aria-pressed` by `a11y.js`, including when a view flips the class in place), focus fell to `<body>` on every route change (it
  now goes to the new page's heading, only on a change of route and only when nothing holds it, so an open dialog keeps its focus), a toast's kind
  was a border colour (a glyph for the eye and a word for the ear now), a pencil on every turn was a bare glyph, as were the draft button, the
  plan row buttons, a chip's remove button and the memory textarea (named; the plan buttons carry the chapter number), and the Talk drawer, built
  on `<body>` outside everything `a11y.js` watched, had no names and would never get any (it names itself and is watched). One defect was not on
  the list: an AI answer for a piece form could land in a DIFFERENT piece. The model answers later; by then the dialog can be closed and another
  piece's form opened into the same host with the same element ids, and the answer was written into it and its buttons reset. The answer is now
  dropped, the reader is told, and the buttons it touches are the ones held when the request started.
- 10, a readable export and find in the story. `coderain/readable.py` and `GET /api/saves/{slug}/readable` give the stored turns as Markdown (the
  title, "You:" quotes, the narration), not the transcript with its marker comments; "Export text" is on the story card, and the zip stays the
  backup that imports again. `webapp/js/find.js`: highlights are `<mark>` elements inside `.turn-body` only and nothing is added to or removed
  from `#transcript`, because the pen and retry address a turn by its position there; closing merges the text nodes back; a search runs again
  when turns come or go; typed text is literal. A match is found inside one run of text, so a phrase that crosses a bold or italic edge is not.
- 11, the per-turn menu (`webapp/js/turnmenu.js`): Edit, Copy text, Branch from here and Regenerate on a "..." button and a touch long press.
  Branch is offered on replies only (a fork that ends on the player's own action has no reply to continue from, D-006) and Regenerate on the last
  reply only. Edit, Branch and Regenerate wait while a reply is being written. Copy takes the turn's own markdown. The branch route's reply was
  read as `out.warnings.length` with no guard in the old Branch button (the failure was swallowed into a toast) and is guarded in both places.
- 12, a Display dialog on the Play page (`webapp/js/display.js`): the text size (new) and the rain switch (reachable only from Settings before).
  Both belong to the browser, apply at once and have no Save, so closing never asks to discard anything.
- 13, Undo AI for the world builder's premise, introduction and world fields: one level per field, dropped when the author types into the field
  (it would throw their own words away with the AI's), when it is used, and never offered after a failed request.
- Found on the way: coming back to a story whose turn was still generating released Send before the transcript was repainted from the store, so
  for one request Send was live over a half-finished exchange. The order is now repaint, then release (commit 1c4b37b); case 29 had been failing
  about one run in ten on it. The mutation runs that exposed what a test could not see: a stale `watchLabels` first paint, a seed button reset
  by another form's answer, a find that marked the version bar, and two long-press cancels (a lifting and a moving finger) that were checked
  together, so one open menu hid the other's failure.

**Later the same day: items 16, 17, 18, 20 and the small part of 19 are built.** Left: 15 (a per-story response length: it needs the length to reach three call sites and the
trinity writer, and streaming is not a setting at all) and 19's two large parts.
- 20, autosave in the world builder: a pause of 1.2 s after the last key saves the main fields, one save at a time, none while the title is blank
  (the route would blank the world's name), a failure is a line the next edit retries, an AI answer and Undo AI are saved too. The first version had a
  bug that a flaky smoke case found: the pause timer of a builder that was left fired while ANOTHER world's builder was open and, looking its fields
  up by id, saved that page's text to the world it belonged to. The fields are held when the page is built; a case opens two worlds in a row.
- 16, the RPG sheet below 900px was `display: none`, so a story with mechanics had no way to show its own sheet on a phone. It is a Story and a Sheet
  tab now (arrow keys, a roving tab stop), side by side above 900px, none without mechanics; the Talk drawer is a side panel on a tablet.
- 17, the phone-width pass is one smoke case over every route and every play dialog at 375px: nothing off the right edge, buttons 40px, fields and the
  first-run link 32px, a strip that scrolls sideways on purpose exempt. It found a chapter title box 25px tall and a first-run link 17px tall, and it
  found that the RPG sheet's section headings had em dashes (the dash sweep had never seen an RPG story): plain upper case now.
- 19, the small part: the three dialogs that used nothing of the play view but the modal helpers left `play.js` for `outline.js` (the chapter
  plan), `context.js` (the context inspector and what the story has cost) and `folds.js` (the fold review). A pure move, 1288 lines to 999.
  The fold review had no browser case, so smoke case 51 opens it, pages, saves, refuses an empty summary, and goes plan > Characters > back.
  What is left of 19 is the dialogs that close over the view's own state (Memory, Canon, Branch) and the 785-line `renderPlay` closure; both
  need the view split by what it owns, not by what it draws, and that is the large part.
- 18, the versions of the last reply (a swipe, or a retry that kept what it replaced) lived only in the engine's memory, so a restart or a settings
  save (which drops every engine) left the page saying "Version 1 of 1" over a reply that had had three. They are kept in `swipes.json` beside the
  transcript and the file is TRUSTED only while it still describes the transcript: the same number of turns, the selected version is the text of
  the last turn, the tail hash matches, the shape is what the engine wrote (a list of at most 12 texts and a position inside it). It is never
  invalidated from the seven places that change a story, and a file that does not fit is ignored, never repaired. A consequence that is deliberate:
  undoing a LATER exchange puts the transcript back exactly as the file describes it, so the real versions of the reply it exposes are offered
  again (the live engine used to forget them at the new turn; nothing about them was wrong). A write that fails is a line in the health log and
  costs the turn nothing. One file, so a new reply's first swipe replaces the earlier reply's versions on disk. What would change this: a report
  that versions of an old reply appear when they should not (the hash would then need the exchange's player text too).

## D-057 — Retry keeps what it replaces, and a failed or stopped retry puts the exchange back

**What was wrong.** A retry deleted the last exchange first and regenerated second. A model error, the Stop button or an empty reply ended
the regeneration early and left the story one exchange shorter, with the player's own action gone too. Swipe-generate did the same, so
Stop there destroyed the exchange. The player could not get back what they had just read.

**Why the text alone cannot be put back.** Rolling an exchange back is not one change. It trims the transcript, resets the world state,
drops ledger records, un-reveals things and trims folds (invariants 3 and 6), and the engine holds ONE undo snapshot that the rollback
consumes (D-002). Restoring the two turns would leave all of that out of step with the story.

**What was built.** `coderain/retry.py`. The whole save is copied before the rollback (`Checkpoint.take`) and copied back when the
regeneration does not put a narrator turn in the exchange's place (`took_hold`: the same transcript length for a narrator tail, one more
for an orphan player action). The engine's in-memory undo record (`_pre_turn_*`, `_rpg_events`, `_swipes`) is put back with it, so an
Undo afterwards still rolls the exchange's mechanics back. Two files are never rolled back: the health log (a failed attempt must stay
visible, invariant 2) and the usage log (the tokens were spent). `.snapshots` is neither copied nor touched. Restoring copies the
checkpoint over the save first (the save is whole again after that step) and removes what the failed attempt added last. It cost 17 ms
to take and 15 ms to restore on an invented 3,000-turn, 5.3 MB save.
- `Engine.retry_exchange` and `Engine.swipe_exchange` wrap the regeneration in a generator, so the checkpoint is taken when the stream
  starts and every way out is covered: an exception, Stop (the pump closes the stream, which raises `GeneratorExit` after the inner
  generator's own cleanup), and an empty reply, which raises `RetryRestored` so the stream says so instead of reporting a shorter story as
  success. The route and the pump carry that error's own wording and code to the browser.
- In a story with no mechanics a retry runs as a swipe: the replaced text stays as a variant to go back to (`◄`). In a story with
  mechanics it does not, because a variant carries prose only and the dice and state of the first try would no longer match it; it is
  still put back on failure. The save payload now says which version is showing (`swipes`), so a retry and a page reload both
  read "Version 2 of 2". The label says earlier versions are kept until the next move. They live in memory and a new turn, an edit or a
  server restart clears them (D-056 item 18 would persist them).
- The client tells the reader: a Stopped note or an error card adds "Your earlier version is back." when the story on screen is the
  length it was, and an empty reply is its own card ("Nothing new came back"). Swipe-generate got its Stop button.
- Found on the way: `Engine.regenerate` took an empty transcript for "retry the opening" even when there was a player action to replay,
  so retrying the first exchange of a story with no opening turn dropped the action. It asks for the opening only when there is none.

**Verified.** `tests/retry_keeps_test.py` (11 cases: byte-for-byte restore through a model error, an empty reply and Stop; the two
logs kept; a stray file removed; mechanics; an orphan action; swipe-generate; the opening; `.snapshots`; the decision function),
`tests/retry_api_test.py` (the frames and the saved story through the real routes and pump), and browser case 29 in
`webapp_smoke_test.py` (a retry keeps and shows the old text; a failed, empty or stopped retry and a stopped swipe leave the story as it
was and say so). Guard mutations are listed in the commit.

**Limits.** Variants are prose only and session only. A restore also reverts anything else the failed attempt wrote to the save (a fate
line, a canon note), which is the point; the canon reader runs after a SUCCESSFUL turn, so it never sees a failed one. The first retry in
a story with mechanics still has one undo level. Evidence that would change this: a save so large that the copy is felt (then copy only
the files a rollback touches), or a player who wants every retry kept in a story with mechanics (then variants would have to carry the
state and the ledger records with them).

## D-058 — Relationship and who-knows-what probes for the scripted player (`python -m soak play --probe-set graph`)

**Why.** A knowledge graph (or an edge table derived from the ledger) would help with relationships, with questions that cross two
character sheets, and with "who knows what". The case for it rests on studies of question answering over books and short templated
scenes (one reported witness records cutting knowledge leakage from 60.7 to 0 points); nobody has measured it for a story played for
thousands of turns, and nothing measured whether the store we already have fails those questions. The plan's seventh principle is to measure
before believing, so the probe comes before any graph.

**What it is.** `soak/graph_probe.py`, wired into the scripted player (D-048). With `--probe-set graph` (or `all`, which keeps the look
probes too), the ties and possessions are stated where the engine keeps them, the player whispers one secret to one character on turn 3
and another to a different character on turn 5, and from turn 16 every `--graph-every` turns (default 4) it asks a question. Ties are each
character's `relationships:` line (both sides of every tie: a sibling pair, a debt, a cousin pair) and possessions are `items.md` entries
that name their holder. The kinds rotate and each walks its own list:
- **relation and possession (one hop):** who is Ottoline's brother, who carries the brass lamp key. The question names the character or the
  item that holds the fact, so name-keyed activation should put it in the prompt.
- **twohop:** who is the brother of the person who carries the brass lamp key. The question names nobody whose entry holds the second half,
  so something has to follow the item to its holder. This is the question an edge table would answer and name-keyed activation may not.
- **recall:** ask the character who WAS told what the player told them. It is the control for the next kind.
- **leak:** ask the characters who were NOT told. A single narrator writes everyone, so a secret in the prompt can come out of any
  mouth; the probe asks whether it does once the telling is far outside the verbatim window and only memory can carry it.
Scoring is a plain string check, no judge: `held`, `wrong`, `mixed`, `invented` or `none` for a hop (the asked character and the middle
of a chain may be named), `held` or `none` for recall, `leak` or `clean` for leak. A hop is scored on what the characters SAY (the quoted
speech), because the first real run showed a correct answer scored `mixed` whenever the narration also named the others in the scene;
when nothing said names anyone the whole narration is read, and a secret is read in the whole narration wherever it was written.
`invented` is a character saying a made-up name (two or more capitalised words that name nobody in the cast): a 4B Writer asked who owes
money produced an NPC that is not in the story and kept using him, and that is a different failure from naming the wrong member of the cast. Secrets are two invented phrases ("north beacon", "marrow
gull") that a narrator will not produce by accident, and a test pins that no question contains its own answer or its token, that a leak
probe never asks the one who was told, and that every secret is told to exactly one character. The summary adds the counts per kind,
`one_hop_right`, `two_hop_right`, `recall_rate`, `leak_rate`, and `leak_meaningful`, which is false when nobody recalled: a store that
forgets the secret entirely looks leak-free for the wrong reason. The look probes are unchanged and are still the default.

**What was in front of the Writer.** Every graph row also records, from the messages the Writer actually received (the final user message,
which is the question itself, is left out because it can contain the evidence words), whether the answer's evidence was in the prompt
(`seen`) and whether it was in memory's part of it, the system message (`seen_memory`). That is the measurement the decision needs. When
the fact was NOT in the prompt the failure is retrieval, and better structure (a graph, an edge table the retrieval can walk) can help;
when it WAS in the prompt and the Writer ignored it or invented around it, the failure is faithfulness, and a graph cannot help. For a
leak probe it records whether the secret was in the prompt at all: a leak needs an exposed secret, and "who witnessed what" metadata exists
to make it unexposed. The summary splits the rates on these flags (`right_when_evidence_in_memory`, `right_when_not`,
`leak_when_secret_in_prompt`, `leak_when_not`, `recall_when_secret_in_prompt`). Evidence is an exact phrase from the sheets or the secret's
token, so a fold that paraphrases a fact counts as not seen; that undercounts what memory carries and is the safe direction for a case
that argues for retrieval, not against it.

**`--facts stated|none`, and what the first design taught.** The first design put the ties in the sheets' free text and gave the items
obvious holders (the lighthouse keeper keeps the key, the salt trader carries the ledger, the customs officer holds the stamp). A first real
run on gemma3:4b (120 turns, squeezed memory: window 4, budget 5000) found both mistakes. (1) After 120 turns the final `characters.md`
held no "Ties" line at all, and none of the 17 hop probes had its evidence in the prompt, not even at turn 16: the folds rewrite a sheet's
body, and a `relationships:` line is "managed" (an omission by the rewrite is read as an intentional clear), so a fact written as free text,
or left out of a rewrite, is gone. That is the same mechanism that drifted a hair colour in the long real story, now seen on ties. (2) The
one-hop questions were answered right 11 of 12 times with the evidence ABSENT, because every answer was guessable from the role, so that
number measured nothing. The possessions now run against the roles (the tavern keeper carries the lamp key, the mudlark boy holds the
ledger, the lighthouse keeper keeps the stamp), a test pins that no holder is the role's obvious guess, and `--facts none` plants nothing
and asks the same questions, so what the Writer gets right there is the guessing and inventing baseline to subtract.

**`--ask plain|open`.** The first run asked the bare question and gemma3:4b narrated around it (about 400 words a turn, no stated answer),
which hides both a right answer and a leak. `plain` (the default) adds "I want a straight answer, in a single sentence" to each question
(37 words a turn, a direct answer); `open` keeps the bare question so the two can be compared on one model.

**The offline writer** answers every question truthfully, which only proves the harness runs. `--stub-knowledge leaky` also lets everyone
say the secret and `wrong` names the wrong person and forgets it, so a test can show the scoring notices.

**How to read a real run (agreed before any number exists).** The decision is about structure, not about how clever the model is, so
compare within one run: one-hop against two-hop (the same facts, the second needs a second entry), and recall against leak. If two-hop is
far below one-hop on the same model, activation by name is the bottleneck and an edge table that the retrieval can walk is worth
building. If the leak rate is high while recall is not, "who witnessed what" metadata is worth building. If one-hop is itself low, the
problem is the reader or the sheets, and a graph would store the same mistakes. If both gaps are small, we do not build it. A run is
small (27 probes in 120 turns, 5 or 6 per kind), so repeat over seeds and more turns before believing a difference of a few points, and
ask the same questions of more than one model (the Writer is the part that varies).

**First results (2026-11-19).** gemma3:4b as the Writer AND the fold model, memory squeezed (window 4, budget 5000), plain wording, 120
turns, 27 probes a run: seeds 5 and 6 with the facts stated, seed 5 with `--facts none`. Scored with the current scorer (rows keep the full
text, so earlier runs can be re-scored).

| | facts stated (54 probes) | no facts (27 probes) |
|---|---|---|
| one-hop answered right | 9 of 24 | 0 of 12 |
| two-hop answered right | 3 of 10 | 1 of 5 |
| a made-up name said, hop questions | 9 of 34 | 9 of 17 |

What was in the Writer's prompt (memory's part), with the facts stated:
- possession (an item entry that names its holder): the evidence was there **12 of 12** times, and the Writer was right **6 of 12**. In
  the wrong cases it gave the role's obvious guess with the contradicting fact in front of it.
- relation (a `relationships:` line): the evidence was there **2 of 12** times. In the final save of the last run **none** of the six
  characters still had a `relationships:` line, while all three item entries were intact: the fold rewrites a character's attrs, and a
  `relationships:` line the rewrite omits is read as an intentional clear (the code says so), but nothing rewrites items.md.
- two-hop: the evidence was there **0 of 10** times. Naming an item activates the item; nothing follows it to its holder's entry. The
  three right answers had no evidence in the prompt: they repeated an earlier, correct one-hop answer that had entered the story.
- with the evidence present, all hops together: right 8 of 14. That is the ceiling a better store could lift this model to, and it is low.
- recall: 0 of 10 (the secret was in the prompt for 3 of the 10, and the told character still did not say it). leak: 0 of 10, and the
  secret was in the prompt for **0 of 10** leak questions: it stayed with the entry of the character who was told, so it was never
  exposed to the others. Nothing to fix there yet, and `leak_meaningful` is false for the same reason.
- The Writer invents a person and keeps using him (a different one in each run): a made-up name was said in 9 of the 17 hop answers of
  the control, and in 9 of 34 with the facts stated. It spread into the recall and leak answers too, because the story's own memory
  carried it forward.

**What this says about a graph.** Not "a graph is better". There are three different failures and a graph database fixes none of them by
itself. (1) Storage: a model-owned rewrite erased the ties, the same mechanism as the hair colour that drifted. (2) Retrieval: the second
hop is never reached, which is a link-following problem. (3) Faithfulness: with the fact in the prompt a 4B Writer was right 57% of the
time, and no store changes that. The two things worth building, if anything, are small and code-owned: ties and possessions recorded in the
ledger (a relationship slot written by code, so a fold cannot clear it, as identity already is in the canon ledger, D-017 and D-018), and activation that follows a named
item or character to the entries it links to. Putting the line in the Scene State Card after the player's action is the lever for (3) that
identity already uses (D-027). Then run THIS probe again: relation evidence should reach 11 or 12 of 12 and two-hop evidence most of 10,
and only the gap that remains after that says whether anything more graph-like is needed. There is no case for "who witnessed what"
metadata yet, because the secret was never exposed.

**Not done.** One model, two seeds with the facts and one control, 27 probes a run: a difference of a few points is noise, and the
conclusions above rest on the evidence counts (12 of 12, 2 of 12, 0 of 10), which are large and agree across seeds. A second Writer was
not measured (llama3.1:8b ran at 53 s a turn on this card and was stopped). Evidence is matched by slug and relation within 80 characters,
so a paraphrase with neither would count as not seen. The probe asks for a Writer that answers in character, so a model that refuses or changes the subject
scores `none`, which the summary shows separately from `wrong`. Control for the verbatim window is by construction (the first question
is 11 turns after the second secret, with a window of 4), not by a second run with the window wide open.

**Tests.** `soak_graph_probe_test.py` (9 cases: the schedule, the fairness of every question, the scoring table, the evidence and the
invented-name checks, the facts (each tie on both sides in the engine's own parser, each possession against its role, every expected
answer derived from the planted facts), a truthful run with the `--facts none` control, a leaky and a wrong run, both families together,
the summary); `soak_play_test.py` is unchanged and still passes. About 55 guard mutations broken in a repo copy, all caught (three equivalent
or untestable lines were removed along the way).


**Correction (2026-11-19, found while measuring D-059).** The probe read "the last model call of the turn" as the Writer's prompt
for its evidence flags (`seen`, `seen_memory`). A fold runs right after a turn and makes model calls of its own, so on a fold turn the
flags described the lore-keeper's prompt. Every two-hop question falls on a fold turn (the probe's cycle of 20 turns and the fold's
cadence coincide), and in all three runs `seen` was 0 on exactly those five turns. The offline stub never folded, so no suite saw it.
What this withdraws: "two-hop evidence reached the prompt 0 of 10 times" and so the claim that retrieval is a separate failure (the
second hop is never reached); that figure is unmeasured, not zero. The "right when the evidence was not in memory" side of the split
is also contaminated, because it contains the two-hop rows. What stands, because those questions were never on a fold turn: every
question's verdict (held, wrong, mixed, invented, none), the one-hop evidence counts (relation 2 of 12, possession 12 of 12), the final
saves holding no tie, and the recall and leak results. The storage failure and the one-hop faithfulness gap are therefore still real;
the retrieval failure is an open question. The fix is `writer_call` (the Writer's call is the one whose last user message is the
player's action, picked before the fold runs) with a stub that folds (`--stub-folds`); see D-059.


## D-059: Ties a fold cannot clear, and a pass that follows holders and ties one hop

**Why.** The graph probe (D-058) found three separate failures behind "who is her brother" and "who is the sister of the person who
carries the key". Storage: a `relationships:` line reached the Writer's prompt in 2 of 12 questions about it, because the fold hands the
lore-keeper model the current entry and keeps what it writes back, and `merge_entry(rewrite=True)` read a missing line as "these ties ended".
Retrieval: D-058 reported two-hop evidence in the prompt 0 of 10 times, and that figure was a measurement error (the correction at the end
of D-058), so the claim "name-keyed activation never reaches the second hop" is unproven. It is still plausible, since activation finds an entry only
when the story names it and the answer sits one link away, which is why the pass below exists, but it is a hypothesis to be measured with the
fixed probe, not a finding. Faithfulness: with the fact in the prompt a 4B Writer was right 8 of 14 times. This entry fixes storage, builds a pass
for the retrieval hypothesis (off by default) and does not touch faithfulness.

**What changed (two pieces).**
1. **Ties are not cleared by omission.** `merge_ties` (coderain/memory.py) decides the `relationships:` line after a fold. A rewrite that leaves
   the line out keeps every tie; a rewrite may add a tie to someone not yet on the line and give a note to a tie that has none; a tie to the
   character itself is refused. A rewrite may NOT change a note already on file. The first version let it, and the first real run with it
   showed why that is wrong: "her brother" came back as "his sister" (the same tie from the other person's side), two cousins as "counselor",
   and a tie nobody planted appeared. First write wins, as for a character's looks. A tie the story really changed is an edit of the file. A
   wrong tie a model ADDED stays until someone removes it by hand; that is the cost of not letting a fold clear ties, and a tie to a name that
   matches no entry (the fold may name a person it promotes later in the same pass) is not refused because of that. Ties are keyed by the other person's slug, so "Hollis Wren" and
   "hollis-wren" are one tie. Bounds: at most 16 ties and 800 characters (the fold's own line bound); a new tie that does not fit is left out and
   an old one is never dropped to make room; a hand-written line already past the bound is neither cut nor grown. Removing a tie is an edit of the
   file, which stays the truth (invariant 7), and a tie removed by hand does not come back. This is always on: it fixes a loss, it does not add
   anything to a prompt. `status` and `when` are still cleared by a rewrite that omits them.
2. **A pass that follows one hop from what activated** (`MemoryStore._follow_links`, `memory: {follow_links: true}`, OFF by default). An activated
   item leads to its holder (an item's optional `holder:` attr, a slug or a name or an alias), an activated person to the people in their ties.
   Each followed entry is ONE bounded line (name and slug, then its ties with the other person's name beside the slug, then a little of what it
   is), in its own "Linked to what is in play" section at the priority of activated lore. Depth 1: what was followed is not followed again. Not
   followed: a hidden entry, one already in the prompt in full, an entry its own gates hold back (`delay`, `chance: 0`, `triggers_not`), and
   anything past 4 per source or 6 a turn. It charges the lore budget exactly for the line it shows. A followed entry is not also printed as a
   `links:` one-liner or recalled again. Everything it reads is the files and the text so far, so a retry follows the same links (invariant 5).

**A deviation from what I proposed.** I said "ties and possessions go into the ledger". They do not. The canon ledger exists only when
`canon: shadow` is on (it is off by default), and the loss was in the merge that every story runs, so a ledger record would have left the default
path unfixed. The merge rule gives the guarantee ("a fold cannot clear it") for every story. What the canon ledger would add, an undoable and
hash-chained record plus the card after the player's action, is the next lever for faithfulness and is not built. A possession is the item's
`holder:` attr, stated by the author; no fold writes it, so no fold loses it, and it can go stale when the story moves the item (the canon card's
`state.held` is the live tracker, and the follow pass shows what is on file).

**Measured (2026-11-19, the fixed probe).** gemma3:4b as the Writer and the fold model, window 4, budget 5000, plain wording, 120 turns, 27
probes a run, `prompt_missing` 0 in every run. Two runs with the pass on (seeds 5 and 6) and one with it off (seed 5, the same code otherwise:
the tie rule and the `holder:` attr are in both). D-058's figures for the same seeds come from the old code and the flawed capture.

| | pass on, s5 | pass on, s6 | pass off, s5 | D-058 (old code), s5 and s6 |
|---|---|---|---|---|
| planted ties kept as planted in the final save | 6 of 6 | 6 of 6 | 6 of 6 | 0 of 6 (last save) |
| tie evidence in the prompt (relation questions) | 6 of 6 | 6 of 6 | 6 of 6 | 2 of 12 |
| possession evidence in the prompt | 6 of 6 | 6 of 6 | 6 of 6 | 12 of 12 |
| two-hop evidence in the prompt | 5 of 5 | 5 of 5 | 3 of 5 | not measured (the flaw) |
| one-hop answers right (12 asked a run) | 10 | 9 | 7 | 9 of 24 |
| two-hop answers right (5 asked a run) | 1 | 4 | 0 | 3 of 10 |
| a made-up name said in a hop answer | 0 of 17 | 0 of 17 | 6 of 17 | 9 of 34 |
| right when the evidence was in the prompt | 11 of 17 | 13 of 17 | 7 of 15 | 8 of 14 |

What it says. The tie rule works: every planted tie is still on its character, with its planted note, after 120 turns, and the question
that names a person finds the tie every time. The pass, on this evidence, does what it was built for and more: it puts the second hop's
evidence in the prompt every time (5 of 5 twice, against 3 of 5 without it, the three being turns where recent narration happened to name
the holder), and the answers follow, with the made-up names gone (0 of 34 against 6 of 17). The faithfulness gap D-058 described is
narrower with the Linked lines (24 of 34 right with the evidence there against 7 of 15), which may be the names beside the slugs
("Ottoline Pike (ottoline-pike): his sister") as much as the extra evidence: this experiment cannot tell those apart.

What it does not say. It is three runs of one 4B model, one control seed, 12 or 5 probes a cell: a difference of two or three answers is
noise, and the seeds differ from each other by that much (two-hop right 1 of 5 against 4 of 5 with the pass on). The consistent direction
across every row is the evidence, not any one cell. No second Writer was run.

Two things the new runs show that were not visible before.
- The model ADDS ties nobody planted. Counted in the final saves: 14 (s5, pass on), 3 and 3. Eight of the 14 were the same person's slug
  written twice ("hollis-wren-hollis-wren: her brother"), a copy of a tie already on the line; those are now collapsed (`_undouble`, tested
  offline against these shapes, not re-measured on a model). The rest are model inventions (cousins who are not), which first-write-wins cannot
  stop and which the pass will repeat. They are the cost of not letting a fold clear a tie.
- Who-knows-what has a first signal. A leak question was answered by someone who was never told in 2 of the 4 cases where the secret was in the
  prompt, and in 0 of 11 where it was not (D-058 saw the secret in the prompt for 0 of 10 and concluded there was nothing to fix; with the
  tie rule and the pass the secret reached the prompt more often). Four cases is nothing to build on, but it is the first time the
  witness-metadata idea has any evidence behind it. The mechanism is visible in the final saves: where the secret was in the prompt it sits in the
  shared summaries (`memory/scenes.md`, `arc.md`, `facts.md`, `timeline.md`, in one run also a character's own sheet and a thread), which are in
  front of whoever is asked; in the seed-6 run it is in none of them, and there was neither recall nor leak.

**Default.** The shipped default stays off, with a recommendation: turn it on (`memory: {follow_links: true}`). One more seed pair and a second
Writer would justify flipping it for everyone; the cost to a story is at most six short lines a turn. (D-061 ran that seed pair and a second Writer: it
did not justify the flip, and the recommendation to turn it on is withdrawn.)

**Defaults, and what would change them.** The merge rule is on. The follow pass is off until a measured run says it helps; the probe takes
`--follow-links` and changes nothing else. A stale tie in a real story (a tie the story ended that no one removed) would call for an explicit
"ended" marker in the fold's output schema. A crowded scene where the Linked lines push out something that mattered would call for a lower cap or
a higher priority number.

**Not built.** Reverse following (a person to the items whose `holder:` is them), a tie's direction (the notes are free text, so "his sister" is
shown as written), witness metadata (the probe found no leak, D-058), and the card line.

**Tests.** `ties_kept_test.py` (14 cases) and `link_follow_test.py` (16 cases: off is the baseline, an item to its holder, a person to their ties,
one line for two sources, depth 1, already in the prompt, hidden, the three gates, the caps, name and alias resolution, the player, the
budget arithmetic to the character, no second copy, determinism, the engine switch, the line's shape). `soak_graph_probe_test.py` pins the
`holder:` attr, `--follow-links`, and (case 9) that a question's evidence is read off the Writer's own prompt on a fold turn, with a stub that folds
and sends the fold's calls through the same `stream()` a real run uses (the test fails with the old "last call" capture). 50 guard mutations broken
in a repo copy, all caught; the pass found one gap in my own test (a duplicate one-liner of a different shape), one wrong removal of mine (a branch I
took for redundant that handled a self-tie), one redundant bound (a note only ever lengthens a line) and one equivalent mutant of the probe fix. One older suite
encoded the rule this entry replaces, `phase3_sweep_test.py` A-H2 ("relationships dropped, not re-emitted"); it was changed with the
reasoning written into it, not to make it pass.

## D-060: Gemma 4 E4B (heretic) as Writer and as reader, against gemma3:4b (graph probe and reader corpus; the transcript read, look probe, refusal count and second control seed are in D-061)

**Question.** The Gemma 4 E4B heretic build (`hf.co/mradermacher/gemma-4-E4B-it-heretic-GGUF:Q4_K_M`, the same weights as the ablated repo the owner linked, pulled 2026-11-19) loads in 3.34 GB and answers fast. Is it a better Writer or reader than gemma3:4b, the default?

**Two things about the instrument first.**
- It thinks when asked nothing. Native `/api/chat`, one passage: thinking unset 9.0 s, 459 tokens, 1369 characters of reasoning; `think: false` 0.7 s, 52 tokens, the same claims. The app is not affected, because the canon reader sends `think: false` by default (D-040). `python -m soak scribe` sends nothing unless `--think off` is given, and a first smoke run without it took 11.7 s a passage for that reason. Every reader number below was run with `--think off`.
- The Writer path does not think. Over `/v1/chat/completions` five request variants returned no reasoning and completion tokens that match the visible text, so the Writer runs are fair as configured. It does write about twice as much: 250 to 272 words a turn at `response_length: medium`, against 119 for gemma3:4b, which is why a turn takes 22 s and not 11.

**Reader, invented corpus** (`python -m soak scribe --split all --think off`, 33 passages, all ok, 201 s wall, validated stage):

| | recall | precision | identity recall / precision | accessory recall (with the accessory prompt) | sequence setups that produced no claim |
|---|---|---|---|---|---|
| Gemma 4 E4B heretic | 0.59 | 0.61 | 0.73 / 0.80 | 1.00 | 6 of 12 |
| gemma3:4b | 0.62 | 0.74 | 0.82 / 1.00 | 0.83 | 0 of 12 |
| llama3.1:8b | 0.59 | 0.66 | 0.82 / 0.82 | 0.17 | 1 of 12 |

With the accessory prompt on, overall recall is 0.72 and precision 0.70 for Gemma 4 (gemma3:4b 0.72 and 0.77). Where the setup did produce a claim it caught the change (1 of 1, none silently committed), but a setup that produces nothing cannot test a contradiction, and that happened in half the sequences. Not a better reader here.

**Writer, graph probe** (120 turns, seeds 5 and 6 with `follow_links` on, seed 5 with it off, plain ask, facts stated; code 25825a2; the gemma3:4b rows are the D-059 runs re-scored with the same scorer):

| | Gemma 4: s5 on / s6 on / s5 off | gemma3:4b: s5 on / s6 on / s5 off |
|---|---|---|
| one-hop right (12) | 8 / 6 / 2 | 10 / 9 / 7 |
| of which relations held (6) | 5 / 4 / 2 | 4 / 5 / 3 |
| of which possessions held (6) | 3 / 2 / 0 | 6 / 4 / 4 |
| two-hop right (5) | 2 / 2 / 1 | 1 / 4 / 0 |
| evidence in the Writer's prompt (17) | 17 / 17 / 12 | 17 / 17 / 15 |
| made-up name in a hop answer | 0 / 0 / 0 | 0 / 0 / 6 |
| recall of a secret, told to one person (5) | 2 / 1 / 4 | 2 / 0 / 1 |
| leak to someone never told (5) | 2 / 0 / 4 | 1 / 0 / 1 |
| degraded rows in `health.jsonl` (most are a skipped promotion of the player, see below) | 3 / 6 / 0 | 26 / 29 / 28 |
| planted ties kept in the final save (6) | 6 / 6 / 6 | 6 / 6 / 6 |
| ties added that nobody planted (not counting ties to the player) | 1 / 1 / 5 | 14 / 3 / 3 |
| seconds a turn | 22.7 / 22.2 / 22.4 | 11.1 / 10.7 / 12.0 |

What it says, with 15 to 17 questions a run and one control seed:
- Not better than gemma3:4b. With the pass on, hops right are 18 of 34 against 24 of 34. Relations are level (9 of 12 each) and two-hop is level (4 of 10 against 5 of 10). The whole gap is possessions: 5 of 12 against 10 of 12 with the pass on, 5 of 18 against 14 of 18 over all three runs. The failure turns were read, not just counted. The scorer was right: Gemma 4 answers in character with a role instead of a name ("the keeper of the record", "those who enforce the law"), echoes the question back, or drifts into narration. It never invented a name.
- It is quieter than gemma3:4b, but less than the row counts suggest. Of gemma3:4b's 26 degraded rows in the seed 5 run, 25 are the fold trying to promote the player as a character ("you", "player"), which the engine skips and logs. Gemma 4's few rows are dropped promotions of a mystery or a character as a "kind". The real failures are rare and sit in gemma3:4b's control run: 2 folds with no valid JSON and 2 scenes with no summary. Gemma 4 had none in the runs read (the no-pass run has no rows at all). It also made no made-up name, where gemma3:4b made 6 in its control run.
- (Corrected in D-061: the second control seed did not replicate this.) The follow pass replicates on a second Writer, in direction. One-hop right 8 of 12 against 2 of 12 at seed 5, evidence in the prompt 17 of 17 against 12 of 17 (gemma3:4b: 10 of 12 against 7 of 12, 17 of 17 against 15 of 17). The control is still one seed (D-059's condition for flipping the default is a second seed pair and a second Writer; the Writer is now met, the second control seed is not).
- A leak needs an exposed secret. With Gemma 4 the secret was in the prompt for all 15 leak questions and it was said 6 times (2, 0, 4); gemma3:4b had it in the prompt for 4 of 15 and said it 2 times. Given exposure the rate is about the same (6 of 15, 2 of 4). The difference is how often it is exposed. Why was not measured; longer turns folding more of the story into the shared summaries is the obvious guess.
- The tie rule held on a second fold model: 6 of 6 planted ties kept in every save. The D-059 count of 14, 3 and 3 added ties leaves out ties to the player ("you", "player"); counted the same way Gemma 4 added 1, 1 and 5 (two of the 5 are invented cousins, three are a `char-` prefix on a real slug). Counting them too the totals are 2, 1, 5 and 18, 3, 15 (gemma3:4b attached "working together" or "rival" to the player on most characters).

**Decision.** Not adopted as the default Writer or reader; gemma3:4b stays the default and llama3.1:8b the recommended reader. Gemma 4 stays installed. Qwen3.5 9B heretic is not removed on this evidence: the reason that build was installed (a reader that does not refuse adult passages) is a reason to keep Gemma 4 and Qwen3.5 as the two candidates until the transcript read below compares them.

**Not run when this entry was written** (paused by the owner after the graph passes; all of it was run afterwards and is in D-061): the 161-passage transcript read (`reader_record.py`) for Gemma 4 and gemma3:4b, which is the comparison against llama3.1:8b and Qwen3.5 that D-036 and D-041 used; the look probe (hair and eyes, canon off and on) for both; llama3.1:8b as a Writer (53 s a turn); the refusal count of D-043 on Gemma 4. A smoke run of 14 turns with the canon card on (role-only sheets) completed with 1 degraded row and no probes yet.

**What would change this.** A transcript read where Gemma 4 holds the looks and files fewer weak identity values than Qwen3.5 (D-041) would make it the uncensored reader and retire Qwen3.5. A look probe where Gemma 4 holds hair and eyes better than gemma3:4b under the same squeeze would make it a Writer candidate despite the possession misses.

**Tests.** No engine or probe code changed, so no tests were added. The runs are in the session scratchpad (`g4_graph_*`, `scribe_g4_*`), not in the repo.

## D-061: The rest of the Gemma 4 measurements, the second control seed for the follow pass (it did not hold), and llama3.1:8b as Writer

**What this closes.** D-060 listed what it had not run: the 161-passage transcript read for Gemma 4 and gemma3:4b, the look probe, llama3.1:8b as a Writer and the refusal count. D-059 set a condition for turning the follow pass on for everyone: a second seed pair and a second Writer. All of it is run now (2026-11-20, code 82c1b86, one GPU, invented story only, my own Ollama stopped and port 11434 confirmed closed after each phase). Every number is one story, one script and a handful of questions a run; read the tables as direction, not as a score.

### 1. The follow pass: the second control seed does not replicate the gain, so the default stays off

Seed 6 with the pass OFF, for both Writers (everything else as the D-059 and D-060 runs: 120 turns, plain wording, facts stated, window 4, budget 5000). One-hop answers right are out of 12 a run, two-hop out of 5, evidence in the prompt out of 17 hops.

| gemma3:4b | one-hop right | two-hop right | evidence in prompt | right when the evidence was there |
|---|---|---|---|---|
| s5, pass on | 10 | 1 | 17 | 11 of 17 |
| s5, pass off | 7 | 0 | 15 | 7 of 15 |
| s6, pass on | 9 | 4 | 17 | 13 of 17 |
| s6, pass off | 11 | 4 | 16 | 15 of 16 |
| both seeds, on / off | 19 / 18 of 24 | 5 / 4 of 10 | 34 / 31 of 34 | 24 of 34 / 22 of 31 |

| Gemma 4 | one-hop right | two-hop right | evidence in prompt | right when the evidence was there |
|---|---|---|---|---|
| s5, pass on | 8 | 2 | 17 | 10 of 17 |
| s5, pass off | 2 | 1 | 12 | 3 of 12 |
| s6, pass on | 6 | 2 | 17 | 8 of 17 |
| s6, pass off | 8 | 2 | 17 | 10 of 17 |
| both seeds, on / off | 14 / 10 of 24 | 4 / 3 of 10 | 34 / 29 of 34 | 18 of 34 / 13 of 29 |

What it says.
- With the pass off, seed 6 put the evidence in the prompt anyway (16 and 17 of 17), because the recent narration happened to name the holders. Seed 5 without the pass is the run where it did not, and every gap D-059 and D-060 reported came from that one run. On seed 6 the pass was neutral to slightly worse on one-hop answers for both Writers (9 against 11, 6 against 8).
- What the pass does is put the evidence in the prompt on the seeds where the narration has not named the holder (34 of 34 against 31 and 29). It does not make the Writer more faithful once the evidence is there: gemma3:4b was right 11 of 17 with the pass at seed 5 and 7 of 15 without, then 13 of 17 with and 15 of 16 without at seed 6. D-059's reading that the Linked lines raise faithfulness "with the evidence there" is not supported; the seed-5 gap reversed on seed 6.
- The other seed-5 contrast went the same way. gemma3:4b's 6 made-up names in its seed-5 control run did not come back: neither seed-6 control made one (the wrong hop answers used cast names or no name). That looks like the seed, not an effect of the pass.
- The tie rule held again: 6 of 6 planted ties kept in both control saves. Ties added that nobody planted, counted as in D-059 (not counting ties to the player): 1 for gemma3:4b (a second one, to "you", is left out) and 3 for Gemma 4 (a sibling tie written from both sides, and a brother-in-law).
- Leak, with the pass off at seed 6: Gemma 4 had the secret in the prompt for 5 of 5 questions and said it 2 times; gemma3:4b had it in the prompt for 2 and said it 0 times.

**Decision.** `follow_links` stays off and D-059's "turn it on" recommendation is withdrawn. It is a cheap insurance (at most six short lines a turn) for a story where an item's holder or a person's tie is not named in the recent narration, and there is no measured loss, but the benefit has been shown on one seed in two, and never on correctness. A third seed with the pass off is the cheapest test that could change this, and only if it came out like seed 5 again.

### 2. Gemma 4 as a reader on the real transcript, and the refusal count

`reader_record.py` on the 161-passage soak transcript (the D-041 method), replayed through the current validator with no model. The Qwen3.5 and llama3.1:8b rows are the earlier recordings; all four are replayed under the same rules.

| | minutes | claims kept / thrown out by the parser | passages with a malformed reply | looks held (of the 7 the story set) | extra values filed | identity records |
|---|---|---|---|---|---|---|
| Gemma 4 E4B heretic | 34.8 | 1447 / 117 | 1 | 6, 0 differ | 2 ("dark" for Bram and Corwin) | 80 |
| gemma3:4b | 41.3 | 1935 / 230 | 42 (52 of 255 calls the wrong shape) | 6, 0 differ | 3 | 73 |
| llama3.1:8b | 31.4 | 1174 / 311 | 5 | 6, 0 differ | 2 | 59 |
| Qwen3.5 9B heretic | 24.8 | 915 / 114 | 1 | 6, 0 differ | 4 | 165 |

All four hold the same 6 of 7 looks and none contradicts the story, so this transcript does not separate them on looks. They differ on format and on how many identity values they file: Gemma 4 and Qwen3.5 have the cleanest replies, gemma3:4b has the worst (a fifth of its calls the wrong shape), and Qwen3.5 files two to three times as many identity values as the others (165 against 59 to 80), including weak ones like "intricate braid", which D-041 counted against it.

Refusal count (the D-043 method on a copy of the review save; counts only, no prose written or kept): 60 of the densest explicit narrator turns and 20 ordinary ones.
- Explicit group: 60 of 60 replies ok, 3.2 claims a passage (gemma3:4b found 4.7 on the same turns, llama3.1:8b 7.1), one passage with 0 claims.
- Control group: 19 ok and 1 reply that started valid JSON and did not finish (not a refusal), 4.5 claims a passage.
- Claims per 100 words: 1.46 on the explicit group and 1.54 on the control (llama3.1:8b 3.15 and 2.91). The densest half of the explicit group yielded 3.4 claims a passage and the least dense half 2.9, so yield does not fall as the text gets more explicit.
- Six explicit passages and one control passage where gemma3:4b found 4 or more claims and Gemma 4 found 0 or 1 (llama3.1:8b: one explicit passage).

It does not refuse and shows no sign of skipping explicit text. It is a lower-yield reader than llama3.1:8b on every passage, explicit or not.

### 3. The look probe (hair and eyes, role sheets): Gemma 4 does not state a colour

`soak play --probe-set look --sheets role`, seed 5, 120 turns, canon off and canon card, both Writers. **A trap in the harness:** with `--sheets role` the sheets state no looks, so `summary.json` reports held, drift and none as 0 for every run (it scores against a sheet only with `--sheets full`). These runs are scored the D-034 way, the story against itself (the first colour the story gives is the truth, later statements are checked against it).

| | looks the story set (of 12) | later statements agree / contradict | probes agree / contradict / set a look / name no colour (15) | words a turn |
|---|---|---|---|---|
| gemma3:4b, card off | 9 | 8 / 1 | 1 / 1 / 5 / 8 | 315 |
| gemma3:4b, card on | 6 | 8 / 0 | 2 / 0 / 2 / 11 | 271 |
| Gemma 4, card off | 2 | 1 / 0 | 1 / 0 / 1 / 13 | 291 |
| Gemma 4, card on | 2 | 0 / 0 | 0 / 0 / 1 / 14 | 312 |

- gemma3:4b with the card is no better than without it (8 agree either way, 1 contradiction against none, 3 fewer looks set); the same "no gain measured" as D-034, on smaller numbers.
- Gemma 4 almost never gives a colour. I read the probe sentences to be sure it was not the scorer: it writes "her dark, thick hair", "a shade of faded sea-glass", "the color of deep, undisturbed water", "dark and knowing". Those are not colours in the list the scorer and the card use, which is the same reason the transcript read filed "dark" as an extra value for Bram and Corwin. Where it names no colour it cannot contradict itself, and it gives the card at most a weak value like "dark" (D-041) to hold. That is a Writer this probe cannot test, not a Writer that holds looks well, and D-060's test "holds hair and eyes better under the same squeeze" is not one it can meet.
- The probe with the looks written in the sheet (`--sheets full`, held and drift against the sheet) was not run, so whether Gemma 4 repeats a stated colour is unmeasured.

### 4. llama3.1:8b as the Writer: the most faithful on this probe, at five times the time

One run, seed 5, `follow_links` on, the same settings as D-060 (no control with the pass off).

| | llama3.1:8b | gemma3:4b (s5 / s6, pass on) | Gemma 4 (s5 / s6, pass on) |
|---|---|---|---|
| one-hop right (12) | 11 | 10 / 9 | 8 / 6 |
| two-hop right (5) | 5 | 1 / 4 | 2 / 2 |
| hops right of 17 | 16 | 11 / 13 | 10 / 8 |
| evidence in the prompt (17) | 17 | 17 / 17 | 17 / 17 |
| recall of a secret (5), secret in prompt | 3, 5 of 5 | 2 / 0 | 2 / 1 |
| leak to someone never told (5) | 1 | 1 / 0 | 2 / 0 |
| planted ties kept (6), added ties | 6, 1 | 6, 14 / 6, 3 | 6, 1 / 6, 1 |
| seconds a turn, words a turn | 58.4, 98 | 11 / 11, 119 | 22.7 / 22.2, 260 |

With the evidence in the prompt every time, it was right on 16 of 17 hops, against 11 and 13 for gemma3:4b and 10 and 8 for Gemma 4 under the same settings. It writes shorter turns (98 words), takes 58 seconds for one, and 0.6 seconds a word against 0.1 for gemma3:4b. Its 88 degraded rows are 2 folds with no valid JSON and 2 arc-folds with no synopsis (the same real-failure count as gemma3:4b's control run) and 84 logged skips and dropped promotions (the player, characters that already exist, a few kinds the fold made up). This probe counts facts only; it says nothing about how the prose reads, and one run is one run.

### Decision for the models

- gemma3:4b stays the default Writer and fold model (fast, held its own on the fact probes); llama3.1:8b stays the recommended reader. llama3.1:8b is also the most faithful Writer measured, for someone who will wait a minute a turn; that is a note for the README, not a default.
- Gemma 4 is not adopted as a Writer (possessions, longer turns, no colours to test) nor as the recommended reader (lowest yield, though the cleanest format and no refusal). It stays installed as a candidate for a reader that does not refuse.
- Qwen3.5 9B heretic: D-060 said Gemma 4 would retire it if the transcript read showed Gemma 4 holding the looks and filing fewer weak identity values. It holds the same 6 of 7 and files 80 identity records against 165 and 2 extra values against 4, so that condition is met on this transcript. Its other reason for being installed, a reader that does not refuse adult passages, is met by llama3.1:8b (D-043) and by Gemma 4 (this entry). It is redundant on this evidence. The owner agreed ("yes remove Qwen3.5", 2026-11-20) and it was removed from the local model store (22.55 GB to 16.93 GB; the other five models were verified still listed). Getting it back is a pull of `hf.co/mradermacher/Qwen3.5-9B-heretic-GGUF:Q4_K_M`; its numbers above stay as the record, and no shipped default points at it (the code only mentions it in comments and in a think-handling test, D-040).

**Not run, and what would change this.** The look probe with the sheet stating the looks; llama3.1:8b with the pass off and on a second seed; a third control seed for the follow pass; a second transcript for the reader table (all four are one story). A seed where the pass-off run again misses the holder would be the only thing that moves the follow-pass default.

**Tests.** No engine or probe code changed, so no tests were added. The runs are in the session scratchpad, not in the repo.

## D-062: The author can say a worn or held item is wrong (state corrections, "is not" only)

**Why.** D-028 let the author correct identity (hair, eyes, build, age, marks, accessories) and left state out on purpose: what someone wears or
holds changes every few turns and is the story's to say. What it left unsolved is the item the reader filed by mistake, a garment another person
wore or a thing that was only mentioned. It sits on the card and is sent to the Writer until the story happens to change it, and the author had
no way to take it off. The Canon panel showed identity values only.

**What changed.** `corrections.md` takes two more slots, `outfit` and `held` (also written wearing, worn, clothes, holding, carrying), and only with
"is not": `- Odile: outfit is not red cloak`, `- Corin: held is not brass key`. A "=" on either is reported with its line and never applied.
1. **Retraction.** `plan` takes every matching item off the person's list and writes the list that is left as one author record (`state_set` for
   outfit, `item_moved` for held, `state_cleared` when nothing is left). Several lines about one list are applied together and written once: each line
   starting from the original list would write back what the line before it took off.
2. **Refusal.** The validator rejects the item as `author_refused` when the Scribe proposes it again, for that person and that list only.
3. **Matching is by item.** `validate.same_item`: the words of one phrase are all inside the other ("cloak" takes off "red cloak"). Not by colour:
   `same_value`, made for hair and eye colours and generous on purpose, calls "grey coat" and "grey scarf" one thing because both say grey. A synonym
   is a different phrase ("scarlet cloak" is not "red cloak"); the author writes the other line.
4. **The card** applies the correction itself, as for identity, so the item is not sent on the very next turn. The Canon panel lists each person's
   worn and held items under their looks (`state_values`), a Wrong button on each, and no Change button; "It is this" waits while Wearing or Holding
   is chosen.

**Why not "=" for state.** Three reasons that point the same way. State is latest wins and narration may supersede anything (state.py), so an author
value would be a starting state, not a fact. `plan` remembers nothing and is run after every turn, so a "=" line could not tell a correction from a
change of clothes and would put the item back after every real change. And what someone wears is already in the author's hands: they can write it
into the story. "Is not" has none of these problems: it is true once, and stays true.

**What it does not do, and what it costs.**
- The reader keeps proposing a refused item every time the story mentions it; each proposal is rejected and counted in the pass's row. The end state
  alone cannot tell a refusal from an accepted item that the correction then retracted at the end of the pass, so the API test reads the row (a
  mutant that stopped passing the refusals to the validator was missed until it did).
- If the person really does wear the item later, the line has to be removed: the refusal keeps rejecting it and the correction keeps taking it off.
  A correction that ends at a turn would be a new format.
- Removing the line writes nothing and restores nothing: the retraction stays, and the story may say the item again from then on. The release of
  "=" lines (D-028 call 7) only ever looks at identity slots.
- Not measured on a real model or a real save; the tests use stub readers.

**What would change it.** Authors who write "is not" lines and then find the same item back through a synonym often enough to want matching by
meaning; a wish to say "he wears this now" (a one-shot action in the panel that is not kept in the file, not a correction); a correction that ends at
a turn.

**Tests.** `canon_state_corrections_test.py` (11 promises: the file, the list that is left, matching by item, several lines at once, idempotence, state
not pinned and per person, the validator, unknown and ambiguous names, `state_values`, the card, removing a line), `canon_api_test.py` 7 (the view,
the route, the ledger, the refusal in the reader's own pass), smoke case 41 (the panel). 14 + 4 mutants of the engine side and 6 of the panel, all
caught in the end.

## D-063: A ties line at the tail of the prompt, after the player's action (built, off, measured in D-067: no effect where the ties were already in the prompt)

**Why.** The graph probe (D-058 to D-061) left a gap that retrieval does not close. With the evidence already in the Writer's prompt, a 4B Writer
answered "who is her brother" or "who carries the key" wrongly a quarter to a third of the time (gemma3:4b with the pass on: 11 of 17 and 13 of 17
right when the evidence was there, D-059 and D-061). The facts sit in the middle of a long system message, far from the question. The one thing the engine already
puts after the player's action is the canon card (D-027), and it is built from the canon ledger, which holds looks and what people wear, not ties or
possessions. Those live in the story's own files: a character's `relationships:` line and an item's `holder:` attr (D-059).

**What it is.** `memory: {tail_ties: true}` (off, and only a literal true turns it on). `coderain/tailties.py` builds ONE short system message
from those files for what the player's action and the last reply name, plus one hop (an item to its holder, then the holder's own ties, because
"the sister of the person who carries the key" is the question that needs it). The engine appends it right after the card and before the chapter
directive, so the chapter goal is still the last thing read. For the soak probe, `python -m soak play --tail-ties` turns it on and each graph row
records the line (`tail_ties`), the summary counts how many questions had it (`tail_ties_rows`).

    Facts in play, from the story's own files (they are true; use them as written): Brass lamp key is held by Hollis Wren. Hollis Wren is tied to Ottoline Pike (his sister).

**Rules it keeps** (each is a promise a test pins): a hidden entry (a secret) is never said, as the thing named, a holder or a tie target; `chance: 0`,
`delay` (against the committed message count) and `triggers_not` hold, as for the follow pass; a holder or tie that names no entry, a tie to oneself
and an item held by itself are left out, never guessed; a first name shared by two entries names nobody; at most 8 facts and 600 characters, the later
ones dropped whole; it depends only on the files and the text, so a retry builds the same line (invariant 5); a failure is reported once
(`tail-ties` in the health log) and means no line. It is a system message, so the echo filter drops a copy of it at the START of a reply, like the
card; a copy in the middle of the prose is not caught, and that is the filter's design (a legitimately repeated line must survive).

**Not measured.** Nothing here has been run against a model. That is why it is off. The measurement is the graph probe with and without it on the
same seeds (`--tail-ties` against the plain run, then with `--follow-links` too), reading right-when-the-evidence-was-there first, because that is
the 30 percent it is for. It is a different lever from D-059's follow pass: that one gets the facts INTO the prompt, this one says them again where the
Writer is looking. D-061 showed the follow pass makes no difference once the evidence is there, so there is a real chance this makes none either.

**What would change it.** A measured gain on right-when-evidence-is-there on two seeds and a second Writer (on by default for stories that have
ties); no gain, or a loss of prose quality (a Writer that now recites ties) would remove it. A scene with many named people would call for a lower cap.

**Tests.** `tail_ties_test.py` (10 promises, including the engine: off for anything but a real true, the position, never stored, a failure costs no turn,
the echo filter), `soak_graph_probe_test.py` 5 (the flag, the row and the summary). 18 + 6 mutants broken in a copy of the repo, all caught in the end
(two first slipped through: an item held by itself was unchecked, and a mutant that was equivalent until the check it duplicated got a test of its own).

## D-064: A tic guard: the phrases the Writer keeps reusing, found by counting and said back (built, off, measured in D-067: it did not help and it hurt; leave it off)

**Why.** A small local Writer feeds on its own recent replies: they are the longest thing in its prompt, so what it wrote last turn is what it writes
this turn. D-055 counted 103 recurring eight-word runs in one 80-turn story, and D-034 saw the reply length grow the same way. The cure that costs no
extra model call is a list: find the phrases that open in several of the last replies and say them back as "another way". Finding them is plain
counting.

**What it is.** `generation: {tic_guard: true}` (off, and only a literal true). `coderain/tics.py` reads the last 8 narrator replies and returns the
phrases (three to six words) that occur in at least 3 different replies. The engine puts one system message after the card and the ties line and
before the chapter directive (so the chapter goal is still last):

    Style note, not part of the story: these phrases keep turning up in the recent replies. Say them another way, or leave them out: "her breath hitched in her throat".

Rules, each pinned by a test: the phrase must recur across DIFFERENT replies (five times in one reply is not a tic); it needs two content words
("but it was not that it was" is grammar, "in the middle of the" has one: a noun inside grammar), and the words of any character's or place's name
never count as content (a name should recur); only the longest version is kept, and pieces that overlap are joined into the run they came from (a
recurring eight-word sentence is one phrase, not three six-word pieces that slide along it); at most 5, the most widespread first; nothing longer
than 60 characters (a longer run is cut back to its opening, which still recurs); only narrator replies are read, never the player's own repeated
action. It depends only on the stored turns, so a retry builds the same line; a failure is reported once (`tic-guard`) and means no line. It is a
system message, so the echo filter drops a copy of it at the start of a reply.

**Measuring it.** `python -m soak play --tic-guard` turns it on; the summary's `repeat_share` (new, for every run) is the mean share of a turn's
eight-word runs that were already in the turn before: 0 is a new turn each time, 1 the same turn again. The comparison is `repeat_share` with and
without the flag on the same seeds, then read the prose, because a Writer told to avoid a phrase can swap it for a worse one. Graph rows record the
line (`tic_line`) and the summary counts them (`tic_rows`), as for the ties line.

**Not measured, and what would change it.** Nothing here has been run on a model. A measured fall in `repeat_share` that does not cost the prose
would make it worth recommending; no fall, or a Writer that now recites the list or reaches for stranger phrases, would remove it. A story that
needs a refrain (a catchphrase on purpose) would call for a way to exempt a phrase.

**Not built.** Voice anchors (a short sample of each character's own speech, to keep them sounding like themselves): they need to know WHO said a
quoted line, and attribution through a pronoun is the failure D-024 exists to stop. That wants a labelled sample before any code.

**Tests.** `tics_test.py` (9 promises, including the engine and the echo filter), `soak_graph_probe_test.py` 5 (the flag, the repeat measure, the
row). 22 mutants broken in a copy of the repo, 21 caught and one equivalent (the early return for fewer than three replies: no phrase can occur in
three replies without them, so the later check covers it; it stays as a short cut).

## D-065: Duplicates in the app: the merge of D-030 and D-038, with an undo

**Why.** A story played through a small local model collects second and third entries for one person ("Dame Vesper", "Vesper", "Vesper Ann-Marie";
a same-name pair under two slugs). Each is a separate character to the memory, the card and the Writer. `python -m coderain.dedupe` found them and
merged them (D-030 same whole name, D-038 names that share words, a merge only when told), and the app had no way to: D-038 listed "the app has no
button for it" under Not done. A merge rewrites a registry file that a fold wrote, and a fold is one-way, so the only way to offer it in an app is one
that can be taken back.

**What it is.** `srv/dedupe_api.py` and the "Duplicates..." button in the Memory dialog (`webapp/js/duplicates.js`).
- `GET /api/saves/{slug}/duplicates`: entries with the same whole name (safe to offer as one button) and entries that may be one person (the author's
  call, so each is a choice of who stays and who is folded in, the entry with the longest body suggested), the backups, and whether `canon/` exists.
- `POST .../duplicates/merge`: `{rel, keep, drop: [slugs]}` or `{auto: true}` (same-name groups only). The same rules as the tool (`explicit_group`,
  `apply_merges`): a backup of every registry it changes first, the player's sheet never merged, a refusal is a 400 that writes nothing.
- `POST .../duplicates/restore`: `{backup: "<stamp>"}` puts that backup's registries back, after backing up what is there now, so a restore can be
  restored too. Only a stamp the tool made is accepted (a path, a missing stamp, a folder with no registry are refused), and only registry files are
  put back (a `meta.json` in a backup is never copied over the live one).
A merge and a restore take the lock every save-changing call takes (409 while a turn is generating). The dialog asks before each one, says what a
merge cannot do ("only you know whether they are one person"), and a declined question changes nothing.

**What it does not do.** It changes the registries only. The canon ledger under `<save>/canon/` is derived and keeps the old entities until it is
rebuilt; the dialog says so and tells the author how (delete that folder, and the reader reads the story again). It does not rewrite the
`[[type:slug]]` links the folds wrote into scene summaries and the arc (the tool counts them; they point at slugs that go away). A restore returns the
whole registry file as it was at that stamp: an edit made since is in the backup the restore makes first, not in the restored file. Names are matched
as the tool matches them (a title only listed as another entry's alias is not a match), so "Master X" and "X" are found only when one name's words are
all inside the other's.

**Why a button for the canon rebuild is not here.** A rebuild reads the whole story again with a local model, which can be hours of GPU on a long
story; that is a decision to make on purpose, not one click away from a merge.

**Tests.** `dedupe_api_test.py` (8 promises: the view, an explicit merge and its backup, every refusal writing nothing, auto, restore byte for byte
and its own undo, what a restore will accept, the lock, an unknown save), smoke case 45 (the dialog: the lists, the confirmations, a declined one
changing nothing, a cluster with the keeper's own box ticked, nothing ticked, a restore). 15 + 11 mutants broken in a copy of the repo; the API ones
caught in the end (two first slipped through: a restore of a non-registry file, a folder that is not a stamp listed as a backup).


## D-066: The creation flow, probed: nothing is overwritten, nothing fails silently, every button runs once

**Why.** The plan's creation-flow polish (A6) started from a list of where creation breaks today, made by driving the creation routes with awkward
input in a throwaway data directory and reading every creation button's handler. Each finding below is reachable from the app, not only from a
hand-made request:
- A NEW piece whose name made the slug of one already in the file REPLACED it, with no question and no way back: a second character called "Vesper"
  (or "VESPER", or "Vesper!") wiped the first one's text. A rename onto another piece's name did the same (the renamed piece's text replaced the
  other, then the old one was removed), and so did dropping the same library character or library piece into a world twice. Six routes wrote a
  piece by `upsert_entry`; none looked first.
- A new story naming a world, a character or a playable character that no longer existed (a picker left open while it was deleted in another
  window) was made anyway, without them and without a word.
- A title of a few hundred characters (a pasted paragraph) made a folder name the file system refuses: creating the world or the story was a 500.
- "Begin" on a new story was an unguarded call: a refusal left the dialog open and said nothing (an unhandled rejection). The deletes of a world, a
  character and a library piece, saving a character sheet, adding a library piece to a world and removing a lore type were the same.
- A double click on Begin, New world, Save piece or Save character sent the request twice: two stories, two "Untitled World"s, two characters.
- A character sheet with a blank name was saved as "Unnamed" without a word; a piece title had no length limit (5000 characters were stored and
  written into the roster; a chapter title stops at 200 and a goal at 2000).

**What it is.**
- `_refuse_clash` (`srv/pieces.py`): the only slug a piece save may land on is the piece's own (`old_slug`). Anything else that is already in the file
  is a 409 naming the existing piece ("There is already <name> in this world. Open that one to change it, or give this one another name."). All six
  routes call it: the world's and the story's piece save, and the four library drops. A drop of the same library piece twice is refused too: it says
  what is already there instead of doing nothing.
- `POST /api/saves` looks up the world, the library character and the playable character BEFORE it makes anything, so a refusal leaves no folder
  behind: 404 "That world is gone", 404 "no longer in your library", 400 "not in this world any more", 400 for a bad id.
- `slugify_name` caps a folder name at 60 characters and never leaves a trailing dash; the uniqueness suffix comes on top, so two long titles that
  share their first 60 characters stay distinct and openable. The title is kept whole.
- `POST /api/characters` refuses a blank name (400); the dialog asks first. A piece title of more than 200 characters is a 400, and the title box has
  `maxlength`.
- `whileBusy(button, fn)` (`webapp/js/util.js`): a button runs its action once at a time and comes back if it is still on the page; every creation
  button uses it and every call is under `guard`, so a refusal is a toast and the dialog stays with what was typed.

**What it does not do (found, left, and why).**
- Chapters were probed too and are well behaved: indexes are validated, blanks are ignored, titles and goals are bounded in the planner.
- `{"title": null}` or `{"premise": null}` from a hand-made request becomes the text "None" (`str(None)`). The app always sends strings, so nothing in
  it reaches this; a body-shape guard on the creation routes would be the fix if an API client appears.
- An alias that equals another piece's title is accepted (two pieces then claim one name for recall). It is a warning at most, and the Duplicates
  dialog (D-065) already finds the pair.
- The reusable library keeps one record per save (ids), so "Save to library" twice makes two records and the same-name sheets are allowed. Nothing
  is lost; a clean-up is a library feature, not a creation fix.
- A piece body is unbounded (1 MB was accepted). The context budget decides how much of it is ever read, so it costs disk, not a turn.
- The confirm-then-delete of a world a story was made from is correct (a story keeps its copy).
- `_unique_slug` checks that a folder name is free and the create happens later, so two creates of the same title that arrive together can
  land in ONE folder (the double click showed it: two requests, one world). The buttons no longer send two; two windows still could. The fix
  is an atomic `mkdir` that retries with the next suffix. Not done: it is a window of milliseconds on a single-user local app.

**Tests.** `creation_guards_test.py` (8 groups: no replace by a new piece, an edit in place still works, renames, the four drops in a world and in a
story, a new story's references with no folder left behind, long titles, a character's name, a piece title's length), smoke cases 46 to 50 (a
refused Begin is said and keeps its dialog and its text; a double click on Begin, New world, Save piece, Save character and a library drop makes one
thing, with the request slowed so the second click lands while the first is in flight; a refused delete of a world and of a character; a library
character already in the world is refused and the picker stays). 19 mutants of the server side and 12 of the buttons were broken in a copy of the repo and all went red in the end. Five single-flight
mutants slipped through the first version of the double-click cases: they counted worlds and stories in the store, and two concurrent creates
race to the same folder name, so one world appeared although two requests went out. The cases now count the writes the page sent. One more
equivalent finding: the `btn.disabled` test inside `whileBusy` is redundant for a real button (the browser drops clicks on a disabled one), and
only matters for a card, which is a div; the library-drop case is what pins it.


## D-067: The graph probe with the ties line and the tic guard (measured 2026-11-21): neither helps; the tic guard hurts

**What was run.** `python -m soak play --probe-set graph`, gemma3:4b as the Writer and the fold model, 120 turns, window 4, budget 5000, plain
wording, facts stated, canon off: the settings of D-058 to D-061. Three arms on seeds 5 and 6, one at a time on the one GPU, about 25 minutes
each (12 s a turn): the baseline (no flag, so the code path of D-061's "pass off"), `--tail-ties` (D-063) and `--tic-guard` (D-064). Six runs,
`prompt_missing` 0 in all of them. Each seed is a different story from the others and the model samples, so an arm is compared with the baseline of
its own seed and nothing here is a controlled trial: 24 one-hop, 10 two-hop, 10 recall and 10 leak probes an arm.

| (two seeds pooled) | baseline | `--tail-ties` | `--tic-guard` |
|---|---|---|---|
| one-hop answered right | 19 of 24 | 19 of 24 | 16 of 24 |
| two-hop answered right | 7 of 10 | 8 of 10 | 3 of 10 |
| right, with the evidence in memory's part of the prompt | 25 of 33 | 26 of 32 | 18 of 33 |
| relation and possession evidence in the prompt | 24 of 24 | 24 of 24 | 24 of 24 |
| the secret reported when asked (recall) | 1 of 10 | 1 of 10 | 3 of 10 |
| a secret said by someone who was not told (leak) | 0 of 10 | 1 of 10 | 0 of 10 |
| repeated 8-grams, seed 5 / seed 6 | 0.183 / 0.000 | 0.002 / 0.008 | 0.218 / 0.075 |
| words a turn, seed 5 / seed 6 | 191 / 117 | 189 / 161 | 139 / 106 |

**The ties line (D-063).** No measurable effect, and the probe could not have shown one. The line says again, at the end of the prompt, the ties
and holders the action and the last reply name. In this setting the evidence for a tie or a holder was already in the prompt every time (24 of 24
in every arm: D-059's `merge_ties` keeps the ties through a fold), so the Writer's misses are faithfulness, not retrieval, which is what D-058
and D-061 found. Right with the evidence present went 25 of 33 to 26 of 32. The case the line is for, a tie that has fallen out of the prompt,
did not occur (right with the evidence absent: 1 of 1, 1 of 1, 0 of 1, 1 of 1 across arms and seeds). It stays off, unproven. A fair test needs a
condition where ties drop out (a much smaller `--budget`, or a larger cast, or a longer story) and compares the right-when-absent rate. The repeat
share fell from 0.183 to 0.002 on seed 5 and not on seed 6, and the baseline's own repeat share is 0.183 on one seed and 0.000 on the other, so
that fall cannot be attributed to the line.

**The tic guard (D-064): leave it off, and the finder needs a different idea before another try.** Answers got worse, not better: two-hop 7 to 3 of
10 (3 to 2 on seed 5, 4 to 1 on seed 6), one-hop 19 to 16 of 24 (a drop on seed 6, none on seed 5), right with the evidence present 25 to 18 of 33,
and the turns got shorter (191 to 139 words on seed 5). It did not reduce repetition either: the repeated-8-gram share went up on both seeds
(0.183 to 0.218, 0.000 to 0.075). Replaying the finder over the real replies shows why it cannot work as built. It never raised (117 windows in each
of three runs), and it found a "tic" in about 90% of the windows (103, 105 and 110 of 117), but what it names is the story's own nouns:
"the mudlark boy", "the mooring lines", "the ferry deck". The names of characters and places are excluded; epithets, props and settings are not,
and a story that returns to its harbour will say "the ferry deck" often because it is where the story is. Telling the Writer to say them another
way or leave them out pushes it away from the very nouns the probes ask about, which is a likely (not measured) reason the answers fell. The finder
would have to ignore every noun phrase the story's own files already hold (titles, aliases, places, items, the words of the premise) and look only
at what the story did not introduce, and then be measured again. With 10 and 24 probes an arm the answer drop is a direction, not a proof; the
repetition result is the plainer one, because the guard did not do the one thing it exists for.

**Leak probes and witness metadata (the plan's next item): not justified at this scale.** Over the six runs a leak happened 1 time in 30. With the
secret in the prompt: 1 leak in 17 questions, and the secret was reported when asked 5 times in 17 (29%). With it absent: 0 of 13. So the secret is
usually not what the Writer says even when it is in front of it (faithfulness again), and a leak is rare. "Who witnessed what" metadata would
guard against a failure that this Writer almost never makes in this probe. It stays an idea. What the probe cannot say is what a larger or hosted
Writer does, since a model that follows the prompt better is the one more likely to repeat an exposed secret.

**What this closes in the plan.** Part C's first item is done. Both flags stay off by default and no documentation recommends turning either
on. The pronoun-attribution item was already measured and built behind a switch in D-035 (94% of 36 answers right, `identity_via_pronoun`, off).


## D-068: The play soak on a hosted free model (`--provider openrouter`), with its limits enforced in code

**Why.** Every long-story measurement so far ran on a 4B or an 8B model on this machine. D-055 asks whether a larger Writer is immune to what a
4B one does (the loop under fate steering), and the plan's Phase 7 asks for a long story at three model tiers. A hosted tier is the only way to
see a model several times the size, and the OpenRouter `:free` models cost nothing, but a free pool is shared, rate-limited and capped per
day, and a key given for a free test must not be able to spend. So the limits are in the code, not in a promise.

**What it is.** `soak/hosted.py` and `python -m soak play --provider openrouter --model <id>:free`.
- The model must end in `:free` (`--allow-paid` is the explicit way round); no model is refused.
- The key is read from `OPENROUTER_API_KEY` by name. It is never an argument, never written to the run's config (which holds the variable's
  name and the OpenRouter address), and no message the module raises can contain it.
- Every chat request of the engine (the Writer, the folds, the canon reader and the direct calls) goes through the OpenAI SDK's own
  `chat.completions.create`; the soak wraps that one function, so nothing in the engine changed. Requests are spaced 3.2 s apart (18.75 a
  minute, under the 20 a minute cap), a busy pool (429), a provider fault (5xx) and a dropped connection are retried after 5, 10, 20, 40, 60, 60
  and 60 seconds, and a bad request, a bad key and a missing model (400 to 404) are not. A daily cap ("per-day" in the provider's message) is
  not retried either: waiting does not lift it.
- Every attempt counts against `--max-requests` (default 900). Before each turn the run stops cleanly if fewer than 12 are left (a turn is the
  Writer's call, sometimes a fold and the canon reader's pass).
- A request that fails for good (the retries are spent, or it is not worth retrying) stops the run AT that turn and the turn is not recorded.
  A free pool can stay saturated for many minutes, and the engine would write its error message into the story as if it were narration, which
  corrupts every row after it. The summary says why it stopped (`stopped`) and how many requests it used (`requests`). The provider's failure
  reaches the play loop as an EXCEPTION out of the engine's turn, not as text (the first version only handled the text and a real run died on
  it at turn 34, with no summary), so the loop catches it, and only when the pacer says the provider failed: a bug of ours still stops the
  run loudly.
- The waits between retries total about 17 minutes (5, 10, 20, 40, 60, 120, 180, 300, 300 s). The first list gave up after 255 s, and
  Particle-1 refused every request for longer than that.
- Local runs are unchanged byte for byte (the config text is pinned by a test) and the summary now carries `provider`, `requests` and `stopped`.

**What it does not do.** The pacing counts attempts it makes itself; the SDK's own two silent retries inside one call are not counted, so the
budget slightly undercounts against the provider. It does not know the account's daily allowance (the key-status call does not report it), so
`--max-requests` is the guard, and a provider that has already spent the day's allowance stops the run on the first request. A reasoning model
(Nemotron 3 Ultra, the free model that was answering when this was built) spends tokens thinking before it writes; the engine's prose call
already gives a reasoning model headroom (`prose_tokens`), and a four-turn trial wrote usable prose in one request a turn. The corpus
harness (`soak scribe`) already supported OpenRouter and is unchanged.

**What was seen on the day.** A first hosted run on Nemotron 3 Ultra (550B total, reasoning) wrote sound prose for 80 turns and then
fell apart: from turn 81 the narrator had the player drowning in every scene and by turn 85 wrote in capitals, with no recovery in the next 20
turns, so the run was stopped at 105 turns. That is a finding about that model under this engine's squeezed memory, not about a Writer in general.
Gemma 4 31B and 26B answered 429 ("temporarily rate-limited upstream") to every request for the first hour, and
Ling 3.2 Flash too; Nemotron 3 Ultra and Flint answered. A hosted corpus run against Gemma 4 31B spent 95 seconds of retries on each of five
passages and failed all of them before it was stopped, which is the reason a run now stops at the first failure for good instead of grinding on.

**Tests.** `soak_hosted_test.py` (7 groups, offline, a fake clock and a canary standing in for the key: the model guard, the key by name, the
pacer, the retry rules and undo, the configs, the command line including the budget boundary, and the stop at a failed turn whether the provider
fails as text or as an exception, with a bug of ours still stopping the run). 36 mutants broken in a copy of the repo, all went red.


## D-069: Measured 2026-11-22/23: the card over 1,000 turns, the accessory slot, Gemma 4 with stated looks, and a hosted tier

**Setting.** The invented ferry-town story of D-046, memory squeezed (window 4, budget 5000), the author's sheets state each character's hair and eyes
(`--sheets full`), a look probe every 8 turns ("I study X's hair"), seed 5, `python -m soak play`, one run per condition. A probe is `held` when the
narration names the sheet's colour, `drift` when it names another, `none` when it names none.

**1. The canon card over 1,000 turns (gemma3:4b as Writer, Scene State Card off against on).** 125 probes each.

| turns | card off: held / drift / none | card on: held / drift / none |
|---|---|---|
| 1-100 | 2 / 6 / 4 | 10 / 1 / 1 |
| 101-200 | 1 / 2 / 10 | 13 / 0 / 0 |
| 201-300 | 1 / 4 / 7 | 8 / 1 / 3 |
| 301-400 | 0 / 7 / 6 | 11 / 2 / 0 |
| 401-500 | 1 / 8 / 3 | 11 / 1 / 0 |
| 501-600 | 1 / 7 / 5 | 11 / 0 / 2 |
| 601-700 | 2 / 1 / 9 | 12 / 0 / 0 |
| 701-800 | 2 / 7 / 4 | 13 / 0 / 0 |
| 801-900 | 0 / 5 / 7 | 9 / 3 / 0 |
| 901-1000 | 1 / 5 / 7 | 13 / 0 / 0 |
| all | 11 / 52 / 62 | 111 / 8 / 6 |

Of the probes that named a colour, 11 of 63 were right without the card (17%) and 111 of 119 with it (93%). With it the Writer named a colour on 119
of 125 probes, without it on 63. The card shows no decay across the 1,000 turns (no block below 9 of 12). This is the first long test of the whole
redesign (the first long soak, D-029, found the card did not help; the fixes since then are what changed that). Cost: 46 s a turn against 25.5, and
12.9 hours against 7.1 for the run; 179 health rows against 56 (not broken down; the extra calls are the reader's).

**What it does not show.** One seed and one story. A probe asks about a character's looks at the moment the card injects them, which is the card's best
case. The looks were stated by the author: when the story has to supply them the reader captured about a third (D-034, not re-measured here). Ties,
state, outfit and everything else the ledger holds were not measured. And the stories themselves degraded in BOTH runs. Replies grew to 1,000 words
and more, and the share of 8-word runs that repeat an earlier one, by 100 turns, was 0.02, 0.08, 0.38, 0.17, 0.69, 0.77, 0.74, 0.57, 0.64, 0.62
without the card and 0.31, 0.80, 0.81, 0.83, 0.76, 0.73, 0.72, 0.75, 0.73, 0.25 with it (0.47 and 0.67 over the run). The card run looped from about
turn 100, the baseline from about turn 200 to 450; with one realisation each, which loops first is not established. What is established is that a 4B
Writer with this memory writes mostly repeated narration after a few hundred turns, with or without the card, that the card keeps the looks right
through it, and that nothing built so far addresses the repetition (the tic guard of D-064 did not, D-067). That is the open problem for a long story.

**2. The accessory slot (D-044): the default stays off.** The corpus runs are deterministic (a repeat of each was identical), so one run each is
enough, and the differences below are the prompt's, not noise. Validated slices, off then on:

| | gemma3:4b | llama3.1:8b |
|---|---|---|
| accessory slice, found of 6 | 0 then 5 (1 false positive) | 0 then 1 (1 false positive) |
| legacy slice recall | 0.77 then 0.69 | 0.73 then 0.69 |
| multi-character recall | 0.86 then 0.57 | 0.71 then 0.71 (precision 0.83 then 0.71) |
| state precision / recall | 0.83 then 0.71 / 0.62 | 0.83 / 0.62 then 0.80 / 0.50 |
| look-alike traps, raw false positives | 18 then 10 | 5 then 8 |

D-044's own condition was that the legacy slice must not drop. It drops on both readers, and the slot works only on gemma3:4b. So the gate stays and
nothing recommends turning it on. The idea that might separate the two effects is asking about ornaments in a call of their own, so the other slots'
prompt is untouched; not built. A hosted reader (Gemma 4 31B) was meant to be measured and could not be, see 4.

**3. Gemma 4 E4B (the heretic quant) with the sheets stating the looks, no card.** 120 turns, 15 probes: held 11, drift 0, none 4, 23.5 s a turn,
275 words a turn, repeat share 0.0, no health rows. The same first 120 turns of the gemma3:4b runs above: card off 2 / 6 / 7, card on 13 / 1 / 1. So
on this measure Gemma 4 without a card is close to gemma3:4b with one. D-061 found Gemma 4 the lowest-yield reader and silent on colours under role
sheets (nothing stated); that was the reader's job on sheets without colours, and this is the Writer's job with them. One seed, 15 probes; a second seed of
each (gemma3:4b and Gemma 4, seed 6) was queued and cancelled by the pause. It is a lead, not a recommendation.

**4. A hosted tier (OpenRouter free models, D-068).** Nemotron 3 Ultra (550B total, reasoning) wrote sound prose for 80 turns, then had the player drowning
in every scene and wrote in capitals from turn 85 with no recovery; stopped at 105 turns. Gemma 4 31B and 26B, Ling and ERNIE answered 429 ("temporarily
rate-limited upstream") all day, so the tier I wanted most was not measured. Particle-1 (size not published): card off 300 turns, 587 requests, held 7 /
drift 10 / none 20; card on 197 turns, 355 requests, 2 / 5 / 17, then the provider answered 429 through every retry and the run stopped cleanly with its
summary (the new handling worked as built). Particle names a colour on 17 of 37 probes without the card and 7 of 24 with it, a literary style that
avoids saying it, so these runs say nothing about the card, and the soak does not record the prompt, so whether the card reached a hosted reader's output
is unverified. The hosted tier is, so far, a negative result about free-pool availability and one model's style, not about the engine.

**Not run (cancelled by the pause).** llama3.1:8b on the graph probe (seed 5), fate on and off on llama3.1:8b (D-055 still asks whether a larger Writer
loops), the second seeds in 3, and a hosted accessory corpus run.

**What would change this.** The card result: a second seed, the story-supplied (`--sheets role`) condition at length, and a Writer that does not loop.
The accessory call: a separate-call design that leaves the legacy slice alone. Gemma 4 as a default Writer: the second seed, and a card-on run.


## D-070: A length cap does not stop the loop: the failure is copying the previous reply, and in these runs it is gemma3:4b's (measured 2026-11-24)

**Why.** The 1,000-turn soak of D-069 ended with both stories degraded: replies grown past 1,000 words and most 8-word runs repeating an earlier
one. The working guess was that reply length is uncapped and a small model feeds on its own long history, so a cap would stop it. Reading the engine
showed the guess was at least half right: the engine's length control caps nothing. `config.prose_tokens` is `reply_tokens + REASONING_HEADROOM`
(3,000), added to every prose call so that a reasoning model has room to think, so the soak's `max_tokens: 700` meant 3,700, `short` meant 4,200 and
`long` 7,096. The only thing that holds a reply short today is the optional `LENGTH: keep it short, 1-2 short paragraphs` directive of
`response_length: short`.

**What was built.** Soak options only (the engine is unchanged): `--response-length short|medium|long`, `--max-tokens N` (at least 64) and
`--no-reasoning-headroom`, which drops the +3,000 for that process so the budget is a real cap for a model that does not reason. The summary records
the budget the Writer actually had (`prose_cap_tokens`). The defaults change nothing (the config text is pinned). `soak_reply_cap_test.py`, 4 groups,
7 mutants broken in a copy of the repo, all red.

**The experiment.** The card-on story of D-069 (gemma3:4b, sheets stating the looks, window 4, budget 5000, seed 5), which looped from about turn 100.
Both arms were stopped early because they had shown what they could.

| arm | what happened |
|---|---|
| `response_length: short` (stopped at turn 58) | replies held at 113 to 260 words for 28 turns, then ran away: 364, 360, 448, 536, 740, 892, 883, 1,135 ... 900 to 1,300 words by turn 37 to 58. The last two replies open with the same sentence. The directive lost to the story's own history |
| a real cap, 450 tokens, no headroom (stopped at turn 98) | length stayed bounded (236 words a turn for turns 1-50, 274 for 51-98), but by turn 60 to 70 the Writer repeated the previous reply almost word for word ("The rain continues to batter the customs shed. Bram Halloran continues to examine the wooden box ..."), and in the last 40 turns 80 to 100% of a reply's 8-word runs came from the reply before. Two replies were empty (turns 13, 14) and the cap cuts replies mid-sentence |

**What it shows.** Runaway length is a symptom of copying, not its cause: each reply is the previous reply plus a little, so it grows until something
caps it, and a cap leaves the copying. The failure is the Writer reproducing its own previous reply. The mean share of a reply's 8-word runs that
came from the reply before it, per 50 turns:
- gemma3:4b, card off, 1,000 turns: 0.01, 0.04, 0.09, 0.08, 0.30, 0.45, 0.16, 0.17, 0.63, 0.76, 0.79, 0.75, 0.75, 0.73, 0.55, 0.60, 0.61, 0.67, 0.59, 0.65
- gemma3:4b, card on, 1,000 turns: 0.06, 0.57, 0.76, 0.82, 0.82, 0.80, 0.82, 0.85, 0.74, 0.78, 0.76, 0.70, 0.73, 0.71, 0.77, 0.74, 0.79, 0.65, 0.18, 0.30
- Gemma 4 E4B, 120 turns (D-069): 0.0, 0.0, 0.0. Particle-1, 300 turns: six zeros.
So under the identical scripted player and squeezed memory, gemma3:4b copies its previous reply for hundreds of turns and the other two models, in
the turns they were given, do not at all. Gemma 4's horizon is short (gemma3:4b with the card off was also clean for its first 200 turns), Particle-1's
is longer and clean. With the card on gemma3:4b started copying around turn 50 to 100 against about 250 with it off, one realisation each, so whether
the card brings the loop forward is not established.

**Why it matters.** gemma3:4b is the shipped default Writer. The card keeps its facts right (D-069) in a story that, in this soak, is a dead loop
after a hundred turns. The soak's player has a small set of action templates, so it is a harsher test than a person who varies what they do, and these
runs show the failure mode, not how often it happens in real play. That is the thing to measure before building anything.

**Not tried (in the order I would try them).** A different Writer: Gemma 4 E4B with the card on for 300 turns or more is the direct test of whether the
fix is the model. An echo guard in the engine (a reply that copies the previous reply is detected and regenerated or trimmed); streaming makes this
awkward, because text already shown cannot be taken back. Dropping the copied replies from the verbatim window so the model stops seeing its loop.
Sampling penalties: the engine already passes `frequency_penalty` and `presence_penalty`, but whether the provider's penalty window reaches back to the
previous reply is not known, so it may not touch cross-turn copying. A second seed of gemma3:4b with the card on and off at 200 turns, to see whether the
card brings the loop forward. A player that varies what it does.

**Follow-up (2026-11-24): is it the model? Gemma 4 E4B with the card on, 300 turns.** The same story, seed, sheets, scripted player, squeezed memory
(window 4, budget 5000) and card as the gemma3:4b run, with Gemma 4 E4B (the heretic quant) as the Writer and as the card's reader.

| | gemma3:4b, card on (its first 300 turns) | Gemma 4 E4B, card on |
|---|---|---|
| look probes held / drift / none | 31 / 2 / 4 | 24 / 1 / 12 |
| of those that named a colour, right | 31 of 33 (94%) | 24 of 25 (96%) |
| words a turn, per 50 turns | 236, 596, 968, 1,198, 1,146, 1,068 | 293, 304, 298, 296, 306, 320 |
| share of a reply copied from the previous one, per 50 turns | 0.06, 0.56, 0.76, 0.82, 0.83, 0.79 | 0.00 in every block |
| 8-word runs repeated anywhere, per 50 turns | 0.06, 0.57, 0.78, 0.82, 0.83, 0.79 | 0.00 (whole run 0.0) |
| seconds a turn | 43.7 | 38.7 |

Gemma 4 did not copy at all and its replies stayed at about 300 words for 300 turns, while gemma3:4b was copying more than half of its previous reply by turn 100.
It holds the looks as well (96% of the colours it named, against 94%) but names a colour less often (12 of 37 probes without one, against 4 of 37), a
difference of style and not of consistency. The cost per turn is about the same. So in this setup the repetition is fixed by the Writer, not by an
engine change, and an engine-level echo guard stays an option only for people who keep gemma3:4b.

What this does not show: one seed and one story; 300 turns (gemma3:4b with the card OFF was clean for its first 250, so this is a fair test of the
card-on case that looped by turn 50 and a short one for a longer horizon); Gemma 4 without the card at length was not run; the quant is a
community "heretic" (uncensored) variant, and the stock Gemma 4 E4B instruct was not measured (it is not installed; pulling it needs your OK); the scripted
player is a harsher test than a person. Before the README's recommended Writer changes: the stock model, a second seed, and ideally 1,000 turns.

**Two cheap checks (2026-11-24).**
- *Does the engine put the previous reply in the Writer's prompt twice?* No. The soak story was played for 30 turns through the real engine with an
  offline writer whose every reply carries a unique marker. In the prompt for the last reply each earlier reply appears exactly once, as an assistant
  message, and never in a system block or a tail directive (card off; the card was not part of this audit). With the soak's window of 4 the Writer sees
  the last two exchanges verbatim plus a 6,000-character system block, so its own last reply is most of the story text it has.
- *Do repetition penalties reach the model on this Ollama?* Yes. This install bundles llama-server. `frequency_penalty` and `presence_penalty` through the
  OpenAI-compatible endpoint the engine uses, and `repeat_penalty`, `repeat_last_n`, frequency and presence through the native endpoint, all change
  gemma3:4b's output at a fixed seed, and they change it earlier than the baseline's own run-to-run drift (two identical baseline calls diverged late). A
  reported bug of the older Ollama runner, which ignored penalties, does not apply here. The probe prompt did not provoke copying (0.00 at baseline),
  so this does not show whether a penalty reduces the loop; that would take a soak arm.

**What others report (a research agent's survey; I have not checked its sources).** No source was found for this symptom in Gemma 3 4B or Gemma 4 E4B in
long chats, so the difference above is, as far as that search goes, new evidence. Adjacent reports: loops on Gemma 4 12B, 26B and 31B (penalties and
temperature did not fix them for several users; E4B's only report is a chat-template problem in multi-turn tool use), and repetition on Llama, Qwen and
Mistral Nemo in other settings. The best-evidenced mitigation is the DRY sampler (a 2026 preprint: 47% fewer loops on small models); whether Ollama
exposes it is unknown. Repetition penalties are weaker evidence, and trimming duplicated replies out of the history is plausible and untested. Watch
item: repeat the copy-share measurement (`copy_share`, per 50 turns) whenever the Writer model or the Ollama version changes.


## D-071: Gemma 4 E4B as the working Writer: the card still helps, ties are weaker than gemma3:4b, and fate does not loop (measured 2026-11-24)

**Setting.** Gemma 4 E4B (the heretic quant) as the Writer and as the card's reader, the soak story and scripted player of D-046, memory squeezed (window 4,
budget 5000), seed 5 unless said, one run per condition. Decided with the owner: Gemma 4 E4B is the model to keep working with (the stock model, a second seed
and a 1,000-turn run were skipped).

**1. The card, off against on (300 turns, sheets state the looks, a look probe every 8 turns).**

| | card off | card on |
|---|---|---|
| held / drift / none | 13 / 2 / 22 | 24 / 1 / 12 |
| right, of the colours it named | 13 of 15 (87%) | 24 of 25 (96%) |
| probes that named a colour | 15 of 37 | 25 of 37 |
| seconds a turn | 26.7 | 38.7 |
| copying of the previous reply, words a turn | 0.00 in every block, about 300 | 0.00 in every block, about 300 |

The card still helps on Gemma 4, mostly by making it say the colour (68% of probes against 41%); what it says is right either way (2 wrong against 1, small
counts). It costs about 45% more time a turn. Neither run copies or grows.

**2. The relationship and secrets probe (ties, possessions, two-hop questions, who-knows-what; 120 turns, seeds 5 and 6, no flags), against gemma3:4b's
baselines of D-067 on the same seeds.**

| | Gemma 4, seed 5 / seed 6 | gemma3:4b, seed 5 / seed 6 |
|---|---|---|
| one-hop answers right | 8 / 5 of 12 | 9 / 10 of 12 |
| two-hop answers right | 1 / 1 of 5 | 3 / 4 of 5 |
| right, with the evidence in memory's part of the prompt | 9 of 15 and 6 of 16 | 12 of 17 and 13 of 16 |
| the told secret recalled | 2 / 2 of 5 | 0 / 1 of 5 |
| a secret said by someone not told (leak) | 1 / 2 of 5 | 0 / 0 of 5 |

The evidence was in the prompt for both models (relation 5 of 6, 6 of 6; possession 6 of 6 each), so this is faithfulness, not retrieval. Gemma 4 E4B uses the
facts it is given less well than gemma3:4b and says a secret it holds more freely: it recalls the secret more (4 of 10 against 1 of 10) and leaks it more
(3 of 10 against 0 of 10). That is the other side of the copying trade: gemma3:4b loops but follows relationship facts better. The two seeds agree; 10 or
5 probes a condition make it a direction, not a proof. The flags that bring facts to the end of the prompt (tail ties D-063, follow links D-059; both off)
were measured on gemma3:4b only, and Gemma 4 is where they might matter. Not run.

**3. Fate (D-055's open question: is a larger Writer immune?), 80 turns, seed 5.** Off: words by third 301, 314, 335, 27.9 s a turn. On: 270, 280, 274,
25.8 s a turn, 73 fate rolls (surprise 29, natural and quiet 29, setback 6, windfall 4, windfall quiet 4, setback quiet 1). Neither run has an 8-word run in
three or more turns or two turns that share an opening. On gemma3:4b steering lengthened replies 1.4 to 1.9 times and two of four steered runs collapsed into a
loop (D-055); on Gemma 4 E4B, in one run of 80 turns, it neither lengthens nor loops (the steered replies are about 14% shorter). Fate stays off by default and
the caution of D-055 stands for gemma3:4b; one run at 80 turns does not make fate safe on Gemma 4.

**What this means.** Gemma 4 E4B does not copy, keeps the looks with the card, and takes fate in its stride, and it is weaker than gemma3:4b at using
ties and at keeping a secret. Not measured: Gemma 4 with tail ties or follow links, story-supplied looks, the stock (not heretic) model, a second seed, and a
1,000-turn run.


## D-072: The prompt is laid out for caching: what never changes first, what changes every turn last (built 2026-11-24, revised 2026-11-27)

**Asked by the owner.** For prompt caching, put on top (static) the prose style guidelines, the JSON formatting rules, the active world, the character, the
lorebook; at the bottom (dynamic) the recent chat history, the current scene state and the player's latest action, with changing timestamps and random seeds
going there too. After the first version he asked to fix its three weak points (activated lore in the cached block, a history window that slides, an author's
note sent every N turns), and for the history to come straight after the top. He chose to have the entries the action activates sit below the history.

**Why order matters.** A hosted provider's prompt cache and a local server's KV cache (llama.cpp, Ollama) reuse the longest EXACT prefix of the previous
request. One changed character ends the reuse, and everything after it is computed again. The old prompt did not respect that, found by playing 30 turns
offline and listing the system message heading by heading: the writer rules, then the story context in the order the author wrote it (Premise, You, **Time**,
World, the arc, recent scenes, the timeline, the people and places the action activated), and only then the static blocks (the RPG rules, the style
directives, the world-update JSON rules, `/no_think`), then the live character sheet. The clock sat third, so every change of clock or location cut the
reusable prefix there, and rules that never change sat behind text that does. The history window also slid by a message or two every turn once full, so it
never matched the turn before.

**The order now (`generation.prompt_layout: cache`, the default).**

1. The system message: the writer rules; the RPG rules when mechanics are on; the style directives (including an author's note set to depth "system" and sent
   every turn); the world-update JSON rules; `/no_think`; then `# STORY & MEMORY CONTEXT`, only what changes when an author edits or a fold lands, ordered by
   how often that is (`_stability_rank`): the premise, the player and the world; then open threads, the arc, established facts, the chapter plan, recent
   scenes, the timeline and always-on lore (`pinned` and `critical`).
2. The recent history, cut only in blocks (below).
3. One system message, `# CURRENT SCENE STATE (this turn)`: the clock and location; any section whose text holds a clock or random macro (`{{day}}`,
   `{{clock}}`, `{{time}}`, `{{random::a::b}}`, `{{roll::2d6}}`), moved whole because it can only be expanded once; everything the action brings in
   (activated lore, linked, related and referenced entries, recalled scenes, the companion chat, the story beat); and the live character sheet. Macros are
   expanded in the same seeded pass (story seed, turn), so a retry reproduces them (invariant 5).
4. The player's action, still the last message `_messages` builds. After it, as before: the lore-check directive, the canon card, the ties line, the tic line,
   fate's steer, and the chapter goal last.

**The history is cut in blocks.** `history_window` still applies the count cap and the token ceiling, then moves the window's start up to the next multiple of
`memory.history_block` messages (default 6, counted from the story's first message; `0` or `1` keeps the old sliding window). Between two cuts the history only
gains messages at its end. Rounding the start up only shortens the window (by at most one block, less one message), so the cap and the ceiling hold, and the
floor of 4 messages wins over the alignment. A window the author set small is cut in smaller blocks: at most a quarter of `short_term_turns`, and not at all
under 8. Legacy never cuts.

**An author's note sent every N turns** (N above 1) would be in the top on one turn and gone on the next, so in this layout it rides before the action as a
tail note does. A note sent every turn stays a style directive in the top.

`generation.prompt_layout: legacy` restores the old order exactly. `python -m soak play --layout cache|legacy` runs either, and the summary records what the
engine used.

**What else had to move.** The Director (quad) used to be handed everything from the context marker on, which then held the RPG rules, the clock and the
sheet; it is now assembled from the same exact texts (`_director_context`). The continuity check, the quad lore-keeper, fate and the soak's prompt probe read
memory's part of the prompt as one block, so they read `context_with_scene(messages)`: the system message plus the scene state. The Context panel
(`inspect.py`) lists the scene-state sections and does not count that message as history.

**A bug this made, caught by the existing tests.** The first version of that helper was called `story_context`, and `fate.py` already had a function of that
name, which silently replaced the import: fate was sent the Python printout of the message list. The new test passed anyway, because the clock's text was in
the printout. `fate_engine_test` caught it. The helper is now `context_with_scene`, and the test asserts that fate reads the text as text.

**Measured offline (no model).** The longest exact prefix each request shares with the one before, as a share of the whole prompt, legacy to cache:

| case | legacy | cache |
|---|---|---|
| synthetic: the clock moves and the action names someone else every turn (8 turns) | 50% | 91% |
| the soak's invented story, 4-message window, 60 turns (turns 10 to 60) | 63.3% | 79.1% |
| the same, default window that never filled, 60 turns | 68.9% | 67.1% |
| the same, default window, token ceiling binding (budget 3000), 120 turns (turns 10 to 120) | 50.0% | 60.7% |

In the third row nothing slid and the legacy top rarely changed, so there was little to gain, and the new layout loses the previous action from the reused
prefix, because the scene state now sits before it. The fourth row is the case the block cut is for. In it the system message alone goes from 77.0% to 90.7%
shared. With the clock and action fixed and the ceiling binding, the system message and history start with the turn before's on 0% of turns sliding and on
64% cut in blocks (`prompt_layout_test`, case 16).

**Measured on a model (2026-11-27).** The relationship and secrets probe of D-071 on Gemma 4 E4B (the heretic quant), 120 turns, seeds 5 and 6, `cache`
against the older order on the same seeds (the `legacy` runs are D-073's runs with both switches off). One run per cell.

| (both seeds pooled; per seed in brackets) | legacy | cache |
|---|---|---|
| one-hop answers right | 13 of 24 (8, 5) | 14 of 24 (8, 6) |
| two-hop answers right | 2 of 10 (1, 1) | 5 of 10 (3, 2) |
| right, when the evidence was in memory's part of the prompt | 15 of 31 (48%) | 18 of 29 (62%) |
| questions whose evidence reached memory's part | 31 of 34 | 29 of 34 |
| the told secret recalled | 4 of 10 (2, 2) | 5 of 10 (3, 2) |
| the secret said by someone not told (leak) | 3 of 10 (1, 2) | 3 of 10 (1, 2) |
| words a reply, mean | 270, 260 | 322, 327 |

No quality drop that the order explains, so `cache` stays the default. The gains are small counts on two seeds. Replies came out about a fifth longer on
both seeds; why was not looked into. The seconds a turn are not comparable, because test runs shared the machine during these. The health lines of the
`cache` runs (1 and 4) are ordinary fold housekeeping: empty promotions dropped and the player not added as a character.

**Limits.** (1) A cut turn (about every third one at the default block) recomputes the history. (2) A fold changes the arc, the scenes and the timeline,
which are in the top, so the turn after a fold reuses less. (3) A section with any volatile macro leaves the top whole, even if the macro is one word in a
long entry. (4) Activated lore now sits after the history, near the action; the A/B above covers the whole new order, not that move on its own. The seconds a
turn are still not measured; a hosted provider's own hit count shows in the usage panel's `cached` figure. (5) A system message between the history and the action is already how the tail author's note works, and the llama-family fold of
D-054 only touches the messages after the action.

**What would change this.** A quality drop on the probes that the order explains (ties or looks worse with `cache` than with `legacy` on the same seed), or a
model that follows the old order measurably better. Then `legacy` becomes the default; the switch is kept for that.

Tests: `tests/prompt_layout_test.py` (17 cases) and a soak `--layout` case in `soak_reply_cap_test.py`. In a copy of the code, 29 breaks were tried and each
turned the tests red, among them: static blocks appended after the context, volatile macros ignored, the scene state after the action, the Director losing the
rules or the clock, the three side calls reading the system message only, fate handed the message list, the soak probe reading the system message only, the
history never cut, cut the wrong way, cut under the floor or cut in legacy, a small window cut in the full block, an every-N note left in the top, activated
lore left in the top. Existing tests that assumed the old positions were changed, with the reason written into them (`phase4_test`, `link_follow_test`,
`canon_inject_test`, `chapter_pressure_test`, `tics_test`, `tail_ties_test`, `cast_test`).


## D-073: Facts next to the action help Gemma 4 use them: follow links and the ties line together (measured 2026-11-24)

**Run.** The relationship and secrets probe of D-071 on Gemma 4 E4B (the heretic quant), 120 turns, seeds 5 and 6, with `--follow-links --tail-ties`
(D-059, D-063), against the same seeds without them. One run per cell; the old prompt layout (before D-072).

| (both seeds pooled; per seed in brackets) | both off | both on |
|---|---|---|
| one-hop answers right | 13 of 24 (8, 5) | 21 of 24 (11, 10) |
| two-hop answers right | 2 of 10 (1, 1) | 9 of 10 (4, 5) |
| right, when the evidence was in memory's part of the prompt | 15 of 31 (48%) | 30 of 34 (88%) |
| questions whose evidence reached memory's part | 31 of 34 | 34 of 34 |
| the told secret recalled | 4 of 10 (2, 2) | 8 of 10 (4, 4) |
| the secret said by someone not told (leak) | 3 of 10 (1, 2) | 6 of 10 (4, 2) |
| leaks, among the leak questions with the secret in the prompt | 3 of 8 | 6 of 10 |
| seconds a turn | 24.3 and 23.3 | 24.0 and 23.1 |

**Read.** The gain is mostly faithfulness: with the evidence already in the prompt, saying it again next to the question made the model use it. That is the
opposite of D-067, where the ties line alone did nothing for gemma3:4b. It costs no time. The leaks rose on seed 5 and not on seed 6; in seed 5 the secret
was in the prompt for all five leak questions both with and without the switches, so the model used what it already had more often. The two switches ran
together, so neither one's share is known, and these are small counts.

**Decided.** Both stay off by default for now. The lore web (D-074) changes how links are followed, so the form that ships is measured again, secret leaks
included, before any default changes.

**Measured again in the shipped form (2026-11-27):** links followed both ways (D-074) and the `cache` layout (D-072), same probe, model and seeds, against
the `cache` runs of D-072 with both switches off.

| (both seeds pooled; per seed in brackets) | both off | both on |
|---|---|---|
| one-hop answers right | 14 of 24 (8, 6) | 19 of 24 (10, 9) |
| two-hop answers right | 5 of 10 (3, 2) | 8 of 10 (3, 5) |
| right, when the evidence was in memory's part of the prompt | 18 of 29 (62%) | 26 of 33 (79%) |
| questions whose evidence reached memory's part | 29 of 34 | 33 of 34 |
| the told secret recalled | 5 of 10 (3, 2) | 6 of 10 (4, 2) |
| the secret said by someone not told (leak) | 3 of 10 (1, 2) | 3 of 10 (3, 0) |
| words a reply, mean | 322, 327 | 295, 307 |

**Read.** The answers improved on both seeds again, by less than before because the `cache` order alone already answers better. Leaks totalled the same, but
moved in opposite directions by seed (1 to 3, 2 to 0), so five leak questions a run are too few to tell a change from noise. Over both measurements they are
6 of 20 off and 9 of 20 on. The replies counted as leaks were read: in each, a character states the secret aloud. **Still off by default:** the gain on
questions is clear, and that leaks do not rise is not shown. A player whose story does not turn on secrets gains by switching both on.


## D-074: The lore web: one graph of how entries point at each other, followed both ways, drawn and edited in the app (built 2026-11-27)

**Asked by the owner.** "Items can refer to each other in a sort of web", as he saw in AI Dungeon and FictionLab. FictionLab's documentation calls its
memory feature the Memory Matrix and its lore entries can be "Linked Lore Pieces": a link makes two pieces more likely to be activated together. The three
pages read show no graph view and do not say whether a link works both ways. For AI Dungeon, nothing found confirms that one story card brings another.

**Where we stood.** Four things in the files already made one entry point at another: a `relationships:` line (any entry), an item's `holder:`, a `links:`
line and a `[[slug]]` reference in the text. `links:` and references gave a one-line "Referenced" copy. The follow pass (D-059, off) walked holders and ties,
but only the way they were written: naming the person who carries the brass lamp key never brought the key.

**The web (`coderain/loreweb.py`).** One set of edges (holds, tie with its note, link, mention), read from the Markdown each time it is needed. Nothing about
the web is stored: a few hundred entries are cheap to read, Markdown stays the only truth (invariant 7), and there is no second copy to fall out of step.
SQLite is used for the story search (D-075), not for the web. A reference that names no entry is left out, never guessed; a mention beside a stronger edge to
the same entry is dropped.

- **Walked both ways** by the follow pass and the ties line: what the activated entry states comes first (so a crowded web still brings what the one-way pass
  brought), then what points at it. A fact is always said in the direction its file states it ("Brass lamp key is held by Hollis Wren"), whichever end was
  named. A mention is drawn but never walked: half the entries mention the town.
- **Secrets.** A hidden entry is never pulled in by an edge in either direction, and a followed entry's line never names a hidden entry it is tied to (the
  old line did: a followed person's tie to a hidden patron printed the patron's name). The author's gates (`chance: 0`, `delay`, `triggers_not`) hold in both
  directions.
- **Caps unchanged:** one hop, at most 4 per source and 6 a turn, within the lore budget.
- **Co-activation** (the FictionLab idea), only with the pass on: an activated entry joined to another activated or always-on entry by a holds, tie or link
  edge ranks 25% higher for the lore budget. An activated entry scores at most 10, so the boost cannot reach the 100 that skips the budget.

**The app.** "Lore web..." in a story's Memory window and in the world builder: a drawing of every entry and connection (a plain force layout with no random
numbers, `webapp/js/loreweb_layout.js`), a picker and keyboard focus so the drawing is never the only way, and each entry's connections with a Remove button.
Adding one writes a tie with an optional note on the stating entry's `relationships:` line, which a fold keeps and whose note it never rewrites (`merge_ties`);
adding again to the same entry replaces the note, since the author's word wins. Removing takes only that tie, link or holder; a mention is edited in the text.
A `;` in a note becomes a comma, since `;` separates ties. Writes are refused while a turn is generating. Two switches in Settings, "Follow connections" and
"Repeat key facts next to your action", are `memory.follow_links` and `memory.tail_ties`.

**Off by default, on purpose.** D-073 measured both switches together in the one-way form and found large gains in using facts, with more secret leaks on one
seed. The two-way form is measured, leaks included, before any default changes.

**Not done.** More than one hop in the drawing's follow; the fold adds ties only for characters, as before; a web of a hundred or more entries draws crowded
(the picker and the list still work).

**What would change this.** The measurement showing the two-way pass answers worse, or leaks more, than the one-way pass on the same seeds: then the follow
pass goes back to forwards only and the drawing stays.

Tests: `tests/loreweb_test.py` (10), `loreweb_api_test.py` (7), `loreweb_layout_test.py` (5, in Node) and browser check 52 in `webapp_smoke_test.py`; 20
breaks tried in copies, each turned a test red (one first slipped through because the test entry had a single tie). Four link-follow cases and the ties tests
changed for the two-way walk, with the reason written in each.


## D-075: Search of the story's own words, in SQLite, by keyword and by meaning (built 2026-11-27)

**Asked by the owner,** from the second architecture blueprint he shared: find old passages by keyword and meaning, locally, with SQLite. A fold keeps what a
summary keeps, and the exact line someone said forty turns ago is gone from the prompt. Semantic recall (Phase 5) searches entries and scene summaries,
never the story's own words, and the memory tool resolved only a turn range, a scene or a timeline line.

**What it is (`coderain/storysearch.py`).** Every turn is cut into passages of at most 500 characters (paragraphs together, long ones at sentence ends) and
indexed in `<save>/search.db`: SQLite FTS5 with Porter stemming, ranked by BM25. A passage must hold at least two of the action's search words (one if there
is only one); stop words are not searched. With semantic recall on, the same embedder also ranks passages by meaning (cosine above 0.3, at most 64 new
embeddings a turn, so a long story catches up over a few turns), and the two lists are merged by reciprocal rank fusion (k 60). The prompt gets at most 3
passages, one per turn, in story order, at most 1,500 characters, quoted with their turn number, the player's lines marked, at most one of them the
player's, and none that adds no word to the action (both added after the measured run below): the section "From earlier in the
story", in the per-turn message below the history (D-072) and first to give way under a tight budget. Only turns BEFORE the history window are searched; not
for Continue, the opening, the move suggestion or the Context panel, whose input is the app's own words. A `{{macro}}` in story text is kept as text. When
the memory tool's reference matches no timeline line or scene, it is searched for in the story itself. That part is not behind the switch, since it only
runs when the model asks the tool for something and would otherwise be told nothing.

**Derived, never truth (invariant 7).** The index is synced to the transcript turn by turn, by content, before every search, so undo, retry, swipe, edit and
branch leave nothing stale, and deleting it only costs a rebuild. A broken index is logged and the turn runs without the section. Export, duplicate,
branch and snapshots now also skip SQLite's side files (`-wal`, `-shm`, `-journal`), which they copied before for semantic recall's index too.

**Off by default** (`memory.story_search`, a switch in Settings), as every new prompt section is until measured.

**The blueprint's note on embedding prefixes did not hold here.** nomic-embed-text's model card asks for `search_document:` and `search_query:` prefixes, and
Ollama does not add them. Measured on this machine, 16 questions over 30 passages of an invented story: without prefixes 15 of 16 answers ranked first
(all 16 in the top three, mean reciprocal rank 0.969), with them 13 of 16 first (all 16 in the top three, 0.896). Not added. A larger test that shows a gain
would change that.

**Measured, first form (2026-11-27):** the relationship and secrets probe of D-071 on Gemma 4 E4B, 120 turns, seeds 5 and 6, search on, against the
`cache` runs of D-072 with it off.

| (both seeds pooled; per seed in brackets) | search off | search on |
|---|---|---|
| one-hop answers right | 14 of 24 (8, 6) | 13 of 24 (8, 5) |
| two-hop answers right | 5 of 10 (3, 2) | 3 of 10 (1, 2) |
| the told secret recalled | 5 of 10 (3, 2) | 7 of 10 (4, 3) |
| the secret said by someone not told (leak) | 3 of 10 (1, 2) | 4 of 10 (2, 2) |
| words a reply, mean | 322, 327 | 314, 309 |

These are small counts and not a verdict either way. Two things limit them. In every recall question the secret was already in the prompt with search
off, so this probe cannot show the one thing the search is for, bringing back what has left the prompt. And the drop in hop answers was on first asks
(10 to 6 of 18), not on repeated ones, so the repeats below do not explain it. The health lines (1 and 18) are all fold housekeeping; the search never
failed.

**What the quotes showed, and the fix.** 136 of 153 quotes were the player's own lines, and 21 of 54 questions had the same question, asked earlier,
quoted back. An action shares its words with earlier actions, and BM25 ranks short passages high, so they beat the paragraphs that say what happened.
Now a passage that adds no word to the action (in any form) is left out, one new word being enough so that a short answer survives, and at most one
quote is the player's, since what the player told someone is theirs. The same two stories replayed through the old and the new code, no model:

| over 54 questions, 162 quotes | before | after |
|---|---|---|
| quotes that are the player's own lines | 139 | 54 |
| questions quoting the same question back | 24 | 0 |
| recall questions where a quote holds the secret (of 10) | 3 | 5 |
| leak questions where a quote holds the secret (of 10) | 2 | 3 |

(The replay approximates the history window, hence 139 where the run quoted 136.) The last two rows are one thing seen twice: the better the search
finds what was told, the more often it puts it in front of someone who was not told.

**Not measured:** the fixed form on a model, whether the Writer uses a quote, and whether a search helps once something has left the prompt, which
needs a probe whose told fact is gone from memory. **Limit:** a passage is the
story as the player saw it, so a secret one character whispered can be quoted when someone asks about its subject; nothing tracks who heard what.

**What would change this.** Passages that mislead the Writer more than they help in a measured run, or noise on most turns: then the two-word rule goes up or
the search runs only when the action asks about the past.

Tests: `tests/storysearch_test.py` (10 cases); 28 breaks tried in copies, all turned it red. The new filter had left an older check, one quote a turn,
testing nothing (both its passages now added no word); a break that stayed green showed it, and the check was rebuilt.

## D-076: Hosted model settings: OpenRouter provider choice, Min-p, strict JSON (built 2026-11-27)

**Asked by the owner,** from the second architecture blueprint: which providers may serve a hosted request and whether they may keep it, `min_p`, and
enforced JSON for the calls that must return it. All three are off unless set.

**OpenRouter's provider block** (`generation.openrouter_provider`) is sent as the request's `provider` object, only to openrouter.ai (matched on the
whole host name), including semantic recall's embedding calls when they go there. Settings writes `order`, `allow_fallbacks`, `data_collection`, `zdr`
and `require_parameters` (field names checked against OpenRouter's docs on 2026-11-27) and keeps any other key written by hand. **It is never dropped to
make a request succeed.** It can carry the user's privacy choice, so a request that cannot be served that way fails with the server's reason, and a value
that is not a mapping stops the request rather than going out without it. In Settings, a name that cannot be a provider is refused, since dropping it
would loosen the choice without saying so.

**Min-p** (`generation.min_p`) goes in `extra_body` only when set. **Strict JSON** (`generation.json_mode: true`) sends `response_format:
{"type": "json_object"}` on the JSON calls (planner, folds, generation, fate), only when the prompt itself asks for JSON, which some providers require; never
on prose, and never beside tools.

**A server that refuses one of these** (400 or 422) must not end a turn. A refusal naming the setting drops it for that client, and usage accounting stays
on. A refusal naming neither is retried without both, and they are given up only if that works, so an unrelated failure (too long, a bad model name) does
not cost them. Either way the story's health log says so (invariant 2). The memory tool's loop, which does not stream, has the same care now; before, a
server that refused `reasoning` there failed the call.

**Ollama ignores Min-p and the repetition penalty here (measured 2026-11-27, Gemma 4 E4B).** The app talks to Ollama's OpenAI-compatible endpoint. With
`min_p` 1.0 at temperature 2, where only the likeliest token should survive, five requests gave four different replies; Ollama's own `/api/chat` with the
same setting gave one. For `repetition_penalty`, an older setting, at temperature 0 with a fixed seed the text was identical with 2.0 and without it, while
the native `repeat_penalty` changed it. Both labels in Settings now say so; the old one read "(local models)". Making them work on Ollama would mean sending
turns through its own API, which is not done.

**Not measured:** whether strict JSON improves any stage on any model, and whether other local servers use either setting.

**What would change this.** A provider whose refusal wording hides which setting it means so often that the retry costs more than it saves, or a model where
forced JSON makes a thinking model answer emptily: then strict JSON becomes per stage.

Tests: `tests/hosted_settings_test.py` (11 cases); 30 breaks tried in copies, all turned it red (one first slipped through and the test was
strengthened).

## D-077: Memory summaries after the reply, beside the next turn (built 2026-11-27)

**Asked by the owner,** from the second architecture blueprint: summaries must not hold up the next turn, and one made from turns that a retry or a branch has
since changed must not land. A fold was already run after the prose streamed, but the turn lock and the reply's "done" were held until it finished: on a
real save, about 4,300 output tokens on 1 turn in 7, with Send refused all that time.

**Three moves, one pipeline.** The fold is split into `next_step` (read what it will summarize), `ask` (the model call, which writes nothing but a health
line on failure) and `apply_step` (write). The inline fold uses the same three, so the two paths cannot drift; its files and events are byte for byte what
the step-by-step path produces.

**With `memory.background_folds: true`** (Settings, "Summarize in the background"; off by default, only a real true) the web server sends "done" with this
turn's mechanics events, then runs due folds on their own thread: the generation lock is held to read and to write, and free while the model answers. A
turn, retry, swipe, Continue or undo goes ahead meanwhile. A turn that meets the lock during a write waits and says "Finishing the memory summary".
Changes to the story's memory (files, plan, world, lore web, cast, merge, delete, branch, import) are refused with a plain message, as during a turn, so a
summary made from the old text cannot overwrite them. Fold events ride the next reply, with "memory: writing a summary in the background" on the one that
started it. One fold runs at a time. The CLI and the desktop app fold inline as before.

**An outdated step writes nothing.** A scene step applies only if the fold pointer has not moved and the turns it summarized are word for word the same
(turns added after them do not matter); a chapter that changed meanwhile is not advanced by it. An arc step applies only if the pointer, the scenes it read
and `arc.md` are unchanged, so a hand-edited arc survives. A dropped step says so in the health log and is made again after a later turn. A fold stays one
way (invariant 6): nothing is applied that is later undone.

**While a summary is overdue, the history keeps every turn it has not covered**, past the short-term count and past the cache layout's block cut (D-072);
the token ceiling still applies. Without this, the reply written meanwhile would have had the oldest unsummarized turns in neither history nor memory.

**What stays under the lock:** planning the first chapters on a story's first fold, and planning the next chapter when one completes. Both are model calls,
once in a while; a turn sent then waits for them.

**Limits.** On a model on the same computer, the summary and the next reply share it: Ollama queues them or runs them side by side, each slower. What a
local player gains is that the reply is theirs to read and answer at once; with a hosted model the two truly run together. If the app closes while a fold is
being asked for, nothing was written and it is made again. The events of a fold that ends after the last turn of a session are not shown, though the memory
is written.

**Not measured:** how much time this saves a player, and whether the extra unsummarized turns in the prompt matter.

**What would change this.** Outdated drops common enough to waste model calls (players who retry right after the turn a fold starts on): then the fold waits
for the next turn before starting.

Tests: `tests/background_fold_test.py` (10 cases, the server ones with a summary call held open on purpose); 22 breaks tried in copies, all turned it red.


## D-078: The two facts switches are on by default; keeping a told secret is left to the writer's rule (owner's call, 2026-11-27)

**Decided by the owner,** who accepts the leak risk and relies on the Writer following the instruction that a character who is not supposed to know
something does not bring it up.

**What changes.** `memory.follow_links` (D-059, D-074) and `memory.tail_ties` (D-063) are on when the config does not mention them
(`config.facts_switch`, which the engine and the Settings page share). A key that is written is on only for a real true, as before. A config saved with a
box unticked stays off. Story search (D-075) and background summaries (D-077) stay off.

**What guards a secret.** An entry marked hidden is never followed or repeated (D-059, D-063): that part is code. A fact told inside the story is guarded
only by the rule "What characters know" in the default writer rules (shipped since rules version 8). That rule was in the Writer's prompt in every measured
run, with the switches off and on, so the leak counts of D-073 already include it: over both measurements 6 of 20 off and 9 of 20 on, Gemma 4 E4B (the
heretic quant). So relying on the rule means accepting counts like these: this model breaks it some of the time. A `writer-rules.md` edited to drop
that section has no guard.

**The soak** still sets both off unless `--follow-links` or `--tail-ties` is given, so earlier runs stay comparable.

**What would change this.** A story that turns on who knows what, where characters keep saying things they were never told: untick the two boxes. A longer
probe showing leaks clearly higher with them on, with the model in use.

Tests: `link_follow_test` 14, `tail_ties_test` 9 and `loreweb_api_test` 7.


## D-079: A fixed model check to run when switching models, scored by code (built 2026-11-27)

**Why.** Models differ in ways a few turns of play do not show, or show only as a thinner memory: ties and possessions answered wrongly, a told secret
coming out of the wrong mouth, the player's lines written for them, a memory summary the app cannot read (the turn goes on regardless). The play soak finds
these at about an hour a run. The check asks the same questions of every model in minutes and compares with the last model checked.

**How.** `python -m soak check --model NAME` (`soak/check.py`). One invented story (the soak's town, with its ties, possessions and two secrets told in a
fixed six-exchange history) built afresh for each question, so one answer never reaches the next. The real engine, the app's shipped settings (the memory
switches are not written, so the check runs what the app runs), temperature 0.9. Per round: the 12 graph-probe questions (D-058) with a plain ask, two
actions with no words of the player's, two tense ones, one action asked short and long, three turns in a row for self-copying, and the three JSON jobs (memory
summary, first chapter, quad planning step) read by the app's own code. Five checks apply to every reply. Two rounds by default: 42 replies and 6 JSON
calls. A model call that fails stops the run with no report, since a report of failed calls would read as a bad model.

**Scoring** is code, pass or fail: simple patterns that catch the plain forms and will miss some (a paraphrased leak such as "the northern beacon" counts as
clean, as in the soak's scorer). So the report quotes failed replies and saves every reply.

**Comparison.** With the newest report of another model by default (`--against` to choose, `none` for no comparison). A check is called worse or better
only when its share of passes moves by a quarter AND by at least two replies: with a handful of replies, one is chance. A check with one reply a round
therefore needs two rounds, both going the other way. Reports of another check version are not compared.

**What would change this.** A scorer that is often wrong on a real model's replies: fix it and bump `PACK_VERSION`, which stops old reports being compared
with new ones. A failure the owner meets in play that no check sees: add a check.

Tests: `tests/soak_check_test.py`: an offline writer that passes every check and one that fails every check, each scorer's edge cases, the comparison's
thresholds, the refusals, and a model that cannot be called.


## D-080: The status block's label, copied into replies, is removed in code (found by the first real model check, 2026-11-27)

**Found.** The first real run of D-079 flagged two Gemma 4 replies ending "Nothing changed:". That is the label the world-sidecar instruction puts over
its empty example block. It came in with the 2026-07-30 rewording (commit 08c988e) that made small models send the block far more often: that A/B counted
blocks and applied changes, not what the reader was shown. Reading every saved reply of the long runs (6,931): it ended 2,288 of 3,100 gemma3:4b replies and 1,421 of 2,814 Gemma 4 E4B
replies (the heretic quant); llama3.1:8b and the hosted models never wrote it. The reader saw it, the transcript kept it, and the next turns saw it in the
history, which teaches the model to write it again. Of 3,765 replies with the words at the start of a line: 3,584 the label alone as the last line, 164 the
label and then the block's JSON without the ```rpg fence (so raw JSON reached the reader), 17 the label and then the model's own editing note. No probe
had ever scored the shown text for this, which is why months of soaks did not report it.

**Decided.** Remove it in code (`sidecar.drop_status_label` and its streaming form), only at the very end of a reply: the label alone on its line, or with
the block's JSON under it. A full stop instead of the colon, a sentence that starts with the words, and a label followed by more text are left alone, so
prose cannot be cut (the 17 editing notes therefore still reach the reader). Both writer paths stream through the filter; whole-reply paths go through
`strip_sidecar`. The prompt's history drops it from stored replies, so a story saved with it stops teaching it; transcripts on disk are not rewritten.

**Not changed: the instruction.** Its wording is what got small models to send the block at all (see the comment above `WORLD_SIDECAR`), and a rewording
would need the compliance measured again. The test reads the labels out of the instruction, so a reworded label that the filter would miss fails it.

**A block written without its fence is still not applied,** as before; the health log now says so. Applying it would be a change to what the model's
output can do to a story, and needs its own look.

Run over all 6,931 saved replies: 3,748 cleaned, the streamed and the whole-reply cut agree on every one, nothing but the label and what hangs under it
was removed, and the 17 editing notes are what remains.

Tests: `tests/status_label_test.py`.


## D-081: Test one setting against the same model, and say what you expect first (2026-11-27)

**Why.** The owner approved three habits taken from arXiv 2611.18856 (Self-Improvement Memory, Google Cloud AI and Google DeepMind). In it, a harness
tuned on one model started below the plain one on another, and the record kept for whoever changes the harness holds each fix's reason and its expected
and observed result. We have met the same: the ties line alone did nothing on gemma3:4b (D-067), and both switches together helped Gemma 4 (D-073),
which is not a like-for-like pair.

**Built into the model check** (D-079). `--set NAME=VALUE` runs one setting changed and compares with the newest run of the same model without it; a
later normal run ignores changed runs. Only settings this short story can show something about are accepted (it is too short for story search,
background summaries or the history cut), and a mistyped name is refused, since it would read as "no difference". `--predict CHECK=better|worse|same|
not-worse` is saved to `prediction.json` before the first reply, and the report says which predictions held. With the check's two-rounds-a-run sizes only
large effects show; use `--repeats` for smaller ones.

**Also corrected in the check after its first real run** (check version 2; version 1 reports are not compared). "Prompt text" is read on what the
reader sees, because 29 of 42 replies failed only for sending the status block the app asks for. A new check asks that the block arrives. The letter's
secret now goes to someone who is nobody in the story: "the keeper of the north beacon" let "it is for Maribel Voss, the lighthouse keeper" score as
forgotten from the one told and as kept from the one not told. The saved D-073 runs were read for that and show no such reply, so those counts stand.
Naming someone by their work ("the keeper of the lighthouse") counts as naming them.

**The habit** is in `CLAUDE.md` ("Measuring") and the index at the top of this file.

Tests: `soak_check_test.py` cases 1, 3, 5, 8 and 9.

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

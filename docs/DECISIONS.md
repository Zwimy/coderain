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

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

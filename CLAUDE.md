# Coderain — working rules

Read this before changing code here. It is short on purpose; everything in it
was paid for by a real defect.

## What this app is

A local-first AI interactive-fiction engine. Memory is Markdown files on disk;
the model is the user's own (local Ollama or a hosted key). FastAPI (`server.py`
+ `srv/`) with a vanilla-JS ES-module SPA (`webapp/js/`). No build step.

`saves/` and `.env` in the repo root are **live user data**. Never point a test,
a script, or a browser session at them — see "Never touch live data" below.

## The invariants

These are the promises the engine makes. Breaking one is always a bug, however
reasonable the change looked.

1. **The validator is pure code, never an LLM.** Dice are engine-rolled. Every
   delta is validated before it reaches state, including magnitude, cardinality
   and text length.
2. **A turn never dies from bad model output.** Malformed anything degrades to a
   no-op. But degrading **invisibly** is its own bug: write to `memory/health.jsonl`
   (`store.log_degraded`) so it surfaces in the Context panel.
3. **State and the replay ledger agree.** `memory/events.jsonl` must always
   describe the state that is actually applied — a branch rebuilds from it.
4. **`pinned:` / `weight: critical` are always in context.** Any budget, any turn.
5. **Replay-safety.** Anything random (activation chance, group lottery, macros)
   is seeded by `(story seed, turn index, subject)` so retrying a turn reproduces.
6. **A fold is one-way.** After it, the paragraph *is* the memory. Fold bugs are
   permanent and silent, so they get the most paranoid review.
7. **Markdown is the source of truth.** State files mirror it, never the reverse.

Deliberate design calls live in `docs/DECISIONS.md`. Read it before "fixing"
something that looks inconsistent — it may be a decision, and each entry records
what evidence would change it.

## Coding standards

Follow the surrounding code first; where it is silent, these apply.

**Python** — PEP 8, with the repo's existing choices: 4-space indent, ~88-char
lines, `snake_case`, `_leading_underscore` for module-private. Type hints on
public signatures (`from __future__ import annotations` is already on). Prefer
small pure functions over methods that reach into `self` for everything.

**JavaScript** — ES modules, 2-space indent, `const` by default, no globals. The
SPA has no build step and no framework; keep it that way. Anything reachable
from another module gets an explicit `export`.

**Naming and shape**
- One name, one meaning, one scope. Do not reuse a local for a second purpose
  (`picked` was a dict of entries in one half of `assemble()` and a list of
  budget segments in the other; that is how the four-stage split started).
- A function that needs a comment to explain *what* it does wants splitting. A
  comment explaining *why* is the good kind — keep those.
- Guard clauses over nesting. Early return beats `else`.

**Comments** — explain the reasoning that is not in the code: why a bound is 32,
what broke before, what a future reader would otherwise "simplify" back into a
bug. Do not narrate the syntax. A comment that contradicts the code is worse than
no comment (`trinity.py` claimed it stripped the sidecar "defensively anyway"
while gating it on `rpg_on`, and that comment is why the leak went unexamined).

**Error handling**
- Never a bare `except:`. Catch the specific exception, and say in a comment why
  swallowing it is correct.
- `except Exception` is allowed on paths that must not break a turn — always with
  a `# noqa: BLE001` and a health-log line.
- Validate at the boundary (model output, HTTP body, file read), then trust it
  inward. Do not re-check the same thing at five depths.

**Bounds** — anything derived from model output needs a bound: magnitude,
list length, and string length. All three, not one. Unbounded values end up
rendered into every subsequent turn's context, which makes them permanent.

**Dependencies** — the runtime dependency list is deliberately short. A new
runtime dependency needs a reason in the commit message. Dev/test-only
dependencies must degrade to a clean skip when absent (see
`tests/webapp_smoke_test.py`).

## Tests

`python run_tests.py` runs every suite (standalone scripts, offline, stub LLMs,
hermetic temp `CODERAIN_HOME`). Green is the bar for every commit.

- A new suite goes in `tests/`, named for the behaviour it protects.
- The docstring says **what broke** and what each numbered assertion pins. That
  is what makes a failure readable a year later.
- **A test that cannot fail is worthless.** After writing one, break the fix and
  confirm it goes red. Several of this repo's suites were written this way and
  two of them caught mistakes in their own assertions.
- When a test fails after a change, decide honestly whether the test or the code
  is wrong. If the test encoded old behaviour, fix the test *and write the
  reasoning into it* (see `sweep2_test.py` §12).

## Never touch live data

The repo root is a real install: real saves, a real `.env` with a real API key.

- Any script or test sets `CODERAIN_HOME` to a fresh temp dir **before**
  importing `coderain`.
- Never drive the UI against a server running on the repo root while testing
  settings. A browser test once typed a placeholder into the API-key field and
  overwrote the user's real key. It was not recoverable.
- Scratch files go in the session scratchpad, never in the repo.

## Git

- **Never `git checkout <file>` to revert an experiment on uncommitted work.** It
  discards everything uncommitted in that file, not just the experiment. Commit
  first, or edit the change back by hand. This cost a dozen fixes once already.
- Commit before starting anything exploratory — a sweep, a refactor, a
  discriminate-check on a test.
- Commit messages explain the *why* and the failure being prevented, in plain
  sentences. They are the best documentation this repo has.

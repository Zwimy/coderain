"""Shadow canon: the Scribe and the ledger run BESIDE the engine.

This is the first place engine code uses `canon/`. By default it is observe-only:
it reads the transcript, asks a local model for the facts each narrator turn states,
keeps them in a canon ledger, and writes a report of what it saw, including every
time the story contradicted a fact it had already recorded. With `shadow: true` alone
nothing it produces is ever put into a prompt.

Putting canon in front of the Writer is a second, separate flag (`inject`, D-027). It
has three states: "off" (the default), "preview" (the card is built and logged each
turn but NOT sent, so a person can read it first) and true (it is sent). The card is
built from an immutable snapshot this thread publishes, never from the live ledger,
so a turn never waits for it, and it is cut back to the turns the transcript still
has, so an undone reply's facts never reach the Writer (canon/card.py).

What makes that safe, each of which a test pins:

  * Derived, not authoritative. The ledger lives in <save>/canon/ and is rebuilt
    from the transcript, so deleting the folder loses nothing (invariant 7).
  * It follows the transcript by CONTENT. Undo, retry, a swipe, an edit and a branch
    all change the transcript, and the engine has a separate code path for each.
    Hooking all of them would be a standing source of drift, so instead each pass
    compares a hash of every narrator turn with what was processed, rolls the ledger
    back to the first turn that differs, and replays from there. One mechanism for
    every way a transcript can change.
  * It never costs a turn anything. It runs on its own thread, waits while a turn is
    generating, never raises into the engine, and reports a failure to the health log
    (invariant 2: degrade, but never invisibly).
  * It is LOCAL. A real story is read by a model nobody chose per call, so anything
    but Ollama on this machine is refused (canon.scribe.require_local).
  * Its report and per-turn rows hold values, counts and turn numbers, never
    narration. The ledger keeps the short quoted span behind each fact as provenance;
    it lives in the save folder, beside the transcript those spans came from, and
    does not travel with an export.

Off unless config.yaml says so:

    canon:
      shadow: true
      model: gemma3:4b            # any local Ollama model
      backfill: 200               # earlier narrator turns to read the first time, or "all"
      inject: preview             # off (default) | preview | true. Needs shadow: true
      card_chars: 2400            # the most the card may add to a prompt (about 600 tokens)
      inject_state: true          # false: identity only (hair, eyes, marks), no clothing etc.
      identity: needed            # needed (default): a look is shown only when it matters; always: every turn
      identity_via_pronoun: false # true: a look said with "he"/"she" is read for the one character the nearest
                                  # sentences name (about 94% right when it answers, D-035); off = D-024
      think: false                # default: ask the model not to reason first (a reasoning model such as
                                  # Qwen3.5 otherwise spends its whole answer budget thinking, D-040)

What a turn's card did is in <save>/canon/injections.jsonl (one row of counts per turn)
and <save>/canon/card-last.txt (the last card in full, marked sent or preview).
"""
from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import threading
import time
from collections import Counter
from pathlib import Path

from canon import Store
from canon.card import Card, Snapshot, build_card, content_hash, coverage
from canon.corrections import FILE as CORRECTIONS_FILE
from canon.corrections import apply_to, describe, held_values, parse as parse_corrections, plan as plan_corrections, refusals
from canon.ledger import LedgerCorrupt, LedgerError
from canon.state import project
from canon.pipeline import process_turn
from canon.referents import gender_votes
from canon.replay import (AUTHORED_UNTIL, BEFORE_TURNS, GenderVotes, identity_table, passage_who,
                          player_entity, player_gender, reads_anyone, seed_entities, seed_player,
                          seed_sheets, skipped_row,
                          state_ages, totals, turn_row)
from canon.scene import FRESH_TURNS, find_scene, render_card
from canon.scribe import NotLocal, OllamaChat, Scribe, require_local

STAGE = "canon-shadow"
BACKFILL_ALL = 10 ** 9
DEFAULTS = {"shadow": False, "model": "gemma3:4b", "host": "http://localhost:11434",
            "num_ctx": 8192, "backfill": 200, "max_errors": 3,
            "inject": "off", "card_chars": 2400, "inject_state": True,
            "identity": "needed", "identity_via_pronoun": False, "think": False}
_ROWS_KEEP = 6000                    # rows.jsonl is trimmed to this many lines
IDENTITY_REACH = 2                   # sentences a pronoun may look back for its name when identity_via_pronoun is on
RECENT_FOR_CARD = 4                  # latest turns whose names pick the cast
_INJECT_LOG_BYTES = 120_000          # injections.jsonl is cut to its newest half past this


def _int(raw, default: int, lo: int, hi: int) -> int:
    """A bounded int from config. bool is rejected (YAML `true` is not a number) and
    so is anything int() cannot take, including `.inf`, which raises OverflowError,
    not ValueError (see history_budget in config.py for the save that cost)."""
    if isinstance(raw, bool):
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, n))


def settings(raw) -> dict:
    """The `canon:` section of config.yaml, validated and bounded. Anything missing
    or malformed falls back to the default, and `shadow` is on only for a literal
    true: a typo must not start sending a story to a model."""
    sec = raw.get("canon") if isinstance(raw, dict) else None
    sec = sec if isinstance(sec, dict) else {}
    out = dict(DEFAULTS)
    out["shadow"] = sec.get("shadow") is True
    for key, limit in (("model", 100), ("host", 200)):
        v = sec.get(key)
        if isinstance(v, str) and 0 < len(v.strip()) <= limit:
            out[key] = v.strip()
    out["num_ctx"] = _int(sec.get("num_ctx"), DEFAULTS["num_ctx"], 2048, 16384)
    bf = sec.get("backfill", DEFAULTS["backfill"])
    out["backfill"] = (BACKFILL_ALL if isinstance(bf, str) and bf.strip().lower() == "all"
                       else _int(bf, DEFAULTS["backfill"], 0, 100_000))
    out["max_errors"] = _int(sec.get("max_errors"), DEFAULTS["max_errors"], 1, 20)
    # Injection (D-027). "on" only for a literal true, like shadow: a typo must not start
    # putting canon into prompts. "preview" builds and logs the card but sends nothing,
    # the step to take first. It means nothing without shadow, which builds the ledger.
    inj = sec.get("inject")
    out["inject"] = ("on" if inj is True
                     else "preview" if isinstance(inj, str) and inj.strip().lower() == "preview"
                     else "off")
    out["card_chars"] = _int(sec.get("card_chars"), DEFAULTS["card_chars"], 600, 4000)
    out["inject_state"] = sec.get("inject_state") is not False
    out["identity_via_pronoun"] = sec.get("identity_via_pronoun") is True      # a literal true, like shadow: it changes what gets locked
    # The reader wants a JSON answer and nothing else. A model that reasons first (Qwen3.5 does by
    # default) spent the whole 1,200-token answer budget thinking and returned nothing, on every
    # call of an 86 minute read (D-040). So the request says think: false unless this is a literal true.
    out["think"] = sec.get("think") is True
    out["identity"] = "always" if isinstance(sec.get("identity"), str) and sec["identity"].strip().lower() == "always" else "needed"
    pl = sec.get("player")
    out["player"] = (pl.strip() if isinstance(pl, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", pl.strip())
                     else None)                 # a character slug; otherwise worked out from player.md
    return out


_hash = content_hash        # one definition for the reader and for the card that compares them


def _short(value, n: int = 60) -> str:
    s = " ".join(str(value).split())
    return s if len(s) <= n else s[:n].rstrip() + "..."


# One reconcile at a time per save folder, whatever objects exist for it. A settings
# change rebuilds every Engine, so an old worker can still be running when a new
# CanonShadow for the same save starts.
_DIR_LOCKS: dict[str, threading.Lock] = {}
_DIR_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(Path(path).resolve())
    with _DIR_LOCKS_GUARD:
        return _DIR_LOCKS.setdefault(key, threading.Lock())


class CanonShadow:
    def __init__(self, store, cfg: dict, *, scribe: Scribe | None = None, busy=None):
        self.store = store                      # the engine's MemoryStore
        self.cfg = cfg
        self.dir = Path(store.dir) / "canon"
        self.scribe = scribe                    # built lazily; tests inject a stub
        self.busy = busy                        # () -> bool, True while a turn runs
        self.enabled = True
        self._guard = threading.Lock()          # protects _dirty and _worker
        self._dirty = False
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._cstore: Store | None = None
        self._reported: set[str] = set()
        self._snap: Snapshot | None = None      # what the card is built from (D-027)

    @classmethod
    def from_config(cls, config, store, **kw) -> "CanonShadow | None":
        cfg = settings(getattr(config, "raw", None))
        return cls(store, cfg, **kw) if cfg["shadow"] else None

    # --- visibility ---------------------------------------------------------------
    def _degrade(self, reason: str) -> None:
        """Say so once per distinct reason: a down model must reach the Context panel,
        but not as one line per turn forever."""
        reason = reason[:200]
        if reason in self._reported or len(self._reported) >= 20:
            return
        self._reported.add(reason)
        try:
            self.store.log_degraded(STAGE, reason)
        except Exception:  # noqa: BLE001 - reporting a failure must not become one
            pass

    # --- running it ---------------------------------------------------------------
    def kick(self) -> None:
        """Ask for a pass and return at once. Never raises, never blocks."""
        if not self.enabled:
            return
        try:
            with self._guard:
                self._dirty = True
                if self._worker is not None and self._worker.is_alive():
                    return
                self._worker = threading.Thread(target=self._loop, daemon=True,
                                                name="canon-shadow")
                self._worker.start()
        except Exception as exc:  # noqa: BLE001 - never breaks a turn
            self._degrade(f"could not start: {type(exc).__name__}: {exc}")

    def _loop(self) -> None:
        while True:
            with self._guard:
                if not self._dirty or not self.enabled or self._stop.is_set():
                    self._worker = None
                    return
                self._dirty = False
            try:
                self.reconcile()
            except Exception as exc:  # noqa: BLE001 - a shadow must never matter to a turn
                self._degrade(f"{type(exc).__name__}: {exc}")

    def wait(self, timeout: float = 30.0) -> None:
        """Block until the worker has drained. For tests and shutdown."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def close(self) -> None:
        self._stop.set()
        self.wait(5.0)

    def _mark_dirty(self) -> None:
        with self._guard:
            self._dirty = True

    def _wait_idle(self) -> bool:
        """Yield to a turn that is generating. Between turns only: a call already
        under way is not interrupted."""
        while self.busy is not None and not self._stop.is_set():
            try:
                if not self.busy():
                    break
            except Exception:  # noqa: BLE001 - a broken probe means "go ahead"
                break
            time.sleep(0.5)
        return not self._stop.is_set()

    # --- the card (D-027) -----------------------------------------------------------
    def _publish(self, cstore: Store, state: dict) -> None:
        """Hand the card builder an immutable copy of what has been read so far. One
        reference assignment, so a turn being prepared sees the old snapshot or the new
        one, never a half-written one, and never waits for this thread."""
        try:
            player = player_entity(self.store.entries("characters.md"),
                                   self.store.read("player.md") or "", self.cfg.get("player"))
            self._snap = Snapshot(tuple(cstore.ledger.records), dict(state["hashes"]),
                                  state["first"], player)
        except Exception as exc:  # noqa: BLE001 - publishing must never break the reader
            self._degrade(f"could not publish the card snapshot: {type(exc).__name__}: {exc}")

    def _load_snapshot(self) -> Snapshot | None:
        """After a restart nothing has been published yet, so read what is on disk. Only
        when the reader is not mid-pass: the lock is tried, never waited for, because a
        turn must not wait on a model call."""
        lock = _lock_for(self.dir)
        if not lock.acquire(blocking=False):
            return None
        try:
            if not (self.dir / "shadow.json").exists():
                return None
            self._publish(self._store(), self._load_state())
        finally:
            lock.release()
        return self._snap

    def card(self, turns: list[dict], visible=(), action: str = "") -> Card:
        """The card for the turn about to be written, or a Card with no text and the
        reason. Never raises and never waits for the reader."""
        if not self.enabled or self.cfg.get("inject", "off") == "off":
            return Card(reason="off")
        try:
            snap = self._snap or self._load_snapshot()
            narr = {i: _hash(t["text"]) for i, t in enumerate(turns, 1)
                    if t["role"] == "narrator"}
            return build_card(snap, narr, [t["text"] for t in turns[-RECENT_FOR_CARD:]],
                              now=len(turns) + 1, max_chars=self.cfg["card_chars"],
                              state=self.cfg["inject_state"],
                              corrections=self.corrections()[0],
                              visible=visible if self.cfg["identity"] == "needed" else (), action=action)
        except Exception as exc:  # noqa: BLE001 - a card must never cost a turn
            self._degrade(f"no card this turn: {type(exc).__name__}: {exc}")
            return Card(reason="error")

    def record_injection(self, card: Card, mode: str, turn: int) -> None:
        """What was put in front of the Writer, or in preview mode WOULD have been: a
        row of values and counts each turn, and the last card in full. For a person to
        read before turning injection on and to audit afterwards. Never raises."""
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            log = self.dir / "injections.jsonl"
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"turn": turn, "mode": mode, **card.row()}) + "\n")
            if log.stat().st_size > _INJECT_LOG_BYTES:
                keep = log.read_text(encoding="utf-8").splitlines()[-300:]
                tmp = self.dir / "injections.jsonl.tmp"
                tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
                os.replace(tmp, log)
            if card.text:
                tmp = self.dir / "card-last.txt.tmp"
                sent = "Sent." if mode == "on" else "Preview only: NOT sent."
                tmp.write_text(f"Turn {turn}, mode {mode}. {sent}\n\n{card.text}\n",
                               encoding="utf-8")
                os.replace(tmp, self.dir / "card-last.txt")
        except Exception as exc:  # noqa: BLE001 - a log must never cost a turn
            self._degrade(f"could not write the injection log: {type(exc).__name__}: {exc}")

    # --- the author's corrections (D-028) --------------------------------------------
    def corrections(self):
        """(corrections, problems) from <save>/corrections.md, read fresh each time: a person edits that
        file by hand, and the next pass and the next card must see the edit."""
        try:
            text = self.store.read(CORRECTIONS_FILE) or ""
        except OSError:
            text = ""
        return parse_corrections(text)

    def _apply_corrections(self, cstore: Store, corr) -> int:
        """Write into the ledger whatever the corrections still need (author-level records), which is
        nothing once it is in line. Never raises: a correction that cannot be written is reported once.
        An EMPTY list is applied too: with no lines left, what a removed line set is released."""
        try:
            last = cstore.ledger.records[-1].turn if cstore.ledger.records else 0
            recs, _unresolved = plan_corrections(cstore.canon, corr, turn=last)
            for fields in recs:
                cstore.append(**fields)
            return len(recs)
        except (LedgerError, OSError) as exc:
            self._degrade(f"could not apply an author correction: {type(exc).__name__}: {exc}")
            return 0

    def view(self, turns: list[dict] | None = None) -> dict:
        """What canon holds about each character, what the author has said, and what could not be applied,
        for the app to show (D-028). Built from the published snapshot with the corrections applied, so it
        shows what the card would, and never waits for the reader."""
        try:
            text = self.store.read(CORRECTIONS_FILE) or ""
        except OSError:
            text = ""
        corr, _ = parse_corrections(text)
        out = {"shadow": True, "inject": self.cfg.get("inject", "off"), **describe(text),
               "values": [], "unread": None, "card": ""}
        snap = self._snap or self._load_snapshot()
        if snap is not None:
            canon = project(snap.records)
            last = snap.records[-1].turn if snap.records else 0
            _recs, unresolved = apply_to(canon, corr, turn=last)
            out["problems"] += unresolved
            out["values"] = held_values(canon)
            if turns is not None:
                narr = {i: _hash(t["text"]) for i, t in enumerate(turns, 1) if t["role"] == "narrator"}
                out["unread"] = coverage(snap, narr)[1]
        try:
            out["card"] = (self.dir / "card-last.txt").read_text(encoding="utf-8")
        except OSError:
            pass
        return out

    # --- the model ----------------------------------------------------------------
    def _get_scribe(self) -> Scribe:
        if self.scribe is None:
            self.scribe = Scribe(OllamaChat(self.cfg["model"], host=self.cfg["host"],
                                            num_ctx=self.cfg["num_ctx"], think=self.cfg["think"]))
        require_local(self.scribe.llm)
        return self.scribe

    # --- state on disk ------------------------------------------------------------
    def _alive(self) -> bool:
        """The save still exists. A late worker must not recreate a deleted save's
        folder by writing into it."""
        return (Path(self.store.dir) / "meta.json").exists()

    def _store(self) -> Store:
        if self._cstore is None:
            try:
                self._cstore = Store(self.dir / "ledger")
            except (LedgerCorrupt, OSError, ValueError) as exc:
                self._reset(f"the shadow ledger was unreadable "
                            f"({type(exc).__name__}); rebuilding it from the transcript")
                self._cstore = Store(self.dir / "ledger")
        return self._cstore

    def _reset(self, why: str) -> None:
        """The ledger is derived data, so the answer to a bad one is to start over."""
        self._degrade(why)
        shutil.rmtree(self.dir, ignore_errors=True)
        self._cstore = None

    def _load_state(self) -> dict:
        try:
            data = json.loads((self.dir / "shadow.json").read_text(encoding="utf-8"))
            hashes = {int(k): str(v) for k, v in data["hashes"].items()}
            first = data.get("first")
            return {"first": first if isinstance(first, int) else None,
                    "fresh": data.get("fresh") is True,
                    "hashes": hashes}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {"first": None, "fresh": False, "hashes": {}}

    def _save_state(self, state: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "first": state["first"], "fresh": state.get("fresh") is True,
                   "hashes": {str(k): v for k, v in sorted(state["hashes"].items())}}
        tmp = self.dir / "shadow.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.dir / "shadow.json")

    def _read_rows(self) -> dict[int, dict]:
        rows: dict[int, dict] = {}
        try:
            lines = (self.dir / "rows.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return rows
        for line in lines:
            try:
                row = json.loads(line)
                rows[int(row["turn"])] = row
            except (ValueError, KeyError, TypeError):
                continue                  # a torn last line
        return rows

    def _write_rows(self, rows: dict[int, dict]) -> None:
        keep = [rows[k] for k in sorted(rows)][-_ROWS_KEEP:]
        tmp = self.dir / "rows.jsonl.tmp"
        tmp.write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
        os.replace(tmp, self.dir / "rows.jsonl")

    def _append_row(self, row: dict) -> None:
        with (self.dir / "rows.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    # --- the pass -----------------------------------------------------------------
    def reconcile(self) -> dict:
        with _lock_for(self.dir):
            return self._reconcile()

    def _first_index(self, ordered: list[int]) -> int:
        """Where the first pass starts: `backfill` narrator turns before the latest,
        or the very first with backfill "all"."""
        return ordered[max(0, len(ordered) - 1 - self.cfg["backfill"])]

    def _reconcile(self) -> dict:
        out = {"processed": 0, "skipped": 0, "rolled_back_to": None, "errors": 0}
        if not self.enabled or not self._alive():
            return out
        try:
            self._get_scribe()
        except NotLocal as exc:
            self.enabled = False
            self._degrade(f"shadow mode is off: {exc}")
            return out
        self.dir.mkdir(parents=True, exist_ok=True)
        cstore = self._store()
        turns = self.store.turns()
        narr = {i: t["text"] for i, t in enumerate(turns, 1) if t["role"] == "narrator"}
        state = self._load_state()
        hashes = state["hashes"]

        # 1. Follow the transcript: roll back to the first narrator turn that is gone
        #    or reads differently from what was processed.
        bad = sorted(i for i, h in hashes.items()
                     if i not in narr or _hash(narr[i]) != h)
        if bad:
            d = bad[0]
            cstore.undo_to(d - 1)
            for i in [i for i in hashes if i >= d]:
                del hashes[i]
            rows = {k: v for k, v in self._read_rows().items() if k < d}
            self._write_rows(rows)
            out["rolled_back_to"] = d - 1
            if state["first"] is not None and d < state["first"]:
                state["first"] = d          # replay resumes at the divergence
            self._publish(cstore, state)    # a card must not show what was just undone

        # 1b. The author's corrections (D-028). Read fresh, because a person edits the file by
        #     hand, and put in line with the ledger again here, because a rollback may just have
        #     cut the records that carried them.
        corr, _bad = self.corrections()
        self._apply_corrections(cstore, corr)

        # 2. Process what is new.
        ordered = sorted(narr)
        if not ordered:
            self._save_state(state)
            self._publish(cstore, state)
            return out
        if state["first"] is None:
            state["first"] = self._first_index(ordered)
            # Was the story brand new when the reader first looked at it? Only then are the
            # character sheets that exist the author's own words (D-029); on a story that is
            # already under way they were folded out of the narration, and seeding them as if
            # authored would lock in whatever the narrator had drifted to.
            state["fresh"] = len(ordered) <= AUTHORED_UNTIL
        todo = [i for i in ordered if i >= state["first"] and i not in hashes]
        votes = GenderVotes(self._read_rows().values())
        errors, since_report = 0, 0
        for idx in todo:
            if not self._wait_idle():
                break
            now = self.store.turns()                       # it may have moved meanwhile
            if (idx > len(now) or now[idx - 1]["role"] != "narrator"
                    or _hash(now[idx - 1]["text"]) != _hash(narr[idx])):
                self._mark_dirty()
                break
            if not self._alive():
                break
            prose = narr[idx]
            entries = self.store.entries("characters.md")
            seed_entities(cstore, entries, turn=idx)
            player_text = self.store.read("player.md") or ""
            player = player_entity(entries, player_text, self.cfg.get("player"))
            seed_player(cstore, player, player_text, turn=idx)       # D-025
            if state.get("fresh") and idx <= AUTHORED_UNTIL:         # D-029: the author's sheets
                seed_sheets(cstore, entries, player, turn=idx)
            refused = refusals(cstore.canon, corr)                   # D-028: values the author called wrong
            at = bisect.bisect_left(ordered, idx)
            before = [narr[i] for i in ordered[max(0, at - BEFORE_TURNS):at]]
            if not reads_anyone(cstore.canon, prose, player, "\n".join(before)):
                row = skipped_row(idx)
                out["skipped"] += 1
            else:
                who = passage_who(cstore.canon, prose, votes=votes, player=player,
                                  before=before, player_is=player_gender(player_text),
                                  identity_reach=IDENTITY_REACH if self.cfg["identity_via_pronoun"] else None)
                rep = process_turn(cstore, idx, prose, self._get_scribe(),
                                   create_unknown=False, record_contradictions=True, who=who,
                                   refused=refused)
                v = gender_votes(cstore.canon, prose, player)
                row = turn_row(idx, rep, v)
                if rep.extraction.status in ("error", "empty_output"):
                    # The model could not be reached, or sent back nothing at all (with a
                    # schema it always has at least {"claims": []}, so nothing is a failure:
                    # a model that reasons first can spend its whole answer budget thinking).
                    # Not recorded as done, so the next pass tries this turn again, and a
                    # down server is not hammered. Recording an empty reply as "read" would
                    # mark a whole story done with no facts and say nothing (D-040).
                    errors += 1
                    out["errors"] += 1
                    if errors >= self.cfg["max_errors"]:
                        if rep.extraction.status == "error":
                            self._degrade(
                                f"the Scribe could not be reached {errors} times in a row; "
                                f"shadow mode will retry after the next turn "
                                f"({rep.extraction.error[:100]})")
                        else:
                            self._degrade(
                                f"the Scribe sent back an empty reply {errors} times in a row; "
                                f"shadow mode will retry after the next turn (a model that "
                                f"reasons before it answers needs canon: think: false, "
                                f"which is the default)")
                        break
                    continue
                errors = 0
                votes.add(v)
                row.update(self._observe(cstore, rep, idx, narr))
                out["processed"] += 1
            self._apply_corrections(cstore, corr)        # an entity may have just appeared
            hashes[idx] = _hash(prose)
            self._append_row(row)
            self._save_state(state)
            self._publish(cstore, state)
            since_report += 1
            if since_report >= 25:
                self._write_report(cstore)
                since_report = 0
        self._save_state(state)
        self._publish(cstore, state)
        self._write_report(cstore)
        return out

    def _observe(self, cstore: Store, rep, idx: int, narr: dict[int, str]) -> dict:
        """What the engine could learn from this turn, as values only: each time the
        story contradicted a fact canon already held, and the cast and card canon
        WOULD show for the next turn (never shown)."""
        held_back = [{"entity": d.entity, "slot": d.claim.slot,
                      "held": _short(cstore.canon.current(d.entity, d.claim.slot)),
                      "proposed": _short(d.claim.value)}
                     for d in rep.decisions if d.status == "contradiction" and d.entity]
        recent = [narr[i] for i in sorted(narr) if i <= idx][-3:]
        scene = find_scene(cstore.canon, recent)
        extra = {"next_cast": list(scene.cast)[:8],
                 "next_card_chars": len(render_card(cstore.canon, scene))}
        if held_back:
            extra["held_back"] = held_back[:6]
        return extra

    # --- the report ---------------------------------------------------------------
    def _corrections_line(self, cstore: Store) -> str:
        corr, problems = self.corrections()
        _recs, unresolved = plan_corrections(cstore.canon, corr, turn=0)
        bad = problems + unresolved
        line = f"Author corrections ({CORRECTIONS_FILE}): {len(corr)} in force"
        if bad:
            line += f", {len(bad)} not applied: " + "; ".join(
                f"line {b['line']}: {b['why'][:60]}" for b in bad[:3])
        return line + "."

    def _write_report(self, cstore: Store) -> None:
        rows = self._read_rows()
        t = totals(rows, cstore.canon)
        held = [(r["turn"], h) for r in rows.values() for h in r.get("held_back", [])]
        held.sort(key=lambda x: x[0])
        mode = self.cfg.get("inject", "off")
        lines = [
            "Canon shadow report. Observe only: nothing here reaches a prompt." if mode == "off"
            else ("Canon shadow report. Injection is ON (D-027): the card is sent to the Writer; "
                  "see injections.jsonl and card-last.txt." if mode == "on"
                  else "Canon shadow report. Injection is in PREVIEW (D-027): the card is built and "
                       "logged each turn but NOT sent; see injections.jsonl and card-last.txt."),
            f"Scribe: {self.cfg['model']} at {self.cfg['host']}; first read "
            f"{self.cfg['backfill'] if self.cfg['backfill'] < BACKFILL_ALL else 'all'} "
            "earlier narrator turns.",
        ]
        if self.cfg["backfill"] < BACKFILL_ALL:
            # Found in the first preview run on a real save: with a 120-turn read, 3 of 8 identity
            # values differed from a full read, because first write wins on whatever the window
            # stated first, which can be a later change (a dye) or another character's value.
            lines.append(
                f"Note: only the last {self.cfg['backfill']} narrator turns were read the first time, so an "
                "identity value is what that window stated first (first write wins), which can be a "
                "later change and not the original. For a story that already exists, backfill: all "
                "reads it from the start.")
        lines += [
            f"Narrator turns seen {t['narrator_turns']}: {t['sent_to_model']} read by the "
            f"model, {t['skipped_nobody_named']} named nobody canon knows. Scribe statuses "
            f"{t['scribe_status']}. Mean {t['seconds_mean']} s a turn.",
            f"Ledger: {t['ledger_records']} records over {t['entities']} entities, "
            f"{t['entities_with_identity']} with identity facts. Decisions "
            f"{t['decisions']}.",
            self._corrections_line(cstore),
            f"Facts whose subject the code found, not a name in the passage (right about 9 "
            f"in 10 on hand-read samples): {sum(t['via'].values())} {t['via'] or ''}".rstrip(),
            f"Times the story contradicted a recorded fact (held back, canon unchanged): "
            f"{len(held)}.",
        ]
        for turn, h in held[-25:]:
            lines.append(f"  turn {turn}: {h['entity']} {h['slot']} held {h['held']!r}, "
                         f"story said {h['proposed']!r}")
        now = max((r["turn"] for r in rows.values()), default=0)
        lines += ["", f"State values and how long ago the story last stated them (turn {now}); "
                      "a card leaves a value out past its window:"]
        for key, a in state_ages(cstore.canon, now, FRESH_TURNS).items():
            lines.append(f"  {key}: {a['values']} characters have one, median age "
                         f"{a['median_age']}, {a['past_window']} past the {a['window']}-turn window")
        table = identity_table(cstore.canon)
        lines += ["", f"Every identity value canon holds ({len(table)} characters):"]
        for row in table:
            parts = [f"{k} {v[0]} (turn {v[1]}, x{v[2]})" for k, v in row["fields"].items()]
            if row["marks"]:
                parts.append("marks: " + "; ".join(row["marks"][:6]))
            lines.append(f"  {row['name']}: " + ", ".join(parts))
        tmp = self.dir / "report.txt.tmp"
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, self.dir / "report.txt")

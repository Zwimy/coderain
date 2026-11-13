"""Run a Scribe over the corpus and report what it gets right, wrong, and refuses.

Two measurements, because they answer different questions:

  extraction   For each hand-labelled passage, does the Scribe propose the right
               claims? Scored twice: RAW (what the model said) and VALIDATED (what
               would reach the ledger after the code checks). The gap between them
               is what validate.py is worth.

  sequences    The Phase 2 gate. Two passages in a row about one character: a
               restatement must corroborate and NOT be flagged (a false
               contradiction blocks invention), a changed identity must be flagged
               (a silent commit is drift getting through), and a fact about an
               empty slot must be accepted.

Scoring is plain code against labels written in advance. There is no model judge.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

from canon import Store
from canon.claims import Claim
from canon.pipeline import process_turn
from canon.scribe import OllamaChat, OpenAIChat, Scribe
from canon.validate import is_pronoun, resolve_loose, validate
from soak.scribe_cases import CASES, D044_IDS, PAIRS, ROSTER, Case, Pair, Truth


class RunAborted(RuntimeError):
    """The model can no longer be asked (daily cap, spent quota). Raised instead of
    finishing the corpus, because the remaining rows would all be transport errors
    and would read as the model failing every passage. No results file is written."""


def _check_not_exhausted(scribe: Scribe, done: int, total: int) -> None:
    why = getattr(scribe.llm, "exhausted", "")
    if why:
        raise RunAborted(f"stopped after {done} of {total} requests: {why}")


def fresh_store(root: Path, name: str) -> Store:
    s = Store(root / name)
    for eid, display, aliases in ROSTER:
        s.append(kind="entity_created", entity=eid, slot="character", value=display,
                 authority="scenario", turn=0, aliases=list(aliases))
    return s


# --- scoring: pure ----------------------------------------------------------
def score(truth: tuple[Truth, ...], claims: list[Claim], canon) -> dict:
    """Match claims to labels by (entity, slot, op, value pattern).

    A claim about someone who is not in the roster is counted separately and is
    NOT a false positive (it may be right; the roster is simply closed here). A
    claim whose entity is a pronoun is a false positive, because the Scribe is
    told never to use one.
    """
    unmatched = list(truth)
    tp = fp = off = 0
    for c in claims:
        eid = resolve_loose(canon, c.entity)
        if eid is None:
            if is_pronoun(c.entity):
                fp += 1
            else:
                off += 1
            continue
        hit = next((t for t in unmatched
                    if t.entity == eid and t.slot == c.slot and t.op == c.op
                    and (c.op == "clear" or re.search(t.value, c.value, re.I))), None)
        if hit:
            unmatched.remove(hit)
            tp += 1
        else:
            fp += 1
    return {"tp": tp, "fp": fp, "fn": len(unmatched), "off_roster": off}


def add(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in ("tp", "fp", "fn", "off_roster")}


def prf(m: dict) -> dict:
    p = m["tp"] / (m["tp"] + m["fp"]) if m["tp"] + m["fp"] else None
    r = m["tp"] / (m["tp"] + m["fn"]) if m["tp"] + m["fn"] else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {**m, "precision": p, "recall": r, "f1": f}


def oracle_claims(case: Case) -> list[Claim]:
    """The perfect Scribe for a case: its labels, as claims. Used to prove the
    corpus is self-consistent (every quote is in the text) and the scorer works.

    The value is the words of the quote that the label's pattern matches, so it is
    in the quote by construction. A label whose pattern matches nothing in its own
    quote is a corpus bug, and raising here is how the test finds it."""
    out = []
    for t in case.truth:
        if t.op == "clear":
            value = ""
        else:
            m = re.search(t.value, t.evidence, re.I)
            if not m:
                raise ValueError(f"{case.id}: {t.value!r} does not match its own "
                                 f"quote {t.evidence!r}")
            value = m.group(0)
        out.append(Claim(t.entity, t.slot, t.op, value, t.evidence, "high"))
    return out


# --- extraction -------------------------------------------------------------
def run_extraction(scribe: Scribe, cases: list[Case], root: Path,
                   log=print) -> dict:
    stat, rows = Counter(), []
    totals = {"raw": defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "off_roster": 0}),
              "validated": defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "off_roster": 0})}
    seconds = []
    for n, case in enumerate(cases, 1):
        store = fresh_store(root, f"x{n}")
        roster = [{"name": d, "aliases": a} for _e, d, a in ROSTER]
        ext = scribe.extract(case.text, roster)
        _check_not_exhausted(scribe, n - 1, len(cases))
        stat[ext.status] += 1
        seconds.append(ext.seconds)
        raw = score(case.truth, ext.claims, store.canon)
        decisions = validate(store.canon, ext.claims, case.text, turn=1,
                             next_id=len(store.ledger) + 1, create_unknown=False)
        # "Validated" means the claim PASSED the checks: committed, or valid but a
        # no-op (a removal of something not yet tracked, a repeat). Scoring only
        # commits would count every "took off her coat" as a miss on a fresh canon.
        kept = [d.claim for d in decisions if d.status in ("commit", "noop")]
        val = score(case.truth, kept, store.canon)
        for stage, m in (("raw", raw), ("validated", val)):
            for key in ("all", case.group, f"split:{case.split}", *(("legacy",) if case.id not in D044_IDS else ())):
                totals[stage][key] = add(totals[stage][key], m)
        rows.append({"id": case.id, "group": case.group, "split": case.split,
                     "status": ext.status, "seconds": round(ext.seconds, 2),
                     "error": ext.error, "raw": raw, "validated": val,
                     "claims": [c.__dict__ for c in ext.claims],
                     "rejects": ext.rejects,
                     "decisions": [{"slot": d.claim.slot, "status": d.status,
                                    "reason": d.reason} for d in decisions],
                     "model_output": ext.raw})
        log(f"  [{n:>2}/{len(cases)}] {case.id:<5} {ext.seconds:5.1f}s "
            f"{ext.status:<12} claims={len(ext.claims)} tp={raw['tp']} "
            f"fp={raw['fp']} fn={raw['fn']}")
    return {"statuses": dict(stat),
            "seconds_mean": sum(seconds) / len(seconds) if seconds else 0,
            "seconds_max": max(seconds) if seconds else 0,
            "raw": {k: prf(v) for k, v in totals["raw"].items()},
            "validated": {k: prf(v) for k, v in totals["validated"].items()},
            "cases": rows}


# --- sequences: the gate ----------------------------------------------------
def _outcome(report, entity: str, slot: str) -> str:
    mine = [d for d in report.decisions
            if d.entity == entity and d.claim.slot == slot]
    if not mine:
        return "none"
    kinds = {d.status for d in mine}
    for status in ("contradiction", "commit"):
        if status in kinds:
            return status
    return "rejected"


def run_sequences(scribe: Scribe, pairs: list[Pair], root: Path, log=print) -> dict:
    rows, tally = [], defaultdict(Counter)
    for n, pair in enumerate(pairs, 1):
        store = fresh_store(root, f"q{n}")
        first = process_turn(store, 1, pair.setup, scribe, create_unknown=False)
        established = _outcome(first, pair.entity,
                               pair.setup_slot or pair.slot) == "commit"
        second = process_turn(store, 2, pair.probe, scribe, create_unknown=False)
        _check_not_exhausted(scribe, n - 1, len(pairs))
        out = _outcome(second, pair.entity, pair.slot)
        verdict = "setup_failed" if not established else {
            ("restate", "commit"): "ok",
            ("restate", "contradiction"): "FALSE_CONTRADICTION",
            ("contradict", "contradiction"): "caught",
            ("contradict", "commit"): "SILENT_DRIFT",
            ("novel", "commit"): "accepted",
            ("novel", "contradiction"): "BLOCKED",
        }.get((pair.kind, out), "missed")
        tally[pair.kind][verdict] += 1
        rows.append({"id": pair.id, "kind": pair.kind, "setup_established": established,
                     "probe_outcome": out, "verdict": verdict,
                     "setup_status": first.extraction.status,
                     "probe_status": second.extraction.status,
                     "probe_claims": [c.__dict__ for c in second.extraction.claims],
                     "probe_output": second.extraction.raw,
                     "seconds": round(first.extraction.seconds + second.extraction.seconds, 2)})
        log(f"  [{n:>2}/{len(pairs)}] {pair.id:<5} {pair.kind:<10} -> {verdict}")
    return {"by_kind": {k: dict(v) for k, v in tally.items()}, "pairs": rows}


# --- entry point ------------------------------------------------------------
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# OpenRouter allows 20 requests a minute on `:free` models. 3.2 s apart is 18.75 a
# minute, which stays under it with a little room for clock slop.
FREE_TIER_INTERVAL = 3.2


def make_llm(provider: str, model: str, *, think=None, host="http://localhost:11434",
             base_url=None, key_env=None, effort=None, token_budget=250_000,
             max_tokens=2000, min_interval=None, allow_paid=False):
    if provider == "ollama":
        return OllamaChat(model, host=host, think=think)
    if provider in ("openai", "openrouter"):
        router = provider == "openrouter"
        free = router and model.endswith(":free")
        if router and not free and not allow_paid:
            # A key given for a free-tier test must not be able to spend. OpenRouter
            # marks the free variants with this suffix; anything else may cost money.
            raise ValueError(f"{model!r} is not a ':free' model; pass allow_paid "
                             "(--allow-paid) to use a model that may cost money")
        if min_interval is None:
            min_interval = FREE_TIER_INTERVAL if free else 0.0
        default_url = OPENROUTER_URL if router else "https://api.openai.com/v1"
        default_key = "OPENROUTER_API_KEY" if router else "OPENAI_API_KEY"
        return OpenAIChat(
            model, base_url=base_url or default_url, key_env=key_env or default_key,
            reasoning_effort=effort, token_budget=token_budget,
            max_tokens=max_tokens, min_interval=min_interval,
            # A free model's pool is shared and is often busy for a minute at a
            # time (measured: every request refused for 35 s on one model).
            attempts=8 if free else 5)
    raise ValueError(f"unknown provider {provider!r}")


def run(llm, label: str, *, split: str, out_dir: Path, log=print, accessories: bool = False) -> dict:
    cases = [c for c in CASES if split == "all" or c.split == split]
    scribe = Scribe(llm, accessories=accessories)
    root = Path(tempfile.mkdtemp(prefix="scribe-eval-"))
    started = time.time()
    try:
        log(f"model {label}  split {split}  {len(cases)} passages + {len(PAIRS)} pairs"
            f"{'  (asked about accessories)' if accessories else ''}")
        log("extraction:")
        ex = run_extraction(scribe, cases, root, log)
        log("sequences:")
        sq = run_sequences(scribe, PAIRS, root, log)
    finally:
        llm.unload()
        shutil.rmtree(root, ignore_errors=True)
    result = {"model": label, "split": split, "accessories": accessories,
              "dropped_fields": sorted(llm.dropped),
              "wall_seconds": round(time.time() - started, 1),
              "tokens": {"in": getattr(llm, "tokens_in", None),
                         "out": getattr(llm, "tokens_out", None)},
              "truncated": getattr(llm, "truncated", None),
              "extraction": ex, "sequences": sq}
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
    (out_dir / f"scribe-{safe}-{split}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    return result


def _f(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def summarize(r: dict) -> str:
    ex, sq = r["extraction"], r["sequences"]
    tok = r.get("tokens") or {}
    spent = (f" Tokens: {tok['in']} in, {tok['out']} out." if tok.get("in") is not None else "")
    if r.get("truncated"):
        # An empty reply from a reasoning model that ran out of tokens thinking is
        # not the same as a model with nothing to say; say which it was.
        spent += f" Replies cut off by max_tokens: {r['truncated']}."
    lines = [f"# Scribe: {r['model']} (split {r['split']}, {r['wall_seconds']}s wall)", "",
             f"Statuses: {ex['statuses']}. Seconds per passage: mean "
             f"{ex['seconds_mean']:.1f}, max {ex['seconds_max']:.1f}. Fields the server "
             f"refused: {r['dropped_fields'] or 'none'}.{spent}", "",
             "| slice | stage | recall | precision | tp | fp | fn | off-roster |",
             "|---|---|---|---|---|---|---|---|"]
    keys = ["all", "legacy", "identity", "state", "multi", "trap", "accessory", "split:dev", "split:test"]
    for k in keys:
        for stage in ("raw", "validated"):
            m = ex[stage].get(k)
            if m:
                lines.append(f"| {k} | {stage} | {_f(m['recall'])} | {_f(m['precision'])} "
                             f"| {m['tp']} | {m['fp']} | {m['fn']} | {m['off_roster']} |")
    lines += ["", "## Sequences (the gate)", ""]
    for kind, v in sq["by_kind"].items():
        lines.append(f"- {kind}: {v}")
    re_ = sq["by_kind"].get("restate", {})
    n_re = sum(v for k, v in re_.items() if k != "setup_failed")
    fc = re_.get("FALSE_CONTRADICTION", 0)
    lines.append(f"- false-contradiction rate on restatements: {fc} of {n_re}")
    co = sq["by_kind"].get("contradict", {})
    n_co = sum(v for k, v in co.items() if k != "setup_failed")
    lines.append(f"- changed identity caught: {co.get('caught', 0)} of {n_co}; "
                 f"silently committed: {co.get('SILENT_DRIFT', 0)}")
    return "\n".join(lines) + "\n"

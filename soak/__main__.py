"""python -m soak audit SAVE_DIR [--fixture NAME] [--out DIR]
   python -m soak scribe --model NAME --out DIR [--provider ollama|openai|openrouter]
   python -m soak gate SAVE_DIR --fixture NAME --out DIR [--model NAME]

audit copies SAVE_DIR into a throwaway CODERAIN_HOME, verifies the source was not
touched, and measures the copy. The order of imports below is not style: the
isolated home has to exist before anything imports coderain (see soak.home).

scribe measures an extraction model on an INVENTED test corpus. It never reads a
save, and with a hosted provider only that invented text is ever sent anywhere.
"""
from __future__ import annotations

import argparse
import importlib
import shutil
import sys
from pathlib import Path

from soak.home import (REPO_ROOT, SourceChanged, UnsafeHome, copy_save,
                       isolated_home)


def _live_memory_settings() -> dict:
    """The two memory knobs that decide what a prompt contains, read from the
    repo's config.yaml so the probe sees the prompt the real app would build.
    Read-only, and only these keys: nothing else in that file is used."""
    path = REPO_ROOT / "config.yaml"
    if not path.exists():
        return {}
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mem = data.get("memory") or {}
    return {k: mem[k] for k in ("short_term_turns", "context_budget_tokens")
            if k in mem}


def _scribe(args) -> int:
    # canon is standard library only and this never touches a save, so none of
    # the isolation below is needed.
    from soak.scribe_eval import RunAborted, make_llm, run, summarize
    think = {"on": True, "off": False, None: None}[args.think]
    llm = make_llm(args.provider, args.model, think=think, host=args.host,
                   base_url=args.base_url, key_env=args.key_env, effort=args.effort,
                   token_budget=args.token_budget, max_tokens=args.max_tokens,
                   min_interval=args.min_interval, allow_paid=args.allow_paid)
    label = args.model + ("" if args.provider == "ollama" else f"@{args.provider}")
    try:
        result = run(llm, label, split=args.split, out_dir=args.out)
    except RunAborted as exc:
        print(f"aborted, no results written: {exc}", file=sys.stderr)
        return 4
    print(summarize(result))
    print(f"results: {args.out}")
    return 0


def _gate(args) -> int:
    """Replay a COPY of a save through the Scribe into canon, on a LOCAL model."""
    from canon.scribe import OllamaChat, Scribe
    from soak.canon_gate import NotLocal, require_local, run_gate

    llm = OllamaChat(args.model, host=args.host, num_ctx=8192, think=None)
    try:
        require_local(llm)              # before the save is even copied
    except NotLocal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    try:
        home = isolated_home()
        slug = copy_save(args.save, home, rules_from=REPO_ROOT / "instructions")
    except (UnsafeHome, SourceChanged, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    from coderain.memory import Library       # only now is importing it safe

    store = Library(home).store(slug)
    facts = importlib.import_module(f"soak.fixtures.{args.fixture}").FACTS
    try:
        report = run_gate(store, facts, Scribe(llm), args.out,
                          start=args.start, end=args.end)
    finally:
        llm.unload()
        shutil.rmtree(home, ignore_errors=True)
    from soak.canon_gate import to_markdown
    print(to_markdown(report))
    print(f"report: {args.out / 'report.md'}")
    return 0


def _tolerant_output() -> None:
    """A finished two-hour gate run once exited 1 on its very last print: a
    character name held a non-breaking hyphen and the Windows console codepage
    (cp1252) cannot encode it. The report was already on disk, so the run looked
    failed when it was not. The reports quote names from the story, so printing
    must never be the thing that fails: unencodable characters become '?'."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:     # a test's StringIO has none, and needs none
            reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _tolerant_output()
    ap = argparse.ArgumentParser(prog="python -m soak")
    sub = ap.add_subparsers(dest="cmd", required=True)
    gt = sub.add_parser(
        "gate", help="replay a COPY of a save through the Scribe into canon "
                     "and score what it holds (local model only)")
    gt.add_argument("save", type=Path, help="path to a save directory (read only)")
    gt.add_argument("--fixture", required=True, help="soak.fixtures.<name>")
    gt.add_argument("--model", default="gemma3:4b")
    gt.add_argument("--host", default="http://localhost:11434",
                    help="must be this machine; anything else is refused")
    gt.add_argument("--out", type=Path, required=True,
                    help="results and the resumable ledger; keep it outside the repo")
    gt.add_argument("--start", type=int, default=1)
    gt.add_argument("--end", type=int, default=None)
    au = sub.add_parser("audit", help="measure a COPY of a save")
    au.add_argument("save", type=Path, help="path to a save directory (read only)")
    au.add_argument("--fixture", default="", help="soak.fixtures.<name> to check")
    au.add_argument("--out", type=Path, default=None,
                    help="where to write report.json/report.md (default: the "
                         "temp home)")
    au.add_argument("--engine-defaults", action="store_true",
                    help="ignore config.yaml; use the engine's own defaults")
    au.add_argument("--cleanup", action="store_true",
                    help="delete the temp home afterwards (needs --out)")
    sc = sub.add_parser(
        "scribe", help="measure a Scribe model on the invented corpus",
        description="Sends only the invented test corpus to the model. Never a save.")
    sc.add_argument("--provider", choices=["ollama", "openai", "openrouter"],
                    default="ollama",
                    help="openai means any OpenAI-compatible endpoint (--base-url); "
                         "openrouter fills in its URL and key variable, and paces "
                         "':free' models under their 20-requests-a-minute cap")
    sc.add_argument("--model", required=True)
    sc.add_argument("--split", choices=["dev", "test", "all"], default="all")
    sc.add_argument("--out", type=Path, required=True,
                    help="where to write the results (required, so they never land "
                         "in the repo by accident)")
    sc.add_argument("--think", choices=["on", "off"], default=None,
                    help="ollama reasoning models: turn thinking on or off")
    sc.add_argument("--host", default="http://localhost:11434", help="ollama server")
    sc.add_argument("--base-url", default=None,
                    help="default: OpenAI's, or OpenRouter's with --provider openrouter")
    sc.add_argument("--key-env", default=None,
                    help="NAME of the environment variable holding the key (default "
                         "OPENAI_API_KEY, or OPENROUTER_API_KEY with --provider "
                         "openrouter); the key itself is never an argument")
    sc.add_argument("--effort", default=None,
                    help="reasoning_effort, e.g. minimal or none; dropped if the model "
                         "refuses it")
    sc.add_argument("--token-budget", type=int, default=250_000,
                    help="hosted only: stop before spending more than this many tokens")
    sc.add_argument("--max-tokens", type=int, default=2000,
                    help="hosted only: reply cap, which reasoning models spend thinking")
    sc.add_argument("--allow-paid", action="store_true",
                    help="openrouter: allow a model that is not ':free' (refused by default)")
    sc.add_argument("--min-interval", type=float, default=None,
                    help="hosted only: seconds between requests (default 3.2 for "
                         "openrouter ':free' models, else 0)")
    args = ap.parse_args(argv)
    if args.cmd == "scribe":
        return _scribe(args)
    if args.cmd == "gate":
        return _gate(args)
    if args.cleanup and not args.out:
        ap.error("--cleanup would delete the report; pass --out as well")

    try:
        home = isolated_home()
        slug = copy_save(args.save, home, rules_from=REPO_ROOT / "instructions")
    except (UnsafeHome, SourceChanged, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3

    # Only now is it safe to import anything that imports coderain.
    from coderain.memory import Library
    from soak.audit import run_audit
    from soak.report import to_markdown, write_report

    memory = {} if args.engine_defaults else _live_memory_settings()
    facts = []
    if args.fixture:
        facts = importlib.import_module(f"soak.fixtures.{args.fixture}").FACTS
    store = Library(home).store(slug)
    report = run_audit(store, facts, memory)
    js, md = write_report(report, args.out or home)
    print(to_markdown(report, max_conflicts=12))
    print(f"report: {md}\njson:   {js}")
    if args.cleanup:
        shutil.rmtree(home, ignore_errors=True)
    return 2 if report["fact_summary"]["diverged_from_expectation"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

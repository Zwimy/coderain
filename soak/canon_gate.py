"""The Phase 3 gate: replay a real save through canon and ask what it holds.

Phase 0 measured what the engine's memory kept of a real story: a scar narrated
once and never recorded (LOST), a hair colour that became another one on the sheet
(DRIFTED), and a few controls it did keep (HELD). This replays the same save's
narrator turns through the Scribe into a fresh canon ledger, then scores the same
facts the same way, on what the Writer would be shown (the identity line and the
state card from canon/scene.py). Same facts, same vocabulary, different memory.

Rules, because this is a person's real story:

  * The model must be LOCAL. `require_local` refuses anything else before a single
    passage is read, so the story cannot reach a hosted API by a wrong flag.
  * The save is only ever read through a COPY in an isolated home (soak.home).
  * The report holds values and counts, never narration. A canon record carries the
    quoted evidence sentence, so records are summarised, not dumped.
  * The run is resumable. The ledger lives in the output directory and each turn
    is logged as it finishes, so an interrupted run continues where it stopped.

A turn that names nobody the canon knows is not sent to the model at all: the
validator would reject every claim from it as being about someone the passage does
not name (D-019), so the call could not change anything.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from canon import Store
from canon.claims import SLOTS
from canon.pipeline import process_turn
from canon.referents import gender_votes
from canon.replay import (GenderVotes, identity_history, identity_table, passage_who,
                          player_entity, player_gender, reads_anyone, seed_entities, seed_player,
                          skipped_row, totals,
                          turn_row, BEFORE_TURNS)
from canon.scene import bible, card_line
# NotLocal and require_local live with the model clients (canon/scribe.py) so the
# engine's shadow mode can use them without importing the test harness; they are
# re-exported here because this module's callers and tests have always imported them
# from it.
from canon.scribe import NotLocal, Scribe, require_local  # noqa: F401
from soak import facts as F


# --- the replay -------------------------------------------------------------------
def _read_progress(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue                    # a torn last line from an interrupted run
        rows[row["turn"]] = row
    return rows


def replay(save, store: Store, scribe: Scribe, out_dir: Path, *, start: int = 1,
           end: int | None = None, log=print, every: int = 25,
           player: str | None = None) -> dict[int, dict]:
    """Feed each narrator turn in [start, end] through the Scribe into `store`.

    `player` is the slug "you" means; when None it is worked out from player.md (D-024)."""
    progress_path = out_dir / "progress.jsonl"
    done = _read_progress(progress_path)
    turns = save.turns()
    player_text = save.read("player.md") or ""
    who_is_you = player_entity(save.entries("characters.md"), player_text, player)
    votes = GenderVotes(done.values())
    narrator = [i for i, t in enumerate(turns, 1) if t["role"] == "narrator"]
    last = len(turns) if end is None else min(end, len(turns))
    todo = [i for i in range(max(1, start), last + 1)
            if turns[i - 1]["role"] == "narrator" and i not in done]
    started, handled = time.time(), 0
    with progress_path.open("a", encoding="utf-8") as fh:
        for n, idx in enumerate(todo, 1):
            prose = turns[idx - 1]["text"]
            before = [turns[i - 1]["text"] for i in narrator if i < idx][-BEFORE_TURNS:]
            if not reads_anyone(store.canon, prose, who_is_you, "\n".join(before)):
                row = skipped_row(idx)
            else:
                # A changed identity is recorded as a disputed claim (canon does
                # not change, see state.py), so the report can say which values
                # were held back instead of only that something was.
                who = passage_who(store.canon, prose, votes=votes, player=who_is_you,
                                  before=before, player_is=player_gender(player_text))
                rep = process_turn(store, idx, prose, scribe, create_unknown=False,
                                   record_contradictions=True, who=who)
                v = gender_votes(store.canon, prose, who_is_you)
                row = turn_row(idx, rep, v)
                votes.add(v)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            done[idx] = row
            handled += 1
            if n % every == 0 or n == len(todo):
                spent = time.time() - started
                eta = spent / handled * (len(todo) - n)
                log(f"  turn {idx}/{last}: {n}/{len(todo)} narrator turns this run, "
                    f"{spent / 60:.1f} min spent, about {eta / 60:.1f} min to go")
    return done


# --- scoring ----------------------------------------------------------------------
def evaluate(store: Store, fixture: list[F.Fact]) -> list[dict]:
    canon = store.canon
    rows = []
    for fact in fixture:
        eid = fact.entity if fact.entity in canon.entities else None
        if eid is None:
            rows.append({"id": fact.id, "entity": fact.entity, "engine": fact.expect,
                         "canon": F.NO_ENTITY, "on_sheet": False})
            continue
        # Classified on an unconstrained rendering, so a budget cut is not mistaken
        # for the memory not holding the fact; then checked against the real budget.
        wide = bible(canon, eid, max_chars=4000) + "\n" + card_line(canon, eid, max_chars=4000)
        shown = bible(canon, eid) + "\n" + card_line(canon, eid)
        truth, stale = F._hit(fact.truth, wide), bool(fact.stale) and F._hit(fact.stale, wide)
        status = (F.CONFLICT if truth and stale else F.HELD if truth else
                  F.DRIFTED if stale else F.LOST)
        mine = [c for c in canon.conflicts if c["entity"] == eid]
        rows.append({
            "id": fact.id, "entity": fact.entity, "slot": fact.slot,
            "engine": fact.expect, "canon": status,
            "on_sheet": F._hit(fact.truth, shown),
            "outside_scribe_slots": fact.slot not in SLOTS,
            "identity": identity_history(canon, eid),
            "conflicts": [{k: c[k] for k in ("turn", "slot", "reason", "proposed", "existing")}
                          for c in mine][:12],
            "conflict_count": len(mine)})
    return rows


def to_markdown(report: dict) -> str:
    t = report["totals"]
    lines = ["# Canon replay gate", "",
             f"Narrator turns {t['narrator_turns']}: {t['sent_to_model']} sent to the "
             f"model, {t['skipped_nobody_named']} named nobody the canon knows. "
             f"Scribe statuses {t['scribe_status']}. Mean {t['seconds_mean']} s a turn.",
             f"Ledger: {t['ledger_records']} records over {t['entities']} entities; "
             f"{t['entities_with_identity']} have at least one identity fact. "
             f"Conflicts recorded (a changed identity, held back): "
             f"{t['conflicts_recorded']}.",
             f"Decisions {t['decisions']}. Top reasons {t['reasons']}.",
             f"Facts whose subject the code found, not a name in the passage: "
             f"{sum(t.get('via', {}).values())} {t.get('via') or ''}".rstrip(),
             f"Player: {report.get('player') or 'not known'}. Seeded from player.md at scenario "
             f"authority: {[f'{s.split(chr(46), 1)[1]} {v}' for s, v in report.get('seeded_player', [])] or 'nothing'}.",
             "",
             "| fact | Phase 0 engine | canon | on the Writer's sheet | notes |",
             "|---|---|---|---|---|"]
    for r in report["facts"]:
        notes = []
        if r.get("outside_scribe_slots"):
            notes.append("slot is outside the Scribe's list")
        if r.get("conflict_count"):
            notes.append(f"{r['conflict_count']} change(s) held back")
        lines.append(f"| {r['id']} | {r['engine']} | {r['canon']} | "
                     f"{'yes' if r['on_sheet'] else 'no'} | {'; '.join(notes)} |")
    table = report.get("identity_table", [])
    if table:
        lines += ["", f"## Every identity value canon holds ({len(table)} characters)", ""]
        for row in table:
            parts = [f"{k} {v[0]} (turn {v[1]}, x{v[2]})" for k, v in row["fields"].items()]
            if row["marks"]:
                parts.append("marks: " + "; ".join(row["marks"][:6])
                             + (f" (+{len(row['marks']) - 6} more)" if len(row["marks"]) > 6 else ""))
            if row.get("accessories"):
                parts.append("accessories: " + "; ".join(row["accessories"][:6]))
            lines.append(f"- {row['name']}: " + ", ".join(parts))
        lines.append(f"Held-back changes by slot: {report.get('conflicts_by_slot')}")
    held = [r for r in report["facts"] if r["canon"] == F.HELD]
    lines += ["", f"Held by canon: {len(held)} of {len(report['facts'])}. "
              "Phase 0 engine held only its three controls.", ""]
    for r in report["facts"]:
        if r.get("identity"):
            lines.append(f"- {r['id']}: " + "; ".join(
                f"{slot} = " + ", ".join(
                    f"{h['value']} (turn {h['from_turn']}, x{h['confirmations']})"
                    for h in hist) for slot, hist in r["identity"].items()))
        for c in r.get("conflicts", [])[:6]:
            lines.append(f"  - turn {c['turn']}: {c['slot']} held at {c['existing']!r}, "
                         f"{c['proposed']!r} proposed ({c['reason']})")
    return "\n".join(lines) + "\n"


def run_gate(save, fixture: list[F.Fact], scribe: Scribe, out_dir: Path, *,
             start: int = 1, end: int | None = None, log=print,
             player: str | None = None) -> dict:
    """Replay, score, and write report.json and report.md into `out_dir`."""
    require_local(scribe.llm)
    F.validate_fixture(fixture)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    store = Store(out_dir / "canon")
    seeded = seed_entities(store, save.entries("characters.md"))
    log(f"canon seeded with {len(store.canon.entities)} entities "
        f"({seeded['made']} new, {len(seeded['skipped'])} skipped)")
    # The protagonist's own file is the first write for their looks (D-025).
    player_text = save.read("player.md") or ""
    pid = player_entity(save.entries("characters.md"), player_text, player)
    seeded_player = seed_player(store, pid, player_text, turn=0)
    log(f"player is {pid or 'not known'}; seeded from player.md: "
        f"{[f'{s.split(chr(46), 1)[1]} {v}' for s, v in seeded_player] or 'nothing'}")
    rows = replay(save, store, scribe, out_dir, start=start, end=end, log=log,
                  player=pid)
    report = {"totals": totals(rows, store.canon), "facts": evaluate(store, fixture),
              "identity_table": identity_table(store.canon),
              "conflicts_by_slot": dict(Counter(c["slot"].split(".")[1] if "." in c["slot"] else c["slot"]
                                                for c in store.canon.conflicts)),
              "seeded": seeded, "player": pid,
              "seeded_player": [[s, v] for s, v in seeded_player]}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")
    return report

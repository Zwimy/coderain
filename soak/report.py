"""Render an audit dict as JSON and as a short Markdown summary."""
from __future__ import annotations

import json
from pathlib import Path


def _yes(v: bool | None) -> str:
    return "-" if v is None else ("yes" if v else "no")


def to_markdown(report: dict, max_conflicts: int = 25) -> str:
    save = report["save"]
    out = ["# Soak baseline",
           "",
           f"Save: {save['turns']} turns, {save['scenes']} folded scenes, "
           f"{save['characters']} character entries. Settings used: "
           f"{report['settings']['memory'] or 'engine defaults'}.",
           "",
           "## Known cases (did the memory keep the fact?)",
           "",
           "| case | status | expected | age (turns) | on prompt, named | "
           "on prompt, unnamed | elsewhere in memory |",
           "|---|---|---|---|---|---|---|"]
    for f in report["facts"]:
        p = f["prompt"]
        out.append("| {id} | {status} | {exp} | {age} | {n} | {a} | {el} |".format(
            id=f["id"], status=f["status"], exp=f["expected"] or "-",
            age=f["age_turns"] if f["age_turns"] is not None else "-",
            n=_yes(p.get("named_system")), a=_yes(p.get("ambient_system")),
            el=", ".join(f["elsewhere"]) or "none"))
    div = report["fact_summary"]["diverged_from_expectation"]
    out += ["", "Statuses: " + ", ".join(
        f"{k} {v}" for k, v in sorted(report["fact_summary"]["statuses"].items())),
        "Cases that no longer match their expected status: "
        + (", ".join(div) if div else "none"), ""]

    s = report["structure"]
    t, c, a = s["transient_in_identity"], s["clock"], s["arc"]
    out += ["## Structure", "",
            f"- Transient state inside a permanent Visual facet: {t['count']} of "
            f"{t['characters']} characters (marker words only; {t['caveat']}).",
            f"- Scenes stamped with a year-shaped day (over 1000): "
            f"{c['year_shaped']} of {c['stamped']} stamped "
            f"({c['distinct_year_shaped'] or 'none'}).",
            f"- Arc: {a['arc_chars']} characters long; it names "
            f"{a['named_in_arc']} of {a['introduced']} introduced characters, by "
            f"when they were introduced:"]
    for row in a["by_cohort"]:
        out.append(f"  - {row['cohort']} (first seen turns {row['first_turns']}): "
                   f"{row['in_arc']} of {row['characters']}")

    d = report["attribute_drift"]
    out += ["", "## Hair and eye colour in narration versus the sheet", "",
            f"- Character-attributes asserted at least twice in narration: "
            f"{d['pairs']}; with two conflicting colours: {d['conflict_count']}.",
            f"- For those conflicts, the sheet matches: " + ", ".join(
                f"{k.replace('sheet_', '').replace('_', ' ')} {v}"
                for k, v in d["summary"].items()),
            f"- Caveat: {d['caveat']}.", ""]
    for c_ in d["conflicts"][:max_conflicts]:
        out.append(
            f"- {c_['entity']} {c_['noun']}: turn {c_['first']['turn']} "
            f"{c_['first']['families']} then turn {c_['conflicting']['turn']} "
            f"{c_['conflicting']['families']} (sheet: {c_['sheet']}, "
            f"{c_['sheet_families']})")
        out.append(f"    - \"{c_['first']['snippet']}\"")
        out.append(f"    - \"{c_['conflicting']['snippet']}\"")
    if len(d["conflicts"]) > max_conflicts:
        out.append(f"- ... {len(d['conflicts']) - max_conflicts} more in the JSON")
    return "\n".join(out) + "\n"


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    js, md = out_dir / "report.json", out_dir / "report.md"
    js.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md.write_text(to_markdown(report), encoding="utf-8")
    return js, md

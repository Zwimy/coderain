"""A no-model audit of a world's files: where creation leaves defects the engine pays for later (D-046).

The consistency work began with measurement, and the owner wants chapter, scenario, world and character generation to be
"as seamless as possible", so this does the same first step for creation: lint what is on disk, with no model and no
engine. It reads Markdown only (it never opens a store, which would write migration files), so it is safe on a copy of a
real save or on the shipped default scenario.

Checks (each a defect class that has already cost something):
  shared_label        two entries in one registry answer to the same name or alias (the D-039 class: 28 claims about one
                      character refused, 1,452 in the first soak)
  alias_is_other_name an alias that is another entry's own name or slug
  dangling_link       a [[slug]] or [[kind:slug]] that no entry has (a link to a folded-away slug points nowhere, D-030)
  thin_body           a sheet shorter than a few sentences is little for the writer to hold (thresholds are untuned
                      starting points, listed in THIN_WORDS)
  uniform_importance  four or more entries in a registry all with the same importance: no ranking signal
  restating_chapters  two outline chapters share a run of content words (planner._restates)
  no_looks            a character whose sheet states no hair or eye COLOUR, so the canon card has nothing to hold until
                      the story states one (a shapeshifter may be that on purpose)
  empty_registry      a registry file that is missing or holds no entries

    python -m soak creation-audit DIR | --default [--out FILE] [--strict]
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

REGISTRIES = ["characters.md", "locations.md", "factions.md", "items.md", "threads.md", "canon-events.md", "events.md"]
ENTITY_REGISTRIES = ("characters.md", "locations.md", "factions.md", "items.md")
# words in a body below which a sheet is called thin (untuned, a place to start)
THIN_WORDS = {"characters.md": 20, "locations.md": 12, "factions.md": 12, "items.md": 5, "threads.md": 8}
_LINK = re.compile(r"\[\[(?:[a-z-]+:)?([^\]|]+?)(?:\|[^\]]*)?\]\]", re.IGNORECASE)
_LOOK_NOUNS = {"hair", "haired", "eye", "eyes", "eyed"}


def states_a_look(text: str) -> bool:
    """Does the text give a hair or eye COLOUR (a colour word within a few words of the noun)? The word "hair" alone is
    not a look ("hair wet to the scalp"), and neither is "a face the eye slides off": the card holds colours."""
    from canon import shape
    words = shape._tokens(text)
    return any(w in _LOOK_NOUNS and any(x in shape._COLOURS for x in words[max(0, k - 4):k + 8])
               for k, w in enumerate(words))


def _entries(root: Path, rel: str):
    from coderain.memory import parse_entries
    p = root / rel
    return parse_entries(p.read_text(encoding="utf-8")) if p.exists() else []


def audit_dir(root: Path) -> dict:
    """Lint the world files under `root` (a scenario folder or a save folder). Returns the inventory, the findings
    and a count per check. Pure reading."""
    from coderain.memory import name_key
    from coderain.planner import _restates
    root = Path(root)
    entries = {rel: _entries(root, rel) for rel in REGISTRIES}
    entries["memory/outline.md"] = _entries(root, "memory/outline.md")
    findings: list[dict] = []

    def add(check: str, rel: str, slug: str, why: str) -> None:
        findings.append({"check": check, "where": f"{rel}:{slug}" if slug else rel, "why": why})

    for rel in REGISTRIES:
        if not entries[rel]:
            if rel in ENTITY_REGISTRIES:
                add("empty_registry", rel, "", "missing or no entries")
    for rel in ENTITY_REGISTRIES:
        es = entries[rel]
        owners: dict[str, list[str]] = {}
        for e in es:
            for label in {name_key(e.title), *(name_key(a) for a in e.aliases), name_key(e.slug)}:
                if label:
                    owners.setdefault(label, []).append(e.slug)
        for label, slugs in sorted(owners.items()):
            slugs = list(dict.fromkeys(slugs))
            if len(slugs) > 1:
                add("shared_label", rel, slugs[0], f"{label!r} is used by {', '.join(slugs)}")
        titles = {name_key(e.title): e.slug for e in es}
        for e in es:
            for a in e.aliases:
                other = titles.get(name_key(a)) or next((x.slug for x in es if name_key(x.slug) == name_key(a)), None)
                if other and other != e.slug:
                    add("alias_is_other_name", rel, e.slug, f"alias {a!r} is the name of {other}")
        if len(es) >= 4 and len({e.importance for e in es}) == 1:
            add("uniform_importance", rel, "", f"all {len(es)} entries have importance {es[0].importance}")
    slugs_all = {e.slug for rel in REGISTRIES for e in entries[rel]} | {"player", "you", "you-player"}
    texts = [(rel, e.slug, e.body + " " + " ".join(str(v) for v in e.attrs.values()))
             for rel in REGISTRIES + ["memory/outline.md"] for e in entries[rel]]
    for rel, slug, text in texts:
        for target in sorted(set(_LINK.findall(text))):
            if name_key(target) not in {name_key(s) for s in slugs_all} and target.strip() not in slugs_all:
                add("dangling_link", rel, slug, f"[[{target.strip()}]] points at nothing")
    for rel, floor in THIN_WORDS.items():
        for e in entries[rel]:
            words = len(e.body.split())
            if words < floor:
                add("thin_body", rel, e.slug, f"{words} words (under {floor})")
    for e in entries["characters.md"]:
        if not states_a_look(e.body + " " + " ".join(str(v) for v in e.attrs.values())):
            add("no_looks", "characters.md", e.slug, "no hair or eye colour stated in the sheet")
    chapters = entries["memory/outline.md"]
    for i, c in enumerate(chapters):
        hit = _restates(c.body, [o.body for o in chapters[:i]])
        if hit:
            add("restating_chapters", "memory/outline.md", c.slug, f"shares {hit!r} with an earlier chapter")
    return {"root": root.name, "inventory": {rel: len(es) for rel, es in entries.items()},
            "counts": dict(Counter(f["check"] for f in findings)), "findings": findings}


def format_report(r: dict, limit: int = 4) -> str:
    inv = ", ".join(f"{rel.replace('.md', '')} {n}" for rel, n in r["inventory"].items() if n)
    lines = [f"creation audit of {r['root']}: {inv or 'nothing found'}"]
    if not r["findings"]:
        lines.append("no findings")
    for check, n in sorted(r["counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {check}: {n}")
        for f in [x for x in r["findings"] if x["check"] == check][:limit]:
            lines.append(f"      {f['where']}: {f['why']}")
    return "\n".join(lines)


def run_creation_audit(args) -> int:
    import tempfile
    if args.default:
        from coderain import default_scenario
        tmp = Path(tempfile.mkdtemp(prefix="creation-audit-"))
        default_scenario.seed(tmp)
        root = tmp
    else:
        root = Path(args.dir)
        if not root.is_dir():
            raise SystemExit(f"not a folder: {root}")
    report = audit_dir(root)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(format_report(report))
    return 1 if (args.strict and report["findings"]) else 0

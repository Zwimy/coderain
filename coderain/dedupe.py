"""Merge entries that are one person (or place) written under two slugs, in a save that already has them.

The fold used to trust the slug a small lore-keeper model wrote and dedupe by slug alone (D-029), so a story
played through a local model collects second and third entries for the same character: `bram-halloran`,
`bram-halloran-4`, `bram-halloran-bram-halloran`. The fold no longer makes new ones; this cleans up the old.

It is the one operation in this repo that rewrites a registry file the fold wrote, and a fold is one-way, so
it is built to be undone and to be asked for:

  * a dry run is the default and writes nothing: it prints what would merge and why
  * `--apply` first copies every registry it will change into `<save>/.dedupe-backup/<time>/`, and
    restoring is a plain file copy
  * only whole-name matches merge (case, punctuation and a leading "the" ignored). "Ottoline Wren" is not
    "Ottoline Pike", and a title that is merely listed as another entry's alias is not a match, because
    small models write wrong aliases. A doubtful pair is left alone: a duplicate can be merged later, a wrong
    merge needs the backup.
  * the player's sheet, threads and canon events are never touched
  * it changes nothing outside the registries: scene summaries and the arc still hold `[[character:old-slug]]`
    links (the report counts them), and the canon ledger under `<save>/canon/` is derived and keeps the old
    entities until it is rebuilt (delete that folder; the reader reads the story again)

    python -m coderain.dedupe --home <CODERAIN_HOME> --save <slug>             # report only
    python -m coderain.dedupe --home <CODERAIN_HOME> --save <slug> --apply     # back up, then merge
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .memory import ENTITY_FILES, MAX_ALIASES, Entry, _LINK_RE, name_key, usable_alias
from .summarizer import BODY_LIMIT, _slugify

BACKUP_DIR = ".dedupe-backup"
_NEWEST_WINS = ("status", "when", "relationships", "wants", "motivation")   # what a fold rewrites whole


@dataclass(frozen=True)
class Group:
    rel: str                        # the registry file
    keep: str                       # the slug that stays
    drop: tuple[str, ...]           # the slugs folded into it, in file order
    why: str                        # why they are one entity ("same name")


def _keep_for(members: list[Entry]) -> Entry:
    """The entry made under its own name's slug, else the oldest (first in the file)."""
    return next((e for e in members if e.slug == _slugify(e.title)), members[0])


def plan_merges(registries: dict[str, list[Entry]], skip_names=()) -> list[Group]:
    """Every group of entries that are one entity, per registry. Pure: reads nothing but its argument.

    Entries with the same whole name form a group, and nothing else does. A title that is only listed as
    another entry's alias is NOT a match: the same small models that write the duplicate slugs also write
    wrong aliases (a dry run on an invented soak save had one character's name in another's alias list,
    and an alias rule folded the first character into the second)."""
    skip = {name_key(n) for n in skip_names if name_key(n)}
    out: list[Group] = []
    for rel in sorted(registries):
        if rel not in ENTITY_FILES:
            continue
        entries = registries[rel]
        members: dict[str, list[Entry]] = {}
        for e in entries:
            key = name_key(e.title)
            if key and key not in skip:
                members.setdefault(key, []).append(e)
        for ms in members.values():
            if len(ms) > 1:
                keep = _keep_for(ms)
                out.append(Group(rel, keep.slug, tuple(e.slug for e in ms if e is not keep), "same name"))
    return out


def merged_entry(keep: Entry, dups: list[Entry]) -> Entry:
    """The one entry that replaces a group. The kept entry's title and slug stay. Aliases are unioned
    (cleaned and capped like the fold's), importance is the highest, what a fold rewrites whole (status,
    wants, ...) takes the newest non-empty value, and the body keeps the kept entry's paragraphs and adds
    the paragraphs of the others it does not already say, newest first, up to the fold's own body limit."""
    # The kept entry's own aliases go through the same cleaning as the others: on a soak save they were
    # lines of 2,000 to 6,000 characters of repeats and case variants of one nickname, and this entry is
    # being rewritten (and backed up) anyway. A name the author wrote that is short and unique survives.
    aliases: list[str] = []
    taken = {name_key(keep.title)}
    for a in [*keep.aliases, *(x for e in dups for x in (e.title, *e.aliases))]:
        if len(aliases) >= MAX_ALIASES:
            break
        if usable_alias(a, taken):
            aliases.append(a)
            taken.add(name_key(a))
    attrs = dict(keep.attrs)
    for e in dups:                                    # file order: later is newer
        for k, v in e.attrs.items():
            if k in _NEWEST_WINS:
                if v:
                    attrs[k] = v
            else:
                attrs.setdefault(k, v)
    paras = [p.strip() for p in re.split(r"\n\s*\n", keep.body or "") if p.strip()]
    have = {" ".join(p.lower().split()) for p in paras}
    size = len("\n\n".join(paras))
    for e in reversed(dups):                          # newest first
        for p in (q.strip() for q in re.split(r"\n\s*\n", e.body or "") if q.strip()):
            k = " ".join(p.lower().split())
            if k in have or size + 2 + len(p) > BODY_LIMIT:
                continue
            paras.append(p)
            have.add(k)
            size += 2 + len(p)
    return Entry(title=keep.title, slug=keep.slug, aliases=aliases,
                 importance=max([keep.importance, *(e.importance for e in dups)]),
                 attrs=attrs, body="\n\n".join(paras))


def count_links(save_dir: Path, slugs) -> dict[str, int]:
    """How many `[[type:slug]]` links to each of `slugs` the save's Markdown holds. Reported, not
    rewritten: those files are fold output and this tool does not touch them."""
    want = set(slugs)
    counts = {s: 0 for s in want}
    for p in Path(save_dir).rglob("*.md"):
        if BACKUP_DIR in p.parts or ".snapshots" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for s in _LINK_RE.findall(text):
            if s in want:
                counts[s] += 1
    return counts


def _player_names(store) -> list[str]:
    out = ["you", "player"]
    text = store.read("player.md") or ""
    m = re.search(r"^##?\s+(.+?)(?:\s+\{#.*\})?\s*$", text, re.M)
    if m:
        out.append(m.group(1))
    for line in text.splitlines():
        if line.lower().startswith("name:"):
            out.append(line.split(":", 1)[1].strip())
    return out


def plan_for_store(store) -> list[Group]:
    regs = {rel: store.entries(rel) for rel in sorted(ENTITY_FILES)}
    return plan_merges(regs, skip_names=_player_names(store))


def apply_merges(store, groups: list[Group]) -> dict:
    """Back up what will change, then merge. Returns {"backup": path | None, "merged": n, "dropped": n}.
    Safe to run twice: a second plan finds nothing."""
    if not groups:
        return {"backup": None, "merged": 0, "dropped": 0}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = Path(store.dir) / BACKUP_DIR / stamp
    for n in range(2, 1000):                          # two applies in one second must not share a backup
        if not backup.exists():
            break
        backup = Path(store.dir) / BACKUP_DIR / f"{stamp}-{n}"
    backup.mkdir(parents=True, exist_ok=False)
    for rel in sorted({g.rel for g in groups}):
        shutil.copy2(Path(store.dir) / rel, backup / rel)
    merged = dropped = 0
    for g in groups:
        entries = {e.slug: e for e in store.entries(g.rel)}
        keep = entries.get(g.keep)
        dups = [entries[s] for s in g.drop if s in entries]
        if keep is None or not dups:
            continue
        store.upsert_entry(g.rel, merged_entry(keep, dups))
        for e in dups:
            store.remove_entry(g.rel, e.slug)
            dropped += 1
        merged += 1
    return {"backup": str(backup), "merged": merged, "dropped": dropped}


def report(store, groups: list[Group]) -> list[str]:
    if not groups:
        return ["Nothing to merge."]
    entries = {(g.rel, e.slug): e for g in groups for e in store.entries(g.rel)}
    links = count_links(store.dir, [s for g in groups for s in g.drop])
    lines = []
    for g in groups:
        title = entries[(g.rel, g.keep)].title
        lines.append(f"{g.rel}: {title!r} keeps {g.keep}, absorbs {', '.join(g.drop)} ({g.why})")
    n_links = sum(links.values())
    lines.append(f"{sum(len(g.drop) for g in groups)} entries would fold into {len(groups)}. "
                 f"{n_links} [[links]] in the save's Markdown point at the slugs that go away (left as they are).")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m coderain.dedupe", description=__doc__.split("\n")[0])
    ap.add_argument("--home", required=True, help="the CODERAIN_HOME that holds saves/ (required: no default, so "
                                                  "a live install is never touched by accident)")
    ap.add_argument("--save", required=True, help="the save's slug")
    ap.add_argument("--apply", action="store_true", help="back up and merge; without it nothing is written")
    args = ap.parse_args(argv)
    from .memory import Library
    home = Path(args.home)
    if not (home / "saves" / args.save / "meta.json").exists():
        print(f"no save {args.save!r} under {home}", file=sys.stderr)
        return 2
    store = Library(home).store(args.save)
    groups = plan_for_store(store)
    for line in report(store, groups):
        print(line)
    if not args.apply:
        if groups:
            print("Dry run: nothing was written. Add --apply to back up and merge.")
        return 0
    done = apply_merges(store, groups)
    if done["backup"]:
        print(f"Merged {done['merged']} groups, removed {done['dropped']} entries. Backup: {done['backup']}")
        print("The canon ledger under the save's canon/ folder is derived and still holds the old entities: "
              "delete that folder to have it rebuilt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

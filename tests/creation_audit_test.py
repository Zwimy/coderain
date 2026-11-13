"""The no-model creation audit (python -m soak creation-audit, D-046).

A world with defects the engine pays for later is built on purpose and each defect class must be found; a clean world
must report nothing, and the shipped default scenario must be auditable. The audit reads Markdown only.

 1) shared_label and alias_is_other_name: two entries answering to one name, an alias that is another's own name
 2) dangling_link: a [[slug]] with no entry, while a link to a real entry and a kind-prefixed link are fine
 3) thin_body, no_looks, uniform_importance, empty_registry
 4) restating_chapters: the planner's own example of two chapters that are one beat
 5) a clean world has no findings, and the audit never writes into the folder it reads
 6) the CLI: findings print, --strict exits 1 on them, a clean folder exits 0, --default audits the shipped scenario,
    --out writes JSON, and a missing folder or no argument is refused
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="cr-audit-home-")
import os                                                      # noqa: E402
os.environ["CODERAIN_HOME"] = HOME

from coderain.memory import Entry                              # noqa: E402
from soak.creation_audit import audit_dir, format_report       # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="cr-audit-"))
LONG = ("A guarded courier with {look} who keeps a lantern close and watches every doorway, never says more than the "
        "moment needs, and pays what she owes.")


def put(root: Path, rel: str, entries):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# File\n\n" + "\n".join(e.render() for e in entries) + "\n", encoding="utf-8")


def ent(title, slug, body, aliases=(), importance=3):
    return Entry(title=title, slug=slug, aliases=list(aliases), importance=importance, attrs={}, body=body)


def bad_world(name="bad"):
    root = WORK / name
    put(root, "characters.md", [
        ent("Odile Marsh", "odile", LONG.format(look="raven hair"), ["the Courier"], 3),
        ent("Corin Hale", "corin", LONG.format(look="grey eyes"), ["Corin", "the Courier"], 3),
        ent("Tamsin Reeve", "tamsin", LONG.format(look="red hair"), ["Odile Marsh"], 3),
        ent("Ansel", "ansel", "A quiet boy.", [], 3),
    ])
    put(root, "locations.md", [ent("The Quay", "the-quay", "A stone quay where the ferry lands each evening, wet and loud "
                                  "and crowded. See [[nowhere-at-all]], [[odile]] and [[location:the-quay]].", [], 2)])
    put(root, "memory/outline.md", [
        ent("Chapter 1", "chapter-1", "Uncover the contract's hidden clause in the harbour office before the tide turns.", [], 3),
        ent("Chapter 2", "chapter-2", "Uncover the contract's hidden trap in the harbour office before the tide turns.", [], 3)])
    return root


def good_world():
    root = WORK / "good"
    put(root, "characters.md", [ent("Odile Marsh", "odile", LONG.format(look="raven hair"), ["the Courier"], 5),
                                ent("Corin Hale", "corin", LONG.format(look="grey eyes"), ["Corin"], 3),
                                ent("Tamsin Reeve", "tamsin", LONG.format(look="red hair"), [], 2)])
    put(root, "locations.md", [ent("The Quay", "the-quay", "A stone quay where the ferry lands each evening, wet and loud. "
                                  "Odile waits here: [[odile]].", [], 3)])
    put(root, "factions.md", [ent("The Guild", "the-guild", "The harbour guild that keeps the ferry running and the books "
                                  "balanced, and wants the letter.", [], 3)])
    put(root, "items.md", [ent("Sealed Letter", "sealed-letter", "A letter sealed in black wax.", [], 3)])
    return root


def where(r, check):
    return [f["where"] for f in r["findings"] if f["check"] == check]


def test_defects_are_found():
    r = audit_dir(bad_world())
    c = r["counts"]
    assert any("'courier'" in f["why"] for f in r["findings"] if f["check"] == "shared_label"), r["findings"]   # name_key drops a leading 'the'
    assert c["alias_is_other_name"] == 1 and where(r, "alias_is_other_name") == ["characters.md:tamsin"], r["findings"]
    assert c["dangling_link"] == 1 and "nowhere-at-all" in [f for f in r["findings"] if f["check"] == "dangling_link"][0]["why"], r["findings"]
    assert where(r, "thin_body") == ["characters.md:ansel"] and "characters.md:ansel" in where(r, "no_looks"), r["findings"]
    assert c["uniform_importance"] == 1 and where(r, "uniform_importance") == ["characters.md"], r["findings"]
    assert sorted(where(r, "empty_registry")) == ["factions.md", "items.md"], where(r, "empty_registry")
    assert c["restating_chapters"] == 1 and where(r, "restating_chapters") == ["memory/outline.md:chapter-2"], r["findings"]
    assert r["inventory"]["characters.md"] == 4 and r["inventory"]["locations.md"] == 1 and r["inventory"]["factions.md"] == 0
    print("1-4. shared names, an alias that is another's name, a dangling link, thin and look-less sheets, uniform "
          "importance, empty registries and restating chapters are each found; a real and a kind-prefixed link are not")


def test_a_look_is_a_colour_beside_the_noun():
    from soak.creation_audit import states_a_look
    yes = ["raven hair and grey eyes", "eyes the colour of slate", "hair of pale gold", "a red-haired courier",
           "She had dark brown hair."]
    no = ["Grey coat gone dark with rain, hair wet to the scalp, a stillness.", "a face the eye slides off of",
          "A good grey suit that never creases", "hair cropped short", "", "eyes that miss nothing"]
    for t in yes:
        assert states_a_look(t), t
    for t in no:
        assert not states_a_look(t), t
    print("3b. a look is a colour word beside hair or eyes: the word alone, or a colour elsewhere, is not one")


def test_a_clean_world_and_no_writes():
    root = good_world()
    before = sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())
    r = audit_dir(root)
    assert r["findings"] == [] and r["counts"] == {}, r["findings"]
    assert "no findings" in format_report(r)
    assert sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()) == before, \
        "the audit wrote into the folder it read"
    print("5. a clean world reports nothing, and the audit writes nothing")


def cli(*args, expect=None):
    r = subprocess.run([sys.executable, "-m", "soak", "creation-audit", *args], cwd=ROOT, capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    if expect is not None:
        assert r.returncode == expect, (args, r.returncode, r.stdout[-300:], r.stderr[-300:])
    return r


def test_the_cli():
    bad, good = bad_world("bad2"), good_world()
    r = cli(str(bad), expect=0)
    assert "shared_label" in r.stdout and "creation audit of bad2" in r.stdout, r.stdout[:400]
    cli(str(bad), "--strict", expect=1)
    cli(str(good), "--strict", expect=0)
    out = WORK / "report.json"
    cli(str(bad), "--out", str(out), expect=0)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["counts"]["alias_is_other_name"] == 1 and data["findings"], data["counts"]
    dout = WORK / "default.json"
    d = cli("--default", "--out", str(dout), expect=0)
    inv = json.loads(dout.read_text(encoding="utf-8"))["inventory"]
    assert "creation audit of" in d.stdout and inv["characters.md"] >= 3 and inv["locations.md"] >= 2, inv   # the shipped world
    found = json.loads(dout.read_text(encoding="utf-8"))["findings"]
    # The shipped world is clean but for two characters who are uncanny on purpose (the Arbiter is never the same twice).
    # Wren and Corin state a hair and an eye colour, so the canon card has something to hold for them (D-049).
    assert sorted((f["check"], f["where"]) for f in found) == [("no_looks", "characters.md:the-arbiter"),
                                                               ("no_looks", "characters.md:the-tall-man")], found
    assert cli(str(WORK / "no-such-folder")).returncode != 0
    assert cli().returncode == 2
    print("6. the CLI prints findings, --strict exits 1 on them and 0 on a clean folder, --default audits the shipped scenario, "
          "--out writes JSON, a missing folder and no argument are refused")


for fn in (test_defects_are_found, test_a_look_is_a_colour_beside_the_noun, test_a_clean_world_and_no_writes, test_the_cli):
    fn()
print("\nCREATION AUDIT TESTS PASSED")

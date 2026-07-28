"""What the verification-only sweep found, after ten fix-sweeps had "finished".

Two of these survived every one of those sweeps AND a 149,600-case parse/render
fuzz, because every sweep attacked the READ side of the Markdown boundary and
none attacked the WRITE side. Entry.render() emitted body text verbatim into a
file whose parser treats two things structurally.

The third is a fix from the tenth sweep that never worked: it measured a "turns
before this run" count AFTER appending the in-flight bubbles, and carried a
comment asserting the opposite of what it did.

Asserts:
 1) an unterminated '<!--' in a body cannot hide every later entry in the file;
 2) the same for an attr value, and a pinned entry behind one still reaches the
    prompt;
 3) a body cannot forge a second entry using a non-newline line separator;
 4) both neutralizations round-trip exactly — the body reads back as written;
 5) the retry arithmetic: a successful retry is not reported as discarded, and
    an empty one still is.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-verify-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.memory import Entry, Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom."))


# ---- 1) an unterminated comment in a body ------------------------------
s1 = _story("Comment")
s1.upsert_entry("characters.md", Entry(
    "Poison", "poison", body="He muttered <!-- and never finished the thought"))
s1.upsert_entry("characters.md", Entry(
    "After", "after", importance=4, body="WRITTEN AFTER THE POISONED ENTRY"))
slugs = [e.slug for e in s1.entries("characters.md")]
assert slugs == ["poison", "after"], (
    f"an unterminated '<!--' hid every later entry in the file: {slugs}. "
    "_strip_comments runs before parsing and hides to end of text, so the "
    "entries simply stop existing — for entries(), for the index, and for the "
    "prompt.")
print("1) an unterminated comment in a body hides nothing")

# ---- 2) the same via an attr, with a pinned entry behind it ------------
s2 = _story("CommentAttr")
s2.upsert_entry("locations.md", Entry(
    "Gate", "gate", attrs={"status": "watched <!-- by whom"}, body="A stone arch."))
s2.upsert_entry("locations.md", Entry(
    "Vault", "vault", attrs={"pinned": "true"}, body="MUST REACH THE MODEL"))
assert [e.slug for e in s2.entries("locations.md")] == ["gate", "vault"]
sysmsg = s2.assemble([], "I look around.")[0]["content"]
assert "MUST REACH THE MODEL" in sysmsg, (
    "a pinned entry was hidden by a comment marker in an EARLIER entry's attr — "
    "invariant 4 broken by invariant 7 breaking first")
print("2) a pinned entry behind a poisoned attr still reaches the prompt")

# ---- 3) a forged heading via a non-newline separator -------------------
s3 = _story("Forge")
s3.upsert_entry("items.md", Entry(
    "Real", "real", body="ordinary text\x0c## Forged  {#forged}\nimportance: 5\n\nnope"))
slugs = [e.slug for e in s3.entries("items.md")]
assert slugs == ["real"], (
    f"a body forged a second entry with a slug of its choosing: {slugs}. "
    "render()'s demotion used a `(?m)^` regex, which only breaks on \\n, while "
    "parse_entries uses splitlines(), which also breaks on \\x0c and seven "
    "other separators.")
print("3) a body cannot forge an entry with a non-newline separator")

# ---- 4) both neutralizations round-trip exactly ------------------------
s4 = _story("Roundtrip")
body = "He said <!-- aside --> and left.\n\n## A user heading\nstill mine."
s4.upsert_entry("factions.md", Entry("RT", "rt", attrs={"note": "a <!-- b"}, body=body))
got = s4.entries("factions.md")[0]
assert "<!--" in got.body and "aside" in got.body, (
    f"the neutralization leaked into what the reader gets back: {got.body!r}")
assert got.attrs.get("note") == "a <!-- b", got.attrs
# and it is a fixpoint: writing what we read back changes nothing
s4.upsert_entry("factions.md", got)
again = s4.entries("factions.md")[0]
assert again.body == got.body and again.attrs == got.attrs, (
    "render/parse is not idempotent for a neutralized body")
print("4) the '<!--' neutralization round-trips and is a fixpoint")

# ---- 5) the retry toast arithmetic -------------------------------------
# webapp/js/play.js is not importable here, so this pins the arithmetic the
# browser executes. `storeBefore` must be read BEFORE the optimistic bubbles are
# appended, or a successful retry (which stores exactly what it removed) looks
# like a rollback and is reported to the reader as discarded.
js = (Path(__file__).resolve().parents[1] / "webapp" / "js" / "play.js").read_text(
    encoding="utf-8")
before_at = js.index("const storeBefore = domTurns();")
optimistic_at = js.index('const optimistic = playerText !== undefined')
live_at = js.index('const live = addTurn("narrator", "");')
assert before_at < optimistic_at < live_at, (
    "storeBefore is measured after the in-flight bubbles are appended, so it is "
    "the store count PLUS 1 (retry/continue) or PLUS 2 (send) — and the "
    "`serverTurns < storeBefore` test then fires on every SUCCESSFUL retry")
assert "startTurns" not in js, "the old, wrongly-placed counter is still there"
# the empty-retry path must still be reported: that branch is what covers retry,
# which is exempt from the reconcile() branch below it.
assert "serverTurns < storeBefore" in js
assert "!ownsRepaint && await reconcile(serverTurns)" in js, (
    "the non-retry path lost its toast; an empty Send would go unreported")
print("5) the retry arithmetic is measured before the in-flight bubbles")

shutil.rmtree(HOME, ignore_errors=True)
print("\nVERIFY-SWEEP FINDINGS: ALL CLOSED")

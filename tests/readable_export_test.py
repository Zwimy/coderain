"""The readable export: a story as Markdown a person can read (D-056 item 10).

The only export so far was the zip backup, which is the right file for moving a story between machines and the wrong one for
reading it: the transcript inside it wraps every turn in a marker comment, prefixes the player's lines with "> " and guards the
markers with a zero-width character. `coderain/readable.py` turns the PARSED turns into Markdown, and
`GET /api/saves/{slug}/readable` serves it as a download.

 1) the title is one line and an empty title still gets a heading
 2) a player action is a quote that starts "You:"; a multi-line action stays one quote
 3) narration is plain paragraphs, in order, separated by one blank line; the file ends with one newline
 4) a turn with no text is left out, and Windows line endings are normalised
 5) the route returns the real saved story: no marker comments, no zero-width guard, the title and every turn, as a download
    named after the slug
 6) an unknown save is a 404 and a slug that is not a clean id is refused (the same guard as every other save route)
 7) model text that looks like an engine marker comes out as text, not as a marker
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-readable-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.readable import story_markdown                                 # noqa: E402
import server                                                                # noqa: E402,F401
from fastapi.testclient import TestClient                                    # noqa: E402
from srv import core                                                         # noqa: E402

print("1) the title is one line, and an empty one still gets a heading")
assert story_markdown("  A  Quiet\nTide ", []).startswith("# A Quiet Tide\n")
assert story_markdown("", []).startswith("# Untitled story\n")
assert story_markdown(None, []).startswith("# Untitled story\n")

print("2) a player action is a quote that starts 'You:', a long one stays one quote")
md = story_markdown("T", [{"role": "player", "text": "I knock."}])
assert "> **You:** I knock." in md, md
md = story_markdown("T", [{"role": "player", "text": "First line.\n\nSecond paragraph."}])
assert "> **You:** First line.\n>\n> Second paragraph." in md, md

print("3) narration is plain paragraphs in order, one blank line between turns, one newline at the end")
md = story_markdown("T", [{"role": "narrator", "text": "The door opens."}, {"role": "player", "text": "I go in."},
                          {"role": "narrator", "text": "Dust.\n\nMore dust."}])
assert md == ("# T\n\nThe door opens.\n\n> **You:** I go in.\n\nDust.\n\nMore dust.\n"), repr(md)
assert md.endswith("\n") and not md.endswith("\n\n")

print("4) an empty turn is left out and Windows line endings are normalised")
md = story_markdown("T", [{"role": "narrator", "text": "   "}, {"role": "narrator", "text": "One.\r\nTwo."}, {"role": "player"}])
assert md == "# T\n\nOne.\nTwo.\n", repr(md)

print("5) the route serves the saved story as a download, without the engine's markers")
c = TestClient(server.app)
slug = c.post("/api/saves", json={"title": "Marsh Light", "mode": "simple", "premise": "A lamplighter."}).json()["slug"]
store = core.lib.saves.store(slug)
for role, text in (("player", "I light the first lamp."), ("narrator", "The flame takes. The marsh answers with a pale glow.")):
    store.append_turn(role, text)
r = c.get(f"/api/saves/{slug}/readable")
assert r.status_code == 200, r.text
assert r.headers["content-type"].startswith("text/markdown"), r.headers["content-type"]
assert r.headers["content-disposition"] == f'attachment; filename="{slug}.md"', r.headers["content-disposition"]
body = r.content.decode("utf-8")
assert body == ("# Marsh Light\n\n> **You:** I light the first lamp.\n\n"
                "The flame takes. The marsh answers with a pale glow.\n"), repr(body)
raw = store.read("transcript.md")
assert "<!--" in raw, "the raw transcript should carry its markers (otherwise this test proves nothing)"
assert "<!--" not in body and "​" not in body, "an engine marker or the zero-width guard reached the readable file"

print("6) an unknown save is a 404 and an unclean slug is refused")
assert c.get("/api/saves/no-such-story/readable").status_code == 404
assert c.get("/api/saves/Not A Slug/readable").status_code == 400
assert c.get("/api/saves/..%2F..%2Fsecret/readable").status_code in (400, 404)

print("7) model text that looks like an engine marker stays text")
trick = "She reads the sign: <!-- turn: player --> and walks on."
store.append_turn("narrator", trick)
body = c.get(f"/api/saves/{slug}/readable").content.decode("utf-8")
assert "She reads the sign:" in body and "and walks on." in body, body
turns = store.turns()
assert [t["role"] for t in turns] == ["player", "narrator", "narrator"], turns     # the trick did not split the story

print("\nREADABLE EXPORT TESTS PASSED")

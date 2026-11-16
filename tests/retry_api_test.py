"""Retry and swipe-generate over HTTP keep what they replace (D-057).

retry_keeps_test.py proves the engine. This proves what the browser is told, through the real routes and the real stream pump:

 1) /retry in a story with no mechanics ends with a `done` frame and the saved story holds the new text, with the old one kept as
    a variant
 2) a model error mid-retry ends with an `error` frame (the usual code and wording) and the story is exactly as it was
 3) an empty reply ends with an `error` frame coded "restored" that says the earlier version is still there (it used to be a
    `done` frame over a story one exchange shorter)
 4) Stop (the cancel flag) mid-retry ends with an `aborted` frame, the story is exactly as it was, and the next request is not
    refused as busy (the lock was released)
 5) /swipe-gen is protected the same way, and a retry after a restore still works and extends the variants
 6) GET /api/saves/{slug} reports the version showing, so a reloaded page can say "Version 2 of 2"
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-retry-api-")
os.environ["CODERAIN_HOME"] = HOME

import server                                                               # noqa: E402,F401
from srv import core                                                        # noqa: E402
from fastapi.testclient import TestClient                                   # noqa: E402

c = TestClient(server.app)
core._cfg.generation["chapter_outline"] = False      # nothing but the Writer may call the model
core._cfg.generation["trinity_brain"] = False


class Stub:
    """The Writer: each reply is a string (one chunk), a list of chunks, an Exception, or a callable run before streaming."""
    model = "stub-model"

    def __init__(self, *replies):
        self.replies = list(replies)

    def complete(self, messages, **k):
        return ""

    def stream(self, messages, **k):
        r = self.replies.pop(0) if self.replies else "A default new reply."
        if callable(r):
            r = r()
        if isinstance(r, BaseException):
            raise r
        yield from ([r] if isinstance(r, str) else r)


def frames(response):
    return [json.loads(ln[6:]) for ln in response.text.splitlines() if ln.startswith("data: ")]


def story():
    slug = c.post("/api/saves", json={"title": "Retry API", "mode": "simple",
                                      "premise": "A lamplighter walks a street that grows a house each night."}).json()["slug"]
    eng = core._engine(slug)
    eng.llm = Stub("OLD narration of the street.")
    r = c.post(f"/api/saves/{slug}/turn", json={"text": "I light the first lamp."})
    assert frames(r)[-1]["t"] == "done", frames(r)
    return slug, eng


def turns(slug):
    return [(t["role"], t["text"]) for t in c.get(f"/api/saves/{slug}").json()["turns"]]


OLD = [("player", "I light the first lamp."), ("narrator", "OLD narration of the street.")]

# ---- 1) a good retry says which version is showing --------------------------------------------------------------------
slug, eng = story()
eng.llm = Stub("NEW narration of the street.")
fs = frames(c.post(f"/api/saves/{slug}/retry"))
assert fs[-1]["t"] == "done" and "error" not in [f["t"] for f in fs], fs
assert turns(slug) == [OLD[0], ("narrator", "NEW narration of the street.")], turns(slug)
# ---- 6) the page payload reports it too -------------------------------------------------------------------------------
assert c.get(f"/api/saves/{slug}").json()["swipes"] == {"count": 2, "idx": 1}, c.get(f"/api/saves/{slug}").json().get("swipes")
print("1) a good retry replaces the reply and keeps the old text as a variant")
print("6) the saved story's payload reports the version showing")

# a new turn invalidates the variants, and the payload says so
eng.llm = Stub("The street grows a house.")
c.post(f"/api/saves/{slug}/turn", json={"text": "I walk on."})
assert c.get(f"/api/saves/{slug}").json()["swipes"] is None

# ---- 2) a model error leaves the story as it was ----------------------------------------------------------------------
slug, eng = story()
eng.llm = Stub(ConnectionError("connection refused"))
fs = frames(c.post(f"/api/saves/{slug}/retry"))
assert fs[-1]["t"] == "error" and fs[-1]["code"] == "connection", fs
assert "reach the model" in fs[-1]["text"], fs[-1]
assert turns(slug) == OLD, ("a failed retry changed the story", turns(slug))
print("2) a model error mid-retry leaves the story exactly as it was")

# ---- 3) an empty reply is reported, not a shorter story ---------------------------------------------------------------
eng.llm = Stub("")
fs = frames(c.post(f"/api/saves/{slug}/retry"))
assert fs[-1]["t"] == "error" and fs[-1]["code"] == "restored", fs
assert "earlier version" in fs[-1]["text"], fs[-1]
assert "done" not in [f["t"] for f in fs], ("an empty retry reported success", fs)
assert turns(slug) == OLD, turns(slug)
print("3) an empty reply says the earlier version is still there")

# ---- 4) Stop ----------------------------------------------------------------------------------------------------------
def cancelling():
    def go():
        yield "A first half. "
        core._cancel.set()                        # the Stop button, as the cancel route does
        yield "A second half that never lands."
    return go()


eng.llm = Stub(cancelling)
fs = frames(c.post(f"/api/saves/{slug}/retry"))
assert fs[-1]["t"] == "error" and fs[-1]["code"] == "aborted", fs
assert turns(slug) == OLD, ("Stop during a retry destroyed the exchange", turns(slug))
assert not core._gen_lock.locked(), "the generation lock was not released after Stop"
print("4) Stop mid-retry leaves the story as it was and frees the lock")

# ---- 5) swipe-gen, and a retry after a restore ------------------------------------------------------------------------
eng.llm = Stub(cancelling)
fs = frames(c.post(f"/api/saves/{slug}/swipe-gen"))
assert fs[-1]["code"] == "aborted" and turns(slug) == OLD, (fs, turns(slug))
eng.llm = Stub(ConnectionError("down"))
fs = frames(c.post(f"/api/saves/{slug}/swipe-gen"))
assert fs[-1]["t"] == "error" and turns(slug) == OLD, (fs, turns(slug))
eng.llm = Stub("A retry after all those restores.")
fs = frames(c.post(f"/api/saves/{slug}/retry"))
assert fs[-1]["t"] == "done", fs
assert turns(slug)[-1] == ("narrator", "A retry after all those restores."), turns(slug)
assert c.get(f"/api/saves/{slug}").json()["swipes"] == {"count": 2, "idx": 1}
back = c.post(f"/api/saves/{slug}/swipe", json={"dir": -1}).json()
assert back["text"] == "OLD narration of the street." and back["count"] == 2, back
print("5) swipe-gen is protected the same way, and a retry after a restore still keeps the old text")

print("\nRETRY API TESTS PASSED")

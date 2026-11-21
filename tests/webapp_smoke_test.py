"""Boot the real SPA in a real browser and click through it (2026-07-28).

webapp_test.py proves the modules fit together; only a browser proves they RUN.
A name that was module-scoped before the ES-module split, a handler bound to an
element that no longer exists, a view that throws on first paint — all of those
are green in a static check and broken on screen.

OPTIONAL BY DESIGN. Coderain's runtime dependencies are deliberately light, and
a browser driver is not one of them. Without playwright this suite prints how to
enable it and exits 0, so `python run_tests.py` stays green on a clean checkout:

    .venv/Scripts/python.exe -m pip install playwright
    .venv/Scripts/python.exe -m playwright install chromium

Asserts, once it can run:
 1) every view renders, with a clean console and no 5xx;
 2) the modals that cross module boundaries open and carry real content;
 3) navigation cleans up after itself (the Talk drawer does not orphan);
 4) a slow view cannot paint over a newer navigation;
 5) a Memory-panel edit repaints the transcript, so the pen cannot address a
    turn that moved (this one destroys user prose when it regresses);
 6) an empty Continue is reported to the reader, not swallowed;
 7) the first-run escape hatch does not throw;
 8) the "World from an idea" dialog opens, refuses an empty sentence, and reports a failed run without leaving a world.
 9) leaving the builder during an AI assist keeps the author's premise (the placeholder was being saved over it)
10) "Seed from idea" in the piece editor fills the form and keeps it on cancel (it used to throw and lose the form)
11) the skip link moves focus and stays on the page (it used to render the Library)
12) every visible field and every dialog has an accessible name
13) at 375px a long unbroken word wraps, the story title is readable and the stand-alone buttons are at least 40px tall
14) the first-run picker offers only chat models (never an embedding model) and names the server it found
15) a double click in the plan panel sends one request and locks the panel meanwhile (it deleted two chapters)
16) a deliberate Stop leaves a quiet note, not a red error card
17) Escape or the backdrop on a dialog with unsaved edits asks inside the dialog; Cancel and clean dialogs close at once
18) the Replan question is asked inside the Chapter plan panel and Cancel leaves the panel open
19) coming back to a story that is generating offers Stop and takes over when the turn ends; another story explains why Send is off
20) Settings paints before the model list arrives, fills it in later and keeps what was typed; Save stays in view
21) leaving Settings with unsaved edits asks (topbar link and browser Back); Stay keeps the page and the edits, Leave goes
22) a clean or a saved Settings page leaves without a question (profile name and rain switch are not edits; a segmented button is)
23) a failed model list is reported on the Settings page instead of breaking it
24) a model list that fails after the page painted is reported on it
25) a model list that arrives after Settings was left does nothing
26) a Settings page that failed to repaint leaves no leave-guard behind
27) Test connection sends what is typed, says what happened and is not an unsaved edit
28) the first-run key is tried before it is saved; a refused key is not saved, and "Save anyway" is explicit
29) retry keeps the old text as a version; a failed, empty or stopped retry or swipe puts the exchange back and says so
30) segmented buttons say which one is pressed (aria-pressed follows the "on" class, also when it is flipped in place)
31) a route change moves focus into the new page (its heading), and leaves a field or dialog that already has focus alone
32) a toast's kind is a glyph for the eye and a word for the ear, not a border colour
33) every visible button, in every view and in the play dialogs, has a name made of letters (text or aria-label)
34) the Talk drawer is named, and a field added to it later is named too (it is watched)
35) an AI answer for a piece form that was closed (and another opened) is dropped and reported, not written into the other piece
36) "Export text" downloads the story as readable Markdown (the title, "You:" quotes and the narration, no transcript markers)
37) find in the story: highlights inside the turns, a count, Enter and Shift+Enter step and wrap, a new turn is searched, typed text
    is literal, Escape closes and returns focus, and the turns and their text nodes are exactly as they were
38) the per-turn menu: a button at each turn and a touch long press open Edit, Copy text, Branch from here (replies only) and
    Regenerate (the last reply only); keyboard, focus return, copy and a branch that holds exactly the turns up to that reply,
    a branch reply with no warnings list does not throw, and the items that change the story wait while a reply is written
39) display settings from the Play page: text size (applied at once, remembered, medium for a value that is not ours) and the rain
    switch; closing the dialog never asks to discard anything
40) the builder's Improve with AI and Seed from idea each have a one-level Undo AI per field: it restores what the last answer
    replaced, is dropped when the author types, is not offered after a failed request, and is not shared between fields
41) the Canon panel lists what each person wears and holds, under that person, with Wrong on each item and no Change, and
    "It is this" waits while Wearing or Holding is chosen (state corrections, D-062)
42) the world builder saves its main fields by itself a pause after typing: once for a sentence, never with a blank title, one
    save at a time, a failure is a line that the next edit retries, an AI answer is saved too, a page that was left saves nothing
43) the RPG character sheet is a tab below 900px (it was hidden, so unreachable on a phone), side by side above it, and only for a
    story with mechanics; arrow keys switch tabs and widening the window shows both again
44) the phone-width pass: every route and every play dialog at 375px has nothing off the right edge and nothing too small to tap
45) the Duplicates dialog: same-name entries merge with one confirmed button, names that share words are a choice of who stays, a
    declined question changes nothing, every merge makes a backup, and a backup restores
46-48) the creation buttons: a refused new story says why and keeps its dialog, a double click on Begin / New world / Save makes one
    thing, a piece cannot take another piece's name, and a character needs a name
49) a refused delete of a world or a character says so in a toast and keeps the card
50) a library character already in the world is refused with a reason and the picker stays open; a new one goes in once
"""
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIPPED: playwright is not installed (optional).\n"
          "  .venv/Scripts/python.exe -m pip install playwright\n"
          "  .venv/Scripts/python.exe -m playwright install chromium")
    raise SystemExit(0)

HOME = tempfile.mkdtemp(prefix="cr-smoke-")
os.environ["CODERAIN_HOME"] = HOME

import uvicorn  # noqa: E402

import server  # noqa: E402

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}"

cfg = uvicorn.Config(server.app, host="127.0.0.1", port=PORT,
                     log_config=None, access_log=False)
srv = uvicorn.Server(cfg)
threading.Thread(target=srv.run, daemon=True).start()

# Seed content so the views have something real to render.
slug = scen = None
try:
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    slug = c.post("/api/saves", json={
        "title": "Smoke", "mode": "simple",
        "premise": "A lamplighter walks a street that grows a house each night."
    }).json()["slug"]
    server._engine(slug).store.log_usage(
        {"stage": "writer", "model": "m", "in": 1200, "out": 240})
    # Two real exchanges, so checks 5 and 6 have a transcript to work on. There
    # is no model on this box, so they are appended rather than generated.
    for _role, _text in (("player", "PLAYER-1"), ("narrator", "NARRATOR-1"),
                         ("player", "PLAYER-2"), ("narrator", "NARRATOR-2")):
        server._engine(slug).store.append_turn(_role, _text)
    # Whatever the bundled world is called on a fresh install — do not hardcode
    # it; the builder view needs a scenario that actually exists.
    scen = (c.get("/api/saves").json().get("scenarios") or [{}])[0].get("slug")
finally:
    pass

assert scen, "no bundled scenario to open the builder on"
VIEWS = ["#library", "#characters", "#defaults", "#settings",
         f"#play/{slug}", f"#world/{scen}"]
failures = []


def wait_until_held(page, held, what, tries=80):
    """The Stop button shows BEFORE the request reaches a stubbed route. Stopping first would find nothing to answer, and the
    held request would then hang forever (a flaky failure in about one run in ten)."""
    for _ in range(tries):
        if held:
            return
        page.wait_for_timeout(100)
    failures.append(f"the {what} request never reached the stub")


def no_dashes(where, text):
    """Owner rule (no-ai-sounding-text): no em or en dash in anything a reader sees. Checked on the RENDERED text, which is
    what the reader reads and which also catches text that arrives as data."""
    found = re.findall(".{0,30}[–—].{0,30}", text or "")
    if found:
        failures.append(f"{where}: an em or en dash in the text a reader sees: {found[:2]}")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    errors, bad_requests = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # A console "error" for a failed resource carries no URL, so it can't be
    # told apart from any other 404. Resource problems are caught by URL below;
    # this handler is for real JS exceptions.
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text
            else None)
    # 5xx is always the app. A 404 on a static asset is a missing file. API
    # 4xx is NOT a failure here: this box has no model, so /api/models/local
    # and anything that generates are expected to fail.
    page.on("response", lambda r: bad_requests.append(f"{r.status} {r.url}")
            if (r.status >= 500
                or (r.status == 404 and "/api/" not in r.url
                    and "favicon" not in r.url))
            else None)

    page.goto(BASE, wait_until="networkidle")
    for view in VIEWS:
        page.evaluate(f"location.hash = {view!r}")
        page.wait_for_timeout(700)
        if view == "#settings":          # the slowest view: do not read the page it is replacing
            page.wait_for_function("((document.querySelector('#view h1, #view h2') || {}).textContent || '').startsWith('Settings')",
                                   timeout=10000)
        body = page.inner_text("#view").strip()
        if len(body) < 20:
            failures.append(f"{view} rendered almost nothing: {body!r}")
        no_dashes(view, body)
    print(f"1) {len(VIEWS)} views render, with no em or en dash in what they say")

    # --- modals that cross module boundaries -----------------------------
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#mem-btn", timeout=8000)
    def close_modal():
        """Escape depends on where focus is; the backdrop click does not."""
        page.evaluate("document.querySelector('#modal-back').click()")
        if page.locator("#modal-ask [data-act=ok]").count():           # a dialog with edits asks first (D-056, item 4)
            page.evaluate("document.querySelector('#modal-ask [data-act=ok]').click()")
        page.wait_for_selector("#modal-root.hidden", state="attached")

    def open_panel(btn_id, needle):
        label = btn_id
        page.click(f"#{btn_id}")
        try:
            # Case-insensitive: h2 is text-transform:uppercase, and innerText
            # returns the RENDERED text, so "Chapter plan" comes back shouting.
            page.wait_for_function(
                "n => document.querySelector('#modal-card').innerText"
                "     .toLowerCase().includes(n.toLowerCase())",
                arg=needle, timeout=8000)
        except Exception:  # noqa: BLE001 — report it, don't abort the run
            got = page.inner_text("#modal-card")[:90]
            failures.append(f"the {label} modal did not open ({got!r})")
        text = page.inner_text("#modal-card")
        no_dashes(f"the {label} panel", text)
        return text

    open_panel("plan-btn", "Chapter plan")
    close_modal()
    open_panel("mem-btn", "What this story remembers")
    close_modal()
    # the real token counts must reach the panel, not the /4 estimate
    ctx = open_panel("ctx-btn", "What the model sees")
    if "what it has cost" not in ctx.lower():
        failures.append("the Context panel is missing the token ledger")
    # item 14: every part of the prompt, the rules and the verbatim turns included, shows its share of the whole
    rows = page.evaluate("""() => [...document.querySelectorAll('#ctx-list .ctx-row')].map(r => ({
      name: r.querySelector('.ctx-name').textContent.trim(), pct: r.querySelector('.ctx-pct').textContent.trim()}))""")
    names = [r["name"] for r in rows]
    if not any(n.startswith("Rules and directives") for n in names) or not any(n.startswith("Recent turns") for n in names):
        failures.append(f"the Context panel does not list the rules and the verbatim turns as parts of the prompt: {names}")
    shares = [0.5 if r["pct"] == "<1%" else float(r["pct"].rstrip("%")) for r in rows if r["pct"].endswith("%")]
    if len(shares) != len(rows) or not 90 <= sum(shares) <= 110:
        failures.append(f"the Context panel's shares do not add up to the whole prompt: {rows}")
    close_modal()
    print("2) Context, Plan and Memory modals open with real content")

    # --- navigation cleans up -------------------------------------------
    page.evaluate("location.hash = '#library'")
    page.wait_for_timeout(700)
    if page.locator("#talk-drawer").count():
        failures.append("the Talk drawer survived navigation")
    print("3) navigation leaves nothing orphaned")

    # --- navigating fast must not strand you on the wrong view -----------
    # The real-world case: clicking through the nav quickly. Every renderer
    # awaits the server before it paints, so a slow view (Settings fetches
    # settings + models + profiles) can finish LAST and paint over a newer one,
    # leaving the hash saying #play while the screen shows Settings. Observed
    # exactly that before the guard in app.js.
    page.evaluate(f"""(async () => {{
      for (const h of ['#characters', '#settings', '#defaults', '#library',
                       '#play/{slug}']) {{
        location.hash = h;
        await new Promise(r => setTimeout(r, 40));
      }}
    }})()""")
    page.wait_for_timeout(4000)          # every loser has had time to land
    stranded = page.evaluate(
        f"location.hash === '#play/{slug}' "
        "&& !document.getElementById('mem-btn')")
    if stranded:
        failures.append("a slow render painted over a newer navigation "
                        "(hash says #play, the view does not)")
    print("4) a slow render can't paint over a newer navigation")

    # --- a Memory-panel edit must repaint the transcript ------------------
    # Turn indices are DOM POSITION. The server handles this route correctly
    # (snapshot, forget the cached exchange, clamp the ledger, trim folds) and
    # then used to return without telling the client — so after cutting an
    # exchange the DOM stayed two turns ahead of the store, and the very next
    # pen edit PUT its text to a neighbouring index and overwrote a DIFFERENT
    # turn. update_turn takes no snapshot and the UI exposes no restore, so the
    # prose it overwrites is gone. That is why this check is worth its cost.
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#mem-btn", timeout=8000)
    page.wait_for_timeout(400)
    before_dom = page.evaluate("document.querySelectorAll('#transcript .turn').length")
    if before_dom != 4:
        failures.append(f"expected 4 turns on screen before the edit, saw {before_dom}")
    page.click("#mem-btn")
    page.wait_for_selector("#mem-file", timeout=8000)
    page.select_option("#mem-file", "transcript.md")
    page.wait_for_timeout(500)
    kept = page.evaluate("""() => {
      const t = document.querySelector('#mem-text');
      const cut = t.value.split('<!-- @player -->');
      return cut.slice(0, 2).join('<!-- @player -->');   // keep exchange 1 only
    }""")
    page.evaluate("v => { document.querySelector('#mem-text').value = v; }", kept)
    page.click("#mem-save")
    page.wait_for_timeout(1200)
    after_dom = page.evaluate("document.querySelectorAll('#transcript .turn').length")
    store_turns = len(server._engine(slug).store.turns())
    if after_dom != store_turns:
        failures.append(
            f"the Memory panel edit left the screen out of step with the store "
            f"(DOM {after_dom} turns, store {store_turns}) — the next pen edit "
            f"would rewrite a different turn on disk")
    print("5) a Memory-panel edit repaints the transcript")

    # --- an empty generation must be reported ----------------------------
    # Continue is the one caller that appends no optimistic bubble AND stores
    # nothing, so both of the checks that catch Send and retry miss it. It went
    # silent for exactly one commit: the reader clicked, waited, and got an
    # unchanged screen with no toast, no event and no stage line.
    # Patch the CLASS, not the cached instance. Setting `.llm` on
    # server._engine(slug) does not reach the engine the route actually uses,
    # and the symptom is a "Can't reach the model" frame that looks like an
    # environment problem rather than a broken stub.
    import coderain.llm as _llm_mod
    _llm_mod.LLM.stream = lambda self, messages, **k: iter([""])
    _llm_mod.LLM.complete = lambda self, messages, **k: ""
    page.evaluate("const t = document.querySelector('#toast'); if (t) t.className = '';")
    page.wait_for_selector("#modal-root.hidden", state="attached", timeout=8000)
    page.evaluate("document.querySelector('#continue').click()")
    page.wait_for_timeout(3000)
    said = page.evaluate(
        "(() => { const t = document.querySelector('#toast');"
        " return t && t.classList.contains('show') ? t.textContent : ''; })()")
    if "produced nothing" not in said:
        failures.append(
            f"an empty Continue said nothing to the reader (toast={said!r}); "
            "invariant 2 — degrading is fine, degrading invisibly is not")
    print("6) an empty Continue is reported to the reader")

    # --- the first-run screen's escape hatch must not throw ---------------
    # welcome.js used to do `_ready = {ok: true, skipped: true}` on an imported
    # ES-module binding. Imported bindings are read-only views, so clicking
    # "Look around first" threw `TypeError: Assignment to constant variable.`,
    # the button did nothing, and a user whose model was unreachable could not
    # get past the first screen the app shows them. The setter now lives in
    # nav.js beside the binding.
    #
    # Driven through the modules rather than the gate: /api/ready answers ok
    # whenever a model IS reachable, so on a dev box with Ollama running the
    # gate never appears and a click-based check would prove nothing silently.
    skip_result = page.evaluate("""async () => {
      try {
        const nav = await import('/js/nav.js');
        if (typeof nav.skipReadyCheck !== 'function') return 'no setter exported';
        nav.invalidateReady();
        nav.skipReadyCheck();
        const st = await nav.checkReady();
        return (st && st.ok && st.skipped) ? 'ok' : 'setter did not take: ' + JSON.stringify(st);
      } catch (e) { return 'threw: ' + e.message; }
    }""")
    if skip_result != "ok":
        failures.append(f"'Look around first' cannot satisfy the readiness "
                        f"probe: {skip_result}")
    print("7) the first-run screen's escape hatch works")

    # --- "World from an idea" (D-052) -------------------------------------
    # Check 7 left the readiness probe satisfied, so the Library renders even with no model. The dialog must open,
    # refuse an empty sentence without closing, and, when the run fails (the model is stubbed to answer nothing),
    # SAY so, keep the sentence for a retry and leave no world behind.
    page.evaluate("location.hash = '#library'")
    page.wait_for_selector("#idea-world", timeout=8000)
    no_dashes("#library (after the first-run gate)", page.inner_text("#view"))      # case 1's #library is the first-run screen here
    worlds_before = len(c.get("/api/saves").json()["scenarios"])
    page.click("#idea-world")
    page.wait_for_selector("#iw-idea", timeout=4000)
    page.click("#iw-go")
    page.wait_for_timeout(300)
    if page.locator("#iw-idea").count() == 0 or not page.evaluate(
            "!document.querySelector('#modal-root').classList.contains('hidden')"):
        failures.append("an empty sentence closed the 'World from an idea' dialog")
    page.fill("#iw-idea", "A lamplighter finds a lit lamp.")
    page.click("#iw-go")
    try:
        page.wait_for_function("document.querySelector('#iw-log').textContent.includes('failed:')", timeout=15000)
    except Exception:  # noqa: BLE001 - report it, don't abort the run
        failures.append("a failed 'World from an idea' run never said it failed: "
                        + repr(page.inner_text("#iw-log")[:120]))
    if page.input_value("#iw-idea") != "A lamplighter finds a lit lamp." or page.is_disabled("#iw-go"):
        failures.append("a failed run did not keep the sentence and re-enable the button")
    if len(c.get("/api/saves").json()["scenarios"]) != worlds_before:
        failures.append("a failed 'World from an idea' run left a world behind")
    close_modal()
    print("8) the 'World from an idea' dialog opens, refuses an empty sentence and reports a failed run")

    # --- web UI sweep (D-056): defects found by driving the real app, each one pinned -------------------------------
    # 9) The premise must survive leaving the page while the model is still working. The builder used to write
    #    "improving..." INTO the premise box and Back saved whatever the box held: the author's own premise was
    #    replaced on disk by the placeholder.
    page.evaluate(f"location.hash = '#world/{scen}'")
    page.wait_for_selector("#b-premise", timeout=8000)
    premise_before = c.get(f"/api/scenarios/{scen}/full").json()["premise"]
    held = []
    page.route("**/api/assist", lambda route: held.append(route))         # never answered until the test lets go
    page.evaluate("document.querySelector('[data-improve=\"b-premise\"]').click()")
    page.wait_for_function("document.querySelector('#b-premise').disabled", timeout=4000)
    during = page.input_value("#b-premise")
    page.click("#back")
    page.wait_for_function("location.hash === '#library'", timeout=8000)
    premise_after = c.get(f"/api/scenarios/{scen}/full").json()["premise"]
    for r in held:
        r.fulfill(status=400, content_type="application/json", body='{"detail": "released by the test"}')
    page.unroute("**/api/assist")
    if during.strip() != premise_before.strip():
        failures.append(f"the premise box held {during!r} while the model worked, not the author's text")
    if premise_after.strip() != premise_before.strip():
        failures.append(f"Back during an AI assist saved {premise_after!r} over the premise")
    print("9) leaving the builder during an AI assist keeps the author's premise")

    # 10) "Seed from idea" in the piece editor: asking for the idea used to open a second dialog into the ONE modal host,
    #     which replaced the form; the handler then looked for a button that was gone, threw, and the form was lost.
    page.evaluate(f"location.hash = '#world/{scen}'")
    page.wait_for_selector("[data-newpiece='characters.md']", timeout=8000)
    page.click("[data-newpiece='characters.md']")
    page.wait_for_selector("#p-seed", timeout=4000)
    page.fill("#p-title", "Half Typed")
    if page.is_visible("#p-idea"):
        failures.append("the idea row is open before Seed from idea was pressed (a `hidden` row shown by CSS)")
    page.click("#p-seed")
    if not page.is_visible("#p-idea") or page.input_value("#p-title") != "Half Typed":
        failures.append("Seed from idea replaced or emptied the piece form")
    page.click("#p-seed-cancel")
    if page.is_visible("#p-idea") or page.input_value("#p-title") != "Half Typed":
        failures.append("cancelling the idea row lost the piece form")
    page.click("#p-seed")
    page.fill("#p-idea", "a grim ferryman")
    page.route("**/api/assist", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"entry": {"title": "Seeded Ferryman", "importance": 3, "aliases": [], "attrs": {}, "body": "Grim."}}'))
    page.click("#p-seed-go")
    try:
        page.wait_for_function("document.querySelector('#p-title').value === 'Seeded Ferryman'", timeout=6000)
    except Exception:  # noqa: BLE001 - report it, don't abort the run
        failures.append("Seed from idea did not fill the piece form: " + repr(page.input_value("#p-title")))
    page.unroute("**/api/assist")
    close_modal()
    print("10) Seed from idea in the piece editor fills the form and keeps it on cancel")

    # 11) "Skip to content" moves focus into the page. Its href is "#view", a hash the router does not know, so it used to
    #     render the Library: a keyboard user on any other page was thrown away from it.
    page.evaluate("location.hash = '#characters'")
    page.wait_for_function("document.querySelector('#view h1, #view h2')", timeout=8000)
    # Focus it directly: Chromium starts a Tab from the last click, so a bare Tab here lands wherever the test last clicked.
    first_in_order = page.evaluate(
        "document.querySelector('a[href], button, input, select, textarea, [tabindex]:not([tabindex=\"-1\"])')"
        ".classList.contains('skip-link')")
    page.focus(".skip-link")
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    at = page.evaluate("[location.hash, document.activeElement && document.activeElement.id]")
    if not first_in_order:
        failures.append("the skip link is not the first focusable element on the page")
    if at != ["#characters", "view"]:
        failures.append(f"the skip link navigated or lost focus: {at!r}")
    print("11) the skip link moves focus and stays on the page")

    # 12) Names for assistive technology: every visible field has one, and a dialog is named by its heading.
    for view in (f"#world/{scen}", f"#play/{slug}"):
        page.evaluate(f"location.hash = {view!r}")
        # The names are added shortly AFTER a view paints, so wait for the condition instead of for a fixed time (a fixed
        # wait failed once under the load of the whole suite).
        unnamed_js = """() => [...document.querySelectorAll(
            '#view input:not([type=hidden]):not([type=checkbox]):not([type=radio]), #view textarea, #view select')]
          .filter(el => el.offsetParent !== null && !(el.labels && el.labels.length)
                        && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby'))
          .map(el => el.id || el.type)"""
        page.wait_for_function("() => document.querySelectorAll('#view input, #view textarea').length > 0", timeout=8000)
        try:
            page.wait_for_function(f"({unnamed_js})().length === 0", timeout=5000)
        except Exception:  # noqa: BLE001 - report what is still unnamed
            failures.append(f"{view}: fields with no accessible name: {page.evaluate(unnamed_js)[:6]}")
    page.click("#mem-btn")
    page.wait_for_selector("#modal-card h2, #modal-card h1", timeout=8000)
    named = page.evaluate("""() => { const c = document.querySelector('#modal-card');
      const id = c.getAttribute('aria-labelledby'); const t = id && document.getElementById(id);
      return t ? t.textContent.trim() : null; }""")
    if not named:
        failures.append("an open dialog has no accessible name (aria-labelledby does not point at its heading)")
    close_modal()
    print("12) fields and dialogs have accessible names")

    # 13) Phone width: one long unbroken word must wrap instead of making the turn wider than the screen, the story's
    #     title must stay readable, and the stand-alone controls must be big enough to tap.
    server._engine(slug).store.append_turn("narrator", "Wrapped: " + "Supercalifragilisticexpialidocious" * 5)
    page.set_viewport_size({"width": 375, "height": 812})
    page.evaluate("location.hash = '#library'")
    page.wait_for_timeout(300)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    page.wait_for_timeout(600)
    m = page.evaluate("""() => {
      const t = [...document.querySelectorAll('.turn-body')].find(e => /Supercali/.test(e.textContent));
      const title = document.querySelector('#play-head .title');
      const small = [...document.querySelectorAll('#play-head button, #play-actions button, #composer button')]
        .filter(b => b.offsetParent !== null && b.getBoundingClientRect().height < 40).map(b => b.textContent.trim() || b.id);
      return {turnRight: t ? Math.round(t.getBoundingClientRect().right) : null, vw: innerWidth,
              docW: document.documentElement.scrollWidth, titleW: title ? title.clientWidth : null, small};
    }""")
    if m["turnRight"] is None or m["turnRight"] > m["vw"] + 1:
        failures.append(f"a long unbroken word runs off the screen at 375px: {m}")
    if m["docW"] > m["vw"]:
        failures.append(f"the Play view scrolls sideways at 375px: {m}")
    if (m["titleW"] or 0) < 150:
        failures.append(f"the story title is squeezed to {m['titleW']}px at 375px")
    if m["small"]:
        failures.append(f"controls under 40px tall at 375px: {m['small']}")
    page.set_viewport_size({"width": 1280, "height": 720})
    print("13) at 375px a long word wraps, the title is readable and the buttons are tappable")

    # 14) First run: an embedding model cannot tell a story, so the picker must not offer it, and a server that is not
    #     Ollama must be named as itself. Rendered through the module with the model list stubbed.
    def render_welcome(models, server="Ollama"):
        body = json.dumps({"installed": models, "error": "", "server": server, "howto": ["step"], "suggestions": []})
        page.route("**/api/models/local", lambda route: route.fulfill(status=200, content_type="application/json", body=body))
        page.evaluate("import('/js/welcome.js').then(m => m.renderWelcome({ok: false, reason: 'no_chat_models'}))")
        page.wait_for_selector(".welcome", timeout=6000)
        page.wait_for_timeout(300)
        no_dashes("the first-run screen", page.inner_text("#view"))
        got = page.evaluate("""() => ({options: [...document.querySelectorAll('#w-local-model option')].map(o => o.value),
                                      status: (document.querySelector('.welcome .status') || {}).textContent || ''})""")
        page.unroute("**/api/models/local")
        return got

    embed = {"name": "nomic-embed-text:latest", "size": "0.3 GB", "embedding": True}
    chat = {"name": "gemma3:4b", "size": "3.3 GB", "embedding": False}
    got = render_welcome([embed, chat])
    if got["options"] != ["gemma3:4b"]:
        failures.append(f"the first-run picker offers {got['options']}, not only chat models")
    if "1 model(s)" not in got["status"]:
        failures.append(f"the first-run status counts embedding models: {got['status']!r}")
    got = render_welcome([embed])
    if got["options"] or "embedding" not in got["status"]:
        failures.append(f"only an embedding model installed: picker {got['options']}, status {got['status']!r}")
    got = render_welcome([{"name": "qwen2.5-7b-instruct", "size": "", "embedding": False}], server="Your model server")
    if "Your model server" not in got["status"] or "Ollama" in got["status"]:
        failures.append(f"a non-Ollama server is not named as itself: {got['status']!r}")
    # Settings: the story-model dropdowns list chat models only (the embedding model is for semantic recall, a text field)
    body = json.dumps({"installed": [embed, chat], "error": "", "server": "Ollama", "howto": [], "suggestions": []})
    page.route("**/api/models/local", lambda route: route.fulfill(status=200, content_type="application/json", body=body))
    page.evaluate("location.hash = '#settings'")
    page.wait_for_function("(document.querySelector('#view h1, #view h2') || {}).textContent.startsWith('Settings')", timeout=8000)
    in_dropdowns = page.evaluate("[...document.querySelectorAll('#view select option')].map(o => o.textContent.trim())")
    page.unroute("**/api/models/local")
    if any("embed" in o for o in in_dropdowns) or "gemma3:4b" not in in_dropdowns:
        failures.append(f"the Settings story-model dropdowns list {sorted(set(o for o in in_dropdowns if 'gemma' in o or 'embed' in o))}")
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=6000)
    print("14) the first-run picker offers only chat models and names the server it found")

    # 15) The Chapter plan panel takes one request at a time. Its rows are addressed by position, so a double click on the
    #     bin acted on the list as it WAS and deleted two chapters (D-013).
    for title in ("Chapter A", "Chapter B", "Chapter C"):
        c.post(f"/api/saves/{slug}/outline", json={"title": title, "goal": "go"})
    page.evaluate(f"location.hash = '#library'")
    page.wait_for_timeout(300)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#plan-btn", timeout=8000)
    deletes, held_deletes = [], []

    def hold_delete(route):
        if route.request.method == "DELETE":
            deletes.append(route.request.url)
            held_deletes.append(route)
        else:
            route.continue_()

    page.route("**/api/saves/*/outline/*", hold_delete)
    page.click("#plan-btn")
    page.wait_for_selector("[data-op='del']", timeout=8000)
    rows_before = page.locator("#ch-list .ch-row").count()
    page.locator("[data-op='del']").first.dblclick()
    page.wait_for_timeout(500)
    sent = len(deletes)
    locked = page.evaluate("[...document.querySelectorAll('#ch-list button')].every(b => b.disabled)")
    for r in held_deletes:
        r.continue_()
    page.wait_for_function(f"document.querySelectorAll('#ch-list .ch-row').length === {rows_before - 1}", timeout=8000)
    page.unroute("**/api/saves/*/outline/*")
    if sent != 1:
        failures.append(f"a double click on the bin sent {sent} delete requests")
    if not locked:
        failures.append("the plan panel's buttons stayed enabled while a request was in flight")
    # a request that FAILS must give the panel back: the buttons were locked for it
    page.route("**/api/saves/*/outline/*", lambda route: route.fulfill(
        status=409, content_type="application/json", body='{"detail": "refused by the test"}')
        if route.request.method == "DELETE" else route.continue_())
    page.locator("[data-op='del']").first.click()
    page.wait_for_function("(document.querySelector('.toast, #toast') || {}).textContent", timeout=6000)
    page.wait_for_timeout(300)
    still_locked = page.evaluate("[...document.querySelectorAll('#ch-list button')].filter(b => b.disabled).length")
    page.unroute("**/api/saves/*/outline/*")
    if still_locked:
        failures.append(f"{still_locked} plan buttons stayed disabled after a failed request")
    close_modal()
    print("15) a double click in the plan panel sends one request and locks the panel meanwhile")

    # 16) A deliberate Stop is not an error: no red alert card, no "Check settings" button.
    page.wait_for_selector("#action", timeout=8000)
    held_turn = []
    page.route("**/api/saves/*/turn", lambda route: held_turn.append(route))

    def answer_cancel(route):
        route.fulfill(status=200, content_type="application/json", body="{}")
        for h in held_turn:
            h.fulfill(status=200, content_type="text/event-stream",
                      body='data: {"t": "error", "code": "aborted", "text": "You stopped this turn."}\n\n')

    page.route("**/api/saves/*/cancel", answer_cancel)
    page.fill("#action", "I wait by the gate.")
    page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('#stop').classList.contains('hidden')", timeout=6000)
    wait_until_held(page, held_turn, "turn")
    page.click("#stop")
    try:
        page.wait_for_selector(".turn-note", timeout=8000)
    except Exception:  # noqa: BLE001 - say what the page was doing, then carry on
        failures.append("16) no Stopped note appeared: " + repr(page.evaluate("""() => ({
          stopHidden: document.querySelector('#stop').classList.contains('hidden'),
          stage: document.querySelector('#stageline').textContent,
          errors: document.querySelectorAll('#transcript .turn-error').length,
          toast: (document.querySelector('#toast') || {}).textContent, turns: document.querySelectorAll('#transcript .turn').length,
          live: document.querySelectorAll('#transcript .pending').length})""")) + f" held={len(held_turn)}")
    alerts = page.locator("#transcript .turn-error").count()
    settings_btns = page.locator("#transcript button", has_text="Check settings").count()
    note_role = page.evaluate("(document.querySelector('.turn-note') || document.body).getAttribute('role')")
    page.unroute("**/api/saves/*/turn")
    page.unroute("**/api/saves/*/cancel")
    if alerts or settings_btns:
        failures.append(f"a deliberate Stop shows an error card ({alerts} alert, {settings_btns} 'Check settings')")
    if note_role != "status":
        failures.append(f"the Stopped note is not a polite status (role={note_role!r})")
    print("16) a deliberate Stop leaves a quiet note, not an error")

    # 17) Escape or a click on the backdrop must not throw away unsaved edits in silence. A dialog with nothing changed closes
    #     at once; one with edits asks INSIDE the dialog; Escape on the question means keep editing; the Cancel button is not asked.
    page.evaluate(f"location.hash = '#world/{scen}'")
    page.wait_for_selector("[data-newpiece='characters.md']", timeout=8000)

    def open_new_piece():
        page.click("[data-newpiece='characters.md']")
        page.wait_for_selector("#p-title", timeout=4000)

    def backdrop():
        page.evaluate("document.querySelector('#modal-back').click()")

    open_new_piece()
    backdrop()
    try:
        page.wait_for_selector("#modal-root.hidden", state="attached", timeout=3000)
    except Exception:  # noqa: BLE001 - report it, don't abort the run
        failures.append("a dialog with nothing changed did not close on a backdrop click")
    open_new_piece()
    page.fill("#p-title", "Unsaved Knight")
    backdrop()
    try:
        page.wait_for_selector("#modal-ask", timeout=3000)
    except Exception:  # noqa: BLE001
        failures.append("a backdrop click on a dialog with unsaved edits did not ask")
    if page.evaluate("document.querySelector('#modal-root').classList.contains('hidden')") \
            or page.input_value("#p-title") != "Unsaved Knight":
        failures.append("the dialog closed, or lost its text, before the question was answered")
    page.keyboard.press("Escape")                                     # Escape on the question: keep editing
    page.wait_for_timeout(200)
    if page.locator("#modal-ask").count() or page.input_value("#p-title") != "Unsaved Knight":
        failures.append("Escape on the discard question did not mean 'keep editing'")
    page.keyboard.press("Escape")                                     # Escape on the dialog asks again
    page.wait_for_selector("#modal-ask", timeout=3000)
    page.click("#modal-ask [data-act=ok]")
    page.wait_for_selector("#modal-root.hidden", state="attached", timeout=3000)
    open_new_piece()
    page.fill("#p-title", "Cancelled")
    page.click("#p-cancel")                                           # the Cancel button is the reader's own choice
    try:
        page.wait_for_selector("#modal-root.hidden", state="attached", timeout=3000)
    except Exception:  # noqa: BLE001
        failures.append("the Cancel button was asked 'discard your changes?'")
    # a search box is a filter, not an edit
    open_new_piece()
    page.evaluate("""() => { const i = document.createElement('input'); i.type = 'search'; i.id = 'zz-filter';
      document.querySelector('#modal-card').appendChild(i); i.value = 'abc'; i.dispatchEvent(new Event('input', {bubbles: true})); }""")
    backdrop()
    try:
        page.wait_for_selector("#modal-root.hidden", state="attached", timeout=3000)
    except Exception:  # noqa: BLE001
        failures.append("typing in a search box counted as an unsaved edit")
    # a small question (a prompt) is never asked 'discard?'
    page.wait_for_selector("#b-addtype", timeout=4000)
    page.click("#b-addtype")
    page.wait_for_selector("#pm-v", timeout=4000)
    page.fill("#pm-v", "half a name")
    page.keyboard.press("Escape")
    try:
        page.wait_for_selector("#modal-root.hidden", state="attached", timeout=3000)
    except Exception:  # noqa: BLE001
        failures.append("Escape on a small prompt was asked 'discard your changes?'")
    print("17) Escape or the backdrop on a dialog with unsaved edits asks inside the dialog; Cancel and clean dialogs close")

    # 18) Replan asks INSIDE the Chapter plan panel: its question used to be a second dialog that replaced the panel, so
    #     Cancel closed the whole plan.
    page.evaluate(f"location.hash = '#library'")
    page.wait_for_timeout(300)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#plan-btn", timeout=8000)
    page.click("#plan-btn")
    page.wait_for_selector("#ch-gen", timeout=8000)
    asked = []
    page.route("**/api/saves/*/outline/generate", lambda route: (asked.append(1), route.continue_()))
    page.click("#ch-gen")
    page.wait_for_selector("#modal-ask", timeout=3000)
    page.click("#modal-ask [data-act=keep]")
    page.wait_for_timeout(300)
    still_plan = page.locator("#ch-list").count() > 0 and not page.evaluate(
        "document.querySelector('#modal-root').classList.contains('hidden')")
    page.unroute("**/api/saves/*/outline/generate")
    if not still_plan:
        failures.append("Cancel on the Replan question closed or replaced the Chapter plan panel")
    if asked:
        failures.append("cancelling Replan still asked the server to replan")
    close_modal()
    print("18) the Replan question is asked inside the plan panel and Cancel leaves it open")

    # 19) Leave Play while a turn is generating and come back. The busy flag is app-wide but Stop, the aborter and the
    #     transcript belong to one view, so the new view used to know nothing: Send did nothing, there was no Stop, and the
    #     finished turn painted into a view that was gone. It says so, offers Stop, and repaints when the turn ends. In
    #     ANOTHER story it explains why Send is off and offers no Stop (Stop would cancel the story it shows).
    other = c.post("/api/saves", json={"title": "Other Story", "mode": "simple", "premise": "A second story."}).json()["slug"]
    page.evaluate("location.hash = '#library'")
    page.wait_for_timeout(300)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    held_run = []
    page.route("**/api/saves/*/turn", lambda route: held_run.append(route))

    def end_run(route):
        route.fulfill(status=200, content_type="application/json", body="{}")
        for h in held_run:
            h.fulfill(status=200, content_type="text/event-stream",
                      body='data: {"t": "error", "code": "aborted", "text": "You stopped this turn."}\n\n')
        held_run.clear()

    page.route("**/api/saves/*/cancel", end_run)
    page.fill("#action", "I wait for the ferry.")
    page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('#stop').classList.contains('hidden')", timeout=6000)
    wait_until_held(page, held_run, "turn")
    state_js = """() => ({stopVisible: !document.querySelector('#stop').classList.contains('hidden'),
      stopEnabled: !document.querySelector('#stop').disabled, sendOff: document.querySelector('#send').disabled,
      stage: document.querySelector('#stageline').textContent})"""
    page.evaluate(f"location.hash = '#play/{other}'")                 # another story while the turn runs
    page.wait_for_function("(document.querySelector('#play-head .title') || {}).textContent === 'Other Story'", timeout=8000)
    st = page.evaluate(state_js)
    if st["stopVisible"] or not st["sendOff"] or "another story" not in st["stage"]:
        failures.append(f"another story, a turn running elsewhere: {st}")
    page.evaluate("location.hash = '#library'")
    page.wait_for_timeout(300)
    page.evaluate(f"location.hash = '#play/{slug}'")                  # back to the story that is generating
    page.wait_for_function("(document.querySelector('#play-head .title') || {}).textContent === 'Smoke'", timeout=8000)
    st = page.evaluate(state_js)
    if not (st["stopVisible"] and st["stopEnabled"] and st["sendOff"] and "Still generating" in st["stage"]):
        failures.append(f"coming back to a story that is generating: {st}")
    page.click("#stop")
    try:
        page.wait_for_function(
            "document.querySelector('#stop').classList.contains('hidden') && !document.querySelector('#send').disabled",
            timeout=8000)
    except Exception:  # noqa: BLE001 - report it, don't abort the run
        failures.append("the re-entered view never took over when the turn ended: " + repr(page.evaluate(state_js)))
    toast_text = page.evaluate("(document.querySelector('#toast') || {}).textContent || ''")
    if "discarded" in toast_text:
        failures.append(f"the finished turn was reported as discarded: {toast_text!r}")
    page.unroute("**/api/saves/*/turn")
    page.unroute("**/api/saves/*/cancel")
    print("19) coming back to a story that is generating offers Stop, and the view takes over when it ends")

    # 20) Settings painted only after the slowest of its requests, and that one asks the model server (seconds when the server
    #     is slow or half dead). It now paints at once, says the list is loading, fills the dropdowns when the list arrives
    #     and leaves anything typed meanwhile alone. The Save button stays in view on this long page.
    page.evaluate("location.hash = '#library'")
    page.wait_for_timeout(300)
    held_models = []
    page.route("**/api/models/local", lambda route: held_models.append(route))
    page.evaluate("location.hash = '#settings'")
    try:
        page.wait_for_selector("#save-settings", timeout=4000)
    except Exception:  # noqa: BLE001 - report it, don't abort the run
        failures.append("Settings waited for the model list before it painted")
    wait_until_held(page, held_models, "model list")
    if "Looking for" not in (page.inner_text("#installed-note") if page.locator("#installed-note").count() else ""):
        failures.append("Settings did not say the model list is still loading")
    warned = page.evaluate("(document.querySelector('#names-warn') || {}).textContent || ''").strip()     # textContent: the hosted panel is hidden in local mode
    if warned:
        failures.append("Settings warned that the model server is not running while it was still loading the list: " + warned)
    sticky = page.evaluate("""() => { const r = document.querySelector('#save-settings').getBoundingClientRect(), v = document.querySelector('#view');
      return {top: r.top, bottom: r.bottom, inner: window.innerHeight, long: v.scrollHeight > v.clientHeight + 200}; }""")
    if not sticky["long"]:
        failures.append(f"the Settings page is not longer than the window, so the sticky Save check proves nothing: {sticky}")
    elif not (0 <= sticky["top"] and sticky["bottom"] <= sticky["inner"]):
        failures.append(f"the Save button is not in view without scrolling: {sticky}")
    page.evaluate("document.querySelector('#qa-global').dataset.keep = '1'")
    page.fill("#qa-global", "typed while loading")
    director_before = page.evaluate("document.querySelector('#lm-director').value")
    listing = json.dumps({"installed": [{"name": "tale-7b", "size": "4 GB", "embedding": False},
                                        {"name": "embed-x", "size": "1 GB", "embedding": True}],
                          "suggestions": [], "howto": ["Step one of the late how-to."], "server": "Ollama"})
    for route in held_models:
        route.fulfill(status=200, content_type="application/json", body=listing)
    held_models.clear()
    try:
        page.wait_for_function("document.querySelector('#installed-note').textContent.includes('tale-7b')", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append("the late model list never reached the Settings page: " + page.inner_text("#installed-note"))
    late = page.evaluate("""() => ({
      writer: [...document.querySelectorAll('#lm-writer option')].map(o => o.textContent),
      hosted: [...document.querySelectorAll('#hm-director option')].map(o => o.textContent),
      director: document.querySelector('#lm-director').value,
      kept: (document.querySelector('#qa-global') || {dataset: {}}).dataset.keep, typed: (document.querySelector('#qa-global') || {}).value,
      howto: (document.querySelector('#local-howto') || {}).textContent || '',
      errHidden: !!(document.querySelector('#local-error') || {}).hidden })""")
    if not late["errHidden"]:
        failures.append("the late fill left an empty 'could not read the model list' line showing")
    if "tale-7b" not in late["writer"] or "embed-x" in late["writer"]:
        failures.append(f"the late list should offer chat models only: {late['writer']}")
    if late["hosted"][:1] != ["(use the hosted model)"] or "tale-7b" not in late["hosted"]:
        failures.append(f"the late fill lost the '(use the hosted model)' row or the model: {late['hosted']}")
    if director_before and late["director"] != director_before:
        failures.append(f"the late fill changed the configured Director: {director_before!r} -> {late['director']!r}")
    if late["kept"] != "1" or late["typed"] != "typed while loading":
        failures.append(f"the late fill repainted the page or wiped what was typed: {late}")
    if "Step one" not in late["howto"]:
        failures.append("the late fill did not bring the how-to steps")
    no_dashes("Settings after the late list", page.inner_text("#view"))
    page.unroute("**/api/models/local")
    print("20) Settings paints before the model list, fills it in later and keeps what was typed; Save stays in view")

    # 21) A Settings page with unsaved edits asks before it is left (a topbar click, the browser Back button), keeps the
    #     page and the edits on Stay, and leaves on Leave. Navigation made the router repaint from the server, which
    #     threw the edits away without a word.
    asked_hash = []
    page.evaluate("history.back()")                                  # the browser Back button: the Library entry
    try:
        page.wait_for_selector("#cm-yes", timeout=3000)
        page.click("#cm-no")
        page.wait_for_function("document.querySelector('#modal-root').classList.contains('hidden')", timeout=3000)
    except Exception:  # noqa: BLE001
        failures.append("Back from Settings with unsaved edits did not ask")
    back = page.evaluate("({hash: location.hash, kept: (document.querySelector('#qa-global') || {dataset: {}}).dataset.keep})")
    if back["hash"] != "#settings" or back["kept"] != "1":
        failures.append(f"Stay after Back did not keep the page and the hash: {back}")
    unload_js = "(() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; })()"
    if not page.evaluate(unload_js):
        failures.append("closing the tab with unsaved Settings edits did not ask the browser to confirm")
    page.click('#topbar nav a[href="#characters"]')
    try:
        page.wait_for_selector("#cm-yes", timeout=3000)
        title_text = page.evaluate("document.querySelector('#modal-card h2').textContent")
        if "Leave without saving" not in title_text:
            failures.append("the leave question has the wrong title: " + title_text)
        page.click("#cm-no")                                         # Stay
        page.wait_for_function("document.querySelector('#modal-root').classList.contains('hidden')", timeout=3000)
    except Exception:  # noqa: BLE001
        failures.append("a topbar click away from Settings with unsaved edits did not ask")
    stayed = page.evaluate("""({hash: location.hash, kept: (document.querySelector('#qa-global') || {dataset: {}}).dataset.keep,
      typed: (document.querySelector('#qa-global') || {}).value, active: (document.querySelector('#topbar nav a.active') || {}).textContent})""")
    if stayed["hash"] != "#settings" or stayed["kept"] != "1" or stayed["typed"] != "typed while loading":
        failures.append(f"Stay did not keep the page, the hash and the edits: {stayed}")
    if (stayed["active"] or "").strip() != "Settings":
        failures.append(f"Stay left the wrong topbar link highlighted: {stayed['active']!r}")
    # two navigations before the first question is answered: the second replaces the first question and is the one decided
    page.evaluate("location.hash = '#characters'")
    page.wait_for_selector("#cm-yes", state="visible", timeout=3000)
    page.evaluate("location.hash = '#defaults'")
    page.wait_for_timeout(300)
    page.click("#cm-yes")                                            # Leave
    try:
        page.wait_for_function("location.hash === '#defaults' && !document.querySelector('#save-settings')", timeout=6000)
    except Exception:  # noqa: BLE001
        failures.append("Leave did not leave Settings for the last page asked for: " + page.evaluate("location.hash"))
    print("21) leaving Settings with unsaved edits asks; Stay keeps the page and the edits, Leave goes")

    # 22) A clean Settings page, and one that was just saved, leave without a question. The profile name box and the rain
    #     switch are not settings edits. A segmented button (reply length) is one: it raises no input event.
    def leave_via_topbar():
        page.click('#topbar nav a[href="#characters"]')
        try:
            page.wait_for_function("location.hash === '#characters' && !document.querySelector('#save-settings')", timeout=6000)
        except Exception:  # noqa: BLE001
            return False
        return True

    def modal_open():
        return page.evaluate("!document.querySelector('#modal-root').classList.contains('hidden')")

    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#save-settings", timeout=8000)
    page.fill("#pf-name", "just a profile name")
    if page.evaluate(unload_js):
        failures.append("closing the tab asked for confirmation on a Settings page with no edits")
    page.evaluate("document.querySelector('#pf-list').dispatchEvent(new Event('input', {bubbles: true}))")
    if page.locator("#ap-rain").count():
        page.evaluate("document.querySelector('#ap-rain').click(); document.querySelector('#ap-rain').click()")
    if not leave_via_topbar() or modal_open():
        failures.append("typing a profile name or flipping the rain switch counted as an unsaved settings edit")
    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#save-settings", timeout=8000)
    page.click("#len-seg button:not(.on)")
    page.click('#topbar nav a[href="#characters"]')
    try:
        page.wait_for_selector("#cm-yes", state="visible", timeout=3000)
        page.click("#cm-yes")
        page.wait_for_function("location.hash === '#characters' && !document.querySelector('#save-settings')", timeout=6000)
    except Exception:  # noqa: BLE001
        failures.append("changing the reply length (a segmented button) was not counted as an unsaved edit")
    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#save-settings", timeout=8000)
    page.fill("#qa-global", "Look around\nWait and listen")
    page.click("#save-settings")
    try:
        page.wait_for_function("/Saved|error/.test((document.querySelector('#save-status') || {}).textContent || '')", timeout=6000)
    except Exception:  # noqa: BLE001
        failures.append("Save & apply gave no answer")
    saved_text = page.inner_text("#save-status")
    if "Saved" not in saved_text:
        failures.append(f"Save & apply did not save in the sandbox, so 'a saved page leaves freely' is untested: {saved_text!r}")
    if not leave_via_topbar() or modal_open():
        failures.append("a Settings page that was just saved still asked 'leave without saving'")
    print("22) a clean or a saved Settings page leaves without a question; a segmented button counts as an edit")

    # 23) The model list failing used to break the whole Settings page ("Something broke"). It now says so on the page.
    page.route("**/api/models/local", lambda route: route.fulfill(
        status=400, content_type="application/json", body=json.dumps({"detail": "the model server said no"})))
    page.evaluate("location.hash = '#settings'")
    try:
        page.wait_for_selector("#save-settings", timeout=8000)
        err = page.evaluate("""() => { const e = document.querySelector('#local-error');
          return {hidden: !e || e.hidden, text: e ? e.textContent : ''}; }""")
        if err["hidden"] or "could not read the model list" not in err["text"] or "the model server said no" not in err["text"]:
            failures.append(f"a failed model list was not reported on the Settings page: {err}")
    except Exception:  # noqa: BLE001
        failures.append("a failed model list broke the Settings page: " + page.inner_text("#view")[:120])
    no_dashes("Settings with a failed model list", page.inner_text("#view"))
    page.unroute("**/api/models/local")
    print("23) a failed model list is reported on the Settings page, which still works")

    # 24) The list can also FAIL after the page has painted: the line appears then, not only at first paint.
    #     (The page before this one is Settings: wait for it to be GONE, or "Save is on screen" is satisfied by the old page
    #     and the answer arrives before the new page has painted, which is not the case under test.)
    page.evaluate("import('/js/nav.js').then(n => { n.invalidateReady(); n.skipReadyCheck(); })")   # the Library, not the first-run probe
    page.evaluate("location.hash = '#library'")
    page.wait_for_function("!document.querySelector('#save-settings')", timeout=6000)
    held_late = []
    page.route("**/api/models/local", lambda route: held_late.append(route))
    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#save-settings", timeout=6000)
    wait_until_held(page, held_late, "model list")
    if "Looking for" not in page.inner_text("#installed-note"):
        failures.append("case 24 did not start from a page that had painted before the model list arrived")
    for route in held_late:
        route.fulfill(status=400, content_type="application/json", body=json.dumps({"detail": "gone after the paint"}))
    held_late.clear()
    try:
        page.wait_for_function("(() => { const e = document.querySelector('#local-error'); return e && !e.hidden && e.textContent.includes('gone after the paint'); })()",
                               timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append("a model list that failed after the paint was not reported on the page")
    if not re.search(r"not\s+running", page.evaluate("(document.querySelector('#names-warn') || {}).textContent || ''")):
        failures.append("a model list that failed after the paint did not bring the 'server is not running' warning")
    page.unroute("**/api/models/local")
    print("24) a model list that fails after the page painted is reported on it")

    # 25) Leave Settings before the list arrives: the late answer must find the page gone and do nothing (it used to be
    #     free to throw on the missing note, which is a console error and a lost promise).
    page.evaluate("import('/js/nav.js').then(n => { n.invalidateReady(); n.skipReadyCheck(); })")   # the Library, not the first-run probe
    page.evaluate("location.hash = '#library'")
    page.wait_for_function("!document.querySelector('#save-settings')", timeout=6000)
    held_gone = []
    page.route("**/api/models/local", lambda route: held_gone.append(route))
    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#save-settings", timeout=6000)
    wait_until_held(page, held_gone, "model list")
    if "Looking for" not in page.inner_text("#installed-note"):
        failures.append("case 25 did not start from a page that had painted before the model list arrived")
    page.evaluate("location.hash = '#characters'")
    page.wait_for_function("!document.querySelector('#save-settings')", timeout=6000)
    before = len(errors)
    for route in held_gone:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"installed": [], "suggestions": [], "howto": [], "server": "Ollama"}))
    held_gone.clear()
    page.wait_for_timeout(500)
    if len(errors) != before:
        failures.append(f"a model list that arrived after Settings was left threw: {errors[before:]}")
        del errors[before:]                       # reported here, once
    page.unroute("**/api/models/local")
    print("25) a model list that arrives after Settings was left does nothing")

    # 26) A Settings page that fails to repaint must not leave its guard behind (it would ask 'leave without saving' on the
    #     error page, about edits that are no longer there).
    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#save-settings", timeout=8000)
    page.fill("#qa-global", "an edit that the failed repaint discards")
    page.route("**/api/settings", lambda route: route.fulfill(
        status=400, content_type="application/json", body=json.dumps({"detail": "settings unreadable"})))
    page.evaluate("import('/js/app.js').then(m => m.render())")
    try:
        page.wait_for_function("((document.querySelector('#view h1') || {}).textContent || '').includes('Something broke')", timeout=6000)
    except Exception:  # noqa: BLE001
        failures.append("the failed Settings repaint did not show the error page: " + page.inner_text("#view")[:100])
    page.unroute("**/api/settings")
    page.click('#topbar nav a[href="#library"]')
    page.wait_for_timeout(600)
    if modal_open() or page.evaluate("location.hash") != "#library":
        failures.append("the error page asked 'leave without saving' about a Settings page that was already gone")
    print("26) a Settings page that failed to repaint leaves no leave-guard behind")

    # 27) "Test connection" in Settings (the hosted panel): it sends what is typed (blank fields fall back to the saved values
    #     on the server), shows the answer in words, shows a failed request as such, and is not an unsaved edit.
    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#save-settings", timeout=8000)
    page.evaluate("document.querySelector('#panel-hosted').classList.remove('hidden')")     # the panel shows in hosted mode
    sent = []
    answers = {"body": {"ok": False, "reason": "rejected", "detail": "api.example.test answered, but it did not accept this key."}, "status": 200}

    def answer_test(route):
        sent.append(route.request.post_data)
        route.fulfill(status=answers["status"], content_type="application/json", body=json.dumps(answers["body"]))

    page.route("**/api/connection/test", answer_test)
    page.click("#hm-test")
    page.wait_for_function("document.querySelector('#hm-test-status').textContent.includes('did not accept')", timeout=4000)
    first = json.loads(sent[0])
    on_page = page.evaluate("({base: document.querySelector('#hm-base').value, model: document.querySelector('#hm-model').value})")
    if first != {"base_url": on_page["base"], "api_key": "", "model": on_page["model"]}:
        failures.append(f"Test connection did not send what is on the page: {first} vs {on_page}")
    if page.evaluate("document.querySelector('#hm-test').disabled"):
        failures.append("Test connection stayed disabled after the answer")
    if page.evaluate(unload_js):
        failures.append("pressing Test connection counted as an unsaved settings edit")
    answers["body"] = {"ok": True, "reason": "connected", "detail": "Connected to api.example.test."}
    page.click("#hm-test")
    page.wait_for_function("document.querySelector('#hm-test-status').textContent.startsWith('Connected')", timeout=4000)
    if page.evaluate("document.querySelector('#hm-test-status').style.color") != "var(--ok)":
        failures.append("a good connection is not shown as good")
    answers["status"], answers["body"] = 400, {"detail": "the test route refused"}
    page.click("#hm-test")
    page.wait_for_function("document.querySelector('#hm-test-status').textContent.startsWith('Could not run the test')", timeout=4000)
    if "the test route refused" not in page.inner_text("#hm-test-status"):
        failures.append("a failed test request did not say why: " + page.inner_text("#hm-test-status"))
    answers["status"], answers["body"] = 200, {"ok": True, "reason": "connected", "detail": "Connected to api.example.test."}
    page.fill("#hm-key", "sk-typed-key-for-the-test")
    page.click("#hm-test")
    page.wait_for_function("document.querySelector('#hm-test-status').textContent.startsWith('Connected')", timeout=4000)
    if json.loads(sent[-1]).get("api_key") != "sk-typed-key-for-the-test":
        failures.append(f"the typed key was not sent to the test: {sent[-1]}")
    page.unroute("**/api/connection/test")
    page.click('#topbar nav a[href="#characters"]')               # the typed key is an edit: leave through the question
    page.wait_for_selector("#cm-yes", state="visible", timeout=3000)
    page.click("#cm-yes")
    page.wait_for_function("location.hash === '#characters' && !document.querySelector('#save-settings')", timeout=6000)
    print("27) Test connection sends what is typed, says what happened and is not an unsaved edit")

    # 28) First run, "Use an API key": the button said "Checking..." and checked nothing. The key is tried against the
    #     provider's model list BEFORE it is saved. A refused or unreachable key is not saved; the same button then reads
    #     "Save anyway". A good answer, or a provider with no model list, saves at once.
    saves, tests = [], []
    outcome = {"reason": "rejected", "ok": False}

    def fake_test(route):
        tests.append(route.request.post_data)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": outcome["ok"], "reason": outcome["reason"], "detail": "the provider said so."}))

    def fake_save(route):
        if route.request.method == "PUT":
            saves.append(route.request.post_data)
            route.fulfill(status=200, content_type="application/json", body="{}")
        else:
            route.continue_()

    def first_run():
        saves.clear()
        tests.clear()
        page.evaluate("import('/js/welcome.js').then(m => m.renderWelcome({ok: false, reason: 'no_key'}))")
        page.wait_for_selector("#w-key", timeout=6000)
        for _ in range(8):             # a repaint left over from the previous save can empty the box: type until it holds
            page.fill("#w-key", "sk-first-run-key")
            page.wait_for_timeout(200)
            if page.input_value("#w-key") == "sk-first-run-key":
                break

    page.route("**/api/connection/test", fake_test)
    page.route("**/api/settings", fake_save)
    # Every saved key ends in a render() that asks /api/ready. On a box with no model server that probe takes seconds, and a
    # render that finishes late repaints whatever view is open by then: answer it at once, so none is left pending.
    page.route("**/api/ready", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok": true}'))
    first_run()
    page.click("#w-use-hosted")
    page.wait_for_function("document.querySelector('#w-use-hosted').textContent === 'Save anyway'", timeout=4000)
    note = page.inner_text("#w-hosted-note")
    sent_test = json.loads(tests[0])
    if "the provider said so." not in note or "save it anyway" not in note:
        failures.append(f"a refused key was not explained on the first-run screen: {note!r}")
    if saves:
        failures.append("a key the provider refused was saved on the first press")
    if sent_test.get("api_key") != "sk-first-run-key" or not sent_test.get("base_url"):
        failures.append(f"the first-run check did not test the typed key against the preset: {sent_test}")
    page.click("#w-use-hosted")                                       # Save anyway
    page.wait_for_timeout(600)
    if len(saves) != 1 or json.loads(saves[0]).get("hosted", {}).get("api_key") != "sk-first-run-key" or len(tests) != 1:
        failures.append(f"'Save anyway' did not save once without testing again: saves={len(saves)} tests={len(tests)}")
    for ok, reason in ((True, "connected"), (False, "no_model_list")):
        outcome.update(ok=ok, reason=reason)
        first_run()
        page.click("#w-use-hosted")
        page.wait_for_timeout(600)
        if len(saves) != 1:
            failures.append(f"a {reason} answer should save at once: saves={len(saves)}")
    outcome.update(ok=False, reason="unreachable")
    first_run()
    page.click("#w-use-hosted")
    page.wait_for_function("document.querySelector('#w-use-hosted').textContent === 'Save anyway'", timeout=4000)
    if page.locator("#w-preset option").count() < 2:
        failures.append("the first-run screen offers one provider, so 'a new provider re-arms the check' cannot be tested")
    else:
        page.select_option("#w-preset", index=1)
        if page.inner_text("#w-use-hosted") != "Save and start":
            failures.append("changing the provider kept the 'Save anyway' label of the previous one")
        tests_before = len(tests)
        page.click("#w-use-hosted")
        page.wait_for_function("document.querySelector('#w-use-hosted').textContent === 'Save anyway'", timeout=4000)
        if len(tests) != tests_before + 1 or saves:
            failures.append(f"a different provider was saved without being tried: tests {len(tests)} (was {tests_before}), saves {len(saves)}")
    page.unroute("**/api/connection/test")
    page.unroute("**/api/settings")
    page.evaluate("location.hash = '#library'")                      # (often already there, so this alone repaints nothing)
    page.evaluate("import('/js/app.js').then(m => m.render())")      # the Library, now that readiness is answered
    page.wait_for_function("!document.querySelector('#w-key')", timeout=8000)
    page.wait_for_timeout(500)
    page.unroute("**/api/ready")
    print("28) the first-run key is tried before it is saved; a refused key is not saved, and 'Save anyway' is explicit")

    # 29) Retry keeps what it replaces, and a failed or stopped retry or swipe puts the exchange back (D-057). Driven through the
    #     real routes and engine with a stub Writer (the server runs in this process).
    from srv import core as srv_core

    class Writer:
        model = "stub-writer"

        def __init__(self, *replies):
            self.replies = list(replies)

        def complete(self, messages, **k):
            return ""

        def stream(self, messages, **k):
            r = self.replies.pop(0) if self.replies else "A default version."
            if callable(r):
                r = r()
            if isinstance(r, BaseException):
                raise r
            yield from ([r] if isinstance(r, str) else r)

    def slow_until_stopped():
        def go():
            yield "A first half that never lands. "
            for _ in range(60):                               # six seconds at most, and only until Stop is pressed
                if srv_core._cancel.is_set():
                    break
                time.sleep(0.1)
            yield "A second half."
        return go()

    srv_core._cfg.generation["chapter_outline"] = False
    srv_core._cfg.generation["trinity_brain"] = False
    engine29 = server._engine(slug)
    page.evaluate("location.hash = '#library'")
    page.wait_for_function("!document.querySelector('#save-settings')", timeout=6000)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#retry", timeout=8000)
    tail_js = "(() => { const t = [...document.querySelectorAll('#transcript .turn .turn-body')]; return t.map(x => x.textContent.trim()); })()"
    bar_js = "(() => { const b = document.querySelector('.swipebar span'); return b ? b.textContent.trim() : ''; })()"
    before_turns = page.evaluate(tail_js)
    if len(before_turns) < 2:
        failures.append(f"case 29 needs a story with an exchange to retry: {before_turns}")
    old_tail = before_turns[-1]
    engine29.llm = Writer("A freshly written version of the last reply.")
    page.click("#retry")
    page.wait_for_function("document.querySelector('.swipebar span') && document.querySelector('.swipebar span').textContent.includes('of 2')", timeout=8000)
    now = page.evaluate(tail_js)
    if now[-1] != "A freshly written version of the last reply." or len(now) != len(before_turns):
        failures.append(f"a good retry did not replace the last reply in place: {now}")
    if "Version 2 of 2" not in page.evaluate(bar_js):
        failures.append(f"a good retry did not say it kept the old text as a version: {page.evaluate(bar_js)!r}")
    if "kept until your next move" not in (page.evaluate("document.querySelector('.swipebar span').title") or ""):
        failures.append("the version label does not say how long earlier versions are kept")
    page.evaluate("location.hash = '#library'")                      # leave and come back: the version showing is the server's
    page.wait_for_function("!document.querySelector('#retry')", timeout=6000)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#retry", timeout=8000)
    if "Version 2 of 2" not in page.evaluate(bar_js):
        failures.append(f"coming back to the story lost which version was showing: {page.evaluate(bar_js)!r}")
    page.click(".swipebar .swl")
    page.wait_for_function("document.querySelector('.swipebar span').textContent.includes('Version 1 of 2')", timeout=6000)
    if page.evaluate(tail_js)[-1] != old_tail:
        failures.append("going back to Version 1 did not show the text the retry replaced")
    # a model error: the exchange is back, the reader is told, nothing is lost
    shown = page.evaluate(tail_js)
    engine29.llm = Writer(ConnectionError("connection refused"))
    page.click("#retry")
    page.wait_for_selector(".turn-error", timeout=8000)
    card = page.inner_text(".turn-error")
    if "Your earlier version is back" not in card:
        failures.append(f"a failed retry did not tell the reader their earlier version is back: {card!r}")
    if page.evaluate(tail_js) != shown:
        failures.append(f"a failed retry changed the story on screen: {page.evaluate(tail_js)}")
    if page.evaluate("fetch('/api/saves/%s').then(r => r.json()).then(j => j.turns.map(t => t.text))" % slug) != shown:
        failures.append("a failed retry changed the SAVED story")
    # an empty reply
    engine29.llm = Writer("")
    page.click("#retry")
    page.wait_for_function("[...document.querySelectorAll('.turn-error')].some(e => e.textContent.includes('Nothing new came back'))", timeout=8000)
    if page.evaluate(tail_js) != shown:
        failures.append("an empty retry made the story shorter")
    # Stop during a retry
    engine29.llm = Writer(slow_until_stopped)
    page.click("#retry")
    page.wait_for_function("!document.querySelector('#stop').classList.contains('hidden')", timeout=6000)
    page.wait_for_timeout(400)
    page.click("#stop")
    page.wait_for_function("[...document.querySelectorAll('.turn-note')].some(e => e.textContent.includes('Your earlier version is back'))", timeout=10000)
    if page.evaluate(tail_js) != shown:
        failures.append(f"Stop during a retry lost the exchange: {page.evaluate(tail_js)}")
    page.wait_for_function("!document.querySelector('#send').disabled", timeout=6000)
    engine29.llm = Writer(slow_until_stopped)
    page.click("#retry")                                              # the next run clears the note of this one
    page.wait_for_function("!document.querySelector('#stop').classList.contains('hidden')", timeout=6000)
    if page.evaluate("document.querySelectorAll('.turn-note').length"):
        failures.append("a retry started with the previous run's Stopped note still on screen")
    page.wait_for_timeout(400)
    page.click("#stop")
    page.wait_for_function("[...document.querySelectorAll('.turn-note')].some(e => e.textContent.includes('Your earlier version is back'))", timeout=10000)
    # swipe forward past the end writes a new version, with a Stop that is safe
    page.wait_for_function("!document.querySelector('#send').disabled", timeout=6000)
    engine29.llm = Writer(slow_until_stopped)
    page.click(".swipebar .swr")                                    # Version 1 of 2: this only browses to Version 2 ...
    page.wait_for_function("document.querySelector('.swipebar span').textContent.includes('Version 2 of 2')", timeout=6000)
    page.click(".swipebar .swr")                                    # ... and this one, at the end, writes a new one
    page.wait_for_function("!document.querySelector('#stop').classList.contains('hidden')", timeout=6000)
    if page.evaluate("document.querySelectorAll('.turn-note').length"):
        failures.append("the Stopped note of the previous run was still on screen when the next run started")
    page.wait_for_timeout(400)
    page.click("#stop")
    page.wait_for_function("[...document.querySelectorAll('.turn-note')].some(e => e.textContent.includes('Your earlier version is back'))", timeout=10000)
    after_stop = page.evaluate(tail_js)
    if len(after_stop) != len(shown) or after_stop[-1] != "A freshly written version of the last reply.":
        failures.append(f"Stop during swipe-generate lost or changed the exchange: {after_stop}")
    page.wait_for_function("!document.querySelector('#send').disabled", timeout=6000)
    engine29.llm = Writer("A third version, written by the swipe.")
    page.click(".swipebar .swr")
    page.wait_for_function("document.querySelector('.swipebar span') && document.querySelector('.swipebar span').textContent.includes('of 3')", timeout=8000)
    if page.evaluate(tail_js)[-1] != "A third version, written by the swipe.":
        failures.append("swipe-generate did not write the third version")
    # leave mid-swipe and come back: the same promise as for a turn (D-056 item 5), now that a swipe sets the run state too
    page.wait_for_function("!document.querySelector('#send').disabled", timeout=6000)
    engine29.llm = Writer(slow_until_stopped)
    page.click(".swipebar .swr")                                    # at the last version: writes a fourth
    page.wait_for_function("!document.querySelector('#stop').classList.contains('hidden')", timeout=6000)
    page.wait_for_timeout(300)
    page.evaluate("location.hash = '#library'")
    page.wait_for_function("!document.querySelector('#retry')", timeout=6000)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#retry", timeout=8000)
    back_in = page.evaluate("""() => ({stage: document.querySelector('#stageline').textContent,
      stop: !document.querySelector('#stop').classList.contains('hidden'), sendOff: document.querySelector('#send').disabled})""")
    if "Still generating" not in back_in["stage"] or not back_in["stop"] or not back_in["sendOff"]:
        failures.append(f"coming back to a story whose swipe is generating: {back_in}")
    # Make the repaint from the store slow (700 ms). The controls must not come back before it lands: with the old order Send
    # was live over the stale transcript for exactly that long, and this case failed about one run in ten by timing alone.
    page.evaluate("""() => { const f = window.fetch.bind(window); window.__realFetch = window.fetch;
      window.fetch = (u, o) => (typeof u === 'string' && /^\\/api\\/saves\\/[^/]+$/.test(u) && (!o || !o.method || o.method === 'GET'))
        ? new Promise(r => setTimeout(r, 700)).then(() => f(u, o)) : f(u, o); }""")
    page.click("#stop")
    try:
        page.wait_for_function("!document.querySelector('#send').disabled && document.querySelector('#stop').classList.contains('hidden')", timeout=10000)
    except Exception:  # noqa: BLE001
        failures.append("the re-entered view never took over when the swipe ended: " + repr(page.evaluate(
            "({send: document.querySelector('#send').disabled, stage: document.querySelector('#stageline').textContent})")))
    if page.evaluate(tail_js)[-1] != "A third version, written by the swipe.":
        failures.append(f"a swipe stopped from another visit lost the exchange, or Send came back before the repaint: {page.evaluate(tail_js)}")
    page.evaluate("() => { window.fetch = window.__realFetch; }")
    print("29) retry keeps the old text as a version; a failed, empty or stopped retry or swipe puts the exchange back and says so")

    # --- D-056 item 9: the accessibility remainder ------------------------------------------------------------------
    # 30) A segmented control said which choice was current by a colour only. The "on" class is mirrored into aria-pressed.
    def pressed_all_match(root):
        return (f"(() => {{ const bs = [...document.querySelectorAll('{root} .seg button')]; return bs.length > 0 && "
                f"bs.every(b => b.getAttribute('aria-pressed') === String(b.classList.contains('on'))); }})()")

    page.evaluate("location.hash = '#settings'")
    page.wait_for_selector("#len-seg", timeout=10000)
    try:
        page.wait_for_function(pressed_all_match("#view"), timeout=5000)
    except Exception:  # noqa: BLE001
        failures.append("the segmented buttons on Settings do not carry an aria-pressed that matches the one that is on: "
                        + repr(page.evaluate("[...document.querySelectorAll('#view .seg button')].map(b => [b.classList.contains('on'), b.getAttribute('aria-pressed')])")))
    # the Author's note dialog flips the class in place (no repaint), so this is the path a later change has to follow
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    page.click("#note-btn")
    page.wait_for_selector("#an-depth", timeout=6000)
    try:
        page.wait_for_function(pressed_all_match("#modal-card"), timeout=5000)
        page.click("#an-depth button:not(.on)")
        page.wait_for_function(pressed_all_match("#modal-card")
                               + " && document.querySelectorAll('#an-depth button[aria-pressed=true]').length === 1", timeout=5000)
    except Exception:  # noqa: BLE001
        failures.append("a segmented button's pressed state did not follow the choice: "
                        + repr(page.evaluate("[...document.querySelectorAll('#an-depth button')].map(b => [b.classList.contains('on'), b.getAttribute('aria-pressed')])")))
    close_modal()
    # markup that is already there when a root starts being watched (the Talk drawer is built that way) is synced at once
    early = page.evaluate("""async () => { const m = await import('/js/a11y.js'); const d = document.createElement('div');
        d.innerHTML = '<div class="seg"><button class="on">A</button><button>B</button></div>'; document.body.appendChild(d);
        m.watchLabels(d); const r = [...d.querySelectorAll('button')].map(b => b.getAttribute('aria-pressed')); d.remove(); return r; }""")
    if early != ["true", "false"]:
        failures.append(f"segmented buttons already on the page when a root is watched are not synced at once: {early}")
    print("30) segmented buttons say which one is pressed, and follow the choice")

    # 31) A route change replaced the page under the reader's focus, which fell to <body>: nothing was announced and a keyboard
    #     user had to Tab from the top again. Focus now lands in the new page, and is left alone when a view or a dialog has it.
    page.evaluate("location.hash = '#library'")
    page.wait_for_function("document.querySelector('#view h1, #view h2')", timeout=8000)
    page.wait_for_timeout(300)
    page.evaluate("location.hash = '#characters'")
    page.wait_for_selector("#lib-types", timeout=8000)
    in_view_js = ("(() => { const a = document.activeElement; const v = document.querySelector('#view');"
                  " return !!a && a !== document.body && v.contains(a) || a === v; })()")
    try:
        page.wait_for_function(in_view_js, timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append("after a route change focus is on "
                        + repr(page.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.tagName)"))
                        + ", not in the new page")
    if page.evaluate("document.activeElement.matches('h1, h2') && document.activeElement.getAttribute('tabindex') !== '-1'"):
        failures.append("the heading that took focus is a Tab stop (it should take programmatic focus only)")
    # a dialog that is open keeps the focus it has: the route change must not pull it out from under the reader
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#note-btn", timeout=8000)
    page.click("#note-btn")
    page.wait_for_selector("#an-depth", timeout=6000)
    page.evaluate("location.hash = '#library'")
    page.wait_for_function("document.querySelector('#view h1, #view h2') && !document.querySelector('#note-btn')", timeout=8000)
    page.wait_for_timeout(400)
    if not page.evaluate("document.querySelector('#modal-card').contains(document.activeElement)"):
        failures.append("a route change pulled focus out of an open dialog: "
                        + repr(page.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.tagName)")))
    close_modal()
    print("31) a route change moves focus into the new page, and leaves an open dialog's focus alone")

    # 32) The kind of a toast was only the colour of its left border. It now has a glyph for the eye and a word for the ear.
    for kind, word, glyph in (("error", "Error", "!"), ("ok", "Done", "✓"), ("info", "Note", "i")):
        got = page.evaluate("""async (k) => { const m = await import('/js/util.js'); m.toast('A sample message', k);
            const t = document.querySelector('#toast'); const mark = t.querySelector('.toast-mark');
            const hidden = t.querySelector('.sr-only');
            return {text: t.textContent, mark: mark && mark.textContent, ariaHidden: mark && mark.getAttribute('aria-hidden'),
                    spoken: hidden && hidden.textContent, spokenWidth: hidden && getComputedStyle(hidden).width, cls: t.className}; }""", kind)
        if got["mark"] != glyph or got["ariaHidden"] != "true":
            failures.append(f"a {kind} toast has no glyph for the eye (mark {got['mark']!r}, aria-hidden {got['ariaHidden']!r})")
        if got["spoken"] != f"{word}: " or got["spokenWidth"] != "1px":
            failures.append(f"a {kind} toast has no word for the ear, or it is shown on screen: {got['spoken']!r} at {got['spokenWidth']}")
        if "A sample message" not in got["text"] or not got["cls"].startswith(kind):
            failures.append(f"a {kind} toast lost its message or its class: {got}")
        no_dashes(f"the {kind} toast", got["text"])
    page.evaluate("document.querySelector('#toast').className = ''")
    print("32) a toast's kind is a glyph and a word, not a colour")

    # 33) Every visible button has a name made of letters or digits (its text or an aria-label): the pencil on each turn, the
    #     draft button, the close buttons. A bare glyph is read as the picture it is, or not at all.
    nameless_js = """(root) => [...root.querySelectorAll('button, [role=button], a[href]')].filter(b => b.offsetParent !== null)
      .filter(b => !/[A-Za-z0-9]/.test(b.getAttribute('aria-label') || b.textContent || ''))
      .map(b => b.id || b.className || b.tagName)"""
    for view in VIEWS:
        page.evaluate(f"location.hash = {view!r}")
        page.wait_for_timeout(700)
        if view == "#settings":
            page.wait_for_selector("#len-seg", timeout=10000)
        nameless = page.evaluate(f"({nameless_js})(document.querySelector('#view'))")
        if nameless:
            failures.append(f"{view}: buttons with no name: {nameless[:6]}")
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    for btn in ("note-btn", "mem-btn", "ctx-btn", "plan-btn", "canon-btn", "aids-btn"):
        page.click(f"#{btn}")
        page.wait_for_selector("#modal-root:not(.hidden) #modal-card h1, #modal-root:not(.hidden) #modal-card h2", timeout=8000)
        page.wait_for_timeout(150)                      # the names are added shortly after a dialog paints
        nameless = page.evaluate(f"({nameless_js})(document.querySelector('#modal-card'))")
        if nameless:
            failures.append(f"the {btn} dialog: buttons with no name: {nameless[:6]}")
        unnamed_fields = page.evaluate("""() => [...document.querySelectorAll('#modal-card input:not([type=hidden]):not([type=checkbox]):not([type=radio]), #modal-card textarea, #modal-card select')]
          .filter(el => el.offsetParent !== null && !(el.labels && el.labels.length) && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby'))
          .map(el => el.id || el.className || el.type)""")
        if unnamed_fields:
            failures.append(f"the {btn} dialog: fields with no name: {unnamed_fields[:6]}")
        close_modal()
    page.evaluate(f"location.hash = '#world/{scen}'")
    page.wait_for_selector("[data-newpiece='characters.md']", timeout=8000)
    page.click("[data-newpiece='characters.md']")
    page.wait_for_selector(".chip-in", timeout=4000)
    page.fill(".chip-in", "brave")
    page.press(".chip-in", "Enter")
    chip_label = page.evaluate("(document.querySelector('.chip-tag button') || {getAttribute: () => null}).getAttribute('aria-label')")
    if chip_label != "Remove brave":
        failures.append(f"a chip's remove button is named {chip_label!r}, not by the chip it removes")
    close_modal()
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    labels = page.evaluate("[...document.querySelectorAll('.turn-edit')].map(b => b.getAttribute('aria-label'))")
    if len(set(labels)) < 2 or not all(labels):
        failures.append(f"the pencils on the turns are not named by whose turn it is: {labels}")
    print("33) every visible button has a name")

    # 34) The Talk drawer lives on <body>, outside everything a11y.js watched: its select, its input and its close button had
    #     no name, and a field added to it later would never get one.
    page.evaluate("""async (s) => { const m = await import('/js/play.js'); m.talkDrawer(s, ['Mira', 'Odo']); }""", slug)
    page.wait_for_selector("#talk-drawer", timeout=4000)
    page.evaluate("""() => { const i = document.createElement('input'); i.id = 'talk-later'; i.placeholder = 'A later field';
                             document.querySelector('#talk-drawer').appendChild(i); }""")
    try:
        page.wait_for_function("document.querySelector('#talk-later').getAttribute('aria-label') === 'A later field'", timeout=3000)
    except Exception:  # noqa: BLE001
        failures.append("a field added to the Talk drawer was never named (the drawer is not watched)")
    drawer = page.evaluate("""() => { const d = document.querySelector('#talk-drawer');
        const name = e => e && (e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].textContent) || '');
        return {role: d.getAttribute('role'), label: d.getAttribute('aria-label'), who: name(d.querySelector('#talk-who')),
                input: name(d.querySelector('#talk-input')), close: name(d.querySelector('#talk-close')),
                log: d.querySelector('#talk-log').getAttribute('role')}; }""")
    if not (drawer["role"] and drawer["label"] and drawer["who"] and drawer["input"] and drawer["close"] and drawer["log"] == "log"):
        failures.append(f"the Talk drawer is missing names or roles: {drawer}")
    page.evaluate("document.getElementById('talk-drawer') && document.getElementById('talk-drawer').remove()")
    print("34) the Talk drawer is named and watched")

    # 35) An AI answer for a piece form must not land in another piece. The model answers a moment later; by then the dialog can
    #     be closed and a DIFFERENT piece's form open in the same host with the same element ids, and the answer was written
    #     into it (and its buttons re-labelled). It is dropped now, and the reader is told. Both buttons that ask the model:
    #     "Improve with AI" (an existing piece) and "Seed from idea" (a new one).
    page.evaluate(f"location.hash = '#world/{scen}'")
    page.wait_for_selector("[data-newpiece]", timeout=8000)
    rels = page.evaluate("[...document.querySelectorAll('[data-newpiece]')].map(b => b.dataset.newpiece)")
    first, second = rels[0], next(r for r in rels if r != rels[0])
    answer = '{"entry": {"title": "AI Answer For Another Piece", "importance": 3, "aliases": [], "attrs": {}, "body": "x"}}'

    def ask_seed():
        page.click("#p-seed")
        page.fill("#p-idea", "a grim ferryman")
        page.click("#p-seed-go")

    def late_answer_case(label, open_first, ask):
        page.evaluate(f"location.hash = '#world/{scen}'")
        page.wait_for_selector("[data-newpiece]", timeout=8000)
        open_first()
        held35 = []
        page.route("**/api/assist", lambda route: held35.append(route))
        ask()
        wait_until_held(page, held35, label)
        close_modal()
        page.click(f"[data-newpiece='{second}']")
        page.wait_for_selector("#p-title", timeout=4000)
        page.fill("#p-title", "Piece Two")
        if label == "seed":
            # the form that is open now has a request of its own in flight: the OLD answer must not reset its buttons
            ask_seed()
            for _ in range(80):
                if len(held35) >= 2:
                    break
                page.wait_for_timeout(100)
            else:
                failures.append("the second seed request never reached the stub")
        before = len(errors)
        held35[0].fulfill(status=200, content_type="application/json", body=answer)
        page.wait_for_timeout(900)
        if page.input_value("#p-title") != "Piece Two":
            failures.append(f"{label}: an AI answer meant for another piece form was written into this one: {page.input_value('#p-title')!r}")
        if "was not used" not in page.evaluate("(document.querySelector('#toast') || {}).textContent || ''"):
            failures.append(f"{label}: a dropped AI answer was not reported")
        if label == "seed":
            untouched = page.is_disabled("#p-seed") and "generating" in page.inner_text("#p-seed")
        else:
            untouched = page.is_disabled("#p-improve") and "Seed from idea" in page.inner_text("#p-seed") and not page.is_disabled("#p-seed")
        if not untouched:
            failures.append(f"{label}: the late answer changed the buttons of the form that is open now "
                            f"(improve disabled {page.is_disabled('#p-improve')}, seed {page.inner_text('#p-seed')!r})")
        if len(errors) != before:
            failures.append(f"{label}: a late AI answer threw: {errors[before:]}")
        for r in held35[1:]:
            r.fulfill(status=400, content_type="application/json", body='{"detail": "released by the test"}')
        page.wait_for_timeout(400)
        page.unroute("**/api/assist")
        close_modal()

    if not page.locator("[data-piece]").count():
        failures.append("the bundled world has no existing piece to open for the Improve case")
    else:
        late_answer_case("improve", lambda: page.locator("[data-piece]").first.click(), lambda: page.click("#p-improve"))

    late_answer_case("seed", lambda: page.click(f"[data-newpiece='{first}']"), ask_seed)
    print("35) an AI answer for a closed piece form is dropped, not written into another piece")

    # --- D-056 item 10: a readable export and find in the story ------------------------------------------------------
    # 36) The only export was the zip backup. "Export text" downloads the story as Markdown a person can read: the stored turns,
    #     not the transcript with its marker comments.
    page.evaluate("location.hash = '#library'")
    page.wait_for_selector(f".card[data-slug='{slug}'] [data-act='export-text']", timeout=8000)
    with page.expect_download() as download_info:
        page.click(f".card[data-slug='{slug}'] [data-act='export-text']")
    download = download_info.value
    exported = Path(download.path()).read_text(encoding="utf-8")
    if download.suggested_filename != f"{slug}.md":
        failures.append(f"the readable export is named {download.suggested_filename!r}, not {slug}.md")
    if not exported.startswith("# Smoke\n") or "NARRATOR-1" not in exported or "> **You:** PLAYER-1" not in exported:
        failures.append(f"the readable export does not read as the story: {exported[:200]!r}")
    if "<!--" in exported or "\u200b" in exported:
        failures.append("the readable export carries the transcript's markers")
    if not page.is_visible(f".card[data-slug='{slug}'] [data-act='export']"):
        failures.append("the zip backup button is gone from the story card")
    print("36) Export text downloads the story as readable Markdown")

    # 37) Find in the story: marks inside the turns, a count, Enter and Shift+Enter step, Escape closes, and a search never
    #     changes a turn's text or the turns themselves (edit and retry address a turn by its position in #transcript).
    server._engine(slug).store.append_turn("narrator", "The Tallow burns low. A second tallow stub waits by the door.")
    server._engine(slug).store.append_turn("player", "I snuff the TALLOW.")
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    page.wait_for_function("document.querySelectorAll('#transcript .turn').length > 3", timeout=8000)
    snapshot_js = """() => { const t = document.querySelector('#transcript');
        return {turns: t.children.length, text: t.textContent, nodes: [...t.querySelectorAll('.turn-body')].map(b => b.childNodes.length)}; }"""
    before = page.evaluate(snapshot_js)
    errors_before = len(errors)
    if page.is_visible("#find-bar"):
        failures.append("the find bar is showing before Find was pressed (a `hidden` row shown by CSS)")
    page.click("#find-btn")
    if not page.is_visible("#find-bar") or page.evaluate("document.activeElement.id") != "find-q" \
            or page.get_attribute("#find-btn", "aria-expanded") != "true":
        failures.append("Find did not open the bar with focus in its box")
    page.fill("#find-q", "tallow")
    try:
        page.wait_for_function("document.querySelector('#find-count').textContent === '1 of 3'", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append("find said " + repr(page.inner_text("#find-count")) + " for a word that is in 3 places (any case)")
    marks_js = """() => ({n: document.querySelectorAll('#transcript mark.find-hit').length,
        inBody: [...document.querySelectorAll('#transcript mark.find-hit')].every(m => m.closest('.turn-body')),
        current: [...document.querySelectorAll('#transcript mark.find-hit')].map(m => m.classList.contains('current'))})"""
    got = page.evaluate(marks_js)
    if got["n"] != 3 or not got["inBody"] or got["current"] != [True, False, False]:
        failures.append(f"the highlights are wrong: {got}")
    during = page.evaluate(snapshot_js)
    if during["turns"] != before["turns"] or during["text"] != before["text"]:
        failures.append("a search changed the turns or their text")
    page.press("#find-q", "Enter")
    if page.inner_text("#find-count") != "2 of 3" or page.evaluate(marks_js)["current"] != [False, True, False]:
        failures.append(f"Enter did not step to the second match: {page.inner_text('#find-count')!r} {page.evaluate(marks_js)['current']}")
    page.press("#find-q", "Shift+Enter")
    page.press("#find-q", "Shift+Enter")
    if page.inner_text("#find-count") != "3 of 3":
        failures.append(f"Shift+Enter did not wrap back to the last match: {page.inner_text('#find-count')!r}")
    page.press("#find-q", "Enter")
    if page.inner_text("#find-count") != "1 of 3":
        failures.append(f"Enter did not wrap to the first match: {page.inner_text('#find-count')!r}")
    # a turn that arrives while the bar is open is searched too (the search re-runs when turns come or go)
    page.evaluate("""() => { const d = document.createElement('div'); d.className = 'turn narrator'; const b = document.createElement('span');
        b.className = 'turn-body'; b.textContent = 'One more tallow candle.'; d.appendChild(b); d.id = 'find-extra';
        document.querySelector('#transcript').appendChild(d); }""")
    try:
        page.wait_for_function("document.querySelector('#find-count').textContent.endsWith('of 4')", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append("a turn added while the find bar was open was not searched: " + repr(page.inner_text("#find-count")))
    page.evaluate("document.querySelector('#find-extra').remove()")
    # what is typed is text, not a pattern
    page.fill("#find-q", "(tallow")
    try:
        page.wait_for_function("document.querySelector('#find-count').textContent === 'No matches'", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append("a search for '(tallow' did not say there were no matches: " + repr(page.inner_text("#find-count")))
    # the chrome of a turn (its version bar, its buttons) is not the story: only text inside a turn's body is marked
    page.fill("#find-q", "version")
    page.wait_for_function("document.querySelector('#find-count').textContent.includes(' of ')", timeout=4000)
    chrome = page.evaluate(marks_js)
    if chrome["n"] < 1 or not chrome["inBody"]:
        failures.append(f"a search for a word on a turn's version bar marked something outside the turn bodies: {chrome}")
    page.fill("#find-q", "tallow")
    page.wait_for_function("document.querySelector('#find-count').textContent === '1 of 3'", timeout=4000)
    page.press("#find-q", "Escape")
    after = page.evaluate(snapshot_js)
    if page.is_visible("#find-bar") or page.evaluate("document.querySelectorAll('#transcript mark.find-hit').length") != 0:
        failures.append("Escape did not close the find bar and clear the highlights")
    if page.evaluate("document.activeElement.id") != "find-btn" or page.get_attribute("#find-btn", "aria-expanded") != "false":
        failures.append("closing find did not return focus to its button")
    if after != before:
        failures.append(f"after find the turns are not as they were (text nodes merged back?): {before['nodes']} -> {after['nodes']}")
    if len(errors) != errors_before:
        failures.append(f"find threw: {errors[errors_before:]}")
    print("37) find in the story highlights, counts, steps, searches new turns and leaves the turns untouched")

    # --- D-056 item 11: the per-turn menu ---------------------------------------------------------------------------
    # 38) Edit, Copy, Branch from here and Regenerate in one menu on a "..." button at each turn, and on a long press of a touch
    #     screen. The menu is on <body>, not in #transcript (the pen and retry address a turn by its position there).
    server._engine(slug).store.append_turn("narrator", "She says *hush* and **runs**.")
    page.evaluate("location.hash = '#library'")                          # leave and come back, so the page reads the new turn
    page.wait_for_selector(f".card[data-slug='{slug}']", timeout=8000)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    page.wait_for_function("document.querySelectorAll('#transcript .turn').length > 3", timeout=8000)
    triggers = page.evaluate("""() => [...document.querySelectorAll('#transcript .turn')].map(t => { const b = t.querySelector('.turn-more');
        return [t.classList.contains('player'), b && b.getAttribute('aria-label'), b && b.getAttribute('aria-haspopup'),
                b && b.getAttribute('aria-expanded')]; })""")
    bad = [t for t in triggers if not t[1] or t[2] != "menu" or t[3] != "false"
           or t[1] != ("More for your action" if t[0] else "More for this reply")]
    if bad:
        failures.append(f"turns without a proper menu button: {bad[:3]}")
    items_js = "[...document.querySelectorAll('.turn-menu [role=menuitem]')].map(b => b.textContent.trim())"
    focus_js = "document.activeElement && document.activeElement.textContent.trim()"
    narrators = page.locator("#transcript .turn.narrator")
    first_reply = narrators.first
    first_reply.locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    if not page.evaluate("document.querySelector('.turn-menu').parentElement === document.body"):
        failures.append("the turn menu was put inside the page's own turn list")
    if page.evaluate(items_js) != ["Edit", "Copy text", "Branch from here"]:
        failures.append(f"an earlier reply offers {page.evaluate(items_js)}, not Edit, Copy text and Branch from here")
    if page.evaluate(focus_js) != "Edit" or first_reply.locator(".turn-more").get_attribute("aria-expanded") != "true":
        failures.append(f"opening the menu did not focus its first item (focus on {page.evaluate(focus_js)!r})")
    page.keyboard.press("ArrowDown")
    down = page.evaluate(focus_js)
    page.keyboard.press("End")
    end = page.evaluate(focus_js)
    page.keyboard.press("Home")
    home = page.evaluate(focus_js)
    if (down, end, home) != ("Copy text", "Branch from here", "Edit"):
        failures.append(f"arrow, End and Home keys moved focus to {(down, end, home)}")
    page.keyboard.press("Escape")
    if page.locator(".turn-menu").count() or first_reply.locator(".turn-more").get_attribute("aria-expanded") != "false":
        failures.append("Escape did not close the turn menu")
    if not page.evaluate("document.activeElement.classList.contains('turn-more')"):
        failures.append("closing the turn menu with Escape did not return focus to its button")
    # a player's action: no branch (a fork would end on an action with no reply), no regenerate
    page.locator("#transcript .turn.player").first.locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    if page.evaluate(items_js) != ["Edit", "Copy text"]:
        failures.append(f"a player turn offers {page.evaluate(items_js)}, not Edit and Copy text")
    page.mouse.click(3, 300)                                           # a click anywhere else closes it
    if page.locator(".turn-menu").count():
        failures.append("a click outside did not close the turn menu")
    page.locator("#transcript .turn.player").first.locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    page.keyboard.press("Tab")                                         # Tab leaves the menu: it closes and focus moves on
    if page.locator(".turn-menu").count():
        failures.append("Tab did not close the turn menu")
    # the last reply also offers Regenerate; an earlier one does not
    narrators.last.locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    if page.evaluate(items_js) != ["Edit", "Copy text", "Branch from here", "Regenerate this reply"]:
        failures.append(f"the last reply offers {page.evaluate(items_js)}")
    page.keyboard.press("Escape")
    # Copy puts the turn's own text on the clipboard and says so
    page.evaluate("""() => { window.__copied = null; Object.defineProperty(navigator, 'clipboard',
        {value: {writeText: async t => { window.__copied = t; }}, configurable: true}); }""")
    want = page.evaluate("[...document.querySelectorAll('#transcript .turn.narrator')].pop()._raw")
    if want != "She says *hush* and **runs**.":
        failures.append(f"the last reply's raw text is {want!r}")
    narrators.last.locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    page.click(".turn-menu button:has-text('Copy text')")
    page.wait_for_function("window.__copied !== null", timeout=3000)
    if page.evaluate("window.__copied") != want or not want:
        failures.append(f"Copy text copied {page.evaluate('window.__copied')!r}, not the turn's own text {want!r} (the markdown, not what is on screen)")
    if "Copied" not in page.evaluate("(document.querySelector('#toast') || {}).textContent || ''") or page.locator(".turn-menu").count():
        failures.append("Copy text did not say it copied, or left the menu open")
    # Edit opens the editor on that turn
    first_reply.locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    page.click(".turn-menu button:has-text('Edit')")
    page.wait_for_selector("#transcript .turn-editor", timeout=3000)
    if page.input_value("#transcript .turn-editor") != page.evaluate("document.querySelector('#transcript .turn.narrator')._raw"):
        failures.append("Edit from the menu did not open the editor on this turn's text")
    page.click("#transcript .turn-editbar .cx")
    # Branch from here forks the story at that reply: the copy holds exactly the turns up to it
    n_turns = page.evaluate("[...document.querySelectorAll('#transcript .turn')].indexOf(document.querySelectorAll('#transcript .turn.narrator')[1]) + 1")
    second_reply = narrators.nth(1)
    second_reply.locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    page.click(".turn-menu button:has-text('Branch from here')")
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-yes")
    page.wait_for_function(f"location.hash.startsWith('#play/') && location.hash !== '#play/{slug}'", timeout=10000)
    forked = page.evaluate("location.hash.slice(6)")
    fork_turns = len(c.get(f"/api/saves/{forked}").json()["turns"])
    if fork_turns != n_turns:
        failures.append(f"Branch from here made a copy with {fork_turns} turns, not the {n_turns} up to that reply")
    page.wait_for_selector("#action", timeout=8000)
    c.delete(f"/api/saves/{forked}")
    # a menu left open when the reader goes to another page does not follow them there
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_function("document.querySelectorAll('#transcript .turn').length > 3", timeout=8000)
    page.locator("#transcript .turn.narrator").nth(1).locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    page.evaluate("location.hash = '#library'")
    page.wait_for_selector(f".card[data-slug='{slug}']", timeout=8000)
    if page.locator(".turn-menu").count():
        failures.append("a turn menu stayed on screen after the reader left the story")
    # a reply without a "warnings" list (the old button read out.warnings.length unguarded and the failure was swallowed into a
    # toast) must still take the reader to the copy, from either button
    target = c.post("/api/saves", json={"title": "Branch Target", "mode": "simple", "premise": "x"}).json()["slug"]
    errors_before = len(errors)
    page.route("**/api/saves/*/branch", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"slug": target})))
    for how in ("the Branch button", "the turn menu"):
        page.evaluate(f"location.hash = '#play/{slug}'")
        page.wait_for_selector("#action", timeout=8000)
        page.wait_for_function("document.querySelectorAll('#transcript .turn').length > 3", timeout=8000)
        if how == "the Branch button":
            page.click("#branch")
            page.wait_for_selector("#pm-v", timeout=4000)
            page.fill("#pm-v", "2")
            page.click("#pm-yes")
        else:
            page.locator("#transcript .turn.narrator").nth(1).locator(".turn-more").click()
            page.wait_for_selector(".turn-menu", timeout=3000)
            page.click(".turn-menu button:has-text('Branch from here')")
            page.wait_for_selector("#cm-yes", timeout=3000)
            page.click("#cm-yes")
        try:
            page.wait_for_function(f"location.hash === '#play/{target}'", timeout=4000)
        except Exception:  # noqa: BLE001
            failures.append(f"a branch reply with no warnings list did not open the copy from {how}: "
                            + repr(page.evaluate("[location.hash, (document.querySelector('#toast') || {}).textContent]")))
    page.unroute("**/api/saves/*/branch")
    if len(errors) != errors_before:
        failures.append(f"a branch reply with no warnings list threw: {errors[errors_before:]}")
    c.delete(f"/api/saves/{target}")
    # a long press on a touch screen opens the menu; a short touch, a moving finger and a mouse do not
    page.evaluate(f"location.hash = '#library'")
    page.wait_for_selector(f".card[data-slug='{slug}']", timeout=8000)
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    page.wait_for_function("document.querySelectorAll('#transcript .turn').length > 3", timeout=8000)
    fire_js = """([type, kind, dx]) => { const b = document.querySelectorAll('#transcript .turn.narrator .turn-body')[0];
        const r = b.getBoundingClientRect();
        b.dispatchEvent(new PointerEvent(type, {pointerType: kind, bubbles: true, isPrimary: true, pointerId: 9,
                                                clientX: r.left + 20 + dx, clientY: r.top + 10})); }"""
    page.evaluate(fire_js, ["pointerdown", "touch", 0])
    page.wait_for_timeout(900)
    held_open = page.locator(".turn-menu").count()
    if held_open != 1:
        failures.append("a long press on a touch screen did not open the turn menu")
    page.keyboard.press("Escape")
    # each of these must leave NO menu (checked one at a time: the next press would close a menu the one before had opened)
    page.evaluate(fire_js, ["pointerdown", "touch", 0])
    page.wait_for_timeout(200)
    page.evaluate(fire_js, ["pointerup", "touch", 0])
    page.wait_for_timeout(700)
    if page.locator(".turn-menu").count():
        failures.append("a short touch opened the turn menu")
    page.evaluate(fire_js, ["pointerdown", "touch", 0])
    page.evaluate(fire_js, ["pointermove", "touch", 40])
    page.wait_for_timeout(800)
    if page.locator(".turn-menu").count():
        failures.append("a finger that moved while held opened the turn menu")
    page.evaluate(fire_js, ["pointerdown", "mouse", 0])
    page.wait_for_timeout(800)
    if page.locator(".turn-menu").count():
        failures.append("a held mouse button opened the turn menu")
    # while a reply is being written, Edit, Branch and Regenerate wait; Copy does not
    held_turn38 = []
    page.route("**/api/saves/*/turn", lambda route: held_turn38.append(route))

    def answer_cancel38(route):
        route.fulfill(status=200, content_type="application/json", body="{}")
        for h in held_turn38:
            h.fulfill(status=200, content_type="text/event-stream",
                      body='data: {"t": "error", "code": "aborted", "text": "You stopped this turn."}\n\n')

    page.route("**/api/saves/*/cancel", answer_cancel38)
    page.fill("#action", "I wait.")
    page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('#stop').classList.contains('hidden')", timeout=6000)
    wait_until_held(page, held_turn38, "turn")
    page.locator("#transcript .turn.narrator").nth(1).locator(".turn-more").click()
    page.wait_for_selector(".turn-menu", timeout=3000)
    state = page.evaluate("[...document.querySelectorAll('.turn-menu [role=menuitem]')].map(b => [b.textContent.trim(), b.disabled])")
    if state != [["Edit", True], ["Copy text", False], ["Branch from here", True]]:
        failures.append(f"while a reply is being written the menu is {state}")
    page.keyboard.press("Escape")
    page.click("#stop")
    page.wait_for_selector(".turn-note", timeout=8000)
    page.unroute("**/api/saves/*/turn")
    page.unroute("**/api/saves/*/cancel")
    print("38) the per-turn menu: edit, copy, branch from here, regenerate; keyboard, long press, and waiting while a reply is written")

    # --- D-056 item 12: display settings reachable from Play --------------------------------------------------------
    # 39) Text size (new) and the background rain (which could only be reached from Settings) in a dialog on the Play page.
    #     Both are kept in this browser, apply at once, and closing the dialog never asks to discard anything.
    page.evaluate("location.hash = '#library'")
    page.wait_for_selector(f".card[data-slug='{slug}']", timeout=8000)
    page.evaluate("localStorage.removeItem('coderain_font')")
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    page.wait_for_function("document.querySelectorAll('#transcript .turn.narrator').length > 0", timeout=8000)
    size_js = "parseFloat(getComputedStyle(document.querySelector('#transcript .turn.narrator')).fontSize)"
    player_size_js = "parseFloat(getComputedStyle(document.querySelector('#transcript .turn.player')).fontSize)"
    base = page.evaluate(size_js)
    player_base = page.evaluate(player_size_js)
    if page.get_attribute("#display-btn", "aria-label") != "Display settings":
        failures.append("the Display button has no name")
    page.click("#display-btn")
    page.wait_for_selector("#dp-size", timeout=3000)
    state = page.evaluate("""() => ({on: [...document.querySelectorAll('#dp-size button')].filter(b => b.classList.contains('on')).map(b => b.dataset.size),
        rain: document.querySelector('#dp-rain').checked, rainOn: window.rainOn()})""")
    if state["on"] != ["medium"] or state["rain"] != state["rainOn"]:
        failures.append(f"the Display dialog opens showing {state}")
    page.click("#dp-size button[data-size='large']")
    grown = page.evaluate(size_js)
    if not grown > base * 1.1 or not page.evaluate(player_size_js) > player_base * 1.1:
        failures.append(f"Large did not make the story text bigger (replies {base}px -> {grown}px, your actions {player_base}px -> {page.evaluate(player_size_js)}px)")
    if page.evaluate("localStorage.getItem('coderain_font')") != "large":
        failures.append("the text size was not remembered in this browser")
    if page.evaluate("document.querySelector('#dp-size button.on').dataset.size") != "large":
        failures.append("the dialog does not show the size just chosen")
    page.click("#dp-size button[data-size='small']")
    if not page.evaluate(size_js) < base * 0.95:
        failures.append("Small did not make the story text smaller")
    page.click("#dp-size button[data-size='large']")
    # the rain switch is the same one Settings has
    was_on = page.evaluate("window.rainOn()")
    page.click("#dp-rain")
    if page.evaluate("window.rainOn()") == was_on or page.evaluate("localStorage.getItem('coderain_motion')") != ("off" if was_on else "on"):
        failures.append("the rain switch in the Display dialog did not change the background")
    page.click("#dp-rain")
    # nothing to discard: Escape closes at once, with no question
    page.keyboard.press("Escape")
    page.wait_for_selector("#modal-root.hidden", state="attached", timeout=3000)
    if page.locator("#modal-ask").count():
        failures.append("closing the Display dialog asked about discarding changes")
    page.click("#display-btn")
    page.wait_for_selector("#dp-done", timeout=3000)
    page.click("#dp-done")
    page.wait_for_selector("#modal-root.hidden", state="attached", timeout=3000)
    # kept across a reload, applied before the page paints; a stored value that is not ours means medium
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#action", timeout=8000)
    page.wait_for_function("document.querySelectorAll('#transcript .turn.narrator').length > 0", timeout=8000)
    if not page.evaluate(size_js) > base * 1.1:
        failures.append("the text size did not survive a reload")
    page.evaluate("localStorage.setItem('coderain_font', 'banana')")
    page.evaluate("async () => { const m = await import('/js/display.js'); m.applyDisplay(); }")
    if abs(page.evaluate(size_js) - base) > 0.5:
        failures.append("a stored size that is not one of ours did not mean medium")
    page.evaluate("localStorage.removeItem('coderain_font')")
    page.evaluate("async () => { const m = await import('/js/display.js'); m.applyDisplay(); }")
    print("39) display settings: text size and the rain switch from the Play page, remembered, nothing to discard")

    # --- D-056 item 13: one level of undo for the builder's AI assist ------------------------------------------------
    # 40) "Improve with AI" and "Seed from idea" replaced a field's text with no way back. Undo AI restores what the last answer
    #     replaced, one level per field; typing into the field drops it (it would throw the author's own words away).
    page.evaluate(f"location.hash = '#world/{scen}'")
    page.wait_for_selector("#b-premise", timeout=8000)
    real_premise = page.input_value("#b-premise")
    real_intro = page.input_value("#b-intro") if page.is_visible("#b-intro") else None
    answers = ["First AI text.", "Second AI text.", "Intro from the AI."]
    served = []

    def serve_answer(route):
        served.append(1)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"text": answers[len(served) - 1]}))

    page.route("**/api/assist", serve_answer)
    undo_sel = "[data-undo-ai='b-premise']"
    if page.is_visible(undo_sel):
        failures.append("Undo AI is showing before any AI answer")
    page.fill("#b-premise", "My own premise.")
    page.click("[data-improve='b-premise']")
    page.wait_for_function("document.querySelector('#b-premise').value === 'First AI text.'", timeout=5000)
    if not page.is_visible(undo_sel):
        failures.append("Undo AI did not appear after an AI answer")
    if not page.get_attribute(undo_sel, "aria-label") or "Premise" not in page.get_attribute(undo_sel, "aria-label"):
        failures.append(f"Undo AI is not named for its field: {page.get_attribute(undo_sel, 'aria-label')!r}")
    page.click(undo_sel)
    if page.input_value("#b-premise") != "My own premise." or page.is_visible(undo_sel):
        failures.append(f"Undo AI did not restore the author's text and go away: {page.input_value('#b-premise')!r}")
    # one level: two answers in a row, Undo goes back to the FIRST answer, not to the author's own text
    page.click("[data-improve='b-premise']")
    page.wait_for_function("document.querySelector('#b-premise').value === 'Second AI text.'", timeout=5000)
    page.click(undo_sel)
    if page.input_value("#b-premise") != "My own premise.":
        failures.append(f"Undo AI after the second answer restored {page.input_value('#b-premise')!r}")
    # the fields do not share an undo: an answer in another field leaves the premise's alone
    if page.is_visible("#b-intro"):
        page.fill("#b-intro", "My own opening.")
        page.click("[data-improve='b-intro']")
        page.wait_for_function("document.querySelector('#b-intro').value === 'Intro from the AI.'", timeout=5000)
        if page.is_visible(undo_sel):
            failures.append("an answer for the introduction showed the premise's Undo AI")
        page.click("[data-undo-ai='b-intro']")
        if page.input_value("#b-intro") != "My own opening.":
            failures.append(f"the introduction's Undo AI restored {page.input_value('#b-intro')!r}")
    page.unroute("**/api/assist")
    # typing into the field after an answer drops the undo (nothing of the author's may be thrown away by it)
    page.route("**/api/assist", lambda route: route.fulfill(status=200, content_type="application/json", body='{"text": "Another AI text."}'))
    page.click("[data-improve='b-premise']")
    page.wait_for_function("document.querySelector('#b-premise').value === 'Another AI text.'", timeout=5000)
    page.type("#b-premise", " And my edit.")
    if page.is_visible(undo_sel):
        failures.append("Undo AI stayed after the author typed into the field")
    # a failed answer changes nothing and offers nothing to undo
    page.unroute("**/api/assist")
    page.fill("#b-premise", "Kept premise.")
    page.route("**/api/assist", lambda route: route.fulfill(status=400, content_type="application/json", body='{"detail": "no model"}'))
    page.click("[data-improve='b-premise']")
    page.wait_for_function("!document.querySelector('#b-premise').disabled", timeout=5000)
    if page.input_value("#b-premise") != "Kept premise." or page.is_visible(undo_sel):
        failures.append("a failed AI request changed the field or offered an undo")
    # "Seed from idea" is undoable too
    page.unroute("**/api/assist")
    page.route("**/api/assist", lambda route: route.fulfill(status=200, content_type="application/json", body='{"text": "Seeded text."}'))
    page.click("[data-seed='b-premise']")
    page.wait_for_selector("#pm-v", timeout=4000)
    page.fill("#pm-v", "a grim ferryman")
    page.click("#pm-yes")
    page.wait_for_function("document.querySelector('#b-premise').value === 'Seeded text.'", timeout=5000)
    page.click(undo_sel)
    if page.input_value("#b-premise") != "Kept premise.":
        failures.append(f"Undo AI after a seed restored {page.input_value('#b-premise')!r}")
    page.unroute("**/api/assist")
    page.fill("#b-premise", real_premise)                          # leave the world as it was found
    if real_intro is not None:
        page.fill("#b-intro", real_intro)
    print("40) the builder's AI assist has a one-level undo per field")

    # --- A2: canon builds ---------------------------------------------------------------------------------------------
    # 41) State corrections (D-062): the Canon panel lists what each person wears and holds, with a Wrong button on each item
    #     and no Change (what someone wears now is the story's to say), and "It is this" waits while Wearing or Holding is
    #     chosen. The server is stubbed: the reader is off in this suite, so there is nothing real to list.
    canon_view = {"shadow": True, "inject": "off", "unread": 0, "card": "", "text": "", "corrections": [], "problems": [],
                  "values": [{"who": "Odile Marsh", "slug": "odile", "slot": "hair", "value": "raven", "since_turn": 1,
                              "confirmations": 1, "by": "narration"}],
                  "state": [{"who": "Odile Marsh", "slug": "odile", "slot": "outfit", "value": "red cloak", "since_turn": 2, "by": "narration"},
                            {"who": "Odile Marsh", "slug": "odile", "slot": "held", "value": "brass key", "since_turn": 3, "by": "narration"}]}
    posted = []

    def canon_stub(route):
        req = route.request
        if req.method == "POST":
            posted.append(json.loads(req.post_data))
            after = dict(canon_view, state=[x for x in canon_view["state"] if x["value"] != posted[-1]["value"]])
            route.fulfill(status=200, content_type="application/json", body=json.dumps(after))
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(canon_view))

    page.route("**/api/saves/*/canon", canon_stub)
    page.route("**/api/saves/*/canon/corrections", canon_stub)
    # straight to the story: case 39 reloaded the page, which forgot "Look around first", so the Library would show the first-run screen
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#canon-btn", timeout=8000)
    page.click("#canon-btn")
    page.wait_for_selector(".cn-row[data-slot='outfit']", timeout=5000)
    rows = page.evaluate("""() => [...document.querySelectorAll('.cn-row')].map(r => [r.dataset.slot, r.dataset.value,
        [...r.querySelectorAll('button')].map(b => b.dataset.act), r.querySelector('.cn-slot').textContent.trim()])""")
    by_slot = {r[0]: r for r in rows}
    if set(by_slot) != {"hair", "outfit", "held"}:
        failures.append(f"the Canon panel lists {sorted(by_slot)} for Odile, not hair, outfit and held")
    elif by_slot["outfit"][2] != ["wrong"] or by_slot["held"][2] != ["wrong"] or by_slot["hair"][2] != ["wrong", "set"]:
        failures.append(f"the buttons on the rows are {[(r[0], r[2]) for r in rows]}: a worn or held item may only be marked wrong")
    elif (by_slot["outfit"][3], by_slot["held"][3]) != ("Wearing", "Holding"):
        failures.append(f"the worn and held rows are labelled {by_slot['outfit'][3]!r} and {by_slot['held'][3]!r}")
    if page.evaluate("document.querySelectorAll('.cn-char').length") != 1:
        failures.append("the worn and held items are not under the same person as their looks")
    page.select_option("#cn-slot", "outfit")
    if not page.is_disabled("#cn-set") or page.is_hidden("#cn-state-hint"):
        failures.append("'It is this' is available for Wearing (it can only be marked wrong), or the hint is missing")
    page.select_option("#cn-slot", "hair")
    if page.is_disabled("#cn-set") or page.is_visible("#cn-state-hint"):
        failures.append("'It is this' stayed off after going back to Hair")
    page.click(".cn-row[data-slot='outfit'] button[data-act='wrong']")
    page.wait_for_function("!document.querySelector(\".cn-row[data-slot='outfit']\")", timeout=5000)
    if posted != [{"who": "Odile Marsh", "slot": "outfit", "op": "wrong", "value": "red cloak"}]:
        failures.append(f"Wrong on a worn item sent {posted}")
    if not page.query_selector(".cn-row[data-slot='held']"):
        failures.append("marking the outfit wrong dropped the held item from the panel")
    page.unroute("**/api/saves/*/canon")
    page.unroute("**/api/saves/*/canon/corrections")
    close_modal()
    print("41) the Canon panel lists worn and held items, marks them wrong (never sets them), and keeps them with their person")

    # --- D-056 P3 ------------------------------------------------------------------------------------------------------
    # 42) Item 20: the world builder saves the main fields by itself a pause after the last keystroke. One save at a time, none
    #     while the title is blank (the route would blank the world's name), a failure is a line that the next edit retries.
    page.evaluate(f"location.hash = '#world/{scen}'")
    page.wait_for_selector("#b-premise", timeout=8000)
    world_before = c.get(f"/api/scenarios/{scen}/full").json()
    puts, held_put = [], []
    hold_first = [False]

    def count_put(route):
        if route.request.method != "PUT":
            return route.continue_()
        puts.append(json.loads(route.request.post_data))
        if hold_first[0] and not held_put:
            held_put.append(route)                   # answered later by the test
            return None
        return route.continue_()

    def disk_premise():
        return c.get(f"/api/scenarios/{scen}/full").json()["premise"]

    page.route("**/api/scenarios/*/main", count_put)
    page.fill("#b-premise", "Autosaved premise, typed and left alone.")
    page.wait_for_timeout(300)
    if puts:
        failures.append("the builder saved before the pause after typing")
    try:
        page.wait_for_function("document.querySelector('#b-status').textContent === 'Saved'", timeout=6000)
    except Exception:  # noqa: BLE001
        failures.append("the builder did not save by itself after typing: " + repr(page.inner_text("#b-status")))
    if disk_premise() != "Autosaved premise, typed and left alone." or len(puts) != 1:
        failures.append(f"after the pause the premise on disk is {disk_premise()!r} ({len(puts)} saves, one wanted)")
    # fast typing is one save, not one a keystroke
    puts.clear()
    page.type("#b-premise", " More words follow.", delay=30)
    for _ in range(60):                               # the status already says Saved: wait for the NEW save to be asked for
        if puts:
            break
        page.wait_for_timeout(100)
    page.wait_for_function("document.querySelector('#b-status').textContent === 'Saved'", timeout=6000)
    if len(puts) != 1 or not disk_premise().endswith("More words follow."):
        failures.append(f"typing a sentence made {len(puts)} saves (one wanted), disk: {disk_premise()!r}")
    # typing slower than the pause between keystrokes but faster than the pause itself still waits for the END of the typing: the timer
    # is restarted by every key (a save per pause longer than the delay would otherwise land in the middle of a sentence)
    puts.clear()
    page.type("#b-premise", " Slowly now.", delay=300)
    for _ in range(80):
        if puts:
            break
        page.wait_for_timeout(100)
    page.wait_for_function("document.querySelector('#b-status').textContent === 'Saved'", timeout=6000)
    page.wait_for_timeout(1600)
    if len(puts) != 1 or not disk_premise().endswith("Slowly now."):
        failures.append(f"slow typing made {len(puts)} saves (one wanted, after the last key), disk: {disk_premise()[-30:]!r}")
    # a blank title is never saved, and says why
    puts.clear()
    page.fill("#b-title", "")
    page.wait_for_function("document.querySelector('#b-status').textContent.includes('title')", timeout=5000)
    page.wait_for_timeout(1600)
    if puts:
        failures.append("the builder saved a blank title")
    page.fill("#b-title", world_before["title"])
    page.wait_for_function("document.querySelector('#b-status').textContent === 'Saved'", timeout=6000)
    # one save at a time: an edit made while a save is in flight waits for it and then saves again
    puts.clear()
    hold_first[0] = True
    page.fill("#b-premise", "First edit.")
    wait_until_held(page, held_put, "builder autosave")
    page.fill("#b-premise", "Second edit, made while the first save is in flight.")
    page.wait_for_timeout(2200)
    if len(puts) != 1:
        failures.append(f"a second save started while the first was in flight ({len(puts)} requests)")
    hold_first[0] = False
    held_put[0].continue_()
    try:
        page.wait_for_function("document.querySelector('#b-status').textContent === 'Saved'", timeout=6000)
    except Exception:  # noqa: BLE001
        failures.append("the builder never finished its saves after the first was released")
    for _ in range(40):
        if disk_premise() == "Second edit, made while the first save is in flight.":
            break
        page.wait_for_timeout(150)
    if disk_premise() != "Second edit, made while the first save is in flight.":
        failures.append(f"the edit made during a save was lost: {disk_premise()!r}")
    # a failure is a line, and the next edit tries again
    page.unroute("**/api/scenarios/*/main")
    page.route("**/api/scenarios/*/main", lambda route: route.fulfill(
        status=409, content_type="application/json", body='{"detail": "disk full"}') if route.request.method == "PUT" else route.continue_())
    page.fill("#b-premise", "This save will fail.")
    try:
        page.wait_for_function("document.querySelector('#b-status').textContent.startsWith(\"Couldn't save\")", timeout=6000)
    except Exception:  # noqa: BLE001
        failures.append("a failed autosave was not reported: " + repr(page.inner_text("#b-status")))
    page.unroute("**/api/scenarios/*/main")
    page.fill("#b-premise", "This one goes through.")
    page.wait_for_function("document.querySelector('#b-status').textContent === 'Saved'", timeout=6000)
    if disk_premise() != "This one goes through.":
        failures.append(f"the edit after a failed autosave was not saved: {disk_premise()!r}")
    # an AI answer sets the value without a key press: it is saved too
    page.route("**/api/assist", lambda route: route.fulfill(status=200, content_type="application/json", body='{"text": "Written by the AI."}'))
    page.click("[data-improve='b-premise']")
    page.wait_for_function("document.querySelector('#b-premise').value === 'Written by the AI.'", timeout=5000)
    page.wait_for_function("document.querySelector('#b-status').textContent === 'Saved'", timeout=6000)
    for _ in range(40):
        if disk_premise() == "Written by the AI.":
            break
        page.wait_for_timeout(150)
    if disk_premise() != "Written by the AI.":
        failures.append(f"an AI answer was not autosaved: {disk_premise()!r}")
    page.click("[data-undo-ai='b-premise']")                        # Undo AI sets the value without a key press too
    for _ in range(40):
        if disk_premise() == "This one goes through.":
            break
        page.wait_for_timeout(150)
    if disk_premise() != "This one goes through.":
        failures.append(f"Undo AI was not autosaved: {disk_premise()!r}")
    page.unroute("**/api/assist")
    # the pause timer of a page that was left does nothing
    page.fill("#b-premise", "Typed, then left at once.")
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    after_leaving = []
    page.route("**/api/scenarios/*/main", lambda route: (after_leaving.append(1), route.continue_())[1])
    page.wait_for_timeout(2200)
    page.unroute("**/api/scenarios/*/main")
    if after_leaving:
        failures.append("a builder that was left still saved after its pause")
    if disk_premise() != "Typed, then left at once.":
        failures.append(f"leaving the builder right after typing lost the text: {disk_premise()!r}")
    c.put(f"/api/scenarios/{scen}/main", json={k: world_before[k] for k in ("title", "description", "premise", "introduction", "world") if k in world_before})
    # The pause timer of a builder that was left can fire while ANOTHER world's builder is open. It used to look its fields up by id, so
    # it read the other world's text and saved it to the world it belonged to (found because the previous case's timer fired in this one).
    other = c.post("/api/scenarios", json={"title": "Second Smoke World"}).json()["slug"]

    def open_world(slug_, title_):
        """Open a world's builder and wait until THAT world is on screen (the old builder's boxes are still there until it paints)."""
        page.evaluate(f"location.hash = '#world/{slug_}'")
        page.wait_for_function(f"document.querySelector('#b-title') && document.querySelector('#b-title').value === {title_!r}", timeout=8000)

    open_world(other, "Second Smoke World")
    open_world(scen, world_before["title"])
    page.fill("#b-premise", "Typed in the first world.")
    open_world(other, "Second Smoke World")                     # leave within the pause: that page's timer is still running
    page.wait_for_timeout(2400)
    if disk_premise() != "Typed in the first world.":
        failures.append(f"the timer of a builder that was left saved ANOTHER world's text into it, or leaving lost the text: {disk_premise()[:40]!r}")
    if c.get(f"/api/scenarios/{other}/full").json()["premise"] == "Typed in the first world.":
        failures.append("the first world's text was saved into the second world")
    c.put(f"/api/scenarios/{scen}/main", json={k: world_before[k] for k in ("title", "description", "premise", "introduction", "world") if k in world_before})
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    c.delete(f"/api/scenarios/{other}")
    print("42) the builder saves by itself a pause after typing: once, not while the title is blank, one at a time, a failure is retried")

    # 43) Item 16: the RPG character sheet below 900px. It was display:none there, so a story with mechanics had no way to show its own
    #     sheet on a phone or a narrow window. Now it is a tab; above 900px both show, side by side, and there are no tabs.
    rpg_slug = c.post("/api/saves", json={"title": "Sheet Story", "mode": "rpg", "premise": "A ferry town."}).json()["slug"]
    vis_js = """() => { const v = s => { const e = document.querySelector(s); return !!e && e.offsetParent !== null && e.getBoundingClientRect().width > 0; };
        return {tabs: v('#view-tabs'), sheet: v('#sheet'), story: v('#story-col'), view: (document.querySelector('#play') || {dataset: {}}).dataset.view,
                selected: [...document.querySelectorAll('#view-tabs [role=tab]')].filter(b => b.getAttribute('aria-selected') === 'true').map(b => b.id),
                sheetText: (document.querySelector('#sheet') || {textContent: ''}).textContent.trim().slice(0, 12)}; }"""
    page.set_viewport_size({"width": 1280, "height": 720})
    page.evaluate(f"location.hash = '#play/{rpg_slug}'")
    page.wait_for_selector("#sheet", timeout=8000)
    wide = page.evaluate(vis_js)
    if wide["tabs"] or not wide["sheet"] or not wide["story"]:
        failures.append(f"at 1280px the sheet and the story should show side by side with no tabs: {wide}")
    no_dashes("the RPG sheet", page.inner_text("#sheet"))              # its section headings had em dashes (the sweep never saw an RPG story)
    for width in (800, 375):
        page.set_viewport_size({"width": width, "height": 812})
        page.wait_for_timeout(200)
        got = page.evaluate(vis_js)
        if not got["tabs"] or got["sheet"] or not got["story"] or got["selected"] != ["tab-story"]:
            failures.append(f"at {width}px the story should show with Story and Sheet tabs: {got}")
        if page.evaluate("[...document.querySelectorAll('#view-tabs [role=tab]')].map(b => b.tabIndex)") != [0, -1]:
            failures.append("the tabs are not a roving tab stop (the selected one 0, the other -1)")
        page.click("#tab-sheet")
        got = page.evaluate(vis_js)
        if got["sheet"] is not True or got["story"] or got["selected"] != ["tab-sheet"] or not got["sheetText"].startswith("Character"):
            failures.append(f"at {width}px the Sheet tab did not show the character sheet: {got}")
        if page.evaluate("[...document.querySelectorAll('#view-tabs [role=tab]')].map(b => b.tabIndex)") != [-1, 0]:
            failures.append("after choosing Sheet the tab stop did not move to it")
        page.keyboard.press("ArrowLeft")
        got = page.evaluate(vis_js)
        if not got["story"] or got["sheet"] or got["selected"] != ["tab-story"] or page.evaluate("document.activeElement.id") != "tab-story":
            failures.append(f"at {width}px an arrow key did not go back to the Story tab with focus: {got}")
        page.keyboard.press("ArrowRight")
        page.set_viewport_size({"width": 1280, "height": 720})
        page.wait_for_timeout(200)
        got = page.evaluate(vis_js)
        if got["tabs"] or not got["sheet"] or not got["story"]:
            failures.append(f"widening the window with the Sheet tab open should show both again: {got}")
        page.set_viewport_size({"width": width, "height": 812})
        page.click("#tab-story")
    # the Talk drawer is a side panel on a tablet and the whole width on a phone
    page.evaluate("""async (s) => { const m = await import('/js/play.js'); m.talkDrawer(s, ['Mira']); }""", rpg_slug)
    page.wait_for_selector("#talk-drawer", timeout=4000)
    drawer_widths = {}
    for width in (800, 375):
        page.set_viewport_size({"width": width, "height": 812})
        page.wait_for_timeout(150)
        drawer_widths[width] = page.evaluate("Math.round(document.querySelector('#talk-drawer').getBoundingClientRect().width)")
    page.evaluate("document.getElementById('talk-drawer').remove()")
    if not (300 <= drawer_widths[800] <= 420) or drawer_widths[375] != 375:
        failures.append(f"the Talk drawer is {drawer_widths[800]}px at 800px (a side panel, 420 at most) and {drawer_widths[375]}px at 375px (the full width)")
    small = page.evaluate("[...document.querySelectorAll('#view-tabs button')].filter(b => b.getBoundingClientRect().height < 40).map(b => b.id)")
    if small:
        failures.append(f"the tabs are under 40px tall at 375px: {small}")
    page.evaluate(f"location.hash = '#play/{slug}'")                       # a story without mechanics has no tabs
    page.wait_for_selector("#action", timeout=8000)
    page.wait_for_function("!document.querySelector('#view-tabs')", timeout=3000)   # the RPG story's page is still up until this one paints
    page.set_viewport_size({"width": 800, "height": 812})
    page.wait_for_timeout(200)
    if page.evaluate(vis_js)["tabs"] or page.locator("#view-tabs").count():
        failures.append("a story without mechanics has Story and Sheet tabs")
    page.set_viewport_size({"width": 1280, "height": 720})
    print("43) the RPG sheet is a tab below 900px, side by side above it, and only for a story with mechanics")

    # 44) Item 17, the phone-width pass: every route and every dialog at 375px has nothing off the right edge, and what you tap is big
    #     enough (buttons 40px, fields and the first-run link 32px). The pass found a chapter title box 25px tall and a first-run link 17px tall.
    pass_js = """(root) => { const vw = innerWidth; const out = {docW: document.documentElement.scrollWidth, vw, over: [], small: []};
      const rootEl = document.querySelector(root);          // the strip must be INSIDE the page: the page itself may scroll vertically
      const name = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className).slice(0, 20);
      for (const e of document.querySelectorAll(root + ' *')) {
        const r = e.getBoundingClientRect();
        if (r.width === 0 || e.offsetParent === null || e.closest('#transcript') || e.closest('.turn')) continue;
        // a strip that scrolls sideways on purpose (the Pieces type buttons) keeps its overflow inside itself
        let strip = false;
        for (let a = e.parentElement; a && a !== rootEl; a = a.parentElement) { const ox = getComputedStyle(a).overflowX; if ((ox === 'auto' || ox === 'scroll') && a.scrollWidth > a.clientWidth) { strip = true; break; } }
        if (!strip && r.right > vw + 1 && out.over.length < 6) out.over.push(name(e) + ' right=' + Math.round(r.right));
      }
      for (const b of document.querySelectorAll(root + ' button, ' + root + ' select, ' + root + ' input:not([type=hidden]):not([type=checkbox]):not([type=radio]), ' + root + ' #w-skip')) {
        if (b.offsetParent === null || b.closest('#transcript') || b.closest('.chip-tag') || b.closest('.swipebar') || b.closest('.turn')) continue;
        const need = b.tagName === 'BUTTON' ? 40 : 32; const h = b.getBoundingClientRect().height;
        if (h < need && out.small.length < 8) out.small.push(name(b) + ' h=' + Math.round(h)); }
      return out; }"""
    page.set_viewport_size({"width": 375, "height": 812})
    for label, hash_, ready in (("the first-run or library page", "#library", "#view h1, #view h2"), ("Pieces", "#characters", "#lib-types"),
                                ("Defaults", "#defaults", "#view h1"), ("Settings", "#settings", "#len-seg"),
                                ("a story", f"#play/{slug}", "#action"), ("an RPG story", f"#play/{rpg_slug}", "#tab-sheet"),
                                ("the world builder", f"#world/{scen}", "#b-premise")):
        page.evaluate(f"location.hash = {hash_!r}")
        page.wait_for_selector(ready, timeout=10000)
        page.wait_for_timeout(700)
        got = page.evaluate(f"({pass_js})('#view')")
        if got["docW"] > got["vw"] or got["over"] or got["small"]:
            failures.append(f"{label} at 375px: {got}")
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#action", timeout=8000)
    for btn in ("note-btn", "mem-btn", "ctx-btn", "plan-btn", "canon-btn", "aids-btn", "display-btn"):
        page.click(f"#{btn}")
        page.wait_for_selector("#modal-root:not(.hidden) #modal-card h1, #modal-root:not(.hidden) #modal-card h2", timeout=8000)
        page.wait_for_timeout(300)
        got = page.evaluate(f"({pass_js})('#modal-card')")
        card = page.evaluate("(() => { const r = document.querySelector('#modal-card').getBoundingClientRect(); return [r.left, r.right, innerWidth]; })()")
        if got["over"] or got["small"] or card[0] < 0 or card[1] > card[2]:
            failures.append(f"the {btn} dialog at 375px: {got} card {card}")
        close_modal()
    page.set_viewport_size({"width": 1280, "height": 720})
    print("44) every route and dialog at 375px has nothing off the right edge and nothing too small to tap")

    # 45) A4: the Duplicates dialog (D-065) over the merge tool of D-030 and D-038. Same-name entries merge with one confirmed button,
    #     names that only share words are a choice of who stays and who is folded in, every merge is preceded by a backup, and a
    #     backup can be restored.
    from coderain.memory import Entry as DupEntry
    dup_slug = c.post("/api/saves", json={"title": "Dup UI", "mode": "simple", "premise": "A harbour town."}).json()["slug"]
    dup_store = server._engine(dup_slug).store
    long_body = "Dame Vesper keeps the harbour light and a ledger of every debt owed to the ferry. " * 3
    for t_, sl_, body_ in (("Bram Halloran", "bram-halloran", "The customs officer."), ("Bram Halloran", "bram-halloran-2", "Second entry."),
                           ("Vesper", "vesper", "Short."), ("Dame Vesper", "dame-vesper", long_body), ("Vesper Ann-Marie", "vesper-ann-marie", "Given name.")):
        dup_store.upsert_entry("characters.md", DupEntry(title=t_, slug=sl_, importance=3, body=body_))
    dup_slugs = lambda: sorted(e.slug for e in dup_store.entries("characters.md"))      # noqa: E731
    (Path(dup_store.dir) / "canon").mkdir(exist_ok=True)
    page.evaluate(f"location.hash = '#play/{dup_slug}'")
    page.wait_for_selector("#mem-btn", timeout=8000)
    page.click("#mem-btn")
    page.wait_for_selector("#mem-dups", timeout=6000)
    page.click("#mem-dups")
    page.wait_for_selector("#dup-auto", timeout=6000)
    rows = page.evaluate("""() => ({same: [...document.querySelectorAll('.dup-row')].map(r => r.textContent.trim().replace(/\\s+/g, ' ')),
        picks: [...document.querySelectorAll('.dup-cluster input[type=radio]')].map(r => [r.value, r.checked]),
        folded: [...document.querySelectorAll('.dup-fold')].map(r => [r.value, r.checked]), backups: document.querySelectorAll('[data-restore]').length})""")
    if len(rows["same"]) != 1 or "Bram Halloran" not in rows["same"][0] or "bram-halloran-2" not in rows["same"][0]:
        failures.append(f"the same-name group is not listed: {rows['same']}")
    if sorted(p_[0] for p_ in rows["picks"]) != ["dame-vesper", "vesper", "vesper-ann-marie"] or [p_[0] for p_ in rows["picks"] if p_[1]] != ["dame-vesper"]:
        failures.append(f"the possible cluster does not offer the three entries with the longest preselected: {rows['picks']}")
    if dict(rows["folded"]) != {"dame-vesper": False, "vesper": True, "vesper-ann-marie": True} or rows["backups"]:
        failures.append(f"the fold ticks or the backups are wrong at the start: {rows}")
    # merge the same-name group: it asks first, and Keep editing leaves everything as it was
    page.click("#dup-auto")
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-no")
    page.wait_for_selector("#dup-auto", timeout=3000)
    if len(dup_slugs()) != 5:
        failures.append("declining the confirmation still merged something")
    page.click("#dup-auto")
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-yes")
    page.wait_for_function("!document.querySelector('#dup-auto') && document.querySelectorAll('[data-restore]').length === 1", timeout=6000)
    if dup_slugs() != ["bram-halloran", "dame-vesper", "vesper", "vesper-ann-marie"]:
        failures.append(f"merging the same-name group changed {dup_slugs()}")
    if "canon" not in page.inner_text("#modal-card").lower() or "rebuilt" not in page.inner_text("#modal-card"):
        failures.append("the dialog does not say that the memory reader keeps the old names until it is rebuilt")
    # nothing ticked is refused with a word, not a question
    n_backups = page.evaluate("document.querySelectorAll('[data-restore]').length")
    page.uncheck(".dup-fold[value='vesper']")
    page.uncheck(".dup-fold[value='vesper-ann-marie']")
    page.click("[data-merge='0']")
    page.wait_for_timeout(400)
    if page.locator("#cm-yes").count() or page.evaluate("document.querySelectorAll('[data-restore]').length") != n_backups or len(dup_slugs()) != 4:
        failures.append("a merge with nothing ticked went ahead or asked a question")
    # the cluster: untick one, tick the keeper's own box too (it is never folded into itself), the rest fold into the keeper
    page.check(".dup-fold[value='vesper']")
    page.check(".dup-fold[value='dame-vesper']")
    # declining the question changes nothing, for a cluster as for the same-name group (a cluster is the author's call, so it is asked
    # about most of all)
    page.click("[data-merge='0']")
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-no")
    page.wait_for_selector("[data-merge='0']", timeout=3000)
    if len(dup_slugs()) != 4 or page.evaluate("document.querySelectorAll('[data-restore]').length") != 1:
        failures.append(f"declining the cluster merge still merged or backed up: {dup_slugs()}")
    # the question repaints the dialog with the default ticks (everyone but the keeper), so choose again
    page.uncheck(".dup-fold[value='vesper-ann-marie']")
    page.check(".dup-fold[value='dame-vesper']")
    page.click("[data-merge='0']")
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-yes")
    page.wait_for_function("document.querySelectorAll('[data-restore]').length === 2", timeout=6000)
    if dup_slugs() != ["bram-halloran", "dame-vesper", "vesper-ann-marie"]:
        failures.append(f"merging the ticked entries of a cluster changed {dup_slugs()}")
    # restore the oldest backup: everything is back
    oldest = page.locator("[data-restore]").last
    oldest.click()
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-yes")
    page.wait_for_function("document.querySelectorAll('[data-restore]').length === 3", timeout=6000)
    if len(dup_slugs()) != 5:
        failures.append(f"restoring the first backup left {dup_slugs()}")
    close_modal()
    print("45) the Duplicates dialog merges same-name entries and chosen ones, asks first, backs up, and restores")

    # 46-48) The creation buttons (D-066). A refusal is said in a toast and the dialog stays with what was typed (the "Begin" of a new
    #     story used to be an unguarded call: a world deleted in another window left the dialog open and silent), a double click makes
    #     ONE thing (two stories, two "Untitled World"s, two characters before), and a piece may not take another piece's name.
    # Slows the matching write by 600 ms so a second click lands while the first is in flight, and COUNTS the writes the page sent. The
    # count is the evidence: two concurrent creates race to the same folder name on the server, so the store can show one world or
    # one story although two requests went out (counting results let five broken buttons through).
    slow_post_js = """(pat) => { const f = window.fetch.bind(window); window.__realFetch = window.fetch; window.__slowCalls = 0;
        window.fetch = (u, o) => { const hit = typeof u === 'string' && new RegExp(pat).test(u) && o && (o.method === 'POST' || o.method === 'PUT');
          if (hit) window.__slowCalls += 1;
          return hit ? new Promise(r => setTimeout(r, 600)).then(() => f(u, o)) : f(u, o); }; }"""
    clear_toast_js = "() => { const t = document.querySelector('#toast'); if (t) t.textContent = ''; }"
    toast_js = "() => (document.querySelector('#toast') || {}).textContent || ''"

    def saves_titled(title):
        return sum(1 for x in c.get("/api/saves").json()["saves"] if x["title"] == title)

    def worlds_titled(title):
        return sum(1 for x in c.get("/api/saves").json()["scenarios"] if x["title"] == title)

    # 46) New story: a refusal is said and the dialog stays; a double click begins one story
    doomed = c.post("/api/scenarios", json={"title": "Doomed world", "premise": "A harbour."}).json()["slug"]
    # An earlier case reloaded the page, which brings the first-run gate back on a box with no model; skip it as case 7 does.
    page.evaluate("async () => { const nav = await import('/js/nav.js'); nav.invalidateReady(); nav.skipReadyCheck(); }")
    page.evaluate("location.hash = '#library'")
    page.wait_for_selector("#new-save", timeout=8000)
    page.click("#new-save")
    page.wait_for_selector("#ns-go", timeout=4000)
    page.select_option("#ns-scenario", doomed)
    page.fill("#ns-title", "Refused story")
    c.delete(f"/api/scenarios/{doomed}")                                     # deleted in another window while the dialog was open
    errors_before = len(errors)
    page.evaluate(clear_toast_js)
    page.click("#ns-go")
    try:
        page.wait_for_function("(document.querySelector('#toast') || {}).textContent.includes('gone')", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append(f"a refused new story said nothing: toast={page.evaluate(toast_js)!r}")
    if not page.locator("#ns-go").is_visible() or page.input_value("#ns-title") != "Refused story" or page.is_disabled("#ns-go"):
        failures.append("a refused new story closed the dialog, lost what was typed, or left Begin disabled")
    if saves_titled("Refused story") or len(errors) != errors_before:
        failures.append(f"a refused new story made a story or raised an unhandled error: {saves_titled('Refused story')} {errors[errors_before:]}")
    page.select_option("#ns-scenario", "")
    page.fill("#ns-title", "Once only")
    page.fill("#ns-premise", "A harbour town in winter.")
    page.evaluate(slow_post_js, r"^/api/saves$")
    page.dblclick("#ns-go")
    page.wait_for_function("location.hash.startsWith('#play/')", timeout=8000)
    page.wait_for_timeout(1200)                                              # a second request, if it was sent, has landed by now
    sent = page.evaluate("window.__slowCalls")
    page.evaluate("() => { window.fetch = window.__realFetch; }")
    if sent != 1:
        failures.append(f"a double click on Begin sent {sent} requests, not one")
    if saves_titled("Once only") != 1:
        failures.append(f"a double click on Begin made {saves_titled('Once only')} stories, not one")

    # 47) New world: a double click makes one world
    page.evaluate("location.hash = '#library'")
    page.wait_for_selector("#new-world", timeout=8000)
    worlds_before = worlds_titled("Untitled World")
    page.evaluate(slow_post_js, r"^/api/scenarios$")
    page.dblclick("#new-world")
    page.wait_for_function("location.hash.startsWith('#world/')", timeout=8000)
    page.wait_for_timeout(1200)                                              # a second request, if it was sent, has landed by now
    sent = page.evaluate("window.__slowCalls")
    page.evaluate("() => { window.fetch = window.__realFetch; }")
    if sent != 1:
        failures.append(f"a double click on New world sent {sent} requests, not one")
    if worlds_titled("Untitled World") != worlds_before + 1:
        failures.append(f"a double click on New world made {worlds_titled('Untitled World') - worlds_before} worlds, not one")

    # 48) A piece may not take another piece's name; Save runs once; a character needs a name
    w48 = c.post("/api/scenarios", json={"title": "Names world", "premise": "A harbour."}).json()["slug"]
    c.put(f"/api/scenarios/{w48}/pieces/characters.md", json={"entry": {"title": "Vesper", "body": "First."}})
    page.evaluate(f"location.hash = '#world/{w48}'")
    page.wait_for_selector("[data-newpiece='characters.md']", timeout=8000)
    page.click("[data-newpiece='characters.md']")
    page.wait_for_selector("#p-title", timeout=4000)
    page.fill("#p-title", "Vesper")
    errors_before = len(errors)
    page.evaluate(clear_toast_js)
    page.click("#p-save")
    try:
        page.wait_for_function("(document.querySelector('#toast') || {}).textContent.includes('There is already')", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append(f"a new piece with a taken name said nothing: toast={page.evaluate(toast_js)!r}")
    if not page.locator("#p-title").is_visible() or page.input_value("#p-title") != "Vesper" or page.is_disabled("#p-save"):
        failures.append("a refused piece closed its form, lost its title, or left Save disabled")
    full48 = lambda: {e["slug"]: e["body"] for e in c.get(f"/api/scenarios/{w48}/full").json()["pieces"]["characters.md"]}   # noqa: E731
    if full48() != {"vesper": "First."} or len(errors) != errors_before:
        failures.append(f"a refused piece changed the piece that was there, or raised an error: {full48()} {errors[errors_before:]}")
    page.fill("#p-title", "Mara")
    page.evaluate(clear_toast_js)
    page.evaluate(slow_post_js, r"/pieces/characters\.md$")
    page.dblclick("#p-save")
    page.wait_for_selector("#p-title", state="hidden", timeout=8000)
    page.wait_for_timeout(1200)                                              # a second request, if it was sent, has landed by now
    sent = page.evaluate("window.__slowCalls")
    page.evaluate("() => { window.fetch = window.__realFetch; }")
    if sent != 1:
        failures.append(f"a double click on Save piece sent {sent} requests, not one")
    if sorted(full48()) != ["mara", "vesper"] or "There is already" in page.evaluate(toast_js):
        failures.append(f"a double click on Save made a second request that was refused or doubled: {sorted(full48())} {page.evaluate(toast_js)!r}")
    # the character sheet in the library
    page.evaluate("location.hash = '#characters'")
    page.wait_for_selector("#new-piece", timeout=8000)
    page.click("#new-piece")
    page.wait_for_selector("#ch-name", timeout=4000)
    n_chars = len(c.get("/api/characters").json()["characters"])
    page.evaluate(clear_toast_js)
    page.click("#ch-save")
    try:
        page.wait_for_function("(document.querySelector('#toast') || {}).textContent.includes('needs a name')", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append(f"a character with no name said nothing: toast={page.evaluate(toast_js)!r}")
    if len(c.get("/api/characters").json()["characters"]) != n_chars or not page.locator("#ch-name").is_visible():
        failures.append("a nameless character was saved, or its dialog closed")
    page.fill("#ch-name", "Dbl Click")
    page.evaluate(slow_post_js, r"^/api/characters$")
    page.dblclick("#ch-save")
    page.wait_for_selector("#ch-name", state="hidden", timeout=8000)
    page.wait_for_timeout(1200)                                              # a second request, if it was sent, has landed by now
    sent = page.evaluate("window.__slowCalls")
    page.evaluate("() => { window.fetch = window.__realFetch; }")
    if sent != 1:
        failures.append(f"a double click on Save character sent {sent} requests, not one")
    made = [x for x in c.get("/api/characters").json()["characters"] if x["name"] == "Dbl Click"]
    if len(made) != 1:
        failures.append(f"a double click on Save made {len(made)} characters, not one")
    print("46-48) creation buttons: a refusal is said and the dialog stays, a double click makes one thing, a piece cannot take another's name")

    # 49) A refused delete (here: a turn is generating, 409) is said in a toast and the card stays. The delete of a world, a character
    #     and a library piece were unguarded calls: nothing was shown and the rejection went unhandled.
    refuse_delete = lambda route: (route.fulfill(status=409, content_type="application/json", body='{"detail": "A turn is generating."}')   # noqa: E731
                                   if route.request.method == "DELETE" else route.continue_())
    page.evaluate("location.hash = '#library'")
    page.wait_for_selector(".card[data-scen] [data-act='delete-scen']", timeout=8000)
    cards_before = page.locator(".card[data-scen]").count()
    errors_before = len(errors)
    page.route("**/api/scenarios/*", refuse_delete)
    page.evaluate(clear_toast_js)
    page.locator(".card[data-scen] [data-act='delete-scen']").first.click()
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-yes")
    try:
        page.wait_for_function("(document.querySelector('#toast') || {}).textContent.includes(\"Couldn't delete the world\")", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append(f"a refused world delete said nothing: toast={page.evaluate(toast_js)!r}")
    page.unroute("**/api/scenarios/*")
    if page.locator(".card[data-scen]").count() != cards_before or len(errors) != errors_before:
        failures.append(f"a refused world delete removed the card or raised an unhandled error: {errors[errors_before:]}")
    page.evaluate("location.hash = '#characters'")
    page.wait_for_selector(".card[data-id] [data-act='delete']", timeout=8000)
    chars_before = page.locator(".card[data-id]").count()
    page.route("**/api/characters/*", refuse_delete)
    page.evaluate(clear_toast_js)
    page.locator(".card[data-id] [data-act='delete']").first.click()
    page.wait_for_selector("#cm-yes", timeout=3000)
    page.click("#cm-yes")
    try:
        page.wait_for_function("(document.querySelector('#toast') || {}).textContent.includes(\"Couldn't delete the character\")", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append(f"a refused character delete said nothing: toast={page.evaluate(toast_js)!r}")
    page.unroute("**/api/characters/*")
    if page.locator(".card[data-id]").count() != chars_before or len(errors) != errors_before:
        failures.append(f"a refused character delete removed the card or raised an unhandled error: {errors[errors_before:]}")
    print("49) a refused delete of a world or a character says so and keeps the card")

    # 50) Dropping a library character into a world that already has one of that name is said in a toast, keeps the picker open and
    #     replaces nothing; a character that is new to the world goes in once even on a double click.
    vlib = c.post("/api/characters", json={"name": "Vesper", "description": "From the library."}).json()["id"]
    zlib = c.post("/api/characters", json={"name": "Zed Marrow", "description": "New to this world."}).json()["id"]
    page.evaluate(f"location.hash = '#world/{w48}'")
    page.wait_for_selector("[data-fromlib='characters.md']", timeout=8000)
    page.click("[data-fromlib='characters.md']")
    page.wait_for_selector(f"[data-lib='{vlib}']", timeout=4000)
    errors_before = len(errors)
    page.evaluate(clear_toast_js)
    page.click(f"[data-lib='{vlib}']")
    try:
        page.wait_for_function("(document.querySelector('#toast') || {}).textContent.includes('There is already')", timeout=4000)
    except Exception:  # noqa: BLE001
        failures.append(f"dropping in a character that is already there said nothing: toast={page.evaluate(toast_js)!r}")
    if not page.locator("#lib-cancel").is_visible() or full48().get("vesper") != "First." or len(errors) != errors_before:
        failures.append(f"a refused library drop closed the picker, replaced the piece, or raised an error: {full48()} {errors[errors_before:]}")
    page.evaluate(clear_toast_js)
    page.evaluate(slow_post_js, r"/from-library$")
    page.dblclick(f"[data-lib='{zlib}']")
    page.wait_for_selector("#lib-cancel", state="hidden", timeout=8000)
    page.wait_for_timeout(1200)                                              # a second request, if it was sent, has landed by now
    sent = page.evaluate("window.__slowCalls")
    page.evaluate("() => { window.fetch = window.__realFetch; }")
    if sent != 1:
        failures.append(f"a double click on a library drop sent {sent} requests, not one")
    if sorted(full48()) != ["mara", "vesper", "zed-marrow"] or "There is already" in page.evaluate(toast_js):
        failures.append(f"a double click on a library character did not add it exactly once: {sorted(full48())} {page.evaluate(toast_js)!r}")
    print("50) a library character already in the world is refused with a reason and the picker stays; a new one goes in once")

    browser.close()

srv.should_exit = True
shutil.rmtree(HOME, ignore_errors=True)

for e in errors:
    failures.append(f"console error: {e}")
for r in bad_requests:
    failures.append(f"bad response: {r}")
assert not failures, "SPA smoke failures:\n  " + "\n  ".join(failures)
print("\nWEBAPP SMOKE TESTS PASSED")

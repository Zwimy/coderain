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
    page.click("#stop")
    try:
        page.wait_for_function("!document.querySelector('#send').disabled && document.querySelector('#stop').classList.contains('hidden')", timeout=10000)
    except Exception:  # noqa: BLE001
        failures.append("the re-entered view never took over when the swipe ended: " + repr(page.evaluate(
            "({send: document.querySelector('#send').disabled, stage: document.querySelector('#stageline').textContent})")))
    if page.evaluate(tail_js)[-1] != "A third version, written by the swipe.":
        failures.append(f"a swipe stopped from another visit lost the exchange: {page.evaluate(tail_js)}")
    print("29) retry keeps the old text as a version; a failed, empty or stopped retry or swipe puts the exchange back and says so")

    browser.close()

srv.should_exit = True
shutil.rmtree(HOME, ignore_errors=True)

for e in errors:
    failures.append(f"console error: {e}")
for r in bad_requests:
    failures.append(f"bad response: {r}")
assert not failures, "SPA smoke failures:\n  " + "\n  ".join(failures)
print("\nWEBAPP SMOKE TESTS PASSED")

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
 6) an empty Continue is reported to the reader, not swallowed.
"""
import os
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
        body = page.inner_text("#view").strip()
        if len(body) < 20:
            failures.append(f"{view} rendered almost nothing: {body!r}")
    print(f"1) {len(VIEWS)} views render")

    # --- modals that cross module boundaries -----------------------------
    page.evaluate(f"location.hash = '#play/{slug}'")
    page.wait_for_selector("#mem-btn", timeout=8000)
    def close_modal():
        """Escape depends on where focus is; the backdrop click does not."""
        page.evaluate("document.querySelector('#modal-back').click()")
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
        return page.inner_text("#modal-card")

    open_panel("plan-btn", "Chapter plan")
    close_modal()
    open_panel("mem-btn", "What this story remembers")
    close_modal()
    # the real token counts must reach the panel, not the /4 estimate
    ctx = open_panel("ctx-btn", "What the model sees")
    if "what it has cost" not in ctx.lower():
        failures.append("the Context panel is missing the token ledger")
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

    browser.close()

srv.should_exit = True
shutil.rmtree(HOME, ignore_errors=True)

for e in errors:
    failures.append(f"console error: {e}")
for r in bad_requests:
    failures.append(f"bad response: {r}")
assert not failures, "SPA smoke failures:\n  " + "\n  ".join(failures)
print("\nWEBAPP SMOKE TESTS PASSED")

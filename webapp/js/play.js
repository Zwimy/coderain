/* The play view: transcript, composer, sheet, companion drawer, and the Memory and Canon dialogs that close over the view. The chapter plan,
   the context inspector and the fold review are their own modules (outline.js, context.js, folds.js): they use nothing of the view. */
import {$, api, copyText, esc, guard, renderProse, sse, toast, view} from "./util.js";
import {watchLabels} from "./a11y.js";
import {canonModal} from "./canon.js";
import {attachFind} from "./find.js";
import {createTurnMenu} from "./turnmenu.js";
import {displayModal} from "./display.js";
import {duplicatesModal} from "./duplicates.js";
import {outlineModal} from "./outline.js";
import {contextModal} from "./context.js";
import {foldReview} from "./folds.js";
import {
  closeModal,
  confirmModal,
  openModal,
  promptModal
} from "./modal.js";

/* ---------- play ---------- */
export let busy = false;
// Which story a run() is generating for, and the views opened while it runs (they repaint when it ends). The flag above is
// app-wide but the Stop button, the aborter and the transcript belong to ONE view: leave Play mid-turn and come back, and
// Send did nothing and there was no Stop, because the new view knew nothing of the run the old one had started.
let runningSlug = null;
const runEndHooks = new Set();

export let _playKeys = null;          // the play view's keydown handler, so it can be swapped

export async function renderPlay(slug) {
  const s = await api(`/api/saves/${slug}`);
  s.companions = s.companions || [];        // never deref undefined (play head + Talk)
  view.innerHTML = `<div id="play" data-view="story">
    ${s.rpg ? `<div id="view-tabs" role="tablist" aria-label="Story or character sheet">
      <button role="tab" id="tab-story" aria-selected="true" aria-controls="story-col">Story</button>
      <button role="tab" id="tab-sheet" aria-selected="false" tabindex="-1" aria-controls="sheet">Sheet</button>
    </div>` : ""}
    <div id="story-col">
      <div id="play-head">
        <button id="back">← Library</button>
        <div class="title">${esc(s.title)}</div>
        <div class="clock">${esc(s.clock || "")}</div>
        <button id="edit-btn" title="edit this story's characters, lore &amp; world"
          >Edit</button>
        <button id="note-btn" title="author's note: steer tone &amp; pacing"
          >Note</button>
        <button id="mem-btn" title="inspect &amp; repair what the story remembers"
          >Memory</button>
        <button id="plan-btn" title="the rolling chapter plan: steer the story ahead"
          >Plan</button>
        <button id="ctx-btn" title="what the model actually receives this turn"
          >Context</button>
        <button id="canon-btn" title="what the story remembers about each person, and your corrections to it"
          >Canon</button>
        <button id="talk-btn" ${s.companions.length ? "" : "disabled"}
          title="${s.companions.length ? "private companion chat"
                 : "no companions yet"}">Talk</button>
        <button id="find-btn" aria-expanded="false" aria-controls="find-bar"
          title="find a word in this story">Find</button>
        <button id="display-btn" aria-label="Display settings" title="text size and background rain">Aa</button>
      </div>
      <!-- Outside #transcript on purpose: the pen and retry address a turn by its position in it, so nothing may be added there. -->
      <div id="find-bar" role="search" aria-label="Find in the story" hidden>
        <input id="find-q" type="search" placeholder="Find in the story" aria-label="Find in the story" autocomplete="off">
        <span id="find-count" role="status" aria-live="polite"></span>
        <button id="find-prev" aria-label="Previous match">↑</button>
        <button id="find-next" aria-label="Next match">↓</button>
        <button id="find-close" aria-label="Close find">✕</button>
      </div>
      <div id="transcript" aria-label="Story"></div>
      <!-- role=status announces progress WITHOUT stealing focus. Deliberately
           NOT on #transcript: role=status implies aria-atomic, so a live region
           around streaming prose would re-announce the whole passage on every
           chunk. The turn itself carries aria-busy while it streams. -->
      <div id="stageline" role="status" aria-live="polite"></div>
      <div id="eventbar"></div>
      <div id="composer">
        <div id="play-actions">
          <button id="continue">Continue</button>
          <button id="undo">Undo</button>
          <button id="retry">Retry</button>
          <button id="branch">Branch…</button>
          <button id="aids-btn" title="quick actions &amp; output cleanup rules"
            >Quick actions</button>
          <button id="stop" class="hidden" title="stop generating">■ Stop</button>
        </div>
        <div id="quick-bar"></div>
        <div id="composer-inner">
          <button id="suggest" title="let the AI draft your next action" aria-label="Draft my next action with AI">✍</button>
          <textarea id="action" placeholder="What do you do?"></textarea>
          <button class="primary" id="send">Send</button>
        </div>
      </div>
    </div>
    ${s.rpg ? '<aside id="sheet"></aside>' : ""}
  </div>`;

  const transcript = $("#transcript");
  attachFind({transcript, bar: $("#find-bar"), button: $("#find-btn")});
  // Below 900px the story and the character sheet do not fit side by side: the sheet is a tab (above that the tabs are hidden and
  // both show). The sheet used to be display:none there, so an RPG story on a phone had no way to see its own sheet.
  const tabs = $("#view-tabs");
  if (tabs) {
    const showTab = which => {
      $("#play").dataset.view = which;
      for (const b of tabs.querySelectorAll("[role=tab]")) {
        const on = b.id === `tab-${which}`;
        b.setAttribute("aria-selected", String(on));
        b.tabIndex = on ? 0 : -1;
      }
    };
    tabs.addEventListener("click", ev => {
      const tab = ev.target.closest("[role=tab]");
      if (tab) showTab(tab.id.replace("tab-", ""));
    });
    tabs.addEventListener("keydown", ev => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      const next = $("#play").dataset.view === "story" ? "sheet" : "story";
      showTab(next);
      $(`#tab-${next}`).focus();
    });
  }
  $("#display-btn").addEventListener("click", displayModal);
  const stage = $("#stageline");
  const evbar = $("#eventbar");
  let swipe = s.swipes || {count: 1, idx: 0};      // ST-02 state for the last narrator turn (the server knows which is showing)

  const bodyOf = d => d.querySelector(".turn-body");
  const paint = (d, text) => {         // set a turn's text (markdown for prose)
    d._raw = text;
    const b = bodyOf(d);
    if (d.classList.contains("narrator")) b.innerHTML = renderProse(text);
    else b.textContent = text;
  };
  const addTurn = (role, text) => {
    const d = document.createElement("div");
    d.className = `turn ${role}`;
    const body = document.createElement("span");
    body.className = "turn-body";
    d.appendChild(body);
    const pen = document.createElement("button");
    pen.className = "turn-edit"; pen.textContent = "✎"; pen.title = "edit";
    pen.setAttribute("aria-label", role === "player" ? "Edit your action" : "Edit this reply");   // a bare ✎ is read as a pencil, and there is one per turn
    pen.addEventListener("click", () => startEdit(d));   // ST-03
    d.appendChild(pen);
    d.appendChild(turnMenu.trigger(d));
    paint(d, text);
    transcript.appendChild(d);
    transcript.scrollTop = transcript.scrollHeight;
    return d;
  };
  const lastNarrator = () =>
    [...transcript.children].reverse().find(d =>
      d.classList.contains("narrator"));

  // ST-03: in-place message editor
  const startEdit = d => {
    if (busy || d.querySelector(".turn-editor")) return;
    const idx = [...transcript.children].indexOf(d);
    const body = bodyOf(d);
    const ta = document.createElement("textarea");
    ta.className = "turn-editor"; ta.value = d._raw ?? body.textContent;
    const bar = document.createElement("div");
    bar.className = "turn-editbar";
    bar.innerHTML = '<button class="mini primary sv">Save</button>'
                  + '<button class="mini cx">Cancel</button>';
    body.style.display = "none";
    d.append(ta, bar); ta.focus();
    const close = () => { ta.remove(); bar.remove(); body.style.display = ""; };
    bar.querySelector(".cx").onclick = close;
    bar.querySelector(".sv").onclick = async () => {
      const text = ta.value.trim();
      try {
        await api(`/api/saves/${slug}/turns/${idx}`,
                  {method: "PUT", body: {text}});
      } catch (e) { toast(e.message); return; }
      paint(d, text); close();
    };
  };

  // The per-turn menu (D-056 item 11). Branching is offered on a reply only: a fork that ends on the player's own action has no
  // reply to continue from (D-006's snapshots are taken after a reply). Regenerating is offered on the last reply only, because
  // an earlier one cannot be rewritten without rewriting everything after it.
  const copyTurn = async d => {
    try { await copyText(d._raw ?? bodyOf(d).textContent); toast("Copied.", "ok"); }
    catch (_e) { toast("Couldn't copy. Select the text and copy it by hand."); }
  };
  const branchFrom = async d => {
    const n = [...transcript.querySelectorAll(".turn")].indexOf(d) + 1;
    if (!await confirmModal("Branch from here?",
        "Copies the story up to this reply and opens the copy. This story stays as it is.", "Branch")) return;
    const out = await guard(() => api(`/api/saves/${slug}/branch`, {method: "POST", body: {turn: n}}), "Couldn't branch");
    if (!out) return;
    if (out.warnings && out.warnings.length) toast(out.warnings.join("\n"));
    location.hash = `#play/${out.slug}`;
  };
  const turnMenu = createTurnMenu({transcript, itemsFor: d => {
    const reply = d.classList.contains("narrator");
    const wait = "Wait for the reply to finish.";
    const items = [
      {label: "Edit", run: () => startEdit(d), disabled: busy, why: wait},
      {label: "Copy text", run: () => copyTurn(d)},
    ];
    if (reply) items.push({label: "Branch from here", run: () => branchFrom(d), disabled: busy, why: wait});
    if (reply && d === lastNarrator()) {
      items.push({label: "Regenerate this reply", run: () => $("#retry").click(), disabled: busy, why: wait});
    }
    return items;
  }});

  // ST-02: swipe control on the last narrator turn
  const renderSwipeBar = () => {
    transcript.querySelectorAll(".swipebar").forEach(b => b.remove());
    const d = lastNarrator();
    if (!d) return;
    const bar = document.createElement("div");
    bar.className = "swipebar";
    // Labelled: "◄ 1/1 ►" gave no clue that ► GENERATES a new alternative.
    bar.innerHTML =
      `<button class="mini swl" title="previous version (left arrow)"
         aria-label="Previous version" ${swipe.idx ? "" : "disabled"}>◄</button>`
      + `<span ${swipe.count > 1 ? 'title="Earlier versions are kept until your next move."' : ""}
           >Version ${swipe.idx + 1} of ${swipe.count}</span>`
      + `<button class="mini swr" aria-label="Next or new version"
           title="next version: at the end, writes a new one (right arrow)"
           >►</button>`
      + `<span class="hint muted">${swipe.idx + 1 === swipe.count
          ? "› writes a new one" : ""}</span>`;
    d.appendChild(bar);
    bar.querySelector(".swl").onclick = () => swipeMove(-1);
    bar.querySelector(".swr").onclick = () => swipeMove(1);
  };
  let swiping = false;                  // serialize ◄/► so fast clicks can't race
  const swipeMove = async dir => {
    if (busy || swiping) return;
    swiping = true;
    try {
      if (dir < 0) {
        if (swipe.idx === 0) return;
        const out = await api(`/api/saves/${slug}/swipe`,
                              {method: "POST", body: {dir: -1}});
        paint(lastNarrator(), out.text); swipe = {count: out.count, idx: out.idx};
        renderSwipeBar();
      } else if (swipe.idx + 1 < swipe.count) {
        const out = await api(`/api/saves/${slug}/swipe`,
                              {method: "POST", body: {dir: 1}});
        paint(lastNarrator(), out.text); swipe = {count: out.count, idx: out.idx};
        renderSwipeBar();
      } else {
        await swipeGen();               // past the end → generate a new one
      }
    } finally { swiping = false; }
  };
  const swipeGen = async () => {
    const d = lastNarrator();
    if (!d || busy) return;
    setBusy(true); stage.textContent = "Thinking…";
    runningSlug = slug;
    $("#stop").classList.remove("hidden");
    $("#stop").disabled = false;          // Stop works here too: the exchange is put back, so it cannot lose anything (D-057)
    const body = bodyOf(d); body.textContent = ""; d.classList.add("pending");
    transcript.querySelectorAll(".swipebar, .turn-error, .turn-note").forEach(b => b.remove());
    let failedSwipe = null;
    // Only a COMPLETED generation becomes a variant. The `done` frame is the
    // signal, not the first chunk: Stop mid-stream leaves prose on screen that
    // the server never stored, and counting that enabled a ◄ pointing at a
    // variant which does not exist — which then wrote it over a real turn.
    let serverTurns = null;
    const before = domTurns();
    try {
      await sse(`/api/saves/${slug}/swipe-gen`, undefined, {
        stage: m => { stage.textContent = m.text; },
        chunk: m => { d.classList.remove("pending"); body.textContent += m.text;
                      transcript.scrollTop = transcript.scrollHeight; },
        done: m => { serverTurns = m.turns;
                     setEvents(m.events); setSheet(m.sheet || []);
                     $(".clock").textContent = m.clock || "";
                     if (m.text != null) body._settle = m.text; stage.textContent = ""; },
        error: m => { failedSwipe = m; },
      });
    } catch (e) { failedSwipe = {code: "network", text: e.message}; }
    d.classList.remove("pending");
    stage.textContent = "";
    $("#stop")?.classList.add("hidden");
    // The store's turn COUNT decides, not the arrival of a `done` frame. `done`
    // also fires when the regeneration produced nothing: the server has already
    // deleted the exchange and dropped its swipe state, so counting a variant
    // there left a ghost bubble reading "Version 2 of 2" over a transcript two
    // turns shorter, and the next ◄ painted the previous exchange's prose into
    // it — the same text twice on screen, and ✎ addressing turns that are gone.
    // Also when NOTHING streamed. The count is not sufficient on its own: if
    // the tail is not a narrator turn (a quad turn whose Director applied
    // deltas but whose Writer wrote nothing keeps the player turn and stores no
    // narration), swipe_generate refuses and returns without doing anything —
    // so the count matches, and this fell through to paint the buffer it had
    // just cleared OVER a real stored turn, under a bar advertising a variant
    // that does not exist.
    if (serverTurns !== before || !body.textContent.trim()) {
      runningSlug = null;
      setBusy(false);
      await resync();                       // the server put the exchange back, so this shows it
      if (failedSwipe) {
        failedSwipe.restored = domTurns() === before;
        showTurnError(failedSwipe, null);
      }
      for (const hook of [...runEndHooks]) { runEndHooks.delete(hook); hook(); }
      return;
    }
    if (body._settle && body.textContent) body.textContent = body._settle;
    paint(d, body.textContent);
    swipe = {count: swipe.count + 1, idx: swipe.count};
    runningSlug = null;
    setBusy(false); renderSwipeBar();
    for (const hook of [...runEndHooks]) { runEndHooks.delete(hook); hook(); }
  };
  const setSheet = lines => {
    const el = $("#sheet");
    if (el) el.innerHTML =
      '<div class="sheet-title">Character</div>' + esc(lines.join("\n"));
  };
  const setEvents = events => {
    // A fold event is the one worth acting on: ten turns just became a
    // paragraph, and from here on the model sees the paragraph. Make it a
    // button so the review is one click away at the moment it happens —
    // NOT a modal that interrupts reading every ten messages.
    evbar.innerHTML = (events || []).map(e => {
      const fold = e.startsWith("memory: folded scene");
      return fold
        ? `<button class="evt fold" data-fold="1"
             title="see what this fold wrote into memory">${esc(e)} ·
             review</button>`
        : `<span class="evt ${e.startsWith("validator:") ? "warn" : ""}">
             ${esc(e)}</span>`;
    }).join("");
    evbar.querySelectorAll("[data-fold]").forEach(b =>
      b.addEventListener("click", () => foldReview(slug)));
  };

  const setBusy = on => {
    // The FLAG is app-wide and must always be written, even for a detached
    // view. Returning early here latched `busy` on forever when the user left
    // the play view mid-stream: every control looked enabled and did nothing
    // for the rest of the session, with no error, and only a reload recovered.
    busy = on;
    // The NODES, though, belong to a page that may no longer be on screen — a
    // still-pending run must not toggle the new page's controls.
    if (!document.body.contains(transcript)) return;
    ["send", "continue", "undo", "retry", "branch", "suggest"].forEach(id => {
      const b = $("#" + id); if (b) b.disabled = on;
    });
    transcript.querySelectorAll(".swipebar button, .turn-edit")
      .forEach(b => b.disabled = on);
  };
  /* Repaint the transcript from the server's truth. After a failed turn the DOM
     and the store can disagree, and turn indices are derived from DOM position —
     so an edit would PUT to the wrong index and rewrite a different turn. */
  /* How many turns the DOM currently shows. Turn indices are DOM POSITION, so
     this must equal the store's count or ✎ edits and swipes address the wrong
     turn. Call it only once the in-flight bubbles have settled (an empty one is
     removed, a real one painted), which is when both are stored turns. */
  const domTurns = () => transcript.querySelectorAll(".turn").length;

  /* The `done` frame carries the store's authoritative turn count. Believing the
     stream instead was the bug: a generation that COMPLETES but stores nothing —
     prose-less output, deltas all rejected, or an ST-31 rule that empties the
     turn — sends `done`, not `error`, so the optimistic player bubble survived
     and the DOM went one turn ahead of the store. The next ✎ then PUT the edit
     to a neighbouring index and rewrote a different turn on disk, silently. */
  const reconcile = async (serverTurns) => {
    if (typeof serverTurns !== "number" || serverTurns === domTurns()) return false;
    await resync();
    return true;
  };

  const resync = async () => {
    try {
      const fresh = await api(`/api/saves/${slug}`);
      transcript.innerHTML = "";
      (fresh.turns || []).forEach(t => addTurn(t.role, t.text));
      swipe = fresh.swipes || {count: 1, idx: 0};
      renderSwipeBar();
    } catch (_e) { /* offline: leave what's on screen rather than blanking it */ }
  };

  /* An error the user can actually see and act on, in the transcript where the
     turn failed — the old 11.5px stageline was below the fold and had no retry. */
  const showTurnError = (msg, retryFn) => {
    if (msg.code === "aborted") {
      // The reader pressed Stop: that is what they asked for, not a failure. It used to be the red alert card with a
      // "Check settings" button.
      const note = document.createElement("div");
      note.className = "turn-note";
      note.setAttribute("role", "status");
      note.textContent = msg.restored ? "Stopped. Your earlier version is back." : "Stopped.";
      transcript.appendChild(note);
      transcript.scrollTop = transcript.scrollHeight;
      return;
    }
    const box = document.createElement("div");
    box.className = "turn-error";
    box.setAttribute("role", "alert");
    const title = msg.code === "busy" ? "Already generating"
      : msg.code === "auth" ? "The API key was rejected"
      : msg.code === "connection" ? "Can't reach the model"
      : msg.code === "context" ? "This story is too long for the model"
      : msg.code === "restored" ? "Nothing new came back"
      : msg.code === "aborted" ? "Stopped" : "That turn didn't go through";
    // "restored" already says it; any other failure of a retry or a swipe adds that the earlier version is back
    const back = msg.restored && msg.code !== "restored" ? " Your earlier version is back." : "";
    box.innerHTML = `<b>${esc(title)}</b><p>${esc((msg.text || "") + back)}</p>`;
    const row = document.createElement("div");
    row.className = "row";
    if (retryFn && msg.code !== "aborted") {
      const again = document.createElement("button");
      again.className = "primary"; again.textContent = "Try again";
      again.addEventListener("click", () => { box.remove(); retryFn(); });
      row.appendChild(again);
    }
    const settings = document.createElement("button");
    settings.textContent = "Check settings";
    settings.addEventListener("click", () => { location.hash = "#settings"; });
    row.appendChild(settings);
    box.appendChild(row);
    transcript.appendChild(box);
    transcript.scrollTop = transcript.scrollHeight;
  };

  let aborter = null;
  /* `ownsRepaint`: the caller repaints from server truth itself, so run() must
     not claim the turn was discarded when the DOM and the store differ. Retry
     deliberately leaves the old exchange on screen while it regenerates (see its
     handler), so a SUCCESSFUL retry ends this function one turn ahead — which is
     not a rollback and must not be reported as one. */
  const run = async (path, body, playerText, ownsRepaint) => {
    if (busy) return;
    setBusy(true);
    runningSlug = slug;
    evbar.innerHTML = "";
    transcript.querySelectorAll(".turn-error, .turn-note").forEach(b => b.remove());
    transcript.querySelectorAll(".swipebar").forEach(b => b.remove());
    // Elapsed time + a hint once the wait passes Nielsen's 10s attention limit:
    // a 30s+ planner stage under a static "Thinking…" reads as a hang.
    const t0 = Date.now();
    let label = "Thinking…";
    stage.textContent = label;
    const ticker = setInterval(() => {
      const s = Math.round((Date.now() - t0) / 1000);
      const hint = s >= 10 ? ". The planning stage can take a while on local models" : "";
      stage.textContent = `${label} ${s}s${hint}`;
    }, 1000);
    aborter = new AbortController();
    $("#stop").classList.remove("hidden");
    $("#stop").disabled = false;      // was disabled after a prior Stop click

    // BEFORE the optimistic bubbles go in. Taken after them, this counted the
    // in-flight nodes as stored turns, so `serverTurns < storeBefore` fired on
    // every SUCCESSFUL retry — the exact case the comment below claimed it had
    // stopped. Four commits have now touched this branch and the arithmetic is
    // the part that keeps going wrong, so it is measured where its name is true.
    const storeBefore = domTurns();
    const optimistic = playerText !== undefined ? addTurn("player", playerText) : null;
    const live = addTurn("narrator", "");
    const liveBody = bodyOf(live);
    live.classList.add("pending");   // blinking caret until prose streams in
    live.setAttribute("aria-busy", "true");
    let settled = null;                  // ST-31: the regex-cleaned stored text
    let serverTurns = null;              // the store's authoritative turn count
    let streamed = false;                // did any NON-EMPTY chunk arrive
    let failed = null;
    try {
      await sse(path, body, {
        stage: m => { label = m.text; },
        chunk: m => { if (m.text) streamed = true;   // an EMPTY chunk is not prose
                      live.classList.remove("pending");
                      liveBody.textContent += m.text;
                      transcript.scrollTop = transcript.scrollHeight; },
        done: m => { setEvents(m.events); setSheet(m.sheet || []);
                     // Optional chaining on EVERY document-wide lookup in this
                     // function, not just #stop. With the play view detached a
                     // null deref here throws inside the SSE callback, sse()
                     // rejects, and the failure path below then derefs #action
                     // — uncaught, so run() never reaches setBusy(false) and
                     // the app-wide busy flag stays latched for the session.
                     const clk = $(".clock"); if (clk) clk.textContent = m.clock || "";
                     serverTurns = m.turns;
                     if (m.text != null) settled = m.text; },
        error: m => { failed = m; },
      }, aborter.signal);
    } catch (e) {
      failed = e.name === "AbortError"
        ? {code: "aborted", text: "You stopped this turn."}
        : {code: "network", text: e.message};
    }
    clearInterval(ticker);
    stage.textContent = "";
    // Optional chaining: when the stream ends while the user is on another
    // view, #stop is gone and this threw a TypeError that killed run() before
    // its terminal setBusy(false) — the second route to a permanently locked UI.
    $("#stop")?.classList.add("hidden");
    aborter = null;
    live.classList.remove("pending");
    live.removeAttribute("aria-busy");
    // ST-31: settle the raw streamed turn onto the cleaned, stored version. Only a
    // NON-EMPTY settle applies — an empty done.text must never wipe a good turn.
    if (settled && liveBody.textContent) liveBody.textContent = settled;
    if (!liveBody.textContent) live.remove();
    else paint(live, liveBody.textContent);   // ST-06: apply markdown

    if (failed) {
      // The server stored nothing, so the optimistic player bubble would leave
      // the DOM one turn AHEAD of the transcript.
      if (optimistic) optimistic.remove();
      // Repaint from server truth BEFORE showing the card — resync() rebuilds
      // the transcript, so a card appended first would be wiped out again.
      await resync();
      // NO "Try again" for a destructive path. /retry rolls the last exchange
      // back before it regenerates, so re-issuing it hits whatever exchange is
      // now last: after a failed retry the button destroyed a DIFFERENT,
      // healthy exchange, and on a one-exchange story it replaced the whole
      // story with a fresh opening. The retry hotkey is still there when the
      // reader actually wants that.
      const destructive = /\/(retry|swipe-gen)$/.test(path);
      // The server puts the exchange back when a retry fails, is stopped or comes back empty (D-057): say so when the
      // story on screen is the length it was.
      failed.restored = destructive && domTurns() === storeBefore;
      showTurnError(failed, destructive ? null
        : playerText !== undefined ? () => run(path, body, playerText)
        : () => run(path, body));
      const action = $("#action");
      if (playerText !== undefined && action && !action.value) {
        action.value = playerText;            // never lose what they typed
      }
    } else if (typeof serverTurns === "number" && serverTurns < storeBefore) {
      // The story is SHORTER than before this run — turns were rolled back and
      // not replaced. This branch exists for retry, which owns its repaint and
      // is therefore skipped by the one below: a retry whose regeneration came
      // back empty deleted the exchange in silence, and that is the one
      // destructive path that most needs to speak up.
      await resync();
      toast("That turn produced nothing and was discarded.", "info");
    } else if (!ownsRepaint && await reconcile(serverTurns)) {
      // Same length, but the screen is ahead of the store — the turn produced
      // nothing and its optimistic bubble has to go. Retry is exempt: it
      // legitimately ends one bubble ahead while it regenerates.
      toast("That turn produced nothing and was discarded.", "info");
    } else if (!streamed && domTurns() === storeBefore) {
      // Continue. It is the one caller with NEITHER property the two branches
      // above rely on: it appends no optimistic bubble (so the DOM never runs
      // ahead) and it stores nothing (so the story never gets shorter). An
      // empty Continue was therefore reported nowhere — the reader clicked,
      // watched "Thinking… 14s", and got back an unchanged screen in silence.
      // Keyed on the DOM, not on the done frame's count: an empty generation
      // does not always deliver one, and a branch that silently does nothing
      // when its input is null is how this was missed the first time. By here
      // the live bubble is already removed if it stayed empty, so domTurns()
      // is the store's count whenever nothing was stored.
      //
      // Added as a separate branch rather than by loosening one above, because
      // Send and retry are already caught earlier in this chain and must not
      // move: Send-empty keeps its optimistic bubble (so the DOM is ahead and
      // reconcile catches it) and retry-empty makes the story shorter.
      // Invariant 2: degrading is fine, degrading invisibly is not.
      toast("That turn produced nothing and was discarded.", "info");
    }
    // A fresh turn resets alternates. A retry keeps the old text as one, and its handler reads the real state from the server
    // (resync) once this returns. A FAILED run has just done that itself (a failed retry puts the old versions back): leave it.
    if (!failed) swipe = {count: 1, idx: 0};
    renderSwipeBar();
    runningSlug = null;
    setBusy(false);
    for (const hook of [...runEndHooks]) { runEndHooks.delete(hook); hook(); }   // views opened while this ran
    return !failed;                 // callers must not repaint over the error card
  };

  $("#stop").addEventListener("click", () => {
    toast("Stopping…", "info");
    $("#stop").disabled = true;
    // Cooperative cancel: the server sends a clean 'aborted' frame and drops the
    // half-written turn itself. Aborting the fetch instead would race that
    // cleanup and could leave the DOM out of step with the file. The stream
    // closes on its own once the server bails, and run()'s error path resyncs.
    api(`/api/saves/${slug}/cancel`, {method: "POST"}).catch(() => {});
  });

  s.turns.forEach(t => addTurn(t.role, t.text));
  setSheet(s.sheet || []);
  renderSwipeBar();

  // A turn started in an earlier visit is still generating. Say so, keep this view's controls off until it ends, offer Stop
  // when it is THIS story's turn (Stop cancels the story this view shows), and repaint from the store when it is over: the
  // run that finishes paints into a view that is gone.
  if (busy) {
    const mine = runningSlug === slug;
    setBusy(true);
    stage.textContent = mine ? "Still generating the turn you started…"
      : "A turn in another story is still generating…";
    if (mine) { $("#stop").classList.remove("hidden"); $("#stop").disabled = false; }
    runEndHooks.add(async () => {
      if (!document.body.contains(transcript)) return;
      // Repaint BEFORE the controls come back. They used to come back first, so for the length of one request Send was live
      // over a transcript that still showed the half-finished exchange (a smoke case saw it about one run in ten). resync()
      // swallows its own errors, so the controls are released either way.
      if (mine) await resync();
      if (!document.body.contains(transcript)) return;       // the reader left while it repainted
      stage.textContent = "";
      $("#stop")?.classList.add("hidden");
      setBusy(false);
    });
  }

  $("#suggest").addEventListener("click", async () => {
    if (busy) return;
    const b = $("#suggest"); b.disabled = true; const was = b.textContent;
    b.textContent = "…";
    // Capture THIS view's composer, and check it is still on screen when the
    // model answers. $("#action") is a document-wide lookup resolved after a
    // round-trip, so opening another story mid-suggest wrote story A's action
    // into story B's composer — one Enter away from committing it to B.
    const composer = $("#action");
    try {
      const out = await api(`/api/saves/${slug}/impersonate`, {method: "POST"});
      if (composer.isConnected) { composer.value = out.text; composer.focus(); }
    } catch (e) { toast(e.message); }
    if (b.isConnected) { b.disabled = false; b.textContent = was; }
  });

  const send = async () => {
    const text = $("#action").value.trim();
    if (!text || busy) return;
    $("#action").value = "";
    await run(`/api/saves/${slug}/turn`, {text}, text);
  };
  $("#send").addEventListener("click", send);
  $("#action").addEventListener("keydown", ev => {
    // isComposing: without it, Japanese/Chinese/Korean users fire a turn while
    // still composing a word with the IME.
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault(); send();
    }
  });

  /* Keyboard shortcuts. There were none beyond Enter-to-send; SillyTavern users
     in particular expect arrow-key swiping. Ignored while typing or in a modal. */
  const playKeys = ev => {
    if (!document.body.contains(transcript)) return;      // view changed
    if (!$("#modal-root").classList.contains("hidden")) return;
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
              || t.isContentEditable)) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key === "ArrowLeft") { ev.preventDefault(); swipeMove(-1); }
    else if (ev.key === "ArrowRight") { ev.preventDefault(); swipeMove(1); }
    else if (ev.key === "r" && !busy) { ev.preventDefault(); $("#retry").click(); }
    else if (ev.key === "u" && !busy) { ev.preventDefault(); $("#undo").click(); }
    else if (ev.key === "Escape" && busy && aborter) {
      ev.preventDefault(); $("#stop").click();
    }
  };
  // Replace, never stack: renderPlay runs again on every story switch.
  if (_playKeys) document.removeEventListener("keydown", _playKeys);
  _playKeys = playKeys;
  document.addEventListener("keydown", playKeys);

  // ST-30: quick-action buttons — a canned action fills the composer and sends.
  const renderQuickBar = actions => {
    const bar = $("#quick-bar");
    if (!bar) return;
    bar.innerHTML = (actions || []).map((a, i) =>
      `<button class="qa" data-i="${i}">${esc(a)}</button>`).join("");
    bar.querySelectorAll(".qa").forEach(b => b.addEventListener("click", () => {
      if (busy) return;
      $("#action").value = actions[Number(b.dataset.i)] || "";
      send();
    }));
  };
  renderQuickBar(s.quick_actions);

  $("#aids-btn").addEventListener("click", async () => {          // ST-30 + ST-31
    const aids = await api(`/api/saves/${slug}/aids`);
    const fate = await api(`/api/saves/${slug}/fate`);          // D-045
    openModal(`
      <h1>Play aids</h1>
      <label>Quick actions <span class="muted">(this story, one per line)</span></label>
      <textarea id="qa-list" rows="4"
        placeholder="Look around&#10;Check my inventory&#10;Wait and listen"
        >${esc((aids.quick_actions || []).join("\n"))}</textarea>
      <label>Output cleanup rules <span class="muted">(regex find &rarr; replace,
      applied to narration &amp; saved)</span></label>
      <div id="rx-rows"></div>
      <button id="rx-add" class="mini">+ rule</button>
      <label>Fate <span class="muted">(a hidden D20 nudges where the next turn goes)</span></label>
      <select id="fate-mode" ${fate.blocked ? "disabled" : ""}>
        <option value="off">Off</option>
        <option value="preview">Preview: roll and show the idea, send nothing</option>
        <option value="on">On: steer the story</option>
      </select>
      <label class="chk"><input type="checkbox" id="fate-die" ${fate.blocked ? "disabled" : ""}> Show the roll after each turn</label>
      ${fate.blocked ? `<p class="muted">${esc(fate.blocked)}.</p>` : ""}
      <div class="modal-actions">
        <button id="aids-cancel">Cancel</button>
        <button class="primary" id="aids-save">Save</button>
      </div>`);
    const rxRows = $("#rx-rows");
    const addRow = r => {
      const div = document.createElement("div");
      div.className = "rx-row row";
      div.innerHTML =
        `<input class="rx-find" placeholder="find (regex)" value="${esc(r.find || "")}">`
        + `<input class="rx-repl" placeholder="replace" value="${esc(r.replace || "")}">`
        + `<input class="rx-flags" placeholder="ims" style="max-width:4.5em" value="${esc(r.flags || "")}">`
        + `<button class="rx-del mini">✕</button>`;
      div.querySelector(".rx-del").addEventListener("click", () => div.remove());
      rxRows.appendChild(div);
    };
    (aids.regex_rules || []).forEach(addRow);
    $("#fate-mode").value = fate.mode || "off";
    $("#fate-die").checked = !!fate.show_die;
    $("#rx-add").addEventListener("click", () => addRow({}));
    $("#aids-cancel").addEventListener("click", closeModal);
    $("#aids-save").addEventListener("click", async () => {
      const quick = $("#qa-list").value.split("\n").map(t => t.trim()).filter(Boolean);
      const rules = [...rxRows.querySelectorAll(".rx-row")].map(r => ({
        find: r.querySelector(".rx-find").value,
        replace: r.querySelector(".rx-repl").value,
        flags: r.querySelector(".rx-flags").value,
      })).filter(r => r.find.trim());
      const fm = $("#fate-mode").value, fd = $("#fate-die").checked;
      if (!fate.blocked && (fm !== fate.mode || fd !== !!fate.show_die)) {
        const saved = await guard(
          () => api(`/api/saves/${slug}/fate`, {method: "PUT", body: {mode: fm, show_die: fd}}),
          "Couldn't save the fate setting");
        if (saved === undefined) return;       // keep the modal + their edits
      }
      const ok = await guard(
        () => api(`/api/saves/${slug}/aids`,
                  {method: "PUT", body: {quick_actions: quick, regex_rules: rules}}),
        "Couldn't save your quick actions");
      if (ok === undefined) return;          // keep the modal + their edits
      closeModal();
      const fresh = await guard(() => api(`/api/saves/${slug}`), "Couldn't reload");
      if (fresh) renderQuickBar(fresh.quick_actions);
    });
  });

  $("#back").addEventListener("click", () => { location.hash = "#library"; });
  $("#continue").addEventListener("click", () => {
    if (!busy) run(`/api/saves/${slug}/continue`);
  });
  $("#undo").addEventListener("click", async () => {
    if (busy) return;
    const out = await guard(() => api(`/api/saves/${slug}/undo`, {method: "POST"}),
                            "Couldn't undo");
    if (out && out.ok) {
      // Repaint from the server, not by counting DOM children — an error card is
      // also a child, so the old count-based removal could drop a real turn or
      // leave a stale one.
      await resync();
      setSheet(out.sheet || []);
      setEvents(["undone. Try a different action"]);
    } else if (out) {
      toast("Nothing to undo yet.");
    }
  });
  $("#retry").addEventListener("click", async () => {
    if (busy) return;
    if (!store_turn_count()) return;
    // Do NOT prune the DOM up front: if the server's rollback never happens
    // (409, model down) the transcript would be two turns shorter than the
    // store, and turn indices come from DOM position — a later edit would
    // rewrite the wrong turn. run() repaints from server truth instead.
    // Only on SUCCESS. run()'s failure path resyncs and then appends the
    // "That turn didn't go through / Try again" card; resyncing again here
    // wiped it (resync rebuilds the transcript from scratch), so a retry whose
    // model call failed destroyed the last exchange and said nothing at all.
    if (await run(`/api/saves/${slug}/retry`, undefined, undefined, true)) {
      await resync();
    }
  });
  // The true turn count lives on the server; .turn divs in the DOM can be out of
  // step with it (error cards, mid-stream nodes), so ask rather than count.
  const store_turn_count = () =>
    transcript.querySelectorAll(".turn").length;
  $("#branch").addEventListener("click", async () => {
    const info = await guard(() => api(`/api/saves/${slug}`), "Couldn't read the story");
    if (!info) return;
    const total = (info.turns || []).length;
    const n = await promptModal("Branch this story", {
      placeholder: `1 to ${total}`, okLabel: "Branch",
      hint: `Copies the story and rewinds it to that turn. It has ${total} so far.`});
    if (!n) return;
    try {
      const out = await api(`/api/saves/${slug}/branch`,
                            {method: "POST", body: {turn: Number(n)}});
      if (out.warnings && out.warnings.length) toast(out.warnings.join("\n"));
      location.hash = `#play/${out.slug}`;
    } catch (e) { toast(e.message); }
  });
  /* Memory panel: inspect and repair what the story actually remembers.
     Without this a bad fold — a wrong scene summary, a false "fact" — was
     permanent, because the engine re-reads these files every single turn. */
  $("#mem-btn").addEventListener("click", async () => {
    const data = await guard(() => api(`/api/saves/${slug}/files`),
                             "Couldn't read this story's memory");
    if (!data) return;
    const LABEL = {
      "memory/scenes.md": "Scene summaries", "memory/arc.md": "Story so far",
      "memory/timeline.md": "Timeline", "memory/facts.md": "Facts",
      "memory/companion-chat.md": "Companion chats",
      "transcript.md": "Transcript (raw)", "state.json": "World state + sheet",
      "writer-rules.md": "Writer rules", "memory-rules.md": "Memory rules",
      "rpg-rules.md": "RPG rules", "custom-instructions.md": "Custom instructions",
    };
    const pick = data.files.filter(f => f.exists || f.is_rule);
    openModal(`<h2>Memory</h2>
      <p class="muted">What this story remembers. Fix a wrong summary or a false
        fact here and the next turn picks it up.</p>
      <label>File</label>
      <select id="mem-file">${pick.map(f =>
        `<option value="${esc(f.rel)}">${esc(LABEL[f.rel] || f.rel)}</option>`
      ).join("")}</select>
      <div id="mem-layer" class="muted"></div>
      <textarea id="mem-text" rows="14" spellcheck="false" aria-label="Contents of the chosen file"></textarea>
      <div class="modal-actions">
        <button id="mem-dups" title="find the same person written under two names, and merge them">Duplicates…</button>
        <button id="mem-folds" title="review the scene summaries the folds wrote"
          >Recent folds…</button>
        <button id="mem-override" class="hidden"></button>
        <span style="flex:1"></span>
        <button id="mem-cancel">Close</button>
        <button class="primary" id="mem-save">Save</button>
      </div>`);
    $("#mem-dups").addEventListener("click", () => duplicatesModal(slug));
    $("#mem-folds").addEventListener("click",
      () => foldReview(slug, {onDemand: true}));

    const sel = $("#mem-file"), area = $("#mem-text"), layer = $("#mem-layer");
    const ovr = $("#mem-override");
    let current = null;
    const load = async () => {
      const rel = sel.value;
      const got = await guard(() => api(
        `/api/saves/${slug}/files/${rel}`), "Couldn't open that file");
      if (!got) return;
      current = got;
      area.value = got.text;
      if (got.is_rule) {
        const own = got.layer === "save";
        layer.textContent = own
          ? "This story has its own copy. Edits affect only this story."
          : `Shared (${got.layer}): editing this changes EVERY story that uses it.`;
        ovr.classList.remove("hidden");
        ovr.textContent = own ? "Revert to shared" : "Make a copy for this story";
      } else {
        layer.textContent = "";
        ovr.classList.add("hidden");
      }
    };
    sel.addEventListener("change", load);
    ovr.addEventListener("click", async () => {
      const rel = sel.value;
      const own = current && current.layer === "save";
      const ok = await guard(() => api(
        `/api/saves/${slug}/rules/${rel}/override`,
        {method: own ? "DELETE" : "POST"}), "Couldn't change the rule scope");
      if (ok === undefined) return;
      toast(own ? "Back to the shared rules." : "This story now has its own copy.",
            "ok");
      await load();
    });
    $("#mem-cancel").addEventListener("click", closeModal);
    $("#mem-save").addEventListener("click", async () => {
      const ok = await guard(() => api(`/api/saves/${slug}/files/${sel.value}`,
        {method: "PUT", body: {text: area.value}}), "Couldn't save");
      if (ok === undefined) return;      // keep the editor open with their text
      toast("Saved. The next turn will use it.", "ok");
      closeModal();
      // Repaint from server truth. UNCONDITIONALLY, not just for transcript.md —
      // narrowing this is the cleverness that generates the next defect.
      //
      // The server does everything right on this route (snapshot, forget the
      // cached exchange, clamp the ledger, trim the folds) and then never told
      // the client. Cut one exchange in "Transcript (raw)" and the DOM stayed
      // two turns ahead of the store — and turn indices are DOM POSITION, so
      // the next ✎ PUT its edit to a neighbouring index and overwrote a
      // DIFFERENT turn. It returns 200, and the bubble then repaints with the
      // new text, so the screen agrees with the lie. update_turn takes no
      // snapshot and there is no restore path in the UI, so the overwritten
      // prose is simply gone. Undo/Send/Retry all self-correct through
      // reconcile()/resync(); the pen is the one writer that cannot.
      await resync();
    });
    await load();
  });

  $("#plan-btn").addEventListener("click", () => outlineModal(slug));
  $("#ctx-btn").addEventListener("click", () => contextModal(slug));
  $("#canon-btn").addEventListener("click", () => canonModal(slug));
  $("#talk-btn").addEventListener("click", () => talkDrawer(slug, s.companions));
  $("#edit-btn").addEventListener("click", () => { location.hash = `#edit/${slug}`; });
  $("#note-btn").addEventListener("click", async () => {          // ST-21 author's note
    const an = await api(`/api/saves/${slug}/authors-note`);
    openModal(`
      <h1>Author's note</h1>
      <p class="muted">Standing guidance woven into the prompt: tone, pacing,
      style. Never shown to the reader.</p>
      <textarea id="an-content" rows="5"
        placeholder="e.g. Keep the tone noir and terse; end scenes on a hook."
        >${esc(an.content)}</textarea>
      <label>Placement</label>
      <div class="seg" id="an-depth">
        <button data-v="system" ${an.depth === "system" ? 'class="on"' : ""}>
          System prompt</button>
        <button data-v="tail" ${an.depth === "tail" ? 'class="on"' : ""}>
          Near the action (binds harder)</button>
      </div>
      <label>Inject every N turns</label>
      <input id="an-every" type="number" min="1" value="${an.every || 1}">
      <div class="modal-actions">
        <button id="an-cancel">Cancel</button>
        <button class="primary" id="an-save">Save</button>
      </div>`);
    let depth = an.depth;
    $("#an-depth").addEventListener("click", ev => {
      if (!ev.target.dataset.v) return;
      depth = ev.target.dataset.v;
      $("#an-depth").querySelectorAll("button").forEach(b =>
        b.classList.toggle("on", b.dataset.v === depth));
    });
    $("#an-cancel").addEventListener("click", closeModal);
    $("#an-save").addEventListener("click", async () => {
      // Guarded: this 409s while a turn is generating. Unguarded it threw, the
      // modal froze open, nothing was written and nothing was said — the note
      // the user just typed was gone.
      const ok = await guard(
        () => api(`/api/saves/${slug}/authors-note`, {method: "PUT", body: {
          content: $("#an-content").value, depth,
          every: Number($("#an-every").value) || 1}}),
        "Couldn't save the author's note");
      if (ok === undefined) return;          // keep the modal + their text
      closeModal();
    });
  });

  // A brand-new save generates its opening now that every control is wired — so
  // the quick-action bar / Aids / composer are all live while it streams.
  if (!s.turns.length) await run(`/api/saves/${slug}/opening`);
}

export function talkDrawer(slug, companions) {
  if ($("#talk-drawer")) { $("#talk-drawer").remove(); return; }
  const d = document.createElement("div");
  d.id = "talk-drawer";
  // It lives on <body>, outside the view and the dialog the labels are watched in, so it names itself and is watched below.
  d.setAttribute("role", "complementary");
  d.setAttribute("aria-label", "Talk to a companion");
  d.innerHTML = `
    <div class="row" style="align-items:center">
      <select id="talk-who" aria-label="Who to talk to">${companions.map(c =>
        `<option>${esc(c)}</option>`).join("")}</select>
      <button id="talk-close" style="flex:0" aria-label="Close the chat">✕</button>
    </div>
    <div id="talk-log" role="log" aria-label="The conversation">(This chat stays between you two. It never enters
the story transcript.)\n</div>
    <div id="talk-row">
      <input id="talk-input" placeholder="Say something…">
      <button class="primary" id="talk-send" style="flex:0">Send</button>
    </div>`;
  document.body.appendChild(d);
  watchLabels(d);
  const log = $("#talk-log");
  let sending = false;                  // drawer-local; the server lock guards the rest
  const send = async () => {
    const text = $("#talk-input").value.trim();
    const who = $("#talk-who").value;
    if (!text || sending) return;
    $("#talk-input").value = "";
    log.textContent += `\nYou → ${who}: ${text}\n${who}: `;
    sending = true;
    try {
      await sse(`/api/saves/${slug}/talk`, {name: who, text}, {
        chunk: m => { log.textContent += m.text;
                      log.scrollTop = log.scrollHeight; },
        error: m => { log.textContent += `[error: ${m.text}]`; },
      });
    } catch (e) { log.textContent += `[error: ${e.message}]`; }
    log.textContent += "\n";
    sending = false;
  };
  $("#talk-send").addEventListener("click", send);
  $("#talk-input").addEventListener("keydown", ev => {
    // Shift+Enter for a newline (there was no way to write a multi-line message
    // to a companion), and never send mid-IME-composition.
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault(); send();
    }
  });
  $("#talk-close").addEventListener("click", () => d.remove());
}

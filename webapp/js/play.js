/* The play view: transcript, composer, sheet, book plan, context
   inspector, companion drawer. */
import {$, api, esc, guard, renderProse, sse, toast, view} from "./util.js";
import {
  closeModal,
  confirmModal,
  modalCard,
  openModal,
  promptModal
} from "./modal.js";

/* ---------- play ---------- */
export let busy = false;

export let _playKeys = null;          // the play view's keydown handler, so it can be swapped

// The book-plan panel: the rolling chapter outline. View the arc, edit an upcoming
// chapter's goal to steer the story, reorder/insert/delete planned chapters, mark
// the current chapter done, or regenerate the whole plan from the premise.
export async function outlineModal(slug) {
  const call = (path, opts) => api(`/api/saves/${slug}/outline${path}`, opts);

  const render = (data) => {
    const chs = data.chapters || [];
    const rows = chs.map((ch, i) => {
      const ro = ch.status === "done" ? "disabled" : "";
      const label = ch.status === "done" ? "done"
        : ch.status === "active" ? "now" : "planned";
      const ops = ch.status === "planned"
        ? `<button data-op="up" title="move earlier">↑</button>
           <button data-op="down" title="move later">↓</button>
           <button data-op="del" title="delete this chapter">🗑</button>`
        : ch.status === "active"
        ? `<button data-op="advance" class="primary"
             title="mark this chapter complete and plan the next">Chapter done →</button>`
        : "";
      return `<div class="ch-row ${ch.status}" data-i="${i}">
        <div class="ch-head">
          <span class="ch-badge ${ch.status}">${label}</span>
          <input class="ch-title" value="${esc(ch.title)}" ${ro}/>
          <span class="ch-ops">${ops}</span>
        </div>
        <textarea class="ch-goal" rows="2" ${ro}
          placeholder="what this chapter should accomplish">${esc(ch.goal)}</textarea>
        ${ch.status === "done" ? ""
          : `<div class="ch-foot"><button class="ch-save" data-op="save">Save</button></div>`}
      </div>`;
    }).join("");

    const empty = data.enabled
      ? "No plan yet. Generate one from your premise now, or it appears on its own after the first few turns."
      : "The chapter outline is turned off in Settings.";
    openModal(`<h2>Chapter plan</h2>
      <p class="muted">The story's rolling outline — a few chapters planned ahead, a
        fresh one written each time a chapter completes. Edit an upcoming chapter's
        goal to steer where things go; the turns aim toward the <b>now</b> chapter.</p>
      ${chs.length ? `<div id="ch-list">${rows}</div>`
                   : `<p class="muted">${empty}</p>`}
      <div class="modal-actions">
        ${data.enabled ? `<button id="ch-add">+ Add chapter</button>
          <button id="ch-gen">${chs.length ? "Regenerate…" : "Generate outline"}</button>`
          : ""}
        <span style="flex:1"></span>
        <button id="ch-close">Close</button>
      </div>`);

    const refetch = async (fn, busyBtn) => {
      // Generating chapters calls the model (seconds), so show the triggering
      // button as working rather than leaving the panel frozen and silent.
      if (busyBtn) { busyBtn.disabled = true; busyBtn.dataset.busy = busyBtn.textContent;
                     busyBtn.textContent = "Planning…"; }
      const d = await guard(fn, "Couldn't update the plan");
      if (d) render(d);                 // re-render from the server's truth
      else if (busyBtn) { busyBtn.disabled = false;
                          busyBtn.textContent = busyBtn.dataset.busy; }
    };
    $("#ch-close").addEventListener("click", closeModal);
    const gen = $("#ch-gen");
    if (gen) gen.addEventListener("click", async () => {
      if (chs.length && !(await confirmModal("Regenerate the whole plan?",
        "This replaces every chapter — including any already completed — with a "
        + "fresh outline from your premise.", "Regenerate"))) return;
      await refetch(() => call("/generate", {method: "POST"}), gen);
    });
    const add = $("#ch-add");
    if (add) add.addEventListener("click", () =>
      refetch(() => call("", {method: "POST", body: {title: "New chapter", goal: ""}})));

    (chs.length ? modalCard.querySelectorAll("#ch-list .ch-row") : []).forEach(row => {
      const i = Number(row.dataset.i);
      row.querySelectorAll("[data-op]").forEach(btn =>
        btn.addEventListener("click", () => {
          const op = btn.dataset.op;
          if (op === "save") {
            const title = $(".ch-title", row).value.trim();
            const goal = $(".ch-goal", row).value.trim();
            return refetch(() => call(`/${i}`, {method: "PUT", body: {title, goal}}));
          }
          if (op === "up") return refetch(() => call(`/${i}/move`, {method: "POST", body: {dir: -1}}));
          if (op === "down") return refetch(() => call(`/${i}/move`, {method: "POST", body: {dir: 1}}));
          if (op === "del") return refetch(() => call(`/${i}`, {method: "DELETE"}));
          if (op === "advance") return refetch(() => call("/advance", {method: "POST"}), btn);
        }));
    });
  };

  const data = await guard(() => call(""), "Couldn't read the plan");
  if (data) render(data);
}

// What the model actually receives this turn. "The story forgot X" is almost never
// the model forgetting — X was not in the prompt. This shows which sections are
// there, how big each one is, and what is eating the budget.
export async function contextModal(slug) {
  const d = await guard(() => api(`/api/saves/${slug}/context`),
                        "Couldn't inspect the context");
  if (!d) return;
  const bar = (n, max) => `<div class="ctx-bar"><i style="width:${
    Math.max(1, Math.round(n / max * 100))}%"></i></div>`;
  const max = Math.max(...d.sections.map(s => s.chars), 1);
  const warn = d.budget_used_pct >= 95;
  openModal(`<h2>What the model sees</h2>
    <p class="hint">The next turn's prompt, assembled for real (no model call).
      A section missing here is a section the model cannot use.</p>
    <div class="ctx-stats">
      <div><b>${d.approx_tokens.toLocaleString()}</b><span>tokens in</span></div>
      <div><b class="${warn ? "over" : ""}">${d.budget_used_pct}%</b>
        <span>of memory budget</span></div>
      <div><b>${d.history_msgs}</b><span>verbatim turns</span></div>
      <div><b>${d.brain}</b><span>brain</span></div>
      <div><b class="${d.semantic_recall === "on" ? "" : "over"}"
        >${d.semantic_recall}</b><span>semantic recall</span></div>
      <div><b>${d.lore_check.on ? `1/${d.lore_check.every}` : "off"}</b>
        <span>continuity check</span></div>
    </div>
    ${warn ? `<p class="hint" style="color:var(--player)">The budget is nearly
      full, so lower-priority lore is being cut. Raise the memory budget or trim
      the biggest sections below.</p>` : ""}
    ${(d.health || []).length ? `<div class="ctx-health">
      <b>Something fell back quietly</b>
      ${d.health.map(h => `<div>· <code>${esc(h.stage)}</code> (turn ${h.turn}):
        ${esc(h.reason)}</div>`).join("")}
    </div>` : ""}
    <div id="ctx-list">${d.sections.map(s => `<div class="ctx-row">
        <span class="ctx-name">${esc(s.title)}${s.entries
          ? ` <span class="muted">· ${s.entries}</span>` : ""}</span>
        ${bar(s.chars, max)}
        <span class="ctx-n">${s.chars.toLocaleString()}</span>
      </div>`).join("")}</div>
    <p class="hint">Rules &amp; directives add ${d.rules_chars.toLocaleString()}
      chars; the ${d.history_msgs} verbatim turns add
      ${d.history_chars.toLocaleString()}.</p>
    ${usageBlock(d.usage)}
    <div class="modal-actions"><button id="ctx-close">Close</button></div>`);
  $("#ctx-close").addEventListener("click", closeModal);
}

const fmtTok = n => (n >= 1e6 ? (n / 1e6).toFixed(2) + "M"
  : n >= 1000 ? Math.round(n / 1000) + "k" : String(n));

/* What this story has actually spent. Everything above the fold is what we
   THINK we send; this is what the provider billed, off its own usage frame.
   Per stage, because that answers the real question: is the extra brain
   worth it. */
function usageBlock(u) {
  if (!u || !u.calls) {
    return `<p class="hint">No token counts recorded yet. They appear once
      you take a turn (some providers do not report usage at all).</p>`;
  }
  const cost = (tin, tout) => {
    if (!u.price_in && !u.price_out) return "";
    const c = tin / 1e6 * u.price_in + tout / 1e6 * u.price_out;
    return ` · ${c < 0.01 ? "<$0.01" : "$" + c.toFixed(2)}`;
  };
  const stages = Object.entries(u.by_stage || {})
    .sort((a, b) => (b[1].in + b[1].out) - (a[1].in + a[1].out));
  const worst = Math.max(1, ...stages.map(([, s]) => s.in + s.out));
  return `<h2>What it has cost</h2>
    <p class="hint">The provider's own token counts, not an estimate.${
      u.cached ? ` ${fmtTok(u.cached)} of the input was served from the
      provider's prompt cache.` : ""}</p>
    <div class="ctx-stats">
      <div><b>${fmtTok(u.total_in)}</b><span>tokens in, all time</span></div>
      <div><b>${fmtTok(u.total_out)}</b><span>tokens out</span></div>
      <div><b>${u.calls}</b><span>model calls</span></div>
      <div><b>${fmtTok(u.last_turn.in + u.last_turn.out)}</b>
        <span>last turn${cost(u.last_turn.in, u.last_turn.out)}</span></div>
    </div>
    <div id="ctx-list">${stages.map(([name, s]) => `<div class="ctx-row">
        <span class="ctx-name">${esc(name)}
          <span class="muted">· ${s.calls}</span></span>
        <div class="ctx-bar"><i style="width:${
          Math.max(1, Math.round((s.in + s.out) / worst * 100))}%"></i></div>
        <span class="ctx-n">${fmtTok(s.in + s.out)}</span>
      </div>`).join("")}</div>
    <p class="hint">All time: ${fmtTok(u.total_in + u.total_out)} tokens${
      cost(u.total_in, u.total_out)}. Set your model's price per million tokens
      in Settings to see cost.</p>`;
}

export async function renderPlay(slug) {
  const s = await api(`/api/saves/${slug}`);
  s.companions = s.companions || [];        // never deref undefined (play head + Talk)
  view.innerHTML = `<div id="play">
    <div id="story-col">
      <div id="play-head">
        <button id="back">← Library</button>
        <div class="title">${esc(s.title)}</div>
        <div class="clock">${esc(s.clock || "")}</div>
        <button id="edit-btn" title="edit this story's characters, lore &amp; world"
          >Edit</button>
        <button id="note-btn" title="author's note — steer tone &amp; pacing"
          >Note</button>
        <button id="mem-btn" title="inspect &amp; repair what the story remembers"
          >Memory</button>
        <button id="plan-btn" title="the rolling chapter plan — steer the story ahead"
          >Plan</button>
        <button id="ctx-btn" title="what the model actually receives this turn"
          >Context</button>
        <button id="talk-btn" ${s.companions.length ? "" : "disabled"}
          title="${s.companions.length ? "private companion chat"
                 : "no companions yet"}">Talk</button>
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
          <button id="suggest" title="let the AI draft your next action">✍</button>
          <textarea id="action" placeholder="What do you do?"></textarea>
          <button class="primary" id="send">Send</button>
        </div>
      </div>
    </div>
    ${s.rpg ? '<aside id="sheet"></aside>' : ""}
  </div>`;

  const transcript = $("#transcript");
  const stage = $("#stageline");
  const evbar = $("#eventbar");
  let swipe = {count: 1, idx: 0};      // ST-02 state for the last narrator turn

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
    pen.addEventListener("click", () => startEdit(d));   // ST-03
    d.appendChild(pen);
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
      + `<span>Version ${swipe.idx + 1} of ${swipe.count}</span>`
      + `<button class="mini swr" aria-label="Next or new version"
           title="next version — at the end, writes a new one (right arrow)"
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
    const body = bodyOf(d); body.textContent = ""; d.classList.add("pending");
    transcript.querySelectorAll(".swipebar").forEach(b => b.remove());
    try {
      await sse(`/api/saves/${slug}/swipe-gen`, undefined, {
        stage: m => { stage.textContent = m.text; },
        chunk: m => { d.classList.remove("pending"); body.textContent += m.text;
                      transcript.scrollTop = transcript.scrollHeight; },
        done: m => { setEvents(m.events); setSheet(m.sheet || []);
                     $(".clock").textContent = m.clock || "";
                     if (m.text != null) body._settle = m.text; stage.textContent = ""; },
        error: m => { stage.textContent = "error: " + m.text; },
      });
    } catch (e) { stage.textContent = "error: " + e.message; }
    d.classList.remove("pending");
    if (body._settle && body.textContent) body.textContent = body._settle;
    paint(d, body.textContent);
    swipe = {count: swipe.count + 1, idx: swipe.count};
    setBusy(false); renderSwipeBar();
  };
  const setSheet = lines => {
    const el = $("#sheet");
    if (el) el.innerHTML =
      '<div class="sheet-title">Character</div>' + esc(lines.join("\n"));
  };
  const setEvents = events => {
    evbar.innerHTML = (events || []).map(e =>
      `<span class="evt ${e.startsWith("validator:") ? "warn" : ""}">
       ${esc(e)}</span>`).join("");
  };

  const setBusy = on => {
    // If the user navigated away mid-stream this view's nodes are detached, and
    // the still-pending run must not toggle the NEW page's controls.
    if (!document.body.contains(transcript)) return;
    busy = on;
    ["send", "continue", "undo", "retry", "branch", "suggest"].forEach(id => {
      const b = $("#" + id); if (b) b.disabled = on;
    });
    transcript.querySelectorAll(".swipebar button, .turn-edit")
      .forEach(b => b.disabled = on);
  };
  /* Repaint the transcript from the server's truth. After a failed turn the DOM
     and the store can disagree, and turn indices are derived from DOM position —
     so an edit would PUT to the wrong index and rewrite a different turn. */
  const resync = async () => {
    try {
      const fresh = await api(`/api/saves/${slug}`);
      transcript.innerHTML = "";
      (fresh.turns || []).forEach(t => addTurn(t.role, t.text));
      swipe = {count: 1, idx: 0};
      renderSwipeBar();
    } catch (_e) { /* offline: leave what's on screen rather than blanking it */ }
  };

  /* An error the user can actually see and act on, in the transcript where the
     turn failed — the old 11.5px stageline was below the fold and had no retry. */
  const showTurnError = (msg, retryFn) => {
    const box = document.createElement("div");
    box.className = "turn-error";
    box.setAttribute("role", "alert");
    const title = msg.code === "busy" ? "Already generating"
      : msg.code === "auth" ? "The API key was rejected"
      : msg.code === "connection" ? "Can't reach the model"
      : msg.code === "context" ? "This story is too long for the model"
      : msg.code === "aborted" ? "Stopped" : "That turn didn't go through";
    box.innerHTML = `<b>${esc(title)}</b><p>${esc(msg.text || "")}</p>`;
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
  const run = async (path, body, playerText) => {
    if (busy) return;
    setBusy(true);
    evbar.innerHTML = "";
    transcript.querySelectorAll(".turn-error").forEach(b => b.remove());
    transcript.querySelectorAll(".swipebar").forEach(b => b.remove());
    // Elapsed time + a hint once the wait passes Nielsen's 10s attention limit:
    // a 30s+ planner stage under a static "Thinking…" reads as a hang.
    const t0 = Date.now();
    let label = "Thinking…";
    stage.textContent = label;
    const ticker = setInterval(() => {
      const s = Math.round((Date.now() - t0) / 1000);
      const hint = s >= 10 ? " — the planning stage can take a while on local models" : "";
      stage.textContent = `${label} ${s}s${hint}`;
    }, 1000);
    aborter = new AbortController();
    $("#stop").classList.remove("hidden");
    $("#stop").disabled = false;      // was disabled after a prior Stop click

    const optimistic = playerText !== undefined ? addTurn("player", playerText) : null;
    const live = addTurn("narrator", "");
    const liveBody = bodyOf(live);
    live.classList.add("pending");   // blinking caret until prose streams in
    live.setAttribute("aria-busy", "true");
    let settled = null;              // ST-31: the regex-cleaned stored text
    let failed = null;
    try {
      await sse(path, body, {
        stage: m => { label = m.text; },
        chunk: m => { live.classList.remove("pending");
                      liveBody.textContent += m.text;
                      transcript.scrollTop = transcript.scrollHeight; },
        done: m => { setEvents(m.events); setSheet(m.sheet || []);
                     $(".clock").textContent = m.clock || "";
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
    $("#stop").classList.add("hidden");
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
      showTurnError(failed, playerText !== undefined
        ? () => run(path, body, playerText) : () => run(path, body));
      if (playerText !== undefined && !$("#action").value) {
        $("#action").value = playerText;      // never lose what they typed
      }
    }
    swipe = {count: 1, idx: 0};                // fresh turn resets alternates
    renderSwipeBar();
    setBusy(false);
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

  $("#suggest").addEventListener("click", async () => {
    if (busy) return;
    const b = $("#suggest"); b.disabled = true; const was = b.textContent;
    b.textContent = "…";
    try {
      const out = await api(`/api/saves/${slug}/impersonate`, {method: "POST"});
      $("#action").value = out.text; $("#action").focus();
    } catch (e) { toast(e.message); }
    b.disabled = false; b.textContent = was;
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
    openModal(`
      <h1>Play aids</h1>
      <label>Quick actions <span class="muted">(this story — one per line)</span></label>
      <textarea id="qa-list" rows="4"
        placeholder="Look around&#10;Check my inventory&#10;Wait and listen"
        >${esc((aids.quick_actions || []).join("\n"))}</textarea>
      <label>Output cleanup rules <span class="muted">(regex find &rarr; replace,
      applied to narration &amp; saved)</span></label>
      <div id="rx-rows"></div>
      <button id="rx-add" class="mini">+ rule</button>
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
    $("#rx-add").addEventListener("click", () => addRow({}));
    $("#aids-cancel").addEventListener("click", closeModal);
    $("#aids-save").addEventListener("click", async () => {
      const quick = $("#qa-list").value.split("\n").map(t => t.trim()).filter(Boolean);
      const rules = [...rxRows.querySelectorAll(".rx-row")].map(r => ({
        find: r.querySelector(".rx-find").value,
        replace: r.querySelector(".rx-repl").value,
        flags: r.querySelector(".rx-flags").value,
      })).filter(r => r.find.trim());
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
      setEvents(["undone — try a different action"]);
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
    await run(`/api/saves/${slug}/retry`);
    await resync();
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
      placeholder: `1 – ${total}`, okLabel: "Branch",
      hint: `Copies the story and rewinds it to that turn. It has ${total} so far.`});
    if (!n) return;
    try {
      const out = await api(`/api/saves/${slug}/branch`,
                            {method: "POST", body: {turn: Number(n)}});
      if (out.warnings.length) toast(out.warnings.join("\n"));
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
      <textarea id="mem-text" rows="14" spellcheck="false"></textarea>
      <div class="modal-actions">
        <button id="mem-override" class="hidden"></button>
        <span style="flex:1"></span>
        <button id="mem-cancel">Close</button>
        <button class="primary" id="mem-save">Save</button>
      </div>`);

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
          ? "This story has its own copy — edits affect only this story."
          : `Shared (${got.layer}) — editing this changes EVERY story that uses it.`;
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
      toast("Saved — the next turn will use it.", "ok");
      closeModal();
    });
    await load();
  });

  $("#plan-btn").addEventListener("click", () => outlineModal(slug));
  $("#ctx-btn").addEventListener("click", () => contextModal(slug));
  $("#talk-btn").addEventListener("click", () => talkDrawer(slug, s.companions));
  $("#edit-btn").addEventListener("click", () => { location.hash = `#edit/${slug}`; });
  $("#note-btn").addEventListener("click", async () => {          // ST-21 author's note
    const an = await api(`/api/saves/${slug}/authors-note`);
    openModal(`
      <h1>Author's note</h1>
      <p class="muted">Standing guidance woven into the prompt — tone, pacing,
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
  d.innerHTML = `
    <div class="row" style="align-items:center">
      <select id="talk-who">${companions.map(c =>
        `<option>${esc(c)}</option>`).join("")}</select>
      <button id="talk-close" style="flex:0">✕</button>
    </div>
    <div id="talk-log">(This chat stays between you two — it never enters
the story transcript.)\n</div>
    <div id="talk-row">
      <input id="talk-input" placeholder="Say something…">
      <button class="primary" id="talk-send" style="flex:0">Send</button>
    </div>`;
  document.body.appendChild(d);
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

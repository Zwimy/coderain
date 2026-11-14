/* First run: no stories yet, so pick a model and start one. */
import {$, api, esc, guard, toast, view} from "./util.js";
import {checkReady, invalidateReady, skipReadyCheck} from "./nav.js";
import {render} from "./app.js";

export async function renderWelcome(state) {
  const hosted = await api("/api/models/hosted").catch(() => ({presets: []}));
  const local = await api("/api/models/local").catch(() => ({installed: [], howto: []}));
  const running = !local.error;
  const presets = hosted.presets || [];
  // Only a model that can tell a story is offered: an embedding model (nomic-embed-text) used to sit in this list.
  const chat = (local.installed || []).filter(m => !m.embedding);
  const server = local.server || "Ollama";
  view.innerHTML = `<div class="page welcome">
    <h1>Let's get you a storyteller</h1>
    <p class="muted">Coderain runs on <b>your</b> model. Nothing is sent to us,
      and there is no account. Pick one of these once and you're set.</p>
    <div class="cards two">
      <div class="card static">
        <div class="title">Run it on your computer</div>
        <p class="muted">Free, private, works offline. Best if you have a decent GPU.</p>
        <div class="status ${running ? "ok" : "bad"}">
          ${running
            ? chat.length
              ? `${server} is running: ${chat.length} model(s) installed`
              : (local.installed || []).length
                ? `${server} is running, but it only has embedding models, which cannot tell a story`
                : `${server} is running, but no models are pulled yet`
            : `${server} isn't running`}
        </div>
        ${running && chat.length ? `
          <label>Use this model</label>
          <select id="w-local-model">
            ${chat.map(m =>
              `<option value="${esc(m.name)}">${esc(m.name)}${m.size ? `: ${esc(m.size)}` : ""}</option>`).join("")}
          </select>
          <div class="row" style="margin-top:12px">
            <button class="primary" id="w-use-local">Use this and start</button>
          </div>`
        : `<ol class="steps">${(local.howto || []).map(s => `<li>${esc(s)}</li>`).join("")}</ol>
           <div class="row"><button id="w-recheck">Check again</button></div>`}
      </div>

      <div class="card static">
        <div class="title">Use an API key</div>
        <p class="muted">Works on any machine, including a laptop with no GPU.
          You pay the provider directly; roughly the price of a coffee a month.</p>
        <label>Provider &amp; model</label>
        <select id="w-preset">
          ${presets.map((p, i) =>
            `<option value="${i}">${esc(p.label)}</option>`).join("")}
        </select>
        <label>API key</label>
        <input id="w-key" type="password" placeholder="paste your key here"
               autocomplete="off">
        <div class="row" style="margin-top:12px">
          <button class="primary" id="w-use-hosted">Save and start</button>
        </div>
        <p class="muted" id="w-hosted-note"></p>
      </div>
    </div>
    <p class="muted" style="margin-top:22px">
      <a href="#library" id="w-skip">Look around first</a>.
      You can set this up later in Settings.
    </p>
  </div>`;

  const useLocal = $("#w-use-local");
  if (useLocal) useLocal.addEventListener("click", async () => {
    const model = $("#w-local-model").value;
    useLocal.disabled = true;
    const ok = await guard(() => api("/api/settings", {method: "PUT", body: {
      mode: "local", local: {director: model, writer: model, lorekeeper: ""},
    }}), "Couldn't save that");
    useLocal.disabled = false;
    if (ok === undefined) return;
    invalidateReady();
    toast("Ready to play.", "ok");
    location.hash = "#library";
    render();
  });
  const recheck = $("#w-recheck");
  if (recheck) recheck.addEventListener("click", async () => {
    invalidateReady(); await checkReady(true); render();
  });
  $("#w-use-hosted").addEventListener("click", async () => {
    const key = $("#w-key").value.trim();
    if (!key) { toast("Paste your API key first."); return; }
    const p = presets[Number($("#w-preset").value) || 0];
    const btn = $("#w-use-hosted");
    btn.disabled = true; btn.textContent = "Checking…";
    const ok = await guard(() => api("/api/settings", {method: "PUT", body: {
      mode: "hosted",
      hosted: {model: p.model, base_url: p.base_url,
               context_tokens: p.context, api_key: key},
    }}), "Couldn't save that");
    btn.disabled = false; btn.textContent = "Save and start";
    if (ok === undefined) return;
    invalidateReady();
    toast("Ready to play.", "ok");
    location.hash = "#library";
    render();
  });
  $("#w-skip").addEventListener("click", skipReadyCheck);
  const note = $("#w-hosted-note");
  const showNote = () => {
    const p = presets[Number($("#w-preset").value) || 0];
    note.textContent = p ? p.note : "";
  };
  $("#w-preset").addEventListener("change", showNote);
  showNote();
}

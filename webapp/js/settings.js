/* Settings: connection, model, memory, storytelling, play aids. */
import {$, api, esc, guard, toast, view} from "./util.js";
import {confirmModal} from "./modal.js";
import {invalidateReady} from "./nav.js";
import {render} from "./app.js";

/* ---------- settings ---------- */
export async function renderSettings() {
  const [st, local, hosted, profs] = await Promise.all([
    api("/api/settings"), api("/api/models/local"), api("/api/models/hosted"),
    api("/api/profiles").catch(() => ({profiles: [], active: ""})),
  ]);
  const names = local.installed.map(m => m.name);
  const opt = (list, sel) => list.map(n =>
    `<option ${n === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
  const localOpts = sel => opt(
    names.includes(sel) || !sel ? names : [sel, ...names], sel);
  const presetOpts = hosted.presets.map((p, i) =>
    `<option value="${i}" ${p.model === st.hosted.model ? "selected" : ""}>
     ${esc(p.label)}</option>`).join("");

  view.innerHTML = `<div class="page">
    <h1>Settings <span class="ver">v${esc(st.version || "?")}</span></h1>
    <div class="seg" id="mode-seg">
      <button data-v="local" ${st.mode === "local" ? 'class="on"' : ""}>
        Local (Ollama)</button>
      <button data-v="hosted" ${st.mode === "hosted" ? 'class="on"' : ""}>
        Hosted (your API key)</button>
    </div>

    <div class="setting-panel">
      <h2>Connection profiles</h2>
      <p class="muted">Save a connection (provider + model + context) under a name
      and switch between them — e.g. "fast local" vs "quality cloud".</p>
      <div class="row">
        <div style="flex:1"><label>Saved profiles</label>
          <select id="pf-list">
            <option value="">${profs.profiles.length ? "— pick —"
              : "(none saved yet)"}</option>
            ${profs.profiles.map(n => `<option ${n === profs.active
              ? "selected" : ""}>${esc(n)}</option>`).join("")}
          </select>
        </div>
        <div style="align-self:flex-end">
          <button id="pf-load">Load</button>
          <button id="pf-del" class="danger">Delete</button>
        </div>
      </div>
      <div class="row">
        <div style="flex:1"><label>Save current connection as…</label>
          <input id="pf-name" placeholder="fast local"></div>
        <div style="align-self:flex-end"><button id="pf-save">Save</button></div>
      </div>
      <span id="pf-status" class="muted"></span>
    </div>

    <div class="setting-panel" id="panel-local">
      <h2>Local models — quad brain stages</h2>
      <details class="howto">
        <summary>New to this? Install Ollama &amp; set up local models</summary>
        ${(local.howto || []).map(p => `<p>${esc(p)}</p>`).join("")}
      </details>
      ${local.error ? `<p class="muted">${esc(local.error)} — showing
        suggestions only.</p>` : ""}
      <div class="row">
        <div><label>Director (plans the turn — thinking model)</label>
          <select id="lm-director">${localOpts(st.local.director)}</select></div>
        <div><label>Writer (prose — non-thinking is fine)</label>
          <select id="lm-writer">${localOpts(st.local.writer)}</select></div>
      </div>
      <div class="row">
        <div><label>Lore-keeper (optional continuity pass)</label>
          <select id="lm-keeper">
            <option value="" ${!st.local.lorekeeper ? "selected" : ""}>(none — skip it)</option>
            ${localOpts(st.local.lorekeeper)}</select></div>
        <div><label title="How much the model can READ at once (its window)."
          >Context window</label>
          <input id="lm-ctx" type="number" step="1024"
            value="${esc(st.local.context_tokens)}"></div>
      </div>
      <p class="muted">Context window = how much the model can read at once (set
        it to the model's real window). Reply length is set under Storytelling,
        not here.</p>
      <p class="muted">Installed via Ollama: ${local.installed.map(m =>
        `${esc(m.name)} (${esc(m.size)})`).join(", ") || "none detected"}.
      Suggested pulls: ${local.suggestions.map(s =>
        `<b>${esc(s.name)}</b> — ${esc(s.note)}`).join("; ")}.</p>
    </div>

    <div class="setting-panel" id="panel-hosted">
      <h2>Hosted model — one model runs every stage</h2>
      <details class="howto">
        <summary>New to this? How to get running in 5 minutes</summary>
        ${hosted.howto.map(p => `<p>${esc(p)}</p>`).join("")}
      </details>
      <label>Preset</label>
      <select id="hm-preset"><option value="">(custom)</option>${presetOpts}
      </select>
      <div class="row">
        <div><label>Model id</label>
          <input id="hm-model" value="${esc(st.hosted.model)}"></div>
        <div><label title="The model's context window — how much it can read.">
          Context window</label>
          <input id="hm-ctx" type="number" step="1024"
            value="${esc(st.hosted.context_tokens)}"></div>
      </div>
      <label>Base URL (OpenAI-compatible)</label>
      <input id="hm-base" value="${esc(st.hosted.base_url)}">
      <label>API key ${st.hosted.key_set
        ? '<span style="color:var(--ok)">(saved — leave blank to keep)</span>'
        : '<span style="color:var(--player)">(not saved yet)</span>'}</label>
      <input id="hm-key" type="password" placeholder="${st.hosted.key_set
        ? "••••••••" : "paste your key"}">
      <p class="muted">Keys and stories live in this app's data folder:
        <code>${esc(st.home || "")}</code>. The desktop app and a source run use
        DIFFERENT folders, so a key saved in one will read as "not saved" in the
        other.</p>
      <h2>Supporting models (local, free)</h2>
      <p class="muted">The Director plans the turn and the Lore-keeper checks
        continuity. Both are structured work a small local model does well, and
        both run every turn — pointing them at Ollama keeps the hosted model for
        the prose you are paying for. Leave either on
        <b>(use the hosted model)</b> to send it to the hosted endpoint instead.
        ${names.length ? "" : `<span style="color:var(--player)">Ollama is not
        running or has no models pulled, so only the hosted option is
        available.</span>`}</p>
      <div class="row">
        <div><label>Director</label>
          <select id="hm-director">
            <option value="">(use the hosted model)</option>
            ${localOpts(st.hosted.director_local || "")}
          </select></div>
        <div><label>Lore-keeper</label>
          <select id="hm-lorekeeper">
            <option value="">(use the hosted model)</option>
            ${localOpts(st.hosted.lorekeeper_local || "")}
          </select></div>
      </div>
      <h2>Context windows (snapshot)</h2>
      <pre class="table">${esc(hosted.hints.join("\n"))}</pre>
      <details><summary class="muted">What the big platforms actually run</summary>
        <pre class="table">${esc(hosted.platforms.join("\n"))}</pre></details>
    </div>

    <div class="setting-panel">
      <h2>Storytelling</h2>
      <div class="sub-head">Cost vs quality</div>
      <div class="seg" id="cost-seg">
        <button data-v="economy" type="button">Economy</button>
        <button data-v="balanced" type="button">Balanced</button>
        <button data-v="quality" type="button">Quality</button>
      </div>
      <p class="hint">The biggest lever on token cost. <b>Economy</b> /
        <b>Balanced</b> = one call per turn — best for pure narrative.
        <b>Quality</b> = a planner runs first to resolve mechanics, worth it for
        RPG play at roughly 2× the tokens. Sets the two toggles below.</p>
      <div class="indent">
        <label><input type="checkbox" id="gc-trinity"
          ${st.generation.trinity_brain ? "checked" : ""}>
          Multi-stage brain (a planner runs before the writer)</label>
        <p class="hint">Better mechanics, about twice the work per turn.</p>
        <label><input type="checkbox" id="gc-memtool"
          ${st.generation.use_memory_tool ? "checked" : ""}>
          Let the model look things up mid-turn</label>
        <p class="hint">Only worth it on a big hosted model — small local models
          are unreliable at using tools.</p>
      </div>

      <div class="sub-head">Writing</div>
      <label><input type="checkbox" id="gc-agency"
        ${st.generation.ai_acts_as_player ? "checked" : ""}>
        Let the AI speak &amp; act as my character</label>
      <p class="hint">Off (default) = it plays the world and other characters, then
        hands control back to you.</p>
      <label style="margin-top:16px">Response length</label>
      <div class="seg" id="len-seg">
        ${["short", "medium", "long"].map(v => `<button data-v="${v}"
          ${st.generation.response_length === v ? 'class="on"' : ""}>
          ${v}</button>`).join("")}
      </div>

      <div class="sub-head">Story structure</div>
      <label><input type="checkbox" id="gc-outline"
        ${st.generation.chapter_outline !== false ? "checked" : ""}>
        Plan the story in chapters (book plan)</label>
      <p class="hint">A rolling outline plans a few chapters ahead and writes a new
        one as each completes. Not a per-turn brain — it only plans at the
        memory-fold cadence. See the <b>Plan</b> button while playing.</p>
      <div class="indent">
        <label style="text-transform:uppercase;font-size:12px;color:var(--dim)"
          >Chapters planned ahead</label>
        <input type="number" id="gc-horizon" min="2" max="8" step="1"
          value="${st.generation.chapter_horizon || 4}" style="width:80px">
        <p class="hint">Default 4 (range 2–8). Higher = a longer plotted arc.</p>
      </div>

      <div class="sub-head">Continuity</div>
      <label><input type="checkbox" id="gc-lore"
        ${st.generation.lore_check ? "checked" : ""}>
        Continuity check (lore-keeper)</label>
      <p class="hint">The only stage that <b>verifies</b> rather than recalls: it
        looks up what the turn must not contradict and hands the writer the facts
        to honor. Strongest guard against contradictions, and the most expensive —
        one extra call each time it runs.</p>
      <div class="indent">
        <label style="text-transform:uppercase;font-size:12px;color:var(--dim)"
          >Run it every…</label>
        <select id="gc-lore-every" style="max-width:200px">
          ${[[1, "every turn"], [2, "every 2nd turn"], [3, "every 3rd turn"],
             [4, "every 4th turn"], [5, "every 5th turn"]].map(([v, t]) =>
            `<option value="${v}" ${Number(st.generation.lore_check_every || 1) === v
              ? "selected" : ""}>${t}</option>`).join("")}
        </select>
        <p class="hint">The world rarely changes enough to re-verify every turn.
          Every 3rd keeps most of the benefit for a third of the cost.</p>
      </div>
    </div>

    <div class="setting-panel">
      <h2>Memory</h2>
      <label>
        <input type="checkbox" id="rt-enabled"
          ${st.retrieval.enabled ? "checked" : ""}>
        Semantic recall (find relevant past scenes by meaning, not just keywords)
      </label>
      <p class="muted">The strongest consistency feature: it surfaces the right
        past entry even when the wording doesn't match. Needs a provider that
        serves embeddings — many hosted story models (DeepSeek among them) do NOT,
        and the recall then silently does nothing. Use <b>Embed with</b> to run
        embeddings on local Ollama (<code>ollama pull nomic-embed-text</code>)
        while the story runs on your hosted model. Press <b>Check</b> to see
        whether it is genuinely working.</p>
      <div class="row">
        <div><label>Embed with</label>
          <select id="rt-profile">
            <option value="">(the chat model)</option>
            ${(st.retrieval.profiles || []).map(p =>
              `<option value="${esc(p)}" ${st.retrieval.profile === p
                ? "selected" : ""}>${esc(p)}</option>`).join("")}
          </select></div>
        <div style="align-self:flex-end">
          <button id="rt-check" type="button">Check</button></div>
      </div>
      <p id="rt-status" class="muted"></p>
      <div class="row">
        <div><label>Embedding model</label>
          <input id="rt-model" value="${esc(st.retrieval.embed_model)}"></div>
        <div><label>Passages recalled</label>
          <input id="rt-topk" type="number" min="1" max="20"
            value="${esc(st.retrieval.top_k)}"></div>
        <div><label>Min similarity</label>
          <input id="rt-minsim" type="number" step="0.05" min="0" max="1"
            value="${esc(st.retrieval.min_similarity)}"></div>
      </div>
      <details class="adv">
        <summary>Memory depth (advanced)</summary>
        <p class="muted">How much raw history stays verbatim before it is folded
          into summaries. Bigger = more detail, more context used.</p>
        <div class="row">
          <div><label>Verbatim turns</label>
            <input id="mm-short" type="number" min="2" max="200"
              value="${esc(st.memory.short_term_turns)}"></div>
          <div><label>Fold after</label>
            <input id="mm-mafter" type="number" min="2" max="200"
              value="${esc(st.memory.medium_fold_after)}"></div>
          <div><label>Fold size</label>
            <input id="mm-msize" type="number" min="1" max="100"
              value="${esc(st.memory.medium_fold_size)}"></div>
        </div>
        <label>Memory budget — how many tokens of story + memory to send each
          turn</label>
        <input id="mm-budget" value="${esc(st.memory.context_budget_tokens)}">
        <p class="muted">This is the main cost lever. A smaller number = cheaper,
          faster turns that lean more on summaries; larger = more raw detail in
          context. <b>"auto" fills the model's whole window every turn</b> — on a
          big-context model that gets very expensive, so a fixed number
          (8000–16000) is usually better.</p>
        <div class="sub-head">What a turn costs</div>
        <p class="hint">Every turn records the provider's own token counts. Put
          your model's price in and the Context panel shows money instead of just
          tokens. Coderain does not ship a price list because they go stale, and
          a wrong number is worse than none.</p>
        <div class="row2">
          <div><label>$ per 1M input tokens</label>
            <input id="mm-pin" type="number" min="0" step="0.01"
              value="${esc(st.price_in ?? 0)}"></div>
          <div><label>$ per 1M output tokens</label>
            <input id="mm-pout" type="number" min="0" step="0.01"
              value="${esc(st.price_out ?? 0)}"></div>
        </div>
      </details>
    </div>

    <div class="setting-panel">
      <h2>Appearance</h2>
      <label>
        <input type="checkbox" id="ap-rain">
        Animated background rain
      </label>
      <p class="muted">Turn this off for a still background. It follows your
        system "reduce motion" setting unless you choose here.</p>
    </div>

    <div class="setting-panel">
      <h2>Generation controls</h2>
      <label>Start every reply with (optional)</label>
      <input id="gc-prefix" placeholder='e.g. a quote " or an action *'
        value="${esc(st.generation.start_reply_with || "")}">
      <p class="muted">Every narrator turn will begin with this literal text —
      handy to force dialogue or an action tag. Works with any model.</p>
      <label>Stop sequences (one per line)</label>
      <textarea id="gc-stop" rows="2"
        placeholder="text that ends generation, e.g.  User:">${
        esc((st.generation.stop || []).join("\n"))}</textarea>
      <div class="row">
        <div><label>Temperature</label>
          <input id="gc-temp" type="number" step="0.05" min="0" max="2"
            value="${st.generation.temperature ?? 0.9}"></div>
        <div><label>Top-p</label>
          <input id="gc-topp" type="number" step="0.05" min="0" max="1"
            value="${st.generation.top_p ?? 0.95}"></div>
        <div><label title="Only used on 'medium' length; short/long set their own.">
          Max reply tokens (medium)</label>
          <input id="gc-max" type="number" step="50" min="1"
            value="${st.generation.max_tokens ?? 2500}"></div>
      </div>
      <p class="muted">Reply length is normally set by the Response length buttons
        above; this caps the "medium" setting only.</p>
      <details><summary class="muted">Advanced samplers (blank = model default)</summary>
        <div class="row">
          <div><label>Frequency penalty</label>
            <input id="gc-freq" type="number" step="0.1" min="-2" max="2"
              value="${st.generation.frequency_penalty ?? ""}"></div>
          <div><label>Presence penalty</label>
            <input id="gc-pres" type="number" step="0.1" min="-2" max="2"
              value="${st.generation.presence_penalty ?? ""}"></div>
        </div>
        <div class="row">
          <div><label>Repetition penalty <span class="muted">(local models)</span></label>
            <input id="gc-rep" type="number" step="0.05" min="0" max="2"
              value="${st.generation.repetition_penalty ?? ""}"></div>
          <div><label>Seed <span class="muted">(fixed = reproducible)</span></label>
            <input id="gc-seed" type="number" step="1" min="0"
              value="${st.generation.seed ?? ""}"></div>
        </div>
      </details>
    </div>

    <div class="setting-panel">
      <h2>Quick actions (global)</h2>
      <p class="muted">Canned action buttons shown in every story's play bar — one
      per line. Each story can add its own from the play view (Aids).</p>
      <textarea id="qa-global" rows="3"
        placeholder="Look around&#10;Check my inventory&#10;Wait and listen"
        >${esc((st.quick_actions || []).join("\n"))}</textarea>
    </div>

    <div class="savebar">
      <button class="primary" id="save-settings">Save &amp; apply</button>
      <span id="save-status"></span>
    </div>
  </div>`;

  let mode = st.mode;
  let length = st.generation.response_length || "medium";
  const syncPanels = () => {
    $("#panel-local").classList.toggle("hidden", mode !== "local");
    $("#panel-hosted").classList.toggle("hidden", mode !== "hosted");
    $("#mode-seg").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === mode));
  };
  syncPanels();
  $("#mode-seg").addEventListener("click", ev => {
    if (ev.target.dataset.v) { mode = ev.target.dataset.v; syncPanels(); }
  });
  $("#len-seg").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    length = ev.target.dataset.v;
    $("#len-seg").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === length));
  });
  // Cost preset: sets the underlying toggles (quad / memory tool / budget). It
  // doesn't save on its own — the user still presses Save & apply.
  const COST = {
    economy:  {trinity: false, memtool: false, budget: 6000},
    balanced: {trinity: false, memtool: false, budget: 8000},
    quality:  {trinity: true,  memtool: false, budget: 12000},
  };
  const markCost = v => $("#cost-seg").querySelectorAll("button")
    .forEach(b => b.classList.toggle("on", b.dataset.v === v));
  // Reflect the current settings as the active preset (or none if custom).
  (() => {
    const cur = {trinity: $("#gc-trinity").checked,
                 memtool: $("#gc-memtool").checked,
                 budget: Number($("#mm-budget").value) || 0};
    const hit = Object.keys(COST).find(k =>
      COST[k].trinity === cur.trinity && COST[k].memtool === cur.memtool
      && COST[k].budget === cur.budget);
    if (hit) markCost(hit);
  })();
  $("#cost-seg").addEventListener("click", ev => {
    const v = ev.target.dataset.v;
    if (!v || !COST[v]) return;
    $("#gc-trinity").checked = COST[v].trinity;
    $("#gc-memtool").checked = COST[v].memtool;
    $("#mm-budget").value = COST[v].budget;
    markCost(v);
    toast(`${v[0].toUpperCase() + v.slice(1)} preset set — press Save & apply.`,
          "info");
  });
  // Motion is a local preference, not server config — applied instantly so the
  // effect is obvious, and it satisfies WCAG 2.2.2's stop requirement.
  const rainBox = $("#ap-rain");
  if (rainBox) {
    rainBox.checked = typeof window.rainOn === "function" ? window.rainOn() : true;
    rainBox.addEventListener("change", () => {
      if (window.setRain) window.setRain(rainBox.checked);
    });
  }
  $("#hm-preset").addEventListener("change", () => {
    const p = hosted.presets[Number($("#hm-preset").value)];
    if (!p) return;
    $("#hm-model").value = p.model;
    $("#hm-base").value = p.base_url;
    $("#hm-ctx").value = p.context;
  });
  const pfStatus = m => {
    if (!$("#pf-status")) return;
    $("#pf-status").textContent = m;
    setTimeout(() => { if ($("#pf-status")) $("#pf-status").textContent = ""; }, 3000);
  };
  $("#pf-save").addEventListener("click", async () => {
    const name = $("#pf-name").value.trim();
    if (!name) return pfStatus("enter a name first");
    // Apply the form FIRST: this button used to snapshot only the already-active
    // connection, so editing the API key (or model/URL) and pressing this Save
    // silently discarded the edit. Now both Save buttons persist what you see.
    pfStatus("saving…");
    if (!await applySettings(null)) return pfStatus("couldn't save the connection");
    try { await api("/api/profiles", {method: "POST", body: {name}}); render(); }
    catch (e) { pfStatus("error: " + e.message); }
  });
  $("#pf-load").addEventListener("click", async () => {
    const name = $("#pf-list").value;
    if (!name) return pfStatus("pick a profile");
    try {
      await api("/api/profiles/activate", {method: "POST", body: {name}});
      setBrainline(); render();
    } catch (e) { pfStatus("error: " + e.message); }
  });
  $("#pf-del").addEventListener("click", async () => {
    const name = $("#pf-list").value;
    if (!name) return pfStatus("pick a profile");
    if (!await confirmModal(`Delete profile "${name}"?`)) return;
    try {
      await api(`/api/profiles/${encodeURIComponent(name)}`, {method: "DELETE"});
      render();
    } catch (e) { pfStatus("error: " + e.message); }
  });
  // The form as the server wants it. Shared so "Save & apply" AND "Save current
  // connection as…" both persist what you are actually looking at — the latter
  // used to snapshot only the ALREADY-ACTIVE connection, so typing a new API key
  // and pressing the nearer Save silently did nothing.
  const settingsBody = () => {
    const body = {
      mode,
      retrieval: {
        enabled: $("#rt-enabled").checked,
        embed_model: $("#rt-model").value,
        profile: $("#rt-profile") ? $("#rt-profile").value : "",
        top_k: $("#rt-topk").value,
        min_similarity: $("#rt-minsim").value,
      },
      memory: {
        short_term_turns: $("#mm-short").value,
        medium_fold_after: $("#mm-mafter").value,
        medium_fold_size: $("#mm-msize").value,
        context_budget_tokens: $("#mm-budget").value.trim(),
      },
      price_in: $("#mm-pin").value || 0,
      price_out: $("#mm-pout").value || 0,
      generation: {
        response_length: length,
        trinity_brain: $("#gc-trinity").checked,
        use_memory_tool: $("#gc-memtool").checked,
        ai_acts_as_player: $("#gc-agency").checked,
        chapter_outline: $("#gc-outline").checked,
        chapter_horizon: $("#gc-horizon").value,
        lore_check: $("#gc-lore").checked,
        lore_check_every: $("#gc-lore-every").value,
        start_reply_with: $("#gc-prefix").value,
        stop: $("#gc-stop").value,
        temperature: $("#gc-temp").value,
        top_p: $("#gc-topp").value,
        max_tokens: $("#gc-max").value,
        frequency_penalty: $("#gc-freq").value,
        presence_penalty: $("#gc-pres").value,
        repetition_penalty: $("#gc-rep").value,
        seed: $("#gc-seed").value,
      },
      quick_actions: $("#qa-global") ? $("#qa-global").value : "",
      local: {
        director: $("#lm-director") ? $("#lm-director").value : "",
        writer: $("#lm-writer") ? $("#lm-writer").value : "",
        lorekeeper: $("#lm-keeper") ? $("#lm-keeper").value : "",
        context_tokens: Number($("#lm-ctx").value) || 16384,
      },
      hosted: {
        model: $("#hm-model").value.trim(),
        base_url: $("#hm-base").value.trim(),
        context_tokens: Number($("#hm-ctx").value) || 131072,
        api_key: $("#hm-key").value.trim(),
        // "" means "follow the hosted model". The server only writes a stage pin
        // when this names an actual local model, so saving in hosted mode no
        // longer wipes a hand-configured local Director.
        director_local: $("#hm-director") ? $("#hm-director").value : "",
        lorekeeper_local: $("#hm-lorekeeper") ? $("#hm-lorekeeper").value : "",
      },
    };
    return body;
  };

  // Apply the form. Returns true on success. Shared by both Save buttons.
  const applySettings = async (statusEl) => {
    try {
      await api("/api/settings", {method: "PUT", body: settingsBody()});
      invalidateReady();          // the model may now (or no longer) be reachable
      setBrainline();
      if (statusEl) {
        statusEl.textContent = "Saved — applied to new turns.";
        setTimeout(() => { statusEl.textContent = ""; }, 3000);
      }
      return true;
    } catch (e) {
      if (statusEl) statusEl.textContent = "error: " + e.message;
      return false;
    }
  };

  $("#save-settings").addEventListener("click",
    () => applySettings($("#save-status")));

  // Does semantic recall actually work? The checkbox alone was misleading: a
  // provider with no embeddings endpoint left it "on" while doing nothing.
  const rtCheck = $("#rt-check");
  if (rtCheck) rtCheck.addEventListener("click", async () => {
    const out = $("#rt-status");
    rtCheck.disabled = true;
    out.textContent = "Saving settings and testing embeddings…";
    if (!await applySettings(null)) {       // test what's on screen, not on disk
      rtCheck.disabled = false;
      out.textContent = "Couldn't save the settings to test them.";
      return;
    }
    try {
      const r = await api("/api/retrieval/check");
      out.textContent = (r.ok ? "✓ " : "✗ ") + (r.detail || r.state)
        + (r.error ? ` (${r.error})` : "");
      out.style.color = r.ok ? "var(--ok)" : "var(--player)";
    } catch (e) {
      out.textContent = "Check failed: " + e.message;
      out.style.color = "var(--player)";
    }
    rtCheck.disabled = false;
  });
}

/* ---------- brainline ---------- */
export async function setBrainline() {
  try {
    const st = await api("/api/settings");
    $("#brainline").textContent = st.mode === "hosted"
      ? `hosted: ${st.hosted.model}`
      : `local: ${st.local.director} → ${st.local.writer}`;
  } catch (_e) { /* server booting */ }
}

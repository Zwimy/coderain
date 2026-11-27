/* Settings: connection, model, memory, storytelling, play aids. */
import {$, api, esc, guard, toast, view} from "./util.js";
import {confirmModal} from "./modal.js";
import {invalidateReady, registerLeaveGuard} from "./nav.js";
import {render} from "./app.js";

/* ---------- settings ---------- */
export async function renderSettings() {
  // The model list asks the model server, which can take seconds when it is slow or half dead (2.4 s on a sandbox, and up to
  // the probe's own timeout), and the whole page used to wait for it. The page paints as soon as the settings are in; the
  // list is filled into the dropdowns when it arrives, without touching anything typed in the meantime.
  const slowLocal = api("/api/models/local").catch(e => (
    {installed: [], error: `could not read the model list (${e.message})`, suggestions: [], howto: [], server: "Ollama"}));
  const [st, hosted, profs] = await Promise.all([
    api("/api/settings"), api("/api/models/hosted"),
    api("/api/profiles").catch(() => ({profiles: [], active: ""})),
  ]);
  let local = await Promise.race([slowLocal, new Promise(r => setTimeout(() => r(null), 250))]);
  const late = local === null;
  if (late) local = {installed: [], error: "", suggestions: [], howto: [], server: "Ollama", loading: true};
  // The story-model dropdowns list models that can tell a story; embedding models are for semantic recall only.
  const names = local.installed.filter(m => !m.embedding).map(m => m.name);
  const opt = (list, sel) => list.map(n =>
    `<option ${n === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
  const localOpts = sel => opt(
    names.includes(sel) || !sel ? names : [sel, ...names], sel);
  const installedNote = l => l.loading ? "Looking for installed models…"
    : `Installed via ${esc(l.server || "Ollama")}: ${l.installed.map(m =>
        `${esc(m.name)}${m.size ? ` (${esc(m.size)})` : ""}`).join(", ") || "none detected"}.
      Suggested pulls: ${(l.suggestions || []).map(s =>
        `<b>${esc(s.name)}</b>: ${esc(s.note)}`).join("; ")}.`;
  const howtoHtml = l => (l.howto || []).map(p => `<p>${esc(p)}</p>`).join("");
  const errorText = l => l.error ? `${esc(l.error)}. Showing suggestions only.` : "";
  const namesWarn = (list, l) => (list.length || l.loading) ? "" : `<span style="color:var(--player)">${esc(l.server || "Ollama")} is not
        running or has no models pulled, so only the hosted option is
        available.</span>`;
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
      and switch between them, e.g. "fast local" vs "quality cloud".</p>
      <div class="row">
        <div style="flex:1"><label>Saved profiles</label>
          <select id="pf-list">
            <option value="">${profs.profiles.length ? "pick one"
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
      <h2>Local models, one per stage</h2>
      <details class="howto">
        <summary>New to this? Install Ollama &amp; set up local models</summary>
        <div id="local-howto">${howtoHtml(local)}</div>
      </details>
      <p class="muted" id="local-error" ${local.error ? "" : "hidden"}>${errorText(local)}</p>
      <div class="row">
        <div><label>Director (plans the turn; a thinking model)</label>
          <select id="lm-director" data-local>${localOpts(st.local.director)}</select></div>
        <div><label>Writer (prose; non-thinking is fine)</label>
          <select id="lm-writer" data-local>${localOpts(st.local.writer)}</select></div>
      </div>
      <div class="row">
        <div><label>Lore-keeper (optional continuity pass)</label>
          <select id="lm-keeper" data-local>
            <option value="" ${!st.local.lorekeeper ? "selected" : ""}>(none: skip it)</option>
            ${localOpts(st.local.lorekeeper)}</select></div>
        <div><label title="How much the model can READ at once (its window)."
          >Context window</label>
          <input id="lm-ctx" type="number" step="1024"
            value="${esc(st.local.context_tokens)}"></div>
      </div>
      <p class="muted">Context window = how much the model can read at once (set
        it to the model's real window). Reply length is set under Storytelling,
        not here.</p>
      <p class="muted" id="installed-note">${installedNote(local)}</p>
    </div>

    <div class="setting-panel" id="panel-hosted">
      <h2>Hosted model: one model runs every stage</h2>
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
        <div><label title="The model's context window: how much it can read.">
          Context window</label>
          <input id="hm-ctx" type="number" step="1024"
            value="${esc(st.hosted.context_tokens)}"></div>
      </div>
      <label>Base URL (OpenAI-compatible)</label>
      <input id="hm-base" value="${esc(st.hosted.base_url)}">
      <label>API key ${st.hosted.key_set
        ? '<span style="color:var(--ok)">(saved; leave blank to keep)</span>'
        : '<span style="color:var(--player)">(not saved yet)</span>'}</label>
      <input id="hm-key" type="password" placeholder="${st.hosted.key_set
        ? "••••••••" : "paste your key"}">
      <div style="display:flex; gap:10px; align-items:center; margin-top:8px">
        <button type="button" id="hm-test">Test connection</button>
        <span id="hm-test-status" class="muted" role="status"></span>
      </div>
      <p class="muted">Keys and stories live in this app's data folder:
        <code>${esc(st.home || "")}</code>. The desktop app and a source run use
        DIFFERENT folders, so a key saved in one will read as "not saved" in the
        other.</p>
      <div id="or-routing" hidden>
        <h2>OpenRouter: who may serve your requests</h2>
        <p class="muted">OpenRouter passes each request to one of several companies running the model. These choices go with every request
          to openrouter.ai, including semantic recall when it embeds there. If no provider can serve a request this way, it fails and says
          so; it is never sent without them.</p>
        <label><input type="checkbox" id="or-deny" ${st.generation.openrouter_provider.data_collection === "deny" ? "checked" : ""}>
          Only providers that do not keep or train on my prompts</label>
        <label><input type="checkbox" id="or-zdr" ${st.generation.openrouter_provider.zdr === true ? "checked" : ""}>
          Only zero data retention endpoints</label>
        <label><input type="checkbox" id="or-params" ${st.generation.openrouter_provider.require_parameters === true ? "checked" : ""}>
          Only providers that support every setting sent (such as Min-p or strict JSON)</label>
        <label>Providers to try first, in order (names separated by commas; blank = OpenRouter picks)</label>
        <input id="or-order" placeholder="deepinfra, together" value="${esc([].concat(st.generation.openrouter_provider.order || []).join(", "))}">
        <label><input type="checkbox" id="or-only" ${st.generation.openrouter_provider.allow_fallbacks === false ? "checked" : ""}>
          Use only these, with no fallback to others</label>
      </div>
      <h2>Supporting models (local, free)</h2>
      <p class="muted">The Director plans the turn and the Lore-keeper checks
        continuity. Both are structured work a small local model does well, and
        both run every turn, so pointing them at Ollama keeps the hosted model for
        the prose you are paying for. Leave either on
        <b>(use the hosted model)</b> to send it to the hosted endpoint instead.
        <span id="names-warn">${namesWarn(names, local)}</span></p>
      <div class="row">
        <div><label>Director</label>
          <select id="hm-director" data-local>
            <option value="">(use the hosted model)</option>
            ${localOpts(st.hosted.director_local || "")}
          </select></div>
        <div><label>Lore-keeper</label>
          <select id="hm-lorekeeper" data-local>
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
        <b>Balanced</b> = one call per turn, best for pure narrative.
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
        <p class="hint">Only worth it on a big hosted model; small local models
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
        one as each completes. Not a per-turn brain: it only plans at the
        memory-fold cadence. See the <b>Plan</b> button while playing.</p>
      <div class="indent">
        <label style="text-transform:uppercase;font-size:12px;color:var(--dim)"
          >Chapters planned ahead</label>
        <input type="number" id="gc-horizon" min="2" max="8" step="1"
          value="${st.generation.chapter_horizon || 4}" style="width:80px">
        <p class="hint">Default 4 (range 2 to 8). Higher = a longer plotted arc.</p>
      </div>

      <div class="sub-head">Continuity</div>
      <label><input type="checkbox" id="gc-lore"
        ${st.generation.lore_check ? "checked" : ""}>
        Continuity check (lore-keeper)</label>
      <p class="hint">The only stage that <b>verifies</b> rather than recalls: it
        looks up what the turn must not contradict and hands the writer the facts
        to honor. Strongest guard against contradictions, and the most expensive:
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
        <input type="checkbox" id="mm-follow" ${st.memory.follow_links ? "checked" : ""}>
        Follow connections (the lore web)
      </label>
      <p class="muted">When someone or something comes into play, also tell the writer, in one line each, about what is connected to it:
        who holds it, who it is tied to, who is tied to them. Secrets are never brought in this way. See the web with <b>Lore web…</b> in a
        story's Memory window or in the world builder.</p>
      <label>
        <input type="checkbox" id="mm-ties" ${st.memory.tail_ties ? "checked" : ""}>
        Repeat key facts next to your action
      </label>
      <p class="muted">Says who holds what and who is tied to whom once more, right after your action, for what you and the last reply
        named. In two rounds of tests on a small local model, both switches together made it use these facts clearly better. In one
        round it also gave away more secrets; in the other, the same number.</p>
      <label>
        <input type="checkbox" id="mm-search" ${st.memory.story_search ? "checked" : ""}>
        Search the story's own words
      </label>
      <p class="muted">For each action, finds up to three passages from earlier in the story (before the recent turns the writer already
        has) and quotes them, so an exact line said long ago can come back. At most one is an earlier line of yours. Works on its own by
        keyword; with semantic recall on, by meaning too. It can also quote a secret to a character who was never told it.</p>
      <label>
        <input type="checkbox" id="mm-bg" ${st.memory.background_folds ? "checked" : ""}>
        Summarize in the background
      </label>
      <p class="muted">Every few turns the story so far is folded into a memory summary. With this on, you get the reply first and the
        summary is written after it, so you can carry on at once. With a hosted model both can run together; a model on your own computer
        is shared, so the next reply may be slower while a summary is written. While one is written, changing the story's memory waits.</p>
      <label>
        <input type="checkbox" id="rt-enabled"
          ${st.retrieval.enabled ? "checked" : ""}>
        Semantic recall (find relevant past scenes by meaning, not just keywords)
      </label>
      <p class="muted">The strongest consistency feature: it surfaces the right
        past entry even when the wording doesn't match. Needs a provider that
        serves embeddings: many hosted story models (DeepSeek among them) do NOT,
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
        <label>Memory budget: how many tokens of story + memory to send each
          turn</label>
        <input id="mm-budget" value="${esc(st.memory.context_budget_tokens)}">
        <p class="muted">This is the main cost lever. A smaller number = cheaper,
          faster turns that lean more on summaries; larger = more raw detail in
          context. <b>"auto" fills the model's whole window every turn</b>. On a
          big-context model that gets very expensive, so a fixed number
          (8000 to 16000) is usually better.</p>
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
      <p class="muted">Every narrator turn will begin with this literal text.
      Handy to force dialogue or an action tag. Works with any model.</p>
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
          <div><label>Repetition penalty <span class="muted">(Ollama ignores it; some other servers use it)</span></label>
            <input id="gc-rep" type="number" step="0.05" min="0" max="2"
              value="${st.generation.repetition_penalty ?? ""}"></div>
          <div><label>Seed <span class="muted">(fixed = reproducible)</span></label>
            <input id="gc-seed" type="number" step="1" min="0"
              value="${st.generation.seed ?? ""}"></div>
        </div>
        <div class="row">
          <div><label>Min-p <span class="muted">(drops unlikely words; Ollama ignores it, some other servers use it)</span></label>
            <input id="gc-minp" type="number" step="0.01" min="0" max="1"
              value="${st.generation.min_p ?? ""}"></div>
        </div>
        <label><input type="checkbox" id="gc-json" ${st.generation.json_mode ? "checked" : ""}>
          Ask for strict JSON in the behind-the-scenes calls</label>
        <p class="muted">For the planner, the memory summaries and other calls that must answer in JSON, asks the server to force valid
          JSON. Story text is not affected. A server that refuses is noted in the story's health log and gets plain requests after that.</p>
      </details>
    </div>

    <div class="setting-panel">
      <h2>Quick actions (global)</h2>
      <p class="muted">Canned action buttons shown in every story's play bar, one
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

  // Unsaved edits: anything typed or changed on this page is lost when it is left, so leaving asks (nav.js). A save clears it.
  let dirty = false;
  const pageEl = view.firstElementChild;
  // "input" also fires for selects and checkboxes. The profile name and list are bookkeeping, and the rain switch is a local
  // preference applied at once, so none of those is a change that Save would write.
  pageEl.addEventListener("input", ev => { if (!ev.target.closest("#pf-name, #pf-list, #ap-rain")) dirty = true; });
  pageEl.addEventListener("click", ev => { if (ev.target.closest(".seg button")) dirty = true; });
  registerLeaveGuard(() => dirty);

  if (late) {
    slowLocal.then(real => {
      if (!document.body.contains(pageEl)) return;           // the reader has moved on
      const list = real.installed.filter(m => !m.embedding).map(m => m.name);
      pageEl.querySelectorAll("select[data-local]").forEach(sel => {
        const cur = sel.value;
        const blank = sel.querySelector("option[value='']");   // "(none)" and "(use the hosted model)" stay first
        sel.innerHTML = (blank ? blank.outerHTML : "") + opt(list.includes(cur) || !cur ? list : [cur, ...list], cur);
        if (cur || blank) sel.value = cur;     // with no value and no blank row the browser's own first pick stands
      });
      $("#local-howto").innerHTML = howtoHtml(real);
      const lerr = $("#local-error");
      lerr.innerHTML = errorText(real);
      lerr.hidden = !real.error;
      $("#installed-note").innerHTML = installedNote(real);
      $("#names-warn").innerHTML = namesWarn(list, real);
    });
  }

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
    toast(`${v[0].toUpperCase() + v.slice(1)} preset set. Press Save & apply.`,
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
  // Asks the provider's model list with what is typed here (the saved values fill any blank): no tokens are spent, and the
  // key goes to the base URL on this page and nowhere else. It is not an edit, so it does not mark the page unsaved.
  const hmTest = $("#hm-test"), hmTestStatus = $("#hm-test-status");
  hmTest.addEventListener("click", async () => {
    hmTest.disabled = true;
    hmTestStatus.textContent = "Testing…";
    hmTestStatus.style.color = "";
    try {
      const r = await api("/api/connection/test", {method: "POST", body: {
        base_url: $("#hm-base").value.trim(), api_key: $("#hm-key").value.trim(), model: $("#hm-model").value.trim()}});
      hmTestStatus.textContent = r.detail;
      hmTestStatus.style.color = r.ok ? "var(--ok)" : "var(--player)";
    } catch (e) {
      hmTestStatus.textContent = "Could not run the test: " + e.message;
      hmTestStatus.style.color = "var(--player)";
    } finally {
      hmTest.disabled = false;
    }
  });
  // The OpenRouter block shows only for an OpenRouter address, and is saved only while it shows: saving another provider keeps it.
  const isOpenRouter = () => {
    try {
      const h = new URL($("#hm-base").value.trim()).hostname.toLowerCase().replace(/\.$/, "");
      return h === "openrouter.ai" || h.endsWith(".openrouter.ai");
    } catch (_e) { return false; }
  };
  const syncRouting = () => { $("#or-routing").hidden = !isOpenRouter(); };
  $("#hm-base").addEventListener("input", syncRouting);
  syncRouting();
  $("#hm-preset").addEventListener("change", () => {
    const p = hosted.presets[Number($("#hm-preset").value)];
    if (!p) return;
    $("#hm-model").value = p.model;
    $("#hm-base").value = p.base_url;
    $("#hm-ctx").value = p.context;
    syncRouting();
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
        follow_links: $("#mm-follow").checked,
        tail_ties: $("#mm-ties").checked,
        story_search: $("#mm-search").checked,
        background_folds: $("#mm-bg").checked,
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
        min_p: $("#gc-minp").value,
        json_mode: $("#gc-json").checked,
        ...(isOpenRouter() ? {openrouter_provider: {
          order: $("#or-order").value,
          allow_fallbacks: !$("#or-only").checked,
          data_collection: $("#or-deny").checked ? "deny" : "",
          zdr: $("#or-zdr").checked,
          require_parameters: $("#or-params").checked,
        }} : {}),
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
      dirty = false;              // what is on screen is on disk now
      invalidateReady();          // the model may now (or no longer) be reachable
      setBrainline();
      if (statusEl) {
        statusEl.textContent = "Saved. Applied to new turns.";
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

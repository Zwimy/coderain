/* The library view — stories, worlds, and user defaults. */
import {$, api, esc, guard, toast, view} from "./util.js";
import {closeModal, confirmModal, openModal, promptModal} from "./modal.js";
import {render} from "./app.js";

/* ---------- library ---------- */
export async function renderLibrary() {
  const data = await api("/api/saves");
  const cards = data.saves.map(s => `
    <div class="card" data-slug="${esc(s.slug)}">
      <div class="title">${esc(s.title)}</div>
      <div class="meta">
        <span class="chip ${s.rpg_enabled || s.mode === "rpg" ? "rpg" : ""}">
          ${esc(s.mode || (s.rpg_enabled ? "rpg" : "simple"))}</span>
        ${s.scenario ? `<span>${esc(s.scenario)}</span>` : ""}
      </div>
      <div class="actions">
        <button data-act="open">Open</button>
        <button data-act="branch">Branch…</button>
        <button data-act="export">Export</button>
        <button data-act="delete" class="danger">Delete</button>
      </div>
    </div>`).join("");
  const worlds = data.scenarios.map(s => `
    <div class="card" data-scen="${esc(s.slug)}">
      <div class="title">${esc(s.title)}</div>
      <div class="muted">${esc(s.description || "")}</div>
      <div class="actions">
        <button data-act="play">Play</button>
        <button data-act="edit-scen">Edit</button>
        <button data-act="export-scen">Export</button>
        <button data-act="delete-scen" class="danger">Delete</button>
      </div>
    </div>`).join("");

  view.innerHTML = `<div class="page">
    <div class="page-head">
      <h1>Your stories</h1>
      <button id="import-save">Import…</button>
      <button class="primary" id="new-save">+ New story</button>
    </div>
    <div class="cards">${cards ||
      '<p class="muted">No stories yet — start one.</p>'}</div>
    <div class="page-head" style="margin-top:34px">
      <h1>Worlds</h1>
      <button id="import-card" title="import a SillyTavern / Tavern character card">Import card…</button>
      <button id="import-world">Import…</button>
      <button id="new-world">+ New world</button>
    </div>
    <p class="muted">A world is a reusable scenario: name, premise, and an
    introduction — the first message every story in it opens with. Open the
    builder to write every detail yourself, seed sections from an idea, or
    let the AI generate the rest.</p>
    <div class="cards">${worlds ||
      '<p class="muted">No worlds yet — build one.</p>'}</div>
  </div>`;

  $("#new-save").addEventListener("click", () => newSaveModal(data));
  $("#new-world").addEventListener("click", async () => {
    const out = await api("/api/scenarios",
                          {method: "POST", body: {title: "Untitled World"}});
    location.hash = `#world/${out.slug}`;
  });
  $("#import-save").addEventListener("click", () =>
    uploadFile("/api/saves-import", ".zip", () => render()));
  $("#import-world").addEventListener("click", () =>
    uploadFile("/api/scenarios-import", ".zip", () => render()));
  $("#import-card").addEventListener("click", () =>
    uploadFile("/api/cards-import", ".png,.json,.charx", out => {
      const c = out.counts || {};
      toast(`Imported "${out.slug}" — ${c.lore || 0} lore entr`
            + `${(c.lore || 0) === 1 ? "y" : "ies"} + the character. `
            + "Opening the builder to review.");
      location.hash = `#world/${out.slug}`;
    }));
  view.querySelectorAll(".card[data-scen]").forEach(card => {
    const scen = card.dataset.scen;
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      if (act === "delete-scen") {
        ev.stopPropagation();
        if (!await confirmModal("Delete this world? Existing stories keep their copy."))
          return;
        await api(`/api/scenarios/${scen}`, {method: "DELETE"});
        render();
      } else if (act === "edit-scen") {
        ev.stopPropagation();
        location.hash = `#world/${scen}`;
      } else if (act === "export-scen") {
        ev.stopPropagation();
        window.location.href = `/api/scenarios/${scen}/export`;
      } else {
        newSaveModal(data, scen);
      }
    });
  });
  // Save cards ONLY — [data-slug] excludes world cards (which carry data-scen).
  // Without the filter a world card gets BOTH handlers, and this one's `else`
  // branch navigates to #play/undefined (its slug is undefined) — the "no such
  // save: undefined" crash when deleting a world.
  view.querySelectorAll(".card[data-slug]").forEach(card => {
    const slug = card.dataset.slug;
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      if (act === "delete") {
        ev.stopPropagation();
        if (!await confirmModal("Delete this save for good?")) return;
        // guard(), like every other 409-capable call. Deleting a story whose
        // turn is still generating answers "a turn is generating — try again
        // in a moment", and unguarded that became an uncaught rejection: the
        // modal closed, the card stayed, the save stayed, and nothing said why.
        const done = await guard(
          () => api(`/api/saves/${slug}`, {method: "DELETE"}),
          "Couldn't delete this save");
        if (done === undefined) return;      // guard() toasted; leave the card
        render();
      } else if (act === "branch") {
        ev.stopPropagation();
        const info = await api(`/api/saves/${slug}`);
        const n = await promptModal("Branch this story", {
          placeholder: `1 – ${info.turns.length}`, okLabel: "Branch",
          hint: `Copies the story and rewinds it to that turn. `
                + `It currently has ${info.turns.length}.`});
        if (!n) return;
        const out = await guard(
          () => api(`/api/saves/${slug}/branch`,
                    {method: "POST", body: {turn: Number(n)}}),
          "Couldn't branch");
        if (!out) return;
        if (out.warnings && out.warnings.length) toast(out.warnings.join("\n"));
        location.hash = `#play/${out.slug}`;
      } else if (act === "export") {
        ev.stopPropagation();
        window.location.href = `/api/saves/${slug}/export`;
      } else {
        location.hash = `#play/${slug}`;
      }
    });
  });
}

export function newSaveModal(data, preselect) {
  const scen = data.scenarios.map(s =>
    `<option value="${esc(s.slug)}" ${s.slug === preselect ? "selected" : ""}>
     ${esc(s.title)}</option>`).join("");
  openModal(`
    <h1>New story</h1>
    <label>Name</label><input id="ns-title" placeholder="My adventure">
    <label>World</label>
    <select id="ns-scenario">
      <option value="">(blank world — write a premise)</option>${scen}
    </select>
    <div id="ns-premise-wrap">
      <label>Premise</label>
      <textarea id="ns-premise" rows="3"
        placeholder="A dark-fantasy default is used when left empty."></textarea>
    </div>
    <label>Story mode</label>
    <div class="seg" id="ns-mode">
      <button data-v="simple" class="on">Simple</button>
      <button data-v="rpg">RPG campaign</button>
    </div>
    <label>Play as</label>
    <select id="ns-char"></select>
    <div id="ns-newchar" class="hidden" style="margin-top:8px">
      <label>Your character's name</label>
      <input id="ns-pname" placeholder="e.g. Mara Vane">
      <label>Who you are (a short description)</label>
      <textarea id="ns-pdesc" rows="3"
        placeholder="A wandering hedge-witch with a debt to a dangerous patron…"></textarea>
    </div>
    <details class="howto" style="margin-top:14px">
      <summary>Starting day &amp; time (optional)</summary>
      <p class="muted">Not every story begins on Day 1 at dawn. Set where the
      in-world clock starts; the calendar label is free text for a fictional
      date the AI will honour.</p>
      <div class="row">
        <div><label>Day #</label>
          <input id="ns-day" type="number" min="1" value="1"></div>
        <div><label>Time of day</label>
          <input id="ns-phase" list="phases" value="morning"></div>
      </div>
      <datalist id="phases">
        <option>dawn</option><option>morning</option><option>midday</option>
        <option>afternoon</option><option>evening</option><option>dusk</option>
        <option>night</option><option>midnight</option>
      </datalist>
      <label>Calendar / date (fictional, optional)</label>
      <input id="ns-cal" placeholder="e.g. 3rd of Frostmoon, Year 812">
    </details>
    <div class="modal-actions">
      <button id="ns-cancel">Cancel</button>
      <button class="primary" id="ns-go">Begin</button>
    </div>`);
  let mode = "simple";
  // The offer depends on the world: a scenario offers ITS playable
  // characters (user-added or AI-generated); a blank world falls back to
  // your library's playable sheets.
  const fillPlayAs = async () => {
    const sel = $("#ns-char");
    const scenSlug = $("#ns-scenario").value;
    let opts = "";
    if (scenSlug) {
      try {
        const out = await api(`/api/scenarios/${scenSlug}/playable`);
        opts = out.playable.map(p =>
          `<option value="p:${esc(p.slug)}">${esc(p.title)}</option>`).join("");
      } catch (_e) { /* world without characters */ }
    } else {
      opts = data.characters.filter(c => (c.kind || "playable") === "playable")
        .map(c => `<option value="c:${esc(c.id)}">${esc(c.name)}</option>`)
        .join("");
    }
    sel.innerHTML = '<option value="">(let the story decide)</option>' + opts
      + '<option value="new">＋ Create my own character…</option>';
    toggleNewChar();
  };
  const toggleNewChar = () => {
    const box = $("#ns-newchar");
    if (box) box.classList.toggle("hidden", $("#ns-char").value !== "new");
  };
  $("#ns-mode").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    mode = ev.target.dataset.v;
    $("#ns-mode").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === mode));
  });
  $("#ns-premise-wrap").classList.toggle("hidden", Boolean(preselect));
  $("#ns-scenario").addEventListener("change", () => {
    $("#ns-premise-wrap").classList.toggle(
      "hidden", Boolean($("#ns-scenario").value));
    fillPlayAs();
  });
  fillPlayAs();
  $("#ns-char").addEventListener("change", toggleNewChar);
  $("#ns-cancel").addEventListener("click", closeModal);
  $("#ns-go").addEventListener("click", async () => {
    const pick = $("#ns-char").value;
    const out = await api("/api/saves", {method: "POST", body: {
      title: $("#ns-title").value.trim() || "Untitled",
      scenario: $("#ns-scenario").value,
      premise: $("#ns-premise").value.trim(),
      mode,
      character: pick.startsWith("c:") ? pick.slice(2) : "",
      playable: pick.startsWith("p:") ? pick.slice(2) : "",
      player_name: pick === "new" ? $("#ns-pname").value.trim() : "",
      player_desc: pick === "new" ? $("#ns-pdesc").value.trim() : "",
      start_time: {
        day: Number($("#ns-day").value) || 1,
        phase: $("#ns-phase").value.trim(),
        note: $("#ns-cal").value.trim(),
      },
    }});
    closeModal();
    location.hash = `#play/${out.slug}`;
  });
}

/* ---------- user defaults (own nav page) ---------- */
export async function renderDefaults() {
  view.innerHTML = `<div class="page">
    <div class="page-head">
      <h1>User defaults</h1>
      <button id="defaults-import">Import…</button>
      <button class="primary" id="defaults-export">Export</button>
    </div>
    <p class="muted">Your own starting templates — every NEW world and story is
    seeded from these instead of the shipped ones. Edit one to make it yours,
    or revert to the version the app ships with at any time.</p>
    <div class="cards" id="defaults-cards"><p class="muted">loading…</p></div>
  </div>`;
  $("#defaults-export").addEventListener("click", () => {
    window.location.href = "/api/defaults-export";
  });
  $("#defaults-import").addEventListener("click", () =>
    uploadFile("/api/defaults-import", ".zip", () => {
      toast("Defaults imported.");
      loadDefaultsSection();
    }));
  loadDefaultsSection();
}

/* Shared file-picker → POST multipart upload → callback. Used by every Import
   button (defaults, saves, worlds). */
export function uploadFile(url, accept, done) {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = accept;
  inp.addEventListener("change", async () => {
    const f = inp.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch(url, {method: "POST", body: fd});
      if (!r.ok) {
        let msg = r.statusText;
        try { msg = (await r.json()).detail || msg; } catch (_e) { /**/ }
        throw new Error(msg);
      }
      done(await r.json());
    } catch (e) { toast("Import failed: " + e.message); }
  });
  inp.click();
}

/* ---------- user defaults cards ---------- */
export async function loadDefaultsSection() {
  const holder = $("#defaults-cards");
  if (!holder) return;
  const data = await api("/api/defaults");
  holder.innerHTML = data.defaults.map(d => `
    <div class="card" data-def="${esc(d.name)}">
      <div class="title" style="font-size:14px">${esc(d.name)}</div>
      <div class="meta">
        <span class="chip">${esc(d.kind)}</span>
        ${d.customized ? '<span class="chip rpg">customized</span>' : ""}
      </div>
      <div class="actions">
        <button data-act="edit-def">Edit</button>
        <button data-act="revert-def" class="danger"
          ${d.customized ? "" : "disabled"}>Revert to shipped</button>
      </div>
    </div>`).join("");
  holder.querySelectorAll(".card[data-def]").forEach(card => {
    const name = card.dataset.def;
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      if (act === "revert-def") {
        ev.stopPropagation();
        if (!await confirmModal(`Revert ${name} to the shipped default?`)) return;
        await api(`/api/defaults/${name}/revert`, {method: "POST"});
        loadDefaultsSection();
      } else {
        const d = await api(`/api/defaults/${name}`);
        openModal(`
          <h1>${esc(name)}</h1>
          <p class="muted">Seeds every NEW world/story. Existing ones keep
          their copies.</p>
          <textarea id="def-text" rows="18"
            style="font-family:var(--mono);font-size:12px">${esc(d.text)}</textarea>
          <div class="modal-actions">
            <button id="def-cancel">Cancel</button>
            <button class="primary" id="def-save">Save</button>
          </div>`);
        $("#def-cancel").addEventListener("click", closeModal);
        $("#def-save").addEventListener("click", async () => {
          await api(`/api/defaults/${name}`, {
            method: "PUT", body: {text: $("#def-text").value}});
          closeModal();
          loadDefaultsSection();
        });
      }
    });
  });
}

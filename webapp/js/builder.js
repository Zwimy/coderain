/* The world builder: premise, pieces, custom lore types.
   Shared by scenarios and by a save's own copy of its world. */
import {$, api, chipInput, esc, guard, sse, toast, view} from "./util.js";
import {CHIPS, TRAIT_HINT, TRAIT_LABEL, TRAIT_LIMIT, csv, fieldsFor, mergeFill, unmanaged} from "./pieceform.js";
import {
  closeModal,
  confirmModal,
  modalCard,
  openModal,
  promptModal
} from "./modal.js";
import {clearDirty, registerDirty} from "./nav.js";
import {render} from "./app.js";

/* ---------- world builder (#world/<slug>) ---------- */
export const PIECE_LABELS = {
  "characters.md": "Characters", "locations.md": "Locations",
  "items.md": "Items", "factions.md": "Factions", "threads.md": "Threads",
  "events.md": "Events (when X, then Y)",
};

export const PIECE_KIND = rel => {
  const base = rel.replace(".md", "");
  return {"characters": "character", "locations": "location",
          "items": "item", "factions": "faction", "threads": "thread",
          "events": "event"}[base] || base;
};

export const KIND_REL = kind => ({
  character: "characters.md", location: "locations.md", item: "items.md",
  faction: "factions.md", thread: "threads.md", event: "events.md",
}[kind] || kind + ".md");

export async function renderBuilder(slug, scope = "scenario") {
  const isSave = scope === "save";
  const base = isSave ? `/api/saves/${slug}/world` : `/api/scenarios/${slug}`;
  const backHash = isSave ? `#play/${slug}` : "#library";
  const w = await api(`${base}/full`);
  const field = (id, label, rows, val, ph) => `
    <div class="setting-panel">
      <div class="field-head">
        <h2 style="margin:0">${label}</h2>
        <span style="flex:1"></span>
        <button class="mini" data-seed="${id}">✨ Seed from idea</button>
        <button class="mini" data-improve="${id}">Improve with AI</button>
      </div>
      <textarea id="${id}" rows="${rows}"
        placeholder="${esc(ph)}">${esc(val)}</textarea>
    </div>`;

  const groups = Object.keys(w.pieces).map(rel => `
    <div class="setting-panel" data-group="${esc(rel)}">
      <div class="field-head">
        <h2 style="margin:0">${esc(PIECE_LABELS[rel] ||
          rel.replace(".md", "").replace(/-/g, " "))}
          <span class="muted">(${w.pieces[rel].length})</span></h2>
        <span style="flex:1"></span>
        <button class="mini" data-fromlib="${esc(rel)}">From library…</button>
        <button class="mini" data-exportsec="${esc(rel)}">Export</button>
        ${PIECE_LABELS[rel] ? "" :
          `<button class="mini danger" data-deltype="${esc(rel)}">Remove type</button>`}
        <button class="mini" data-newpiece="${esc(rel)}">+ New</button>
      </div>
      <div class="piece-row">${w.pieces[rel].map(p => `
        <button class="piece-chip" data-piece="${esc(rel)}|${esc(p.slug)}">
          ${esc(p.title)}${p.attrs && p.attrs.playable ? " ★" : ""}
          ${p.attrs && p.attrs.hidden === "true" ? " 🕯" : ""}
        </button>`).join("") ||
        '<span class="muted">none yet</span>'}</div>
    </div>
    ${rel === "characters.md" ? `<div style="margin:-6px 0 14px">
      <button class="mini" id="b-addtype">+ Add lore type…</button>
    </div>` : ""}`).join("");

  view.innerHTML = `<div class="page" id="builder">
    <div class="page-head">
      <button id="back">${isSave ? "← Story" : "← Library"}</button>
      <h1 style="margin:0">${isSave ? "Edit this story" : "World builder"}</h1>
      <span style="flex:1"></span>
      <label style="display:flex;align-items:center;gap:6px;margin:0;
                    text-transform:none;font-size:13px">
        <input type="checkbox" id="b-improve" style="width:auto">
        Use prompt improver on seeds
      </label>
      <button class="primary" id="b-save">${isSave ? "Save changes"
        : "Save world"}</button>
      ${isSave ? "" : '<button id="b-tolib" title="copy every character, '
        + 'location, item &amp; faction here into your reusable Pieces library"'
        + '>Add all to library</button>'}
    </div>
    ${isSave ? `<p class="muted">These are THIS story's own live files: edits
      apply from your next turn. They started as copies of the world and have
      been evolving as you play.</p>` : ""}
    <div class="setting-panel">
      <h2 style="margin-top:0">Main details</h2>
      <div class="row">
        <div><label>Name</label><input id="b-title" value="${esc(w.title)}"></div>
        ${isSave ? "" : `<div><label>Description (card blurb)</label>
          <input id="b-desc" value="${esc(w.description)}"></div>`}
      </div>
    </div>
    ${field("b-premise", "Premise", 5, w.premise,
            isSave ? "The situation this story is set in (always in context)."
                   : "The situation every story in this world drops into.")}
    ${isSave ? "" : field("b-intro",
            "Introduction: the first message of every story", 6,
            w.introduction,
            "Second person, present tense. Blank = improvised per story.")}
    ${field("b-world", "World details", 8, w.world,
            "History, geography, factions, magic/technology, tone.")}
    ${groups}
    ${isSave ? "" : `<div class="setting-panel">
      <div class="field-head">
        <h2 style="margin:0">Generate the rest with AI</h2>
      </div>
      <p class="muted">Fills only what's empty (premise, introduction, world
      details, and lore groups up to the counts below). Everything you wrote
      is kept and new pieces are written to fit it.</p>
      <div class="row">
        <div><label>Type</label><input id="b-type" placeholder="optional"></div>
        <div><label>Tone</label><input id="b-tone" placeholder="optional"></div>
      </div>
      <div class="row">
        <div><label>NPCs</label>
          <input id="b-npcs" type="number" min="0" max="20" value="5"></div>
        <div><label>Locations</label>
          <input id="b-locs" type="number" min="0" max="20" value="5"></div>
        <div><label>Items</label>
          <input id="b-items" type="number" min="0" max="20" value="5"></div>
      </div>
      <pre class="table hidden" id="b-log"></pre>
      <div class="modal-actions" style="justify-content:flex-start">
        <button class="primary" id="b-complete">Generate the rest</button>
      </div>
    </div>`}
  </div>`;

  const mainFields = () => ({
    title: $("#b-title").value.trim(),
    description: $("#b-desc") ? $("#b-desc").value.trim() : "",
    premise: $("#b-premise").value.trim(),
    ...($("#b-intro") ? {introduction: $("#b-intro").value.trim()} : {}),
    world: $("#b-world").value.trim(),
  });
  let cleanState = JSON.stringify(mainFields());
  const saveMain = async () => {
    const body = mainFields();
    const out = await api(`${base}/main`, {method: "PUT", body});
    cleanState = JSON.stringify(body);          // now matches what's on disk
    return out;
  };
  // Navigating away (topbar, browser Back, tab close) no longer loses the text.
  registerDirty(() => {
    const el = $("#b-title");
    return Boolean(el && document.body.contains(el)
                   && JSON.stringify(mainFields()) !== cleanState);
  }, saveMain);

  $("#back").addEventListener("click", async () => {
    await guard(saveMain, "Couldn't save this world");
    clearDirty();
    location.hash = backHash;
  });
  $("#b-save").addEventListener("click", async () => {
    if (await guard(saveMain, "Couldn't save this world") === undefined) return;
    const label = isSave ? "Save changes" : "Save world";
    $("#b-save").textContent = "Saved ✓";
    setTimeout(() => {
      if ($("#b-save")) $("#b-save").textContent = label;
    }, 1500);
  });
  const tolib = $("#b-tolib");
  if (tolib) tolib.addEventListener("click", async () => {
    await guard(saveMain, "Couldn't save first");   // mirror the saved state
    const out = await guard(
      () => api(`/api/scenarios/${slug}/to-library`, {method: "POST"}),
      "Couldn't add to the library");
    if (!out) return;
    const a = out.added || {};
    toast(`Added ${a.characters || 0} characters + ${a.pieces || 0} pieces to your `
          + "library.", "ok");
  });

  const FIELD_KIND = {"b-premise": "premise", "b-intro": "introduction",
                      "b-world": "world"};
  const assist = async (id, mode) => {
    const ta = $("#" + id);
    let text = ta.value.trim();
    if (mode === "seed") {
      // Multiline: this is a creative prompt, and a single-line native dialog
      // was the worst possible widget for "describe your idea".
      text = await promptModal("Seed this from an idea", {
        multiline: true, okLabel: "Generate",
        placeholder: "A rain-soaked frontier town on the edge of a haunted forest…",
        hint: "Leave it blank to let the AI decide."});
      if (text === null) return;
    } else if (!text) {
      toast("Nothing to improve yet. Write something or seed it first.");
      return;
    }
    // The status goes NEXT TO the field, never into it. The field's value is what Back, Save and every navigation write
    // to disk (mainFields), so a placeholder put in the value was saved over the author's own premise whenever they left
    // the page while the model was still working. The request is the only thing that may replace the text, and only when
    // it succeeds.
    ta.disabled = true;
    ta.setAttribute("aria-busy", "true");
    const status = document.createElement("div");
    status.className = "muted assist-status";
    status.setAttribute("role", "status");
    status.textContent = mode === "seed" ? "✨ generating…" : "✨ improving…";
    ta.insertAdjacentElement("afterend", status);
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind: FIELD_KIND[id], mode, text, scenario: slug,
        improve: $("#b-improve").checked,
      }});
      ta.value = out.text;
    } catch (e) {
      toast(e.message);
    } finally {
      status.remove();
      ta.removeAttribute("aria-busy");
      ta.disabled = false;
    }
  };
  view.querySelectorAll("[data-seed]").forEach(b => b.addEventListener(
    "click", () => assist(b.dataset.seed, "seed")));
  view.querySelectorAll("[data-improve]").forEach(b => b.addEventListener(
    "click", () => assist(b.dataset.improve, "improve")));

  // World vocabulary for the chip autocompletes: every card (title+slug) and
  // every trait already used anywhere in this world.
  const allPieces = Object.values(w.pieces).flat();
  const vocab = {
    entities: allPieces.map(p => ({title: p.title, slug: p.slug})),
    traits: [...new Set(allPieces.flatMap(p =>
      String((p.attrs && p.attrs.traits) || "").split(",")
        .map(s => s.trim()).filter(Boolean)))].sort(),
  };
  view.querySelectorAll("[data-newpiece]").forEach(b => b.addEventListener(
    "click", () => pieceModal(slug, b.dataset.newpiece, null, null, base, vocab)));
  view.querySelectorAll("[data-piece]").forEach(b => b.addEventListener(
    "click", () => {
      const [rel, pslug] = b.dataset.piece.split("|");
      const p = w.pieces[rel].find(x => x.slug === pslug);
      pieceModal(slug, rel, p, null, base, vocab);
    }));

  view.querySelectorAll("[data-fromlib]").forEach(b => b.addEventListener(
    "click", async () => {
      const rel = b.dataset.fromlib;
      const isChar = rel === "characters.md";
      let items;
      if (isChar) {
        const data = await api("/api/characters");
        items = data.characters.map(c => ({
          id: c.id, title: c.name, tag: c.kind || "playable",
          blurb: c.description || ""}));
      } else {
        const data = await api(`/api/library?type=${PIECE_KIND(rel)}`);
        items = data.pieces.map(p => ({
          id: p.id, title: p.entry.title, tag: "",
          blurb: p.entry.body || ""}));
      }
      if (!items.length) {
        toast("Nothing of this type in your library yet. Save a piece to "
              + "it first (piece editor → 'Save to library').");
        return;
      }
      openModal(`
        <h1>From your library</h1>
        <div class="cards">${items.map(it => `
          <div class="card" data-lib="${esc(it.id)}">
            <div class="title">${esc(it.title)}</div>
            ${it.tag ? `<div class="meta"><span class="chip ${
              it.tag === "playable" ? "rpg" : ""}">${esc(it.tag)}</span></div>`
              : ""}
            <div class="muted">${esc(it.blurb.slice(0, 90))}</div>
          </div>`).join("")}</div>
        <div class="modal-actions"><button id="lib-cancel">Cancel</button></div>`);
      $("#lib-cancel").addEventListener("click", closeModal);
      modalCard.querySelectorAll("[data-lib]").forEach(card =>
        card.addEventListener("click", async () => {
          await api(isChar ? `${base}/from-library`
                           : `${base}/from-piece-library`,
                    {method: "POST", body: {id: card.dataset.lib}});
          closeModal();
          await saveMain();
          render();
        }));
    }));

  view.querySelectorAll("[data-exportsec]").forEach(b => b.addEventListener(
    "click", () => {
      window.location.href =
        `${base}/pieces/${b.dataset.exportsec}/export`;
    }));

  view.querySelectorAll("[data-deltype]").forEach(b => b.addEventListener(
    "click", async () => {
      const rel = b.dataset.deltype;
      if (!await confirmModal(`Remove the '${rel.replace(".md", "")}' lore type? Its `
                   + "pieces are deleted with it.")) return;
      await saveMain();
      await api(`${base}/types/${rel}`, {method: "DELETE"});
      render();
    }));

  $("#b-addtype").addEventListener("click", async () => {
    const name = await promptModal("New lore type", {
      placeholder: "Races", okLabel: "Create",
      hint: "A new registry alongside Characters and Locations, e.g. Races, "
            + "Factions, Technology."});
    if (!name) return;
    try {
      await api(`${base}/types`, {method: "POST", body: {name}});
      await saveMain();
      render();
    } catch (e) { toast(e.message); }
  });

  const completeBtn = $("#b-complete");
  if (completeBtn) completeBtn.addEventListener("click", async () => {
    await saveMain();
    const log = $("#b-log");
    log.classList.remove("hidden");
    log.textContent = "starting…\n";
    $("#b-complete").disabled = true;
    try {
      await sse(`/api/scenarios/${slug}/complete`, {
        type: $("#b-type").value.trim(),
        tone: $("#b-tone").value.trim(),
        improve: $("#b-improve").checked,
        n_npcs: Number($("#b-npcs").value),
        n_locations: Number($("#b-locs").value),
        n_items: Number($("#b-items").value),
      }, {
        stage: m => { log.textContent += "· " + m.text + "\n";
                      log.scrollTop = log.scrollHeight; },
        done: m => { log.textContent += "✓ done\n"
                       + (m.events || []).map(x => "! " + x + "\n").join(""); },
        error: m => { log.textContent += "error: " + m.text + "\n"; },
      });
      setTimeout(render, 1200);
    } catch (e) {
      log.textContent += "error: " + e.message + "\n";
      $("#b-complete").disabled = false;
    }
  });
}

/* piece editor modal — shared by the builder (writes to the world) and the
   Library page (lib = {id, type}: writes to /api/library instead) */
export function pieceModal(slug, rel, piece, lib = null, base = null, vocab = null) {
  base = base || `/api/scenarios/${slug}`;
  vocab = vocab || {traits: [], entities: []};
  const kind = PIECE_KIND(rel);
  const a = (piece && piece.attrs) || {};
  const isChar = rel === "characters.md";
  const isEvent = rel === "events.md";
  const isItem = rel === "items.md";
  const isThread = rel === "threads.md";
  const check = (id, label, on) => `
    <label style="display:flex;align-items:center;gap:6px;text-transform:none">
      <input type="checkbox" id="${id}" style="width:auto" ${on ? "checked" : ""}>
      ${label}</label>`;
  openModal(`
    <h1>${piece ? "Edit" : "New"} ${esc(kind)}</h1>
    <div class="row" style="align-items:flex-end">
      <div style="flex:2"><label>Title</label>
        <input id="p-title" value="${esc(piece ? piece.title : "")}"></div>
      <div><button class="mini" id="p-seed" style="width:100%">✨ Seed from idea</button></div>
      <div><button class="mini" id="p-improve" style="width:100%"
        ${piece ? "" : "disabled"}>Improve with AI</button></div>
      <div><button class="mini" id="p-undo-ai" style="width:100%" hidden>Undo AI</button></div>
    </div>
    <!-- The idea is asked for HERE, not in a second dialog: there is one modal host, so a second dialog replaced this whole
         form (the seed handler then looked for a button that was gone and threw, and Cancel threw the form away). -->
    <div id="p-seed-row" class="row" hidden style="align-items:flex-end">
      <div style="flex:3"><label for="p-idea">Describe the idea (leave it blank to let the AI decide)</label>
        <textarea id="p-idea" rows="2" placeholder="A grim knight bound by a blood-oath…"></textarea></div>
      <div><button class="mini primary" id="p-seed-go">Generate</button></div>
      <div><button class="mini" id="p-seed-cancel">Cancel</button></div>
    </div>
    <div class="row">
      <div><label>Importance 1-5</label>
        <input id="p-imp" type="number" min="1" max="5"
          value="${esc(piece ? piece.importance : 3)}"></div>
      <div><label>Weight</label>
        <select id="p-weight">${["", "minor", "supplementary", "standard",
          "important", "critical"].map(v => `<option ${v === (a.weight || "")
          ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div><label>Aliases (comma)</label>
        <input id="p-aliases" value="${esc((piece && piece.aliases || []).join(", "))}"></div>
    </div>
    <label>Traits / tags</label>
    <div id="p-traits-chips"></div>
    <label>Triggers (extra activation keywords, comma)</label>
    <input id="p-triggers" value="${esc(a.triggers || "")}">
    <div class="row">
      ${check("p-pinned", "Pinned (always in context)", a.pinned === "true")}
      ${check("p-hidden", "Hidden (secret lore)", a.hidden === "true")}
      ${isChar ? check("p-playable", "Playable ★", a.playable === "true") : ""}
      ${isEvent ? check("p-once", "Fires once", a.once === "true") : ""}
    </div>
    ${isChar ? `<label>Wants (their goal right now: what they are trying to get)</label>
      <input id="p-wants" value="${esc(a.wants || "")}"
             placeholder="e.g. win the qualifier without revealing her handler">
      <label>Motivation (why they want it: the driver underneath)</label>
      <input id="p-motivation" value="${esc(a.motivation || "")}"
             placeholder="e.g. her sister's debt is owed to the people running it">
      <p class="muted">The story keeps these current: as the fiction changes what a
        character is after, the memory pass rewrites them. A character with no goal
        gets one filled in the next time they appear in a scene.</p>
      <div class="row">
      <div><label>Stats ("strength 3, agility 2")</label>
        <input id="p-stats" value="${esc(a.stats || "")}"></div>
      <div><label>Skills ("name (stat), …")</label>
        <input id="p-skills" value="${esc(a.skills || "")}"></div>
    </div>
    ${["strengths", "weaknesses", "personality", "goals"].map(f => `
      <label>${esc(TRAIT_LABEL[f])} <span class="muted">${esc(TRAIT_HINT[f])}</span></label>
      ${f === "personality"
        ? `<input id="p-${f}" maxlength="${TRAIT_LIMIT[f]}" value="${esc(a[f] || "")}">`
        : `<textarea id="p-${f}" rows="2" maxlength="${TRAIT_LIMIT[f]}">${esc(a[f] || "")}</textarea>`}`).join("")}` : ""}
    ${isItem ? `<label>Rarity</label>
      <select id="p-rarity">${["", "common", "uncommon", "rare", "epic",
        "legendary"].map(v => `<option ${v === (a.rarity || "") ? "selected"
        : ""}>${v}</option>`).join("")}</select>` : ""}
    ${isThread ? `<label>Objectives (semicolon-separated)</label>
      <input id="p-objectives" value="${esc(a.objectives || "")}">` : ""}
    <label>Content</label>
    <textarea id="p-body" rows="8">${esc(piece ? piece.body : "")}</textarea>
    <details class="adv">
      <summary>Activation (advanced)</summary>
      <p class="muted">Fine control over when this entry enters context. Blank =
        the normal keyword behaviour.</p>
      <div class="row">
        <div><label>Group</label>
          <input id="p-group" value="${esc(a.group || "")}"
                 placeholder="only one of a group fires"></div>
        <div><label>Chance %</label>
          <input id="p-chance" type="number" min="1" max="100"
                 value="${esc(a.chance || "")}" placeholder="100"></div>
      </div>
      <div class="row">
        <div><label>Delay (turns)</label>
          <input id="p-delay" type="number" min="0"
                 value="${esc(a.delay || "")}" placeholder="0"></div>
        <div><label>Sticky (turns)</label>
          <input id="p-sticky" type="number" min="0"
                 value="${esc(a.sticky || "")}" placeholder="0"></div>
        <div><label>Cooldown (turns)</label>
          <input id="p-cooldown" type="number" min="0"
                 value="${esc(a.cooldown || "")}" placeholder="0"></div>
      </div>
      <div class="row">
        <div><label>Requires ALL of (comma)</label>
          <input id="p-triggers-all" value="${esc(a.triggers_all || "")}"></div>
        <div><label>Blocked by (comma)</label>
          <input id="p-triggers-not" value="${esc(a.triggers_not || "")}"></div>
      </div>
      <div>
        <label>Linked cards (connect to other characters, places, factions…)</label>
        <div id="p-links-chips"></div>
      </div>
      <div class="row">
        ${check("p-semantic", "Semantic match (meaning, not just keywords)",
                a.semantic === "true")}
        ${check("p-recurse", "Recursive (may trigger other entries)",
                a.recurse === "true")}
      </div>
    </details>
    <div class="modal-actions">
      ${lib ? "" : '<button id="p-tolib">Save to library</button>'}
      ${piece && (!lib || lib.id)
        ? '<button id="p-delete" class="danger">Delete</button>' : ""}
      <span style="flex:1"></span>
      <button id="p-cancel">Cancel</button>
      <button class="primary" id="p-save">Save piece</button>
    </div>`);

  // Traits autocomplete from every trait already used in this world; links
  // autocomplete from every card in the world (show title, store slug), and this
  // card is excluded so it can't link to itself.
  const selfSlug = piece ? piece.slug : "";
  const chips = {
    traits: chipInput($("#p-traits-chips"), {
      value: csv(a.traits), suggestions: vocab.traits,
      placeholder: "brave, merchant, undead…"}),
    links: chipInput($("#p-links-chips"), {
      value: csv(a.links),
      suggestions: (vocab.entities || []).filter(e => e.slug !== selfSlug)
        .map(e => ({label: e.title, value: e.slug})),
      placeholder: "link a character, place, faction…"}),
  };
  // Attributes the form does not manage ride along untouched, so an entry's extra
  // header lines survive an edit (and an AI result replaces the ones it states).
  let carried = unmanaged(a);
  const fields = fieldsFor(rel);

  // ONE table (pieceform.js) drives both directions, so a field cannot be read
  // but not written, which is what made "Improve with AI" drop traits, links,
  // wants, motivation and the activation controls.
  const collect = () => {
    const attrs = {...carried};
    for (const f of fields) {
      const el = $("#" + f.id);
      if (!el) continue;
      attrs[f.attr] = f.kind === "check" ? (el.checked ? "true" : "") : el.value.trim();
    }
    for (const c of CHIPS) attrs[c] = chips[c].get().join(", ");
    return {
      title: $("#p-title").value.trim(),
      slug: piece ? piece.slug : "",
      importance: Number($("#p-imp").value) || 3,
      aliases: $("#p-aliases").value.split(",").map(s => s.trim())
        .filter(Boolean),
      attrs,
      body: $("#p-body").value.trim(),
    };
  };
  const apply = entry => {
    $("#p-title").value = entry.title || "";
    $("#p-imp").value = entry.importance || 3;
    $("#p-aliases").value = (entry.aliases || []).join(", ");
    $("#p-body").value = entry.body || "";
    const ea = entry.attrs || {};
    for (const f of fields) {
      const el = $("#" + f.id);
      if (!el) continue;
      if (f.kind === "check") el.checked = ea[f.attr] === "true";
      else el.value = ea[f.attr] || "";
    }
    for (const c of CHIPS) chips[c].set(csv(ea[c]));
    carried = unmanaged(ea);
  };
  // What an AI answer changes is decided in pieceform.js: everything it states, nothing it leaves out.
  const fill = entry => apply(mergeFill(collect(), entry));
  // One level of undo for the last AI result, until the piece is saved or the form closed.
  let undo = null;
  const applyAI = entry => {
    undo = collect();
    fill(entry);
    $("#p-undo-ai").hidden = false;
  };
  $("#p-undo-ai").addEventListener("click", () => {
    if (!undo) return;
    apply(undo);
    undo = null;
    $("#p-undo-ai").hidden = true;
  });

  $("#p-cancel").addEventListener("click", closeModal);
  $("#p-save").addEventListener("click", async () => {
    const entry = collect();
    if (!entry.title) { toast("A piece needs a title."); return; }
    // Guarded: a 409 (turn generating) used to close nothing, save nothing and
    // say nothing, losing everything typed into the form.
    const ok = await guard(() => lib
      ? api("/api/library", {method: "POST", body: {
          type: lib.type, entry, id: lib.id || ""}})
      : api(`${base}/pieces/${rel}`, {method: "PUT", body: {
          entry, old_slug: piece ? piece.slug : ""}}),
      "Couldn't save this piece");
    if (ok === undefined) return;            // keep the form open
    closeModal();
    render();
  });
  const del = $("#p-delete");
  if (del) del.addEventListener("click", async () => {
    if (!await confirmModal(`Delete “${piece.title}”?`,
                            "This removes it from this world.")) return;
    const ok = await guard(() => lib
      ? api(`/api/library/${lib.id}`, {method: "DELETE"})
      : api(`${base}/pieces/${rel}/${piece.slug}`, {method: "DELETE"}),
      "Couldn't delete this piece");
    if (ok === undefined) return;
    closeModal();
    render();
  });
  const tolib = $("#p-tolib");
  if (tolib) tolib.addEventListener("click", async () => {
    const ok = await guard(() => isChar
      ? api("/api/characters/from-entry", {method: "POST", body: {entry: collect()}})
      : api("/api/library", {method: "POST", body: {type: kind, entry: collect()}}),
      "Couldn't save to the library");
    if (ok !== undefined) tolib.textContent = "Saved to library ✓";
  });

  const seedRow = $("#p-seed-row");
  $("#p-seed").addEventListener("click", () => {
    seedRow.hidden = false;
    $("#p-idea").focus();
  });
  $("#p-seed-cancel").addEventListener("click", () => {
    seedRow.hidden = true;
    $("#p-seed").focus();
  });
  $("#p-seed-go").addEventListener("click", async () => {
    const idea = $("#p-idea").value;
    $("#p-seed-go").disabled = true;
    $("#p-seed").disabled = true;
    $("#p-seed").textContent = "✨ generating…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind, mode: "seed", text: idea, scenario: slug,
        improve: Boolean($("#b-improve") && $("#b-improve").checked),
      }});
      applyAI(out.entry);
      seedRow.hidden = true;
    } catch (e) { toast(e.message); }
    // The modal can have been closed while the model worked: touch only what is still on screen.
    for (const [sel, fn] of [["#p-seed-go", el => { el.disabled = false; }],
                             ["#p-seed", el => { el.disabled = false; el.textContent = "✨ Seed from idea"; }]]) {
      const el = $(sel);
      if (el) fn(el);
    }
  });
  $("#p-improve").addEventListener("click", async () => {
    $("#p-improve").disabled = true;
    $("#p-improve").textContent = "✨ improving…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind, mode: "improve", text: JSON.stringify(collect()),
        scenario: slug,
      }});
      applyAI(out.entry);
    } catch (e) { toast(e.message); }
    $("#p-improve").disabled = false;
    $("#p-improve").textContent = "Improve with AI";
  });
}

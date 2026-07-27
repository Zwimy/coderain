/* The world builder: premise, pieces, custom lore types.
   Shared by scenarios and by a save's own copy of its world. */
import {$, api, chipInput, esc, guard, sse, toast, view} from "./util.js";
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
    ${isSave ? `<p class="muted">These are THIS story's own live files — edits
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
            "Introduction — the first message of every story", 6,
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
      toast("Nothing to improve yet — write something or seed it first.");
      return;
    }
    ta.disabled = true;
    const old = ta.value;
    ta.value = mode === "seed" ? "✨ generating…" : "✨ improving…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind: FIELD_KIND[id], mode, text, scenario: slug,
        improve: $("#b-improve").checked,
      }});
      ta.value = out.text;
    } catch (e) {
      ta.value = old;
      toast(e.message);
    }
    ta.disabled = false;
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
        toast("Nothing of this type in your library yet — save a piece to "
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
      hint: "A new registry alongside Characters and Locations — e.g. Races, "
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
    ${isChar ? `<label>Wants (their goal right now — what they are trying to get)</label>
      <input id="p-wants" value="${esc(a.wants || "")}"
             placeholder="e.g. win the qualifier without revealing her handler">
      <label>Motivation (why they want it — the driver underneath)</label>
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
    </div>` : ""}
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

  const csv = s => String(s || "").split(",").map(x => x.trim()).filter(Boolean);
  // Traits autocomplete from every trait already used in this world; links
  // autocomplete from every card in the world (show title, store slug), and this
  // card is excluded so it can't link to itself.
  const selfSlug = piece ? piece.slug : "";
  const traitChips = chipInput($("#p-traits-chips"), {
    value: csv(a.traits), suggestions: vocab.traits,
    placeholder: "brave, merchant, undead…"});
  const linkChips = chipInput($("#p-links-chips"), {
    value: csv(a.links),
    suggestions: (vocab.entities || []).filter(e => e.slug !== selfSlug)
      .map(e => ({label: e.title, value: e.slug})),
    placeholder: "link a character, place, faction…"});

  const collect = () => {
    const adv = id => ($("#" + id) ? $("#" + id).value.trim() : "");
    const attrs = {
      weight: $("#p-weight").value,
      triggers: $("#p-triggers").value.trim(),
      pinned: $("#p-pinned").checked ? "true" : "",
      hidden: $("#p-hidden").checked ? "true" : "",
      // Tier-2 activation controls — the engine has supported these all along,
      // but with no form fields they could only be written by hand in Markdown.
      group: adv("p-group"),
      chance: adv("p-chance"),
      delay: adv("p-delay"),
      sticky: adv("p-sticky"),
      cooldown: adv("p-cooldown"),
      triggers_all: adv("p-triggers-all"),
      triggers_not: adv("p-triggers-not"),
      traits: traitChips.get().join(", "),
      links: linkChips.get().join(", "),
      semantic: $("#p-semantic") && $("#p-semantic").checked ? "true" : "",
      recurse: $("#p-recurse") && $("#p-recurse").checked ? "true" : "",
    };
    // preserve attrs the form doesn't manage
    for (const [k, v] of Object.entries(a)) {
      if (!(k in attrs) && !["playable", "once", "stats", "skills", "rarity",
                             "objectives", "wants", "motivation"].includes(k)) {
        attrs[k] = v;
      }
    }
    if (isChar) {
      attrs.playable = $("#p-playable").checked ? "true" : "";
      attrs.stats = $("#p-stats").value.trim();
      attrs.skills = $("#p-skills").value.trim();
      attrs.wants = $("#p-wants").value.trim();
      attrs.motivation = $("#p-motivation").value.trim();
    }
    if (isEvent) attrs.once = $("#p-once").checked ? "true" : "";
    if (isItem) attrs.rarity = $("#p-rarity").value;
    if (isThread) attrs.objectives = $("#p-objectives").value.trim();
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
  const fill = entry => {
    $("#p-title").value = entry.title || "";
    $("#p-imp").value = entry.importance || 3;
    $("#p-aliases").value = (entry.aliases || []).join(", ");
    $("#p-body").value = entry.body || "";
    const ea = entry.attrs || {};
    $("#p-weight").value = ea.weight || "";
    $("#p-triggers").value = ea.triggers || "";
    $("#p-pinned").checked = ea.pinned === "true";
    $("#p-hidden").checked = ea.hidden === "true";
    if (isChar) {
      $("#p-playable").checked = ea.playable === "true";
      $("#p-stats").value = ea.stats || "";
      $("#p-skills").value = ea.skills || "";
    }
    if (isEvent) $("#p-once").checked = ea.once === "true";
    if (isItem) $("#p-rarity").value = ea.rarity || "";
    if (isThread) $("#p-objectives").value = ea.objectives || "";
  };

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

  $("#p-seed").addEventListener("click", async () => {
    const idea = await promptModal("Seed this piece from an idea", {
      multiline: true, okLabel: "Generate",
      placeholder: "A grim knight bound by a blood-oath…",
      hint: "Leave it blank to let the AI decide."});
    if (idea === null) return;
    $("#p-seed").disabled = true;
    $("#p-seed").textContent = "✨ generating…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind, mode: "seed", text: idea, scenario: slug,
        improve: Boolean($("#b-improve") && $("#b-improve").checked),
      }});
      fill(out.entry);
    } catch (e) { toast(e.message); }
    $("#p-seed").disabled = false;
    $("#p-seed").textContent = "✨ Seed from idea";
  });
  $("#p-improve").addEventListener("click", async () => {
    $("#p-improve").disabled = true;
    $("#p-improve").textContent = "✨ improving…";
    try {
      const out = await api("/api/assist", {method: "POST", body: {
        kind, mode: "improve", text: JSON.stringify(collect()),
        scenario: slug,
      }});
      fill(out.entry);
    } catch (e) { toast(e.message); }
    $("#p-improve").disabled = false;
    $("#p-improve").textContent = "Improve with AI";
  });
}

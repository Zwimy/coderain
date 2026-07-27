/* Saved characters and the reusable piece library. */
import {$, api, esc, view} from "./util.js";
import {closeModal, confirmModal, modalCard, openModal} from "./modal.js";
import {KIND_REL, pieceModal} from "./builder.js";
import {render} from "./app.js";

/* ---------- characters ---------- */
export let charFilter = "all";        // playable/npc sub-filter (Characters chip)

export let libType = "character";     // active Library type chip

export async function renderCharacters() {
  const [data, libd] = await Promise.all([
    api("/api/characters"), api("/api/library")]);
  const baseTypes = ["character", "location", "item", "faction", "thread",
                     "event"];
  const types = [...baseTypes,
                 ...libd.types.filter(t => !baseTypes.includes(t))];
  if (!types.includes(libType)) libType = "character";
  const chips = types.map(t => `<button data-v="${esc(t)}"
    ${libType === t ? 'class="on"' : ""}>${esc(t)}${
    t.endsWith("s") ? "" : "s"}</button>`).join("");
  const isChar = libType === "character";

  let cards, subFilter = "", newLabel;
  if (isChar) {
    newLabel = "+ New character";
    subFilter = `<div class="seg" id="ch-filter">
      ${["all", "playable", "npc"].map(v => `<button data-v="${v}"
        ${charFilter === v ? 'class="on"' : ""}>${v}</button>`).join("")}
    </div>`;
    const shown = data.characters.filter(c =>
      charFilter === "all" || (c.kind || "playable") === charFilter);
    cards = shown.map(c => `
      <div class="card" data-id="${esc(c.id)}">
        <div class="title">${esc(c.name)}</div>
        <div class="meta"><span class="chip ${
          (c.kind || "playable") === "playable" ? "rpg" : ""}">${
          esc(c.kind || "playable")}</span></div>
        <div class="muted">${esc(c.description || "")}</div>
        <div class="meta">${data.stats.map(s =>
          `<span class="chip">${s.slice(0, 3)} ${esc(c.stats?.[s] ?? 1)}</span>`)
          .join("")}</div>
        <div class="actions">
          <button data-act="edit">Edit</button>
          <button data-act="delete" class="danger">Delete</button>
        </div>
      </div>`).join("");
  } else {
    newLabel = `+ New ${libType}`;
    const shown = libd.pieces.filter(p => p.type === libType);
    cards = shown.map(p => `
      <div class="card" data-pid="${esc(p.id)}">
        <div class="title">${esc(p.entry.title)}</div>
        <div class="meta"><span class="chip">imp ${esc(p.entry.importance)}
          </span>${p.entry.attrs && p.entry.attrs.weight
          ? `<span class="chip">${esc(p.entry.attrs.weight)}</span>` : ""}</div>
        <div class="muted">${esc((p.entry.body || "").slice(0, 120))}</div>
        <div class="actions">
          <button data-act="edit">Edit</button>
          <button data-act="delete" class="danger">Delete</button>
        </div>
      </div>`).join("");
  }

  view.innerHTML = `<div class="page">
    <div class="page-head">
      <h1>Piece library</h1>
      <button class="primary" id="new-piece">${newLabel}</button>
    </div>
    <p class="muted">Your reusable pieces — drop any of them into a world from
    its builder ("From library…"), or send a world's piece here with
    "Save to library". <b>Playable</b> characters can be the protagonist of a
    story.</p>
    <div class="seg" id="lib-types">${chips}</div>
    ${subFilter}
    <div class="cards" style="margin-top:14px">${cards ||
      `<p class="muted">Nothing here yet.</p>`}</div>
  </div>`;

  $("#lib-types").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    libType = ev.target.dataset.v;
    render();
  });
  const chf = $("#ch-filter");
  if (chf) chf.addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    charFilter = ev.target.dataset.v;
    render();
  });
  $("#new-piece").addEventListener("click", () => {
    if (isChar) charModal(data.stats, null);
    else pieceModal("", KIND_REL(libType), null, {id: "", type: libType});
  });
  view.querySelectorAll(".card[data-id]").forEach(card => {
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      const c = data.characters.find(x => x.id === card.dataset.id);
      if (act === "delete") {
        if (!await confirmModal(`Delete ${c.name}? Worlds already using them keep their copy.`))
          return;
        await api(`/api/characters/${c.id}`, {method: "DELETE"});
        render();
      } else if (act === "edit" || !act) {
        charModal(data.stats, c);
      }
    });
  });
  view.querySelectorAll(".card[data-pid]").forEach(card => {
    card.addEventListener("click", async ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      const p = libd.pieces.find(x => x.id === card.dataset.pid);
      if (act === "delete") {
        if (!await confirmModal(`Delete '${p.entry.title}' from the library? Worlds `
                     + "already using it keep their copy.")) return;
        await api(`/api/library/${p.id}`, {method: "DELETE"});
        render();
      } else if (act === "edit" || !act) {
        pieceModal("", KIND_REL(p.type), p.entry, {id: p.id, type: p.type});
      }
    });
  });
}

export function charModal(statNames, c) {
  const stats = statNames.map(s => `
    <div><label>${esc(s)}</label>
    <input type="number" min="-5" max="10" data-stat="${esc(s)}"
      value="${esc(c?.stats?.[s] ?? 1)}"></div>`).join("");
  openModal(`
    <h1>${c ? "Edit" : "New"} character</h1>
    <label>Kind</label>
    <div class="seg" id="ch-kind">
      <button data-v="playable" ${(c?.kind || "playable") === "playable"
        ? 'class="on"' : ""}>Playable sheet</button>
      <button data-v="npc" ${c?.kind === "npc" ? 'class="on"' : ""}>NPC</button>
    </div>
    <label>Name</label><input id="ch-name" value="${esc(c?.name || "")}">
    <label>Description</label>
    <textarea id="ch-desc" rows="3">${esc(c?.description || "")}</textarea>
    <label>Traits (comma separated)</label>
    <input id="ch-traits" value="${esc(c?.traits || "")}">
    <label>Skills — "name (stat), name (stat)"</label>
    <input id="ch-skills" value="${esc(c?.skills || "")}"
      placeholder="lockpicking (agility), old tongues (knowledge)">
    <div class="row">
      <div><label>Aliases (comma)</label>
        <input id="ch-aliases" value="${esc((c?.aliases || []).join(", "))}"></div>
      <div><label>Importance 1-5</label>
        <input id="ch-imp" type="number" min="1" max="5"
          value="${esc(c?.importance ?? 4)}"></div>
      <div><label>Weight</label>
        <select id="ch-weight">${["", "minor", "supplementary", "standard",
          "important", "critical"].map(v => `<option ${
          v === (c?.extra?.weight || "") ? "selected" : ""}>${v}</option>`)
          .join("")}</select></div>
    </div>
    <label>Triggers (extra activation keywords, comma)</label>
    <input id="ch-triggers" value="${esc(c?.extra?.triggers || "")}">
    <div class="row">
      <label style="display:flex;align-items:center;gap:6px;text-transform:none">
        <input type="checkbox" id="ch-pinned" style="width:auto"
          ${c?.extra?.pinned === "true" ? "checked" : ""}>
        Pinned (always in context)</label>
      <label style="display:flex;align-items:center;gap:6px;text-transform:none">
        <input type="checkbox" id="ch-hidden" style="width:auto"
          ${c?.extra?.hidden === "true" ? "checked" : ""}>
        Hidden (secret lore)</label>
    </div>
    <h2>Stats</h2>
    <div class="stat-grid">${stats}</div>
    <div class="modal-actions">
      <button id="ch-cancel">Cancel</button>
      <button class="primary" id="ch-save">Save</button>
    </div>`);
  let kind = c?.kind || "playable";
  $("#ch-kind").addEventListener("click", ev => {
    if (!ev.target.dataset.v) return;
    kind = ev.target.dataset.v;
    $("#ch-kind").querySelectorAll("button").forEach(b =>
      b.classList.toggle("on", b.dataset.v === kind));
  });
  $("#ch-cancel").addEventListener("click", closeModal);
  $("#ch-save").addEventListener("click", async () => {
    const extra = {...(c?.extra || {})};
    extra.weight = $("#ch-weight").value;
    extra.triggers = $("#ch-triggers").value.trim();
    extra.pinned = $("#ch-pinned").checked ? "true" : "";
    extra.hidden = $("#ch-hidden").checked ? "true" : "";
    for (const k of Object.keys(extra)) if (!extra[k]) delete extra[k];
    const body = {
      id: c?.id, name: $("#ch-name").value, kind,
      description: $("#ch-desc").value, traits: $("#ch-traits").value,
      skills: $("#ch-skills").value, stats: {},
      aliases: $("#ch-aliases").value.split(",").map(s => s.trim())
        .filter(Boolean),
      importance: Number($("#ch-imp").value) || 4,
      extra,
    };
    modalCard.querySelectorAll("[data-stat]").forEach(inp => {
      body.stats[inp.dataset.stat] = Number(inp.value);
    });
    await api("/api/characters", {method: "POST", body});
    closeModal();
    render();
  });
}

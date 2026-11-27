/* The lore web (D-074): how a world's entries point at each other, drawn, and a way to add or take away a connection.

   Four things in the files make one entry point at another: an item's holder, a tie on a `relationships:` line, a `links:` line and a
   [[mention]] in the text. The graph shows them all; a connection added here is written as a tie, in the entry's own Markdown, which a
   fold keeps and whose note it never rewrites. The graph can be used without it: the entry picker, the nodes (Tab, Enter) and the list of
   connections with its buttons do everything the picture does. */
import {$, api, esc, guard, toast} from "./util.js";
import {closeModal, inlineConfirm, openModal} from "./modal.js";
import {layout} from "./loreweb_layout.js";

const TYPE_LABEL = {characters: "character", locations: "place", factions: "faction", items: "item", "canon-events": "event"};

const typeLabel = t => TYPE_LABEL[t] || t;

function shell() {
  return `<div class="lw">
    <h2>Lore web</h2>
    <p class="muted">How entries point at each other: who holds what, ties, links and [[mentions]]. With "follow connections" on in Settings,
      the writer is also told about what is connected to the entries in play. A secret is never brought in through the web.</p>
    <div class="row lw-tools">
      <label for="lw-pick">Entry</label>
      <select id="lw-pick"></select>
      <label class="lw-check"><input type="checkbox" id="lw-mentions"> Show [[mentions]]</label>
    </div>
    <svg id="lw-svg" role="group" aria-label="The entries and their connections" data-noguard></svg>
    <div id="lw-side"></div>
    <div class="modal-actions"><button id="lw-close">Close</button></div>
  </div>`;
}

export async function loreWebModal(base) {
  const url = `${base}/web`;
  let g = await guard(() => api(url), "Couldn't read the lore web");
  if (!g) return;
  let selected = "", mentions = false, pos = {};
  openModal(shell(), null, {guard: false});            // every change here is its own saved call: there is nothing to discard
  $("#lw-close").addEventListener("click", closeModal);
  // About one unit of the picture is one pixel on screen, so labels keep their size; a narrow screen gets a taller picture. Worked out
  // from the window (the dialog is at most 760px with 12px margins and 24px padding) rather than measured: measuring while the dialog
  // opens gave the wrong width.
  // Fitted again before every redraw, so a resized window, or a page that first reported no width, comes right.
  let W = 0, H = 0;
  const fit = () => {
    const wide = document.documentElement.clientWidth || window.innerWidth || 772;       // a hidden page can report 0
    const w = Math.round(Math.min(710, Math.max(280, wide - 62)));
    if (w === W) return false;
    W = w;
    H = W < 480 ? Math.round(W * 1.2) : 420;
    $("#lw-svg").setAttribute("viewBox", `0 0 ${W} ${H}`);
    return true;
  };
  fit();

  const shown = () => g.edges.filter(e => mentions || e.kind !== "mention");
  const byId = () => Object.fromEntries(g.nodes.map(x => [x.slug, x]));
  const arrange = () => { pos = layout(g.nodes.map(x => x.slug), shown().map(e => [e.from, e.to]), W, H, pos); };

  function drawPicker() {
    const pick = $("#lw-pick");
    pick.innerHTML = `<option value="">Choose an entry…</option>` + [...g.nodes].sort((a, b) => a.title.localeCompare(b.title))
      .map(x => `<option value="${esc(x.slug)}">${esc(x.title)} (${esc(typeLabel(x.type))}${x.hidden ? ", secret" : ""})</option>`).join("");
    pick.value = selected;
  }

  function drawGraph() {
    const nodes = byId(), edges = shown();
    const near = new Set(edges.flatMap(e => e.from === selected ? [e.to] : e.to === selected ? [e.from] : []));
    const lines = edges.map(e => {
      const a = pos[e.from], b = pos[e.to];
      if (!a || !b) return "";
      const hot = selected && (e.from === selected || e.to === selected);
      // stop the line at the edge of the circle it points at, so the arrow head is seen
      const d = Math.hypot(b.x - a.x, b.y - a.y) || 1, tx = b.x - ((b.x - a.x) / d) * 11, ty = b.y - ((b.y - a.y) / d) * 11;
      return `<line class="lw-edge lw-k-${e.kind}${hot ? " lw-hot" : selected ? " lw-dim" : ""}" x1="${a.x}" y1="${a.y}"
        x2="${tx}" y2="${ty}" marker-end="url(#lw-arrow)"><title>${esc(e.fact)}</title></line>`;
    }).join("");
    const dots = g.nodes.map(x => {
      const p = pos[x.slug];
      if (!p) return "";
      const state = x.slug === selected ? " lw-sel" : near.has(x.slug) ? " lw-near" : selected ? " lw-dim" : "";
      return `<g class="lw-node lw-t-${esc(x.type)}${x.hidden ? " lw-secret" : ""}${state}" data-node="${esc(x.slug)}" tabindex="0"
        role="button" aria-pressed="${x.slug === selected}" aria-label="${esc(x.title)}, ${esc(typeLabel(x.type))}${x.hidden ? ", secret" : ""}"
        transform="translate(${p.x},${p.y})"><circle r="8"></circle><text y="-12" text-anchor="middle">${esc(x.title)}</text></g>`;
    }).join("");
    $("#lw-svg").innerHTML = `<defs><marker id="lw-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6"
      orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"></path></marker></defs>${lines}${dots}`;
    if (!g.nodes.length) $("#lw-svg").innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="lw-empty">No entries yet</text>`;
    if (nodes[selected] === undefined) selected = "";
  }

  function drawSide() {
    const side = $("#lw-side"), x = byId()[selected];
    if (!x) {
      side.innerHTML = `<p class="hint">Choose an entry to see what it is connected to, or add a connection.
        ${g.edges.length ? "" : "Nothing is connected yet."}</p>`;
      return;
    }
    const mine = shown().filter(e => e.from === selected || e.to === selected);
    const others = [...g.nodes].filter(n => n.slug !== selected).sort((a, b) => a.title.localeCompare(b.title));
    side.innerHTML = `<h3>${esc(x.title)} <span class="muted">(${esc(typeLabel(x.type))}${x.hidden ? ", secret" : ""})</span></h3>
      ${mine.length ? `<ul class="lw-conns">${mine.map((e, i) => `<li><span>${esc(e.fact)}</span>
        ${e.kind === "mention" ? `<span class="muted">in the text</span>`
          : `<button class="mini" data-cut="${i}" aria-label="Remove: ${esc(e.fact)}">Remove</button>`}</li>`).join("")}</ul>`
        : `<p class="hint">No connections${mentions ? "" : " (mentions are not shown)"}.</p>`}
      ${others.length ? `<form id="lw-add" class="lw-add" data-noguard>
        <p>Add: <b>${esc(x.title)}</b> is tied to</p>
        <select id="lw-to" aria-label="The entry to connect to">${others.map(n =>
          `<option value="${esc(n.slug)}">${esc(n.title)} (${esc(typeLabel(n.type))})</option>`).join("")}</select>
        <input id="lw-note" maxlength="120" aria-label="Note for the connection" placeholder="note, for example: his sister">
        <button class="primary" type="submit">Add tie</button>
      </form>` : ""}`;
    side.querySelectorAll("[data-cut]").forEach(btn => btn.addEventListener("click", async () => {
      const e = mine[Number(btn.dataset.cut)];
      if (!await inlineConfirm(`Remove this connection? ${e.fact}`, "Remove", "Keep it")) return;
      await change("disconnect", {from: e.from, to: e.to, kind: e.kind}, "Connection removed.");
    }));
    const form = $("#lw-add");
    if (form) form.addEventListener("submit", async ev => {
      ev.preventDefault();
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      await change("connect", {from: selected, to: $("#lw-to").value, note: $("#lw-note").value.trim()}, "Connection saved.");
      if (button.isConnected) button.disabled = false;
    });
  }

  async function change(path, body, said) {
    const next = await guard(() => api(`${url}/${path}`, {method: "POST", body}), "That did not go through");
    if (!next) return;
    g = next;
    arrange();
    paint();
    toast(said, "ok");
  }

  function paint() {
    if (fit()) { pos = {}; arrange(); }
    drawPicker();
    drawGraph();
    drawSide();
  }

  function choose(slug, focusNode = false) {
    selected = slug;
    paint();
    if (focusNode) { const el = $("#lw-svg").querySelector(`[data-node="${CSS.escape(slug)}"]`); if (el) el.focus(); }
  }

  const svg = $("#lw-svg");
  $("#lw-pick").addEventListener("change", ev => choose(ev.target.value));
  $("#lw-mentions").addEventListener("change", ev => { mentions = ev.target.checked; arrange(); paint(); });
  svg.addEventListener("keydown", ev => {
    const node = ev.target.closest("[data-node]");
    if (node && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); choose(node.dataset.node, true); }
  });
  // drag a node to untangle; a press that does not move selects it
  let drag = null;
  const point = ev => {
    const box = svg.getBoundingClientRect();
    return {x: ((ev.clientX - box.left) / box.width) * W, y: ((ev.clientY - box.top) / box.height) * H};
  };
  svg.addEventListener("pointerdown", ev => {
    const node = ev.target.closest("[data-node]");
    if (!node) return;
    drag = {slug: node.dataset.node, from: point(ev), moved: false};
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", ev => {
    if (!drag) return;
    const at = point(ev);
    if (!drag.moved && Math.hypot(at.x - drag.from.x, at.y - drag.from.y) < 5) return;
    drag.moved = true;
    pos[drag.slug] = {x: Math.min(W - 10, Math.max(10, at.x)), y: Math.min(H - 10, Math.max(10, at.y))};
    drawGraph();
  });
  svg.addEventListener("pointerup", () => {
    if (drag && !drag.moved) choose(drag.slug);
    drag = null;
  });

  arrange();
  paint();
}

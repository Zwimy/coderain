/* The Canon panel: what the story remembers about each person, and the author's corrections to it (D-028).

   The memory reader (a local model, off unless config.yaml turns it on) writes down each person's looks as the
   story states them. First write wins, so a wrong first value would stay, and once it is sent to the writer it
   gets repeated. This panel shows what is held and lets the author say what is true and what is false.

   The corrections are Markdown in the save (corrections.md), so this panel and a hand edit are the same thing:
   every button here changes that one file through the API. A correction outranks the story's own text, is kept
   across undo, retry and a rebuild, and reaches the writer on the next turn. */
import {$, api, esc, guard, toast} from "./util.js";
import {closeModal, openModal, promptModal} from "./modal.js";

const SLOTS = ["hair", "eyes", "build", "age", "marks"];
const LABEL = {hair: "Hair", eyes: "Eyes", build: "Build", age: "Age", marks: "Mark"};
const INJECT = {
  off: "Nothing is sent to the writer. The reader only watches.",
  preview: "The card is built every turn but NOT sent. Read it below before turning it on.",
  on: "The card is sent to the writer with every turn.",
};

// Group the held values by person, keeping the order the server gave (people sorted, slots in order).
function groups(values) {
  const out = [];
  for (const v of values) {
    let g = out[out.length - 1];
    if (!g || g.slug !== v.slug) { g = {slug: v.slug, who: v.who, rows: []}; out.push(g); }
    g.rows.push(v);
  }
  return out;
}

function row(v) {
  const said = v.confirmations > 1 ? `said ${v.confirmations} times, ` : "";
  const mine = v.by === "author"
    ? `<span class="cn-badge" title="You set this, so it outranks the story">yours</span>` : "";
  return `<div class="cn-row" data-who="${esc(v.who)}" data-slot="${esc(v.slot)}"
      data-value="${esc(v.value)}">
    <span class="cn-slot">${esc(LABEL[v.slot] || v.slot)}</span>
    <span><span class="cn-val">${esc(v.value)}</span>${mine}
      <span class="cn-meta">${said}since turn ${v.since_turn}</span></span>
    <span class="cn-act">
      <button data-act="wrong" title="This is wrong: remove it and do not accept it again">Wrong</button>
      <button data-act="set" title="Replace it with the value you give">Change</button>
    </span>
  </div>`;
}

function render(d) {
  const state = !d.shadow
    ? `<p class="hint">The memory reader is off, so there is nothing to show yet. To turn it on, add
        <code>canon: {shadow: true}</code> to config.yaml (it reads each turn with a local Ollama model).
        Anything you write here is kept and applies once it is on.</p>`
    : `<div class="ctx-stats">
        <div><b>on</b><span>memory reader</span></div>
        <div><b class="${d.inject === "on" ? "" : "over"}">${esc(d.inject)}</b><span>sent to the writer</span></div>
        <div><b class="${d.unread ? "over" : ""}">${d.unread ?? "?"}</b><span>turns not read yet</span></div>
        <div><b>${d.corrections.length}</b><span>corrections</span></div>
      </div>
      <p class="hint">${esc(INJECT[d.inject] || INJECT.off)}</p>`;
  const people = groups(d.values);
  const names = [...new Set(d.values.map(v => v.who))];
  const list = d.shadow && people.length
    ? `<input id="cn-filter" type="search" placeholder="Filter by name or value" aria-label="Filter what is held">
       <div id="cn-list">${people.map(g => `<div class="cn-char" data-name="${esc(g.who.toLowerCase())}">
          <h3>${esc(g.who)}</h3>${g.rows.map(row).join("")}</div>`).join("")}</div>`
    : d.shadow ? `<p class="hint">Nothing is held yet. The reader fills this in as it reads turns.</p>` : "";
  const mine = d.corrections.length
    ? `<h3>Your corrections</h3>${d.corrections.map(c => `<div class="cn-mine">
        <span>${esc(c.who)}: ${esc(c.slot)} ${c.op === "set" ? "=" : "is not"} <b>${esc(c.value)}</b></span>
        <button class="cn-rm" data-line="${c.line}" title="Remove this correction">Remove</button></div>`).join("")}`
    : `<p class="hint">No corrections yet. Mark a held value Wrong, or add a fact below.</p>`;
  const bad = d.problems.length
    ? `<div class="cn-warn"><b>Not applied</b>${d.problems.map(p => `<div>· line ${p.line}: ${esc(p.why)}</div>`)
        .join("")}</div>` : "";
  return `<div class="cn"><h2>What the story remembers</h2>
    <p class="hint">What is held about each person, and your say over it. A correction outranks the
      story, survives undo and retry, and reaches the writer on the next turn.</p>
    ${state}${list}
    <h3>Add a fact</h3>
    <div class="cn-form">
      <input id="cn-who" list="cn-names" placeholder="Character" aria-label="Character">
      <select id="cn-slot" aria-label="What about them">${SLOTS.map(s =>
        `<option value="${s}">${esc(LABEL[s])}</option>`).join("")}</select>
      <input id="cn-val" placeholder="Value, for example raven" aria-label="Value">
    </div>
    <datalist id="cn-names">${names.map(n => `<option value="${esc(n)}">`).join("")}</datalist>
    <div class="row"><button id="cn-set" class="primary">It is this</button>
      <button id="cn-wrong">It is not this</button></div>
    ${mine}${bad}
    <details><summary>The file (corrections.md)</summary>
      <p class="hint">One bullet per line, "- Name: hair = raven" or "- Name: hair is not raven". Anything
        that is not a bullet is a note.</p>
      <textarea id="cn-text" rows="7" aria-label="corrections.md">${esc(d.text)}</textarea>
      <div class="row" style="margin-top:8px"><button id="cn-save">Save file</button></div></details>
    <details><summary>What the writer is told next (the last card)</summary>
      ${d.card ? `<pre class="table">${esc(d.card)}</pre>`
        : `<p class="hint">No card yet. It appears after a turn while injection is on or in preview.</p>`}
    </details>
    <div class="modal-actions"><button id="cn-close">Close</button></div></div>`;
}

export async function canonModal(slug) {
  const base = `/api/saves/${slug}/canon`;
  let d = await guard(() => api(base), "Couldn't read the story's memory");
  if (!d) return;

  let scroll = 0;                       // where the list was, kept across the prompt that replaces the panel
  const paint = () => {
    openModal(render(d));
    if ($("#cn-list")) $("#cn-list").scrollTop = scroll;
    wire();
  };
  // Every change is one call that returns the new view, so the panel never shows a stale list. It always
  // ends by painting the panel again, even on failure, because a prompt may have closed it.
  const send = async (method, path, body, said) => {
    scroll = $("#cn-list") ? $("#cn-list").scrollTop : scroll;
    const next = await guard(() => api(base + path, {method, body}), "That didn't save");
    if (next) { d = next; toast(said, "ok"); }
    paint();
  };
  const addLine = (who, slot, op, value) => send("POST", "/corrections", {who, slot, op, value},
    op === "set" ? "Saved. It reaches the writer on the next turn."
                 : "Marked wrong. It will not be accepted again.");

  const wire = () => {
    $("#cn-close").addEventListener("click", closeModal);
    const filter = $("#cn-filter");
    if (filter) filter.addEventListener("input", () => {
      const q = filter.value.trim().toLowerCase();
      document.querySelectorAll(".cn-char").forEach(el => {
        el.classList.toggle("hidden", !!q && !el.textContent.toLowerCase().includes(q));
      });
    });
    document.querySelectorAll(".cn-row button").forEach(btn => btn.addEventListener("click", async () => {
      const r = btn.closest(".cn-row");
      const {who, slot, value} = r.dataset;
      if (btn.dataset.act === "wrong") return addLine(who, slot, "wrong", value);
      const label = `${who}: ${LABEL[slot] || slot}`;
      scroll = $("#cn-list") ? $("#cn-list").scrollTop : 0;    // the prompt replaces the panel
      const v = await promptModal(`New value for ${label}`, {value, okLabel: "Set",
        hint: "This outranks what the story says and is sent to the writer."});
      if (v === null || !v.trim()) return paint();              // cancelled: back to the panel as it was
      await addLine(who, slot, "set", v.trim());
    }));
    const form = op => () => {
      const who = $("#cn-who").value.trim(), value = $("#cn-val").value.trim();
      if (!who || !value) return toast("Give a character and a value.");
      addLine(who, $("#cn-slot").value, op, value);
    };
    $("#cn-set").addEventListener("click", form("set"));
    $("#cn-wrong").addEventListener("click", form("wrong"));
    // The fields are not a <form>, so Enter does nothing by itself: make it submit "it is this".
    $("#cn-val").addEventListener("keydown", ev => {
      if (ev.key === "Enter" && !ev.isComposing) { ev.preventDefault(); form("set")(); }
    });
    $("#cn-who").addEventListener("keydown", ev => {
      if (ev.key === "Enter" && !ev.isComposing) { ev.preventDefault(); $("#cn-val").focus(); }
    });
    document.querySelectorAll(".cn-rm").forEach(btn => btn.addEventListener("click", () => {
      const lines = d.text.split("\n");
      lines.splice(Number(btn.dataset.line) - 1, 1);            // the file is the truth: drop that line
      send("PUT", "/corrections", {text: lines.join("\n")}, "Removed. The story can say it again.");
    }));
    $("#cn-save").addEventListener("click", () =>
      send("PUT", "/corrections", {text: $("#cn-text").value}, "Saved the file."));
  };
  paint();
}

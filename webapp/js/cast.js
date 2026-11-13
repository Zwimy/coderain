/* The Characters screen of the Plan panel: strengths, weaknesses, a personality type and goals for each character (D-032).

   What you write here is yours. It is stored as header lines of the character's entry in characters.md (or the
   protagonist's sheet in player.md), so a hand edit and this screen are the same thing. The writer reads it with the
   character's sheet whenever they are in play, the chapter planner reads it when it plans, and the memory that
   rewrites sheets as the story moves never touches it. "Goals" here are long term and stay until you change them;
   what a character is after right now is kept by the memory and shown beside them for reference. */
import {$, api, esc, guard, toast} from "./util.js";
import {closeModal, openModal} from "./modal.js";
import {TRAIT_HINT, TRAIT_LABEL} from "./pieceform.js";

const LABEL = TRAIT_LABEL;       // one copy of the wording, shared with the piece editor
const HINT = TRAIT_HINT;
const ONE_LINE = new Set(["personality"]);

const filled = c => ["strengths", "weaknesses", "personality", "goals"].filter(f => c[f]);

function item(c, fields, limits) {
  const set = filled(c);
  const badge = set.length ? `<span class="ca-set">${set.map(f => LABEL[f][0]).join(" ")}</span>` : "";
  const inputs = fields.map(f => ONE_LINE.has(f)
    ? `<label class="ca-f"><span>${esc(LABEL[f])}</span>
         <input data-f="${f}" maxlength="${limits[f]}" value="${esc(c[f])}" aria-label="${esc(LABEL[f])} of ${esc(c.title)}">
         <small>${esc(HINT[f])}</small></label>`
    : `<label class="ca-f"><span>${esc(LABEL[f])}</span>
         <textarea data-f="${f}" rows="2" maxlength="${limits[f]}"
           aria-label="${esc(LABEL[f])} of ${esc(c.title)}">${esc(c[f])}</textarea>
         <small>${esc(HINT[f])}</small></label>`).join("");
  const now = c.wants || c.motivation
    ? `<p class="hint ca-now">Right now (kept by the memory, not edited here):
        ${c.wants ? `after <b>${esc(c.wants)}</b>` : ""}${c.wants && c.motivation ? ", " : ""}${
          c.motivation ? `because <b>${esc(c.motivation)}</b>` : ""}</p>` : "";
  return `<details class="ca-char" data-key="${esc(c.key)}" data-name="${esc(c.title.toLowerCase())}">
    <summary><span>${esc(c.title)}${c.player ? ` <em>(protagonist)</em>` : ""}</span>${badge}</summary>
    ${inputs}${now}
    <div class="row"><button class="primary" data-act="save">Save</button></div>
  </details>`;
}

function render(d, back) {
  const list = d.characters.length
    ? d.characters.map(c => item(c, d.fields, d.limits)).join("")
    : `<p class="hint">There are no characters yet. They appear here as the story introduces them.</p>`;
  return `<div class="ca"><h2>Characters</h2>
    <p class="hint">Give each character strengths, weaknesses, a personality type and goals. The writer plays them in
      line with it, the chapter plan is built to use it, and the story's memory never rewrites what you set. Leave
      a field empty to leave it out. The letters mark what is set: S, W, P, G.</p>
    <input id="ca-filter" type="search" placeholder="Filter by name" aria-label="Filter characters">
    <div id="ca-list">${list}</div>
    <div class="modal-actions">
      ${back ? `<button id="ca-back">← Back to the plan</button>` : ""}
      <span style="flex:1"></span><button id="ca-close">Close</button></div></div>`;
}

export async function castModal(slug, back = null) {
  let d = await guard(() => api(`/api/saves/${slug}/cast`), "Couldn't read the characters");
  if (!d) return;
  let open = null;                      // the character that was open, kept across a repaint

  const paint = () => {
    openModal(render(d, back));
    const el = open && document.querySelector(`.ca-char[data-key="${CSS.escape(open)}"]`);
    if (el) el.open = true;
    wire();
  };
  const wire = () => {
    $("#ca-close").addEventListener("click", closeModal);
    const bk = $("#ca-back");
    if (bk) bk.addEventListener("click", () => back());
    $("#ca-filter").addEventListener("input", ev => {
      const q = ev.target.value.trim().toLowerCase();
      document.querySelectorAll(".ca-char").forEach(el => el.classList.toggle("hidden", !!q && !el.dataset.name.includes(q)));
    });
    document.querySelectorAll(".ca-char").forEach(el => {
      $("[data-act=save]", el).addEventListener("click", async () => {
        const body = {};
        el.querySelectorAll("[data-f]").forEach(inp => { body[inp.dataset.f] = inp.value; });
        open = el.dataset.key;
        const row = await guard(() => api(`/api/saves/${slug}/cast/${encodeURIComponent(open)}`,
          {method: "PUT", body}), "That didn't save");
        if (row) {
          d = {...d, characters: d.characters.map(c => c.key === row.key ? row : c)};
          toast("Saved. The writer uses it from the next turn.", "ok");
        }
        paint();                        // from the server's truth, whether or not it saved
      });
    });
  };
  paint();
}

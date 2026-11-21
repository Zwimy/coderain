/* The fold review: the scene summaries the folds wrote, editable in place. Moved out of play.js (D-056 item 19); it uses
   nothing of the play view but the modal helpers. */
import {$, api, esc, guard} from "./util.js";
import {closeModal, modalCard, openModal} from "./modal.js";

/* The fold is where a story quietly loses things: ten turns become a paragraph,
   and from then on the paragraph is what the model gets. Shown right after it
   happens, a bad summary costs one edit; found 50 turns later it has already
   bent the story. Opens on the newest scene, edits in place, or spends one call
   to rewrite it from the original turns. */
export async function foldReview(slug, opts = {}) {
  const d = await guard(() => api(`/api/saves/${slug}/scenes?limit=6`),
                        "Couldn't load the folded scenes");
  if (!d || !d.scenes.length) return;
  const scenes = d.scenes;
  let i = 0;
  const draw = () => {
    const s = scenes[i];
    modalCard.innerHTML = `<h2>Memory folded</h2>
      <p class="hint">${opts.onDemand
        ? "What each fold wrote into memory."
        : `Turns ${esc(s.turns || "?")} are now this summary. From here on the
           model sees this, not those turns.`}
        Fix it now if it lost something.</p>
      <div class="fold-nav">
        <button id="fold-prev" ${i >= scenes.length - 1 ? "disabled" : ""}
          title="older scene">←</button>
        <b>${esc(s.title)}</b>
        <span class="muted">turns ${esc(s.turns || "?")}${
          s.when ? " · " + esc(s.when) : ""}</span>
        <button id="fold-next" ${i <= 0 ? "disabled" : ""}
          title="newer scene">→</button>
      </div>
      <textarea id="fold-text" rows="7">${esc(s.summary)}</textarea>
      ${s.characters ? `<p class="hint">Tagged: ${esc(s.characters)}${
        s.locations ? " · " + esc(s.locations) : ""}</p>` : ""}
      <p class="hint" id="fold-status"></p>
      <div class="modal-actions">
        <button id="fold-redo" title="one model call">Rewrite from the turns</button>
        <button class="primary" id="fold-save">Save summary</button>
        <button id="fold-close">Close</button>
      </div>`;
    const status = (msg, bad) => {
      const el = $("#fold-status");
      el.textContent = msg;
      el.style.color = bad ? "var(--player)" : "var(--ok)";
    };
    $("#fold-prev").addEventListener("click", () => { i++; draw(); });
    $("#fold-next").addEventListener("click", () => { i--; draw(); });
    $("#fold-close").addEventListener("click", closeModal);
    $("#fold-save").addEventListener("click", async () => {
      const summary = $("#fold-text").value.trim();
      if (!summary) return status("A scene summary can't be empty.", true);
      try {
        await api(`/api/saves/${slug}/scenes/${s.slug}`,
                  {method: "PUT", body: {summary}});
        s.summary = summary;
        status("Saved.");
      } catch (e) { status(e.message, true); }
    });
    $("#fold-redo").addEventListener("click", async ev => {
      ev.target.disabled = true;
      status("Rewriting from turns " + (s.turns || "?") + "…");
      try {
        const r = await api(`/api/saves/${slug}/scenes/${s.slug}/redo`,
                            {method: "POST"});
        s.summary = r.summary;
        draw();
        $("#fold-status").textContent = "Rewritten. The old one is in a snapshot.";
        $("#fold-status").style.color = "var(--ok)";
      } catch (e) {
        status(e.message, true);
        ev.target.disabled = false;
      }
    });
  };
  openModal("");
  draw();
}

/* The chapter plan dialog: the rolling outline of the story (D-013). Moved out of play.js (D-056 item 19); it uses nothing of the
   play view but the modal helpers. */
import {$, api, esc, guard} from "./util.js";
import {castModal} from "./cast.js";
import {closeModal, inlineConfirm, modalCard, openModal} from "./modal.js";

// The book-plan panel: the rolling chapter outline. View the arc, edit an upcoming
// chapter's goal to steer the story, reorder/insert/delete planned chapters, mark
// the current chapter done, or regenerate the whole plan from the premise.
export async function outlineModal(slug) {
  const call = (path, opts) => api(`/api/saves/${slug}/outline${path}`, opts);

  const render = (data) => {
    const chs = data.chapters || [];
    const rows = chs.map((ch, i) => {
      const ro = ch.status === "done" ? "disabled" : "";
      const label = ch.status === "done" ? "done"
        : ch.status === "active" ? "now" : "planned";
      // Rewrite one chapter in place. Offered on active too: rewording the goal
      // the writer is aiming at is legitimate steering. Never on done — that is
      // not a plan any more, it is what happened, and the server refuses it.
      // The glyph buttons carry the chapter's number in their name: a list of "↑ ↑ ↑" tells a screen reader nothing.
      const n = i + 1;
      const regen = ch.status === "done" ? ""
        : `<button data-op="regen" aria-label="Rewrite chapter ${n}"
             title="rewrite just this chapter to fit the story so far">↻</button>`;
      const ops = ch.status === "planned"
        ? `${regen}<button data-op="up" aria-label="Move chapter ${n} earlier" title="move earlier">↑</button>
           <button data-op="down" aria-label="Move chapter ${n} later" title="move later">↓</button>
           <button data-op="del" aria-label="Delete chapter ${n}" title="delete this chapter">🗑</button>`
        : ch.status === "active"
        ? `${regen}<button data-op="advance" class="primary"
             title="mark this chapter complete and plan the next">Chapter done →</button>`
        : "";
      return `<div class="ch-row ${ch.status}" data-i="${i}">
        <div class="ch-head">
          <span class="ch-badge ${ch.status}">${label}</span>
          <input class="ch-title" aria-label="Chapter ${n} title" value="${esc(ch.title)}" ${ro}/>
          <span class="ch-ops">${ops}</span>
        </div>
        <textarea class="ch-goal" rows="2" ${ro}
          placeholder="what this chapter should accomplish">${esc(ch.goal)}</textarea>
        ${ch.status === "done" ? ""
          : `<div class="ch-foot"><button class="ch-save" data-op="save">Save</button></div>`}
      </div>`;
    }).join("");

    const empty = data.enabled
      ? "No plan yet. Generate one from your premise now, or it appears on its own after the first few turns."
      : "The chapter outline is turned off in Settings.";
    openModal(`<h2>Chapter plan</h2>
      <p class="muted">The story's rolling outline: a few chapters planned ahead, a
        fresh one written each time a chapter completes. Edit an upcoming chapter's
        goal to steer where things go; the turns aim toward the <b>now</b> chapter.</p>
      ${chs.length ? `<div id="ch-list">${rows}</div>`
                   : `<p class="muted">${empty}</p>`}
      <div class="modal-actions">
        ${data.enabled ? `<button id="ch-add">+ Add chapter</button>
          <button id="ch-gen">${chs.length ? "Regenerate…" : "Generate outline"}</button>`
          : ""}
        <button id="ch-cast" title="strengths, weaknesses, personality and goals for each character"
          >Characters…</button>
        <span style="flex:1"></span>
        <button id="ch-close">Close</button>
      </div>`);

    // ONE request at a time. The rows are addressed by position, so a second click while the first is still in flight
    // acted on the list as it WAS: a double click on the bin deleted two chapters (D-013), and a double click on an arrow
    // moved a chapter twice. Every button in the list is disabled while the request works.
    const refetch = async (fn, busyBtn) => {
      const locked = [...modalCard.querySelectorAll("#ch-list button, #ch-add, #ch-gen")].filter(b => !b.disabled);
      locked.forEach(b => { b.disabled = true; });
      // Generating chapters calls the model (seconds), so show the triggering
      // button as working rather than leaving the panel frozen and silent.
      if (busyBtn) { busyBtn.dataset.busy = busyBtn.textContent; busyBtn.textContent = "Planning…"; }
      const d = await guard(fn, "Couldn't update the plan");
      if (d) render(d);                 // re-render from the server's truth
      else {
        locked.forEach(b => { b.disabled = false; });
        if (busyBtn) busyBtn.textContent = busyBtn.dataset.busy;
      }
    };
    $("#ch-close").addEventListener("click", closeModal);
    $("#ch-cast").addEventListener("click", () => castModal(slug, () => outlineModal(slug)));
    const gen = $("#ch-gen");
    if (gen) gen.addEventListener("click", async () => {
      // Copy corrected with the behaviour: this no longer wipes completed
      // chapters, and no longer plans from the premise alone.
      // Asked inside the panel: a second dialog replaced the Chapter plan, and its Cancel closed the plan with it.
      if (chs.length && !(await inlineConfirm(
        "Replan the upcoming chapters? Completed and current chapters are kept. Every planned chapter is "
        + "replaced, one at a time, using the story so far.", "Replan", "Cancel"))) return;
      await refetch(() => call("/generate", {method: "POST"}), gen);
    });
    const add = $("#ch-add");
    if (add) add.addEventListener("click", () =>
      refetch(() => call("", {method: "POST", body: {title: "New chapter", goal: ""}})));

    (chs.length ? modalCard.querySelectorAll("#ch-list .ch-row") : []).forEach(row => {
      const i = Number(row.dataset.i);
      row.querySelectorAll("[data-op]").forEach(btn =>
        btn.addEventListener("click", () => {
          const op = btn.dataset.op;
          if (op === "save") {
            const title = $(".ch-title", row).value.trim();
            const goal = $(".ch-goal", row).value.trim();
            return refetch(() => call(`/${i}`, {method: "PUT", body: {title, goal}}));
          }
          if (op === "up") return refetch(() => call(`/${i}/move`, {method: "POST", body: {dir: -1}}));
          if (op === "down") return refetch(() => call(`/${i}/move`, {method: "POST", body: {dir: 1}}));
          if (op === "del") return refetch(() => call(`/${i}`, {method: "DELETE"}));
          if (op === "regen") return refetch(
            () => call(`/${i}/regenerate`, {method: "POST"}), btn);
          if (op === "advance") return refetch(() => call("/advance", {method: "POST"}), btn);
        }));
    });
  };

  const data = await guard(() => call(""), "Couldn't read the plan");
  if (data) render(data);
}

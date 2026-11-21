/* Duplicates: the same person, place or item written under two names or two slugs, and the merge (D-065).

   A story played through a small local model collects second and third entries for one person ("Dame Vesper", "Vesper", "Vesper
   Ann-Marie"). Each is a separate character to the memory, the card and the Writer. The tool that merges them used to be a command
   line; this is the same tool, with the one thing a merge needs before it can be offered in an app: a way back. A merge rewrites a
   registry file that a fold wrote and a fold is one-way, so every merge is preceded by a backup and every backup can be restored
   (and the restore itself backs up what it replaces).

   Two kinds of finding, because they are different decisions. Entries with the SAME whole name are one entity written twice; merging
   them is safe enough to offer as one button. Entries whose names only share words ("Vesper" inside "Dame Vesper") MAY be one person
   or two: that is the author's call, so each is a choice of who stays and who is folded in, never automatic. */
import {$, api, esc, guard, toast} from "./util.js";
import {closeModal, confirmModal, openModal} from "./modal.js";

const FILE_LABEL = {"characters.md": "characters", "locations.md": "places", "factions.md": "factions", "items.md": "items"};

function stampLabel(stamp) {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(stamp);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : stamp;
}

function render(d, note) {
  const same = d.same_name.length
    ? `<div class="dup-list">${d.same_name.map(g => `<div class="dup-row">
        <span><b>${esc(g.keep.title)}</b> <span class="muted">(${esc(FILE_LABEL[g.rel] || g.rel)})</span>
          keeps <code>${esc(g.keep.slug)}</code> and takes in ${g.drop.map(x => `<code>${esc(x.slug)}</code>`).join(", ")}</span></div>`).join("")}</div>
       <div class="row"><button class="primary" id="dup-auto">Merge these ${d.same_name.length === 1 ? "entry" : "entries"}</button></div>`
    : `<p class="hint">Nothing is written twice under the same name.</p>`;
  const maybe = d.possible.length
    ? d.possible.map((cl, i) => `<div class="dup-cluster" data-i="${i}">
        <p class="muted">${esc(FILE_LABEL[cl.rel] || cl.rel)}: these names share words. Choose who stays, and who is folded into them.</p>
        ${cl.entries.map(e => `<label class="dup-pick">
          <input type="radio" name="dup-keep-${i}" value="${esc(e.slug)}" ${e.slug === cl.keep ? "checked" : ""}>
          <input type="checkbox" class="dup-fold" value="${esc(e.slug)}" ${e.slug === cl.keep ? "" : "checked"} aria-label="Fold ${esc(e.title)} in">
          <span><b>${esc(e.title)}</b> <code>${esc(e.slug)}</code> <span class="muted">${e.chars} characters</span></span></label>`).join("")}
        <div class="row"><button data-merge="${i}">Merge the ticked ones into the one that stays</button></div>
      </div>`).join("")
    : `<p class="hint">No names share words, so nothing here may be one person.</p>`;
  const backups = d.backups.length
    ? `<ul class="dup-backups">${d.backups.map(b => `<li><span>${esc(stampLabel(b))}</span>
        <button data-restore="${esc(b)}" title="put the registries back as they were then">Restore</button></li>`).join("")}</ul>`
    : `<p class="hint">No backups yet. One is made before every merge.</p>`;
  const canon = d.canon
    ? `<p class="hint">The memory reader keeps the old names until it is rebuilt: delete this story's <code>canon</code> folder and it reads the story again.</p>` : "";
  return `<h2>Duplicates</h2>
    <p class="muted">The same person written twice becomes two characters to the memory. A merge folds the others into the one you keep.
      A backup is made first, and can be restored below.</p>
    ${note ? `<p role="status" class="dup-note">${esc(note)}</p>` : ""}
    <h3>Written twice under the same name</h3>${same}
    <h3>Names that may be one person</h3>${maybe}
    <h3>Backups</h3>${backups}${canon}
    <div class="modal-actions"><button id="dup-close">Close</button></div>`;
}

export async function duplicatesModal(slug) {
  const base = `/api/saves/${slug}/duplicates`;
  let d = await guard(() => api(base), "Couldn't look for duplicates");
  if (!d) return;
  const paint = note => {
    openModal(render(d, note), null, {guard: false});       // every change here is its own confirmed call: nothing is left to discard
    wire();
  };
  // One change is one confirmed call that returns the new view. It always paints again, even on failure, because the question asked
  // first replaces the panel.
  const change = async (path, body, said) => {
    const next = await guard(() => api(base + path, {method: "POST", body}), "That did not go through");
    if (next) { d = next; toast(said, "ok"); }
    paint(next ? said : "");
  };
  const wire = () => {
    $("#dup-close").addEventListener("click", closeModal);
    const auto = $("#dup-auto");
    if (auto) auto.addEventListener("click", async () => {
      if (!await confirmModal("Merge the entries written twice?",
          `${d.same_name.length} group${d.same_name.length === 1 ? "" : "s"} will be folded into the entry that stays. A backup is made first.`, "Merge")) return paint("");
      await change("/merge", {auto: true}, "Merged. A backup was made first.");
    });
    document.querySelectorAll("[data-merge]").forEach(btn => btn.addEventListener("click", async () => {
      const box = btn.closest(".dup-cluster"), cl = d.possible[Number(btn.dataset.merge)];
      const keep = box.querySelector("input[type=radio]:checked").value;
      const drop = [...box.querySelectorAll(".dup-fold:checked")].map(x => x.value).filter(x => x !== keep);
      if (!drop.length) return toast("Tick at least one entry to fold into the one that stays.");
      if (!await confirmModal("Merge these entries?",
          `${drop.length} will be folded into ${keep}. A backup is made first. Only you know whether they are one person.`, "Merge")) return paint("");
      await change("/merge", {rel: cl.rel, keep, drop}, "Merged. A backup was made first.");
    }));
    document.querySelectorAll("[data-restore]").forEach(btn => btn.addEventListener("click", async () => {
      if (!await confirmModal("Restore this backup?",
          "The registries go back to how they were then. What is there now is backed up first, so this can be undone too.", "Restore")) return paint("");
      await change("/restore", {backup: btn.dataset.restore}, "Restored. What was there before is in a new backup.");
    }));
  };
  paint("");
}

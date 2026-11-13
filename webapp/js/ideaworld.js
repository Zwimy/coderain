/* "From an idea": one sentence in, a whole world out (D-052).

   The server runs the full world generator (title, premise, world bible, factions, cast, places,
   items, threads, the opening message) and streams its stages. This dialog shows them as they
   arrive and opens the new world in the builder when it is done, where every piece is editable.

   A world is only created when the premise stage works, so a failed run leaves nothing behind
   and the idea stays in the box to try again. */
import {$, sse, toast} from "./util.js";
import {closeModal, openModal} from "./modal.js";

/* Must match IDEA_MAX in srv/authoring.py: the server refuses longer ideas. */
export const IDEA_MAX = 600;

export function ideaWorldModal(onDone) {
  let running = false;
  let closed = false;
  openModal(`<h2>A world from an idea</h2>
    <p class="muted">One sentence is enough. The AI writes the title, premise, world, cast, places,
    items, story threads and the opening message. You can edit all of it afterwards.</p>
    <textarea id="iw-idea" rows="3" maxlength="${IDEA_MAX}"
      placeholder="A lamplighter finds out someone else has been lighting the harbour lamps."></textarea>
    <label class="check" style="display:flex;align-items:center;gap:6px;margin-top:8px">
      <input type="checkbox" id="iw-fast"> Faster and shallower (one call per section)</label>
    <pre class="table hidden" id="iw-log" style="max-height:180px;overflow:auto"></pre>
    <div class="row" style="margin-top:14px; justify-content:flex-end">
      <button id="iw-no">Cancel</button>
      <button class="primary" id="iw-go">Create world</button>
    </div>`, () => { closed = true; });
  const idea = $("#iw-idea"), fast = $("#iw-fast"), log = $("#iw-log");
  const go = $("#iw-go"), no = $("#iw-no");
  no.addEventListener("click", closeModal);

  async function start() {
    const text = idea.value.trim();
    if (!text) { toast("Describe the world in a sentence first."); idea.focus(); return; }
    if (running) return;
    running = true;
    for (const el of [go, idea, fast]) el.disabled = true;
    log.classList.remove("hidden");
    log.textContent = "starting\n";
    let slug = null;
    let failed = null;
    let events = [];
    try {
      await sse("/api/scenarios-generate",
                {idea: text, detail: fast.checked ? "fast" : "rich"}, {
        stage: m => { log.textContent += "· " + m.text + "\n"; log.scrollTop = log.scrollHeight; },
        done: m => { slug = m.slug; events = m.events || []; },
        error: m => { failed = m.text; },
      });
    } catch (e) { failed = e.message; }
    running = false;
    if (slug) {
      // Read BEFORE closeModal(): closing runs the close callback, which sets `closed` either way.
      // Navigate only if the dialog is still what the author is looking at. Closing it while the AI
      // worked means they went elsewhere, and being pulled into the builder would be a surprise.
      const watching = !closed;
      toast(events.length ? `World created. ${events.join(" ")}` : "World created.", "ok");
      closeModal();
      if (onDone) onDone(slug, watching);
      return;
    }
    log.textContent += "failed: " + (failed || "no world was created") + "\n";
    for (const el of [go, idea, fast]) el.disabled = false;
    log.scrollTop = log.scrollHeight;
  }
  go.addEventListener("click", start);
  idea.addEventListener("keydown", ev => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey) && !ev.isComposing) { ev.preventDefault(); start(); }
  });
}

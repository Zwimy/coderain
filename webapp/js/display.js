/* Display preferences for reading a story: how big the text is, and the background rain.

   Both belong to this browser, not to the story or the server, so they are kept in localStorage and apply at once; there is no Save.
   The rain switch already existed (matrix.js, window.setRain / rainOn) but could only be reached from Settings, a page away from
   where the reader is bothered by it. The text size is new: one factor on a CSS variable that the turns' font sizes multiply, so
   no layout rule has to know about it. A stored value that is not one of ours (a hand-edited or an older one) means "medium". */
import {$, esc} from "./util.js";
import {closeModal, openModal} from "./modal.js";

const KEY = "coderain_font";
export const SIZES = [["small", "Small", 0.88], ["medium", "Medium", 1], ["large", "Large", 1.18], ["xlarge", "Larger", 1.4]];
const FACTOR = Object.fromEntries(SIZES.map(([id, , f]) => [id, f]));

export function storedSize() {
  try {
    const v = localStorage.getItem(KEY);
    return v in FACTOR ? v : "medium";
  } catch (_e) { return "medium"; }                       // private mode or blocked storage: the default, for this visit
}

export function setSize(id) {
  const size = id in FACTOR ? id : "medium";
  try { localStorage.setItem(KEY, size); } catch (_e) { /* session only */ }
  applyDisplay();
}

export function applyDisplay() {
  document.documentElement.style.setProperty("--story-scale", String(FACTOR[storedSize()]));
}

export function displayModal() {
  const now = storedSize();
  const rain = typeof window.rainOn === "function" ? window.rainOn() : true;
  // No Save and nothing to discard: each choice is applied as it is made, so closing never asks.
  openModal(`
    <h2>Display</h2>
    <p class="muted">These stay in this browser.</p>
    <label>Text size</label>
    <div class="seg" id="dp-size">
      ${SIZES.map(([id, label]) => `<button data-size="${id}" ${id === now ? 'class="on"' : ""}>${esc(label)}</button>`).join("")}
    </div>
    <label><input type="checkbox" id="dp-rain" ${rain ? "checked" : ""}> Animated background rain</label>
    <div class="modal-actions"><button class="primary" id="dp-done">Done</button></div>`, null, {guard: false});
  $("#dp-size").addEventListener("click", ev => {
    const id = ev.target.dataset && ev.target.dataset.size;
    if (!id) return;
    setSize(id);
    $("#dp-size").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.size === id));
  });
  $("#dp-rain").addEventListener("change", ev => { if (window.setRain) window.setRain(ev.target.checked); });
  $("#dp-done").addEventListener("click", closeModal);
}

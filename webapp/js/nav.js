/* Hash routing bookkeeping: nav highlight, unsaved-work flush, and the
   cached readiness probe. */
import {$, api, guard, toast} from "./util.js";
import {render} from "./app.js";

/* ---------- router ---------- */
$("#brand").addEventListener("click", () => { location.hash = "#library"; });
$("#brand").addEventListener("keydown", ev => {
  if (ev.key === "Enter" || ev.key === " ") {   // it is a link, so act like one
    ev.preventDefault(); location.hash = "#library";
  }
});
window.addEventListener("hashchange", render);
export function navMark() {
  const h = location.hash || "#library";
  document.querySelectorAll("#topbar nav a").forEach(a =>
    a.classList.toggle("active", a.getAttribute("href") === h));
}

// A slug segment is only real if it's a non-empty value that isn't a stray
// JS "undefined"/"null" — those slip in from a stale browser hash (e.g. an old
// #play/undefined left over from a prior session) and must not 404 the app.
export const validSlug = seg => seg && seg !== "undefined" && seg !== "null";

/* ---------- unsaved-work guard ----------
   The builder only persisted on its own Back button, so a topbar click, browser
   Back, or any hash change silently threw away everything typed. These are local
   files — saving is free — so navigation autosaves rather than nagging. */
export let _dirtyCheck = null, _dirtySave = null;

export function registerDirty(isDirty, save) { _dirtyCheck = isDirty; _dirtySave = save; }

export function clearDirty() { _dirtyCheck = null; _dirtySave = null; }

export async function flushDirty() {
  if (!_dirtyCheck || !_dirtySave || !_dirtyCheck()) return;
  try { await _dirtySave(); toast("Saved your changes.", "ok"); }
  catch (e) { toast("Couldn't save your changes: " + e.message); }
}
window.addEventListener("beforeunload", ev => {
  if (_dirtyCheck && _dirtyCheck()) { ev.preventDefault(); ev.returnValue = ""; }
});

/* ---------- first run: is a model reachable at all? ----------
   The app used to boot straight into an empty library that promised success,
   then failed on the very first turn with an unreadable message. A new user had
   no way to learn that a model is needed at all. */
export let _ready = null;                       // cached probe; cleared after Settings

export async function checkReady(force = false) {
  if (_ready && !force) return _ready;
  try { _ready = await api("/api/ready"); }
  catch (_e) { _ready = {ok: true}; }     // never trap the user behind a bad probe
  return _ready;
}

export function invalidateReady() { _ready = null; }

/* "Look around first" on the first-run screen: satisfy the probe for this
   session without claiming a model was found, so app.js's gate lets the user
   through while Settings still shows the real state.

   This lives HERE, next to the binding, because `_ready` is a module-level
   `let` and an importing module CANNOT assign to it — imported bindings are
   read-only views. welcome.js did exactly that, so the first screen a new user
   sees threw `TypeError: Assignment to constant variable.`, the button did
   nothing, and a stopped Ollama locked an existing user out of their Library. */
export function skipReadyCheck() { _ready = {ok: true, skipped: true}; }

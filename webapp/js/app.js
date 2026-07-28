/* Coderain SPA — entry point and hash router.
   Everything else lives beside this file: util/modal/nav are the shared
   layer, and one module per view. Loaded as a module from index.html, so
   nothing here touches the global scope. */
import {esc, view} from "./util.js";
import {
  checkReady,
  clearDirty,
  flushDirty,
  navMark,
  validSlug
} from "./nav.js";
import {renderWelcome} from "./welcome.js";
import {renderDefaults, renderLibrary} from "./library.js";
import {renderBuilder} from "./builder.js";
import {renderPlay} from "./play.js";
import {renderCharacters} from "./characters.js";
import {renderSettings, setBrainline} from "./settings.js";

export async function render() {
  await flushDirty();          // persist the view we're leaving
  clearDirty();
  navMark();
  // The Talk drawer lives on <body> (not #view), so drop it on any navigation —
  // otherwise it orphans, floating over the next page with a stale slug handler.
  const td = document.getElementById("talk-drawer");
  if (td) td.remove();
  const h = location.hash || "#library";
  // A garbage per-item route → bounce home instead of a cryptic "no such save".
  for (const [pfx, n] of [["#play/", 6], ["#world/", 7], ["#edit/", 6]]) {
    if (h.startsWith(pfx) && !validSlug(decodeURIComponent(h.slice(n)))) {
      location.hash = "#library";
      return;                          // hashchange re-runs render() for #library
    }
  }
  try {
    // First-run gate: land on the chooser instead of an empty library that
    // promises success and then fails on the first turn. Settings stays
    // reachable (that's where you fix it) and "Look around first" opts out.
    if (h === "#library" || h === "") {
      const st = await checkReady();
      if (!st.ok && !st.skipped) { await renderWelcome(st); return; }
    }
    if (h.startsWith("#play/")) await renderPlay(h.slice(6));
    else if (h.startsWith("#world/")) await renderBuilder(h.slice(7), "scenario");
    else if (h.startsWith("#edit/")) await renderBuilder(h.slice(6), "save");
    else if (h === "#characters") await renderCharacters();
    else if (h === "#defaults") await renderDefaults();
    else if (h === "#settings") await renderSettings();
    else await renderLibrary();
    // Every renderer awaits the server before it paints, so two navigations in
    // quick succession race: the SLOWER one finishes last and writes its view
    // over the newer one, leaving you on a page the URL disagrees with.
    // (Settings is the slow one — it fetches settings, models and profiles.)
    // If the hash moved on while we were fetching, the paint we just did is
    // stale, so render whatever the URL says now. Converges, because each pass
    // targets wherever the hash has got to by then.
    if ((location.hash || "#library") !== h) return render();
  } catch (e) {
    // A missing item (deleted save, dead bookmark) shouldn't read as a crash —
    // offer a way back rather than a dead end.
    const gone = /no such (save|scenario)/i.test(e.message || "");
    view.innerHTML = `<div class="page">
      <h1>${gone ? "Not found" : "Something broke"}</h1>
      <p class="muted">${esc(e.message)}</p>
      <button class="primary" onclick="location.hash='#library'"
        >← Back to Library</button></div>`;
  }
}

setBrainline();
render();

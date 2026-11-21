/* Find in the story: every match is highlighted inside its turn, Enter steps through them, and closing leaves the page as it was.

   Two rules from the transcript code shape this module.
   - Edit and retry address a turn by its place in #transcript (the pen sends an index, which is a DOM position), so nothing may
     be added to or removed from #transcript. The bar lives outside it, and the highlights are <mark> elements INSIDE each
     .turn-body only; clearing them puts the text back and merges the text nodes, so a turn's text is never changed by a search.
   - A turn that repaints (a streaming reply, a saved edit) replaces its body and its marks with it. The search is run again
     when turns come or go, which is the only time the set of turns changes.
   A match is found inside one run of text: a phrase that crosses a bold or italic edge ("the *old* door") is not found. */
import {$} from "./util.js";

const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function clearMarks(transcript) {
  for (const mark of transcript.querySelectorAll("mark.find-hit")) {
    const parent = mark.parentNode;
    parent.replaceChild(document.createTextNode(mark.textContent), mark);
    parent.normalize();
  }
}

/* Wrap every match of `query` (literal text, any case) in a <mark class="find-hit">; returns how many there are. */
export function markMatches(transcript, query) {
  clearMarks(transcript);
  if (!query || !query.trim()) return 0;
  const re = new RegExp(escapeRe(query), "giu");          // matched on the original text, so a match never shifts an index
  let count = 0;
  for (const body of transcript.querySelectorAll(".turn-body")) {
    const nodes = [];
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const text = node.nodeValue;
      const hits = [...text.matchAll(re)];
      if (!hits.length) continue;
      const parts = document.createDocumentFragment();
      let last = 0;
      for (const hit of hits) {
        parts.append(text.slice(last, hit.index));
        const mark = document.createElement("mark");
        mark.className = "find-hit";
        mark.textContent = hit[0];
        parts.append(mark);
        last = hit.index + hit[0].length;
        count++;
      }
      parts.append(text.slice(last));
      node.replaceWith(parts);
    }
  }
  return count;
}

export function attachFind({transcript, bar, button}) {
  const input = $("#find-q", bar), tally = $("#find-count", bar);
  let marks = [], at = -1, timer = null, pending = false;       // pending: typed since the last search

  const paintTally = () => {
    if (!input.value.trim()) tally.textContent = "";
    else tally.textContent = marks.length ? `${at + 1} of ${marks.length}` : "No matches";
  };
  const show = idx => {
    if (marks[at]) marks[at].classList.remove("current");
    at = idx;
    if (marks[at]) {
      marks[at].classList.add("current");
      marks[at].scrollIntoView({block: "center"});
    }
    paintTally();
  };
  const search = keepPlace => {
    pending = false;
    markMatches(transcript, input.value);
    marks = [...transcript.querySelectorAll("mark.find-hit")];
    const was = at;
    at = -1;
    show(marks.length ? (keepPlace && was >= 0 ? Math.min(was, marks.length - 1) : 0) : -1);
  };
  const step = delta => { if (marks.length) show((at + delta + marks.length) % marks.length); };
  const open = () => {
    bar.hidden = false;
    button.setAttribute("aria-expanded", "true");
    input.focus();
    input.select();
  };
  const close = () => {
    clearTimeout(timer);
    pending = false;
    clearMarks(transcript);
    marks = [];
    at = -1;
    input.value = "";
    tally.textContent = "";
    bar.hidden = true;
    button.setAttribute("aria-expanded", "false");
    button.focus();
  };

  button.addEventListener("click", () => { if (bar.hidden) open(); else close(); });
  input.addEventListener("input", () => { pending = true; clearTimeout(timer); timer = setTimeout(() => search(false), 120); });
  input.addEventListener("keydown", ev => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      if (pending) { clearTimeout(timer); search(false); }       // Enter before the pause: search what is typed, then stand on the first
      else step(ev.shiftKey ? -1 : 1);
    } else if (ev.key === "Escape") { ev.preventDefault(); close(); }
  });
  $("#find-next", bar).addEventListener("click", () => step(1));
  $("#find-prev", bar).addEventListener("click", () => step(-1));
  $("#find-close", bar).addEventListener("click", close);
  // Direct children only: a mark going into a turn body is not a change of turns, so the search does not trigger itself.
  new MutationObserver(() => {
    if (bar.hidden || !input.value.trim()) return;
    clearTimeout(timer);
    timer = setTimeout(() => search(true), 150);
  }).observe(transcript, {childList: true});
}

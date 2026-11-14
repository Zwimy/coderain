/* The one modal host every dialog renders into, plus confirm/prompt. */
import {$, esc} from "./util.js";

/* ---------- modal ----------
   Now a real dialog: labelled for assistive tech, focus moves in and is trapped,
   Escape closes, and focus returns to whatever opened it. */
export const modalRoot = $("#modal-root"), modalCard = $("#modal-card");

export let _modalOnClose = null, _modalReturnFocus = null;

// Anything typed or changed in a dialog is unsaved until its own Save runs, and Escape or a click on the backdrop used to throw
// it all away without a word. Dialogs ask before discarding (requestClose); small questions (confirm, prompt) opt out.
let modalGuard = true, modalDirty = false;

export function openModal(html, onClose = null, opts = {}) {
  _modalReturnFocus = document.activeElement;
  _modalOnClose = onClose;
  modalGuard = opts.guard !== false;
  modalDirty = false;
  modalCard.innerHTML = html;
  modalCard.setAttribute("role", "dialog");
  modalCard.setAttribute("aria-modal", "true");
  // The comment above said "labelled for assistive tech" and nothing was: name the dialog by its own heading.
  const heading = modalCard.querySelector("h1, h2");
  if (heading) {
    heading.id = heading.id || "modal-title";
    modalCard.setAttribute("aria-labelledby", heading.id);
  } else {
    modalCard.removeAttribute("aria-labelledby");
  }
  modalRoot.classList.remove("hidden");
  const first = modalCard.querySelector(
    "input, textarea, select, button:not([disabled])");
  if (first) first.focus();
}

export function closeModal() {
  if (modalRoot.classList.contains("hidden")) return;
  modalRoot.classList.add("hidden");
  const cb = _modalOnClose; _modalOnClose = null;
  const back = _modalReturnFocus; _modalReturnFocus = null;
  if (back && document.body.contains(back)) back.focus();
  if (cb) cb();                       // promise-based modals resolve here
}
const markDirty = ev => {
  const t = ev.target;
  if (t && t.type !== "search" && !(t.closest && t.closest("[data-noguard]"))) modalDirty = true;   // a filter is not an edit
};
modalCard.addEventListener("input", markDirty);
modalCard.addEventListener("change", markDirty);

/* One question asked INSIDE the open dialog. There is one modal host, so a second dialog would replace the first, and its
   Cancel would close both (the Replan question did exactly that to the Chapter plan panel). Resolves true for the second
   button. The safe answer takes focus. */
export function inlineConfirm(message, okLabel = "Discard", cancelLabel = "Keep editing") {
  return new Promise(resolve => {
    const old = modalCard.querySelector("#modal-ask");
    if (old) old.remove();
    const bar = document.createElement("div");
    bar.id = "modal-ask";
    bar.className = "modal-ask";
    bar.setAttribute("role", "alert");
    bar.innerHTML = `<p>${esc(message)}</p>
      <div class="row"><button data-act="keep">${esc(cancelLabel)}</button>
      <button class="primary" data-act="ok">${esc(okLabel)}</button></div>`;
    modalCard.appendChild(bar);
    const done = v => { bar.remove(); resolve(v); };
    bar.querySelector("[data-act=keep]").addEventListener("click", () => done(false));
    bar.querySelector("[data-act=ok]").addEventListener("click", () => done(true));
    bar.querySelector("[data-act=keep]").focus();
    if (bar.scrollIntoView) bar.scrollIntoView({block: "nearest"});
  });
}

/* Escape and the backdrop: close at once when nothing was changed; otherwise ask. Cancel buttons and programmatic closes
   (after a Save) are not asked. Escape while the question is showing means "keep editing". */
function requestClose() {
  if (modalRoot.classList.contains("hidden")) return;
  if (!modalGuard || !modalDirty) { closeModal(); return; }
  const asking = modalCard.querySelector("#modal-ask");
  if (asking) { asking.querySelector("[data-act=keep]").click(); return; }
  inlineConfirm("Discard your changes?").then(discard => { if (discard) closeModal(); });
}
$("#modal-back").addEventListener("click", requestClose);
document.addEventListener("keydown", ev => {
  if (modalRoot.classList.contains("hidden")) return;
  if (ev.key === "Escape") { ev.preventDefault(); requestClose(); return; }
  if (ev.key !== "Tab") return;
  const f = [...modalCard.querySelectorAll(
    'a[href],button:not([disabled]),input,textarea,select,[tabindex]:not([tabindex="-1"])')]
    .filter(el => el.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
  else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
});

/* Promise-based confirm()/prompt(). Native dialogs are unstyled, single-line,
   and suppressed outright in some embedded webviews — which is exactly what the
   desktop build runs in, so the creative paths that used prompt() were at risk
   of simply not working there. */
export function confirmModal(title, body = "", okLabel = "Delete") {
  return new Promise(resolve => {
    let done = false;
    const finish = v => { if (!done) { done = true; resolve(v); } };
    openModal(`<h2>${esc(title)}</h2>
      ${body ? `<p class="muted">${esc(body)}</p>` : ""}
      <div class="row" style="margin-top:14px; justify-content:flex-end">
        <button id="cm-no">Cancel</button>
        <button class="primary" id="cm-yes">${esc(okLabel)}</button>
      </div>`, () => finish(false), {guard: false});
    $("#cm-no").addEventListener("click", closeModal);
    $("#cm-yes").addEventListener("click", () => { finish(true); closeModal(); });
    $("#cm-yes").focus();
  });
}

export function promptModal(title, opts = {}) {
  const {value = "", placeholder = "", multiline = false,
         okLabel = "OK", hint = ""} = opts;
  return new Promise(resolve => {
    let done = false;
    const finish = v => { if (!done) { done = true; resolve(v); } };
    const field = multiline
      ? `<textarea id="pm-v" rows="4" placeholder="${esc(placeholder)}">${esc(value)}</textarea>`
      : `<input id="pm-v" value="${esc(value)}" placeholder="${esc(placeholder)}">`;
    openModal(`<h2>${esc(title)}</h2>${field}
      ${hint ? `<p class="muted">${esc(hint)}</p>` : ""}
      <div class="row" style="margin-top:14px; justify-content:flex-end">
        <button id="pm-no">Cancel</button>
        <button class="primary" id="pm-yes">${esc(okLabel)}</button>
      </div>`, () => finish(null), {guard: false});
    $("#pm-no").addEventListener("click", closeModal);
    const submit = () => { finish($("#pm-v").value); closeModal(); };
    $("#pm-yes").addEventListener("click", submit);
    if (!multiline) $("#pm-v").addEventListener("keydown", ev => {
      if (ev.key === "Enter" && !ev.isComposing) { ev.preventDefault(); submit(); }
    });
    const f = $("#pm-v"); f.focus(); if (f.select) f.select();
  });
}

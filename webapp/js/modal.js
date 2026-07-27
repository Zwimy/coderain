/* The one modal host every dialog renders into, plus confirm/prompt. */
import {$, esc} from "./util.js";

/* ---------- modal ----------
   Now a real dialog: labelled for assistive tech, focus moves in and is trapped,
   Escape closes, and focus returns to whatever opened it. */
export const modalRoot = $("#modal-root"), modalCard = $("#modal-card");

export let _modalOnClose = null, _modalReturnFocus = null;

export function openModal(html, onClose = null) {
  _modalReturnFocus = document.activeElement;
  _modalOnClose = onClose;
  modalCard.innerHTML = html;
  modalCard.setAttribute("role", "dialog");
  modalCard.setAttribute("aria-modal", "true");
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
$("#modal-back").addEventListener("click", closeModal);
document.addEventListener("keydown", ev => {
  if (modalRoot.classList.contains("hidden")) return;
  if (ev.key === "Escape") { ev.preventDefault(); closeModal(); return; }
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
      </div>`, () => finish(false));
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
      </div>`, () => finish(null));
    $("#pm-no").addEventListener("click", closeModal);
    const submit = () => { finish($("#pm-v").value); closeModal(); };
    $("#pm-yes").addEventListener("click", submit);
    if (!multiline) $("#pm-v").addEventListener("keydown", ev => {
      if (ev.key === "Enter" && !ev.isComposing) { ev.preventDefault(); submit(); }
    });
    const f = $("#pm-v"); f.focus(); if (f.select) f.select();
  });
}

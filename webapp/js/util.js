/* DOM, escaping, the API client, toasts, and the SSE reader.
   Leaf module: imports nothing of ours, so everything else can import it. */
export const $ = (sel, el = document) => el.querySelector(sel);

export const view = $("#view");

export const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

/* ST-06: light, safe markdown for narrator prose — **bold**, *italic*, and
   "quoted dialogue" coloured. Escapes first, so no HTML injection. */
export function renderProse(text) {
  let h = esc(text);
  h = h.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  h = h.replace(/(^|[^_\w])_([^_\n]+)_(?![_\w])/g, "$1<em>$2</em>");
  h = h.replace(/&quot;([\s\S]*?)&quot;/g,
                '<span class="say">&quot;$1&quot;</span>');
  return h;
}

/* Chip / bubble input. Tags and card links used to be raw comma text; this shows
   them as removable bubbles with an autocomplete of values already used elsewhere
   (a trait made on one card is offered on every other card). `suggestions` may be
   plain strings (traits) or {label, value} pairs (links: show the title, store
   the slug). Returns { get } -> the current values. */
export function chipInput(host, opts = {}) {
  const values = (opts.value || []).slice();
  const sugg = (opts.suggestions || []).map(
    s => (typeof s === "string" ? {label: s, value: s} : s));
  const listId = "dl-" + Math.random().toString(36).slice(2, 8);
  const labelOf = v => (sugg.find(s => s.value === v) || {}).label || v;
  const add = raw => {
    const t = raw.trim();
    if (!t) return;
    const m = sugg.find(s => s.label.toLowerCase() === t.toLowerCase()
                             || s.value.toLowerCase() === t.toLowerCase());
    const val = m ? m.value : t;
    if (!values.includes(val)) values.push(val);
    render();
  };
  const render = () => {
    host.className = "chips";
    host.innerHTML = values.map((v, i) =>
      `<span class="chip-tag">${esc(labelOf(v))}` +
      `<button type="button" data-i="${i}" aria-label="remove">×</button></span>`
    ).join("") +
      `<input class="chip-in" list="${listId}" ` +
      `placeholder="${esc(opts.placeholder || "add…")}">` +
      `<datalist id="${listId}">` +
      sugg.map(s => `<option value="${esc(s.label)}">`).join("") + "</datalist>";
    host.querySelectorAll(".chip-tag button").forEach(b =>
      b.addEventListener("click", () => {
        values.splice(Number(b.dataset.i), 1); render();
        host.querySelector(".chip-in").focus();
      }));
    const inp = host.querySelector(".chip-in");
    inp.addEventListener("keydown", ev => {
      if ((ev.key === "Enter" || ev.key === ",") && inp.value.trim()) {
        ev.preventDefault(); add(inp.value); inp.value = "";
        host.querySelector(".chip-in").focus();
      } else if (ev.key === "Backspace" && !inp.value && values.length) {
        values.pop(); render(); host.querySelector(".chip-in").focus();
      }
    });
    // datalist pick fires 'change'
    inp.addEventListener("change", () => {
      if (inp.value.trim()) { add(inp.value); inp.value = "";
        host.querySelector(".chip-in").focus(); }
    });
  };
  render();
  return {get: () => values.slice()};
}

export async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...opts,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_e) { /* text */ }
    throw new Error(msg);
  }
  return r.json();
}

/* Non-blocking status/error line. Replaces alert() for anything that isn't a
   decision: alert is modal, unstyled, and is suppressed outright in some
   embedded webviews (which is what the desktop build runs in). role="status"
   means screen readers announce it without stealing focus. */
export let _toastTimer = null;

export function toast(msg, kind = "error") {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.className = kind + " show";
  el.textContent = msg;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("show"), 6000);
}

/* Run an API action, surfacing failure instead of swallowing it. Unguarded
   `await api(...)` calls became unhandled rejections: a 409 "a turn is
   generating" left the modal open, wrote nothing and said nothing, so an
   author's note typed mid-turn was simply lost. */
export async function guard(fn, what = "That didn't work") {
  try { return await fn(); }
  catch (e) { toast(`${what}: ${e.message}`); return undefined; }
}

/* POST + read an SSE body (fetch streaming — EventSource can't POST).
   `signal` lets the caller abort a run (the Stop button). */
export async function sse(path, body, on, signal) {
  const r = await fetch(path, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!r.ok || !r.body) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_e) { /* text */ }
    throw new Error(msg);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    buf += dec.decode(value, {stream: true});
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        let msg;
        try { msg = JSON.parse(line.slice(6)); } catch (_e) { continue; }
        (on[msg.t] || (() => {}))(msg);
      }
    }
  }
}

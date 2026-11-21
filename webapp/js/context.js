/* The context inspector: what the model actually receives, section by section, and what the story has cost. Moved out of play.js
   (D-056 item 19); it uses nothing of the play view but the modal helpers. */
import {$, api, esc, guard} from "./util.js";
import {closeModal, openModal} from "./modal.js";

// What the model actually receives this turn. "The story forgot X" is almost never
// the model forgetting — X was not in the prompt. This shows which sections are
// there, how big each one is, and what is eating the budget.
export async function contextModal(slug) {
  const d = await guard(() => api(`/api/saves/${slug}/context`),
                        "Couldn't inspect the context");
  if (!d) return;
  const bar = (n, max) => `<div class="ctx-bar"><i style="width:${
    Math.max(1, Math.round(n / max * 100))}%"></i></div>`;
  // Every part of the prompt as a share of the whole, so "what is eating the context" is one glance. The rules and the verbatim
  // turns are parts of the prompt too: they used to be a sentence under the list, and the shares could not add up to anything.
  const rows = [
    ...d.sections.map(s => ({title: s.title, entries: s.entries, chars: s.chars})),
    {title: "Rules and directives", chars: d.rules_chars},
    {title: `Recent turns, word for word (${d.history_msgs})`, chars: d.history_chars},
  ];
  const total = Math.max(1, rows.reduce((a, r) => a + (r.chars || 0), 0));
  const pct = n => (n > 0 && n / total < 0.005 ? "<1%" : Math.round(n / total * 100) + "%");
  const max = Math.max(...rows.map(r => r.chars || 0), 1);
  const warn = d.budget_used_pct >= 95;
  openModal(`<h2>What the model sees</h2>
    <p class="hint">The next turn's prompt, assembled for real (no model call).
      A section missing here is a section the model cannot use.</p>
    <div class="ctx-stats">
      <div><b>${d.approx_tokens.toLocaleString()}</b><span>tokens in</span></div>
      <div><b class="${warn ? "over" : ""}">${d.budget_used_pct}%</b>
        <span>of memory budget</span></div>
      <div><b>${d.history_msgs}</b><span>verbatim turns</span></div>
      <div><b>${d.brain}</b><span>brain</span></div>
      <div><b class="${d.semantic_recall === "on" ? "" : "over"}"
        >${d.semantic_recall}</b><span>semantic recall</span></div>
      <div><b>${d.lore_check.on ? `1/${d.lore_check.every}` : "off"}</b>
        <span>continuity check</span></div>
    </div>
    ${warn ? `<p class="hint" style="color:var(--player)">The budget is nearly
      full, so lower-priority lore is being cut. Raise the memory budget or trim
      the biggest sections below.</p>` : ""}
    ${(d.health || []).length ? `<div class="ctx-health">
      <b>Something fell back quietly</b>
      ${d.health.map(h => `<div>· <code>${esc(h.stage)}</code> (turn ${h.turn}):
        ${esc(h.reason)}</div>`).join("")}
    </div>` : ""}
    <div id="ctx-list">${rows.map(r => `<div class="ctx-row">
        <span class="ctx-name">${esc(r.title)}${r.entries
          ? ` <span class="muted">· ${r.entries}</span>` : ""}</span>
        ${bar(r.chars, max)}
        <span class="ctx-pct" title="share of the whole prompt">${pct(r.chars)}</span>
        <span class="ctx-n">${(r.chars || 0).toLocaleString()}</span>
      </div>`).join("")}</div>
    <p class="hint">Shares are of the prompt's characters, not its tokens, so they are close but not exact.</p>
    ${usageBlock(d.usage)}
    <div class="modal-actions"><button id="ctx-close">Close</button></div>`);
  $("#ctx-close").addEventListener("click", closeModal);
}

const fmtTok = n => (n >= 1e6 ? (n / 1e6).toFixed(2) + "M"
  : n >= 1000 ? Math.round(n / 1000) + "k" : String(n));

/* What this story has actually spent. Everything above the fold is what we
   THINK we send; this is what the provider billed, off its own usage frame.
   Per stage, because that answers the real question: is the extra brain
   worth it. */
function usageBlock(u) {
  if (!u || !u.calls) {
    return `<p class="hint">No token counts recorded yet. They appear once
      you take a turn (some providers do not report usage at all).</p>`;
  }
  const cost = (tin, tout) => {
    if (!u.price_in && !u.price_out) return "";
    const c = tin / 1e6 * u.price_in + tout / 1e6 * u.price_out;
    return ` · ${c < 0.01 ? "<$0.01" : "$" + c.toFixed(2)}`;
  };
  const stages = Object.entries(u.by_stage || {})
    .sort((a, b) => (b[1].in + b[1].out) - (a[1].in + a[1].out));
  const worst = Math.max(1, ...stages.map(([, s]) => s.in + s.out));
  return `<h2>What it has cost</h2>
    <p class="hint">The provider's own token counts, not an estimate.${
      u.cached ? ` ${fmtTok(u.cached)} of the input was served from the
      provider's prompt cache.` : ""}</p>
    <div class="ctx-stats">
      <div><b>${fmtTok(u.total_in)}</b><span>tokens in, all time</span></div>
      <div><b>${fmtTok(u.total_out)}</b><span>tokens out</span></div>
      <div><b>${u.calls}</b><span>model calls</span></div>
      <div><b>${fmtTok(u.last_turn.in + u.last_turn.out)}</b>
        <span>last turn${cost(u.last_turn.in, u.last_turn.out)}</span></div>
    </div>
    <div id="ctx-stages">${stages.map(([name, s]) => `<div class="ctx-row">
        <span class="ctx-name">${esc(name)}
          <span class="muted">· ${s.calls}</span></span>
        <div class="ctx-bar"><i style="width:${
          Math.max(1, Math.round((s.in + s.out) / worst * 100))}%"></i></div>
        <span class="ctx-n">${fmtTok(s.in + s.out)}</span>
      </div>`).join("")}</div>
    <p class="hint">All time: ${fmtTok(u.total_in + u.total_out)} tokens${
      cost(u.total_in, u.total_out)}. Set your model's price per million tokens
      in Settings to see cost.</p>`;
}

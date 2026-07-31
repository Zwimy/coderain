"""What the model ACTUALLY receives this turn, section by section.

Assembles the real payload (no model call, no tokens spent) and reports every
section with its size, so "the story forgot X" can be answered with "X is not in
the prompt, here is why" instead of guesswork.

This lives in `coderain`, not in the HTTP layer, because it is the answer to an
ENGINE question and every front end needs it. It was inline in srv/saves.py, so
the desktop app could not show it at all — and the desktop app is the one that
ships as a binary to people who will never open a browser devtools panel.
"""
from __future__ import annotations

import re

from .config import context_budget

# Section headings assemble() writes. An ENTRY heading carries a {#slug} and
# belongs to the section above it, so it is not a split point.
_SECTION_RE = re.compile(r"(?m)^## (?![^\n]*\{#)(.+)$")
_ENTRY_RE = re.compile(r"(?m)^## [^\n]*\{#")


def usage_report(store, cfg) -> dict:
    """Lifetime tokens for this story, plus the most recent turn, per stage."""
    tot = store.usage_total()
    recent = store.usage(limit=40)
    last_turn = recent[0].get("turn") if recent else None
    return {
        "total_in": int(tot.get("in", 0)),
        "total_out": int(tot.get("out", 0)),
        "cached": int(tot.get("cached", 0)),
        "calls": int(tot.get("calls", 0)),
        "by_stage": tot.get("by_stage", {}),
        "last_turn": store.usage_for_turn(last_turn) if last_turn is not None
        else {"in": 0, "out": 0, "calls": 0},
        "price_in": float(cfg.raw.get("price_in", 0) or 0),
        "price_out": float(cfg.raw.get("price_out", 0) or 0),
    }


def context_report(eng, cfg) -> dict:
    """Assemble the next turn's prompt for real and describe it."""
    store = eng.store
    hist = store.recent_turns(eng.short_term)
    msgs = eng._messages(hist, "(preview of the next turn)")
    sys_txt = msgs[0]["content"]
    parts = _SECTION_RE.split(sys_txt)
    preamble, sections = parts[0], []
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1]
        sections.append({
            "title": parts[i].strip(),
            "chars": len(body.strip()),
            "entries": len(_ENTRY_RE.findall(body)),
        })
    hist_chars = sum(len(m["content"]) for m in msgs[1:])
    total = len(sys_txt) + hist_chars
    budget = context_budget(cfg)
    return {
        "model": cfg.profile.model,
        "brain": "quad" if eng.trinity else "single",
        "lore_check": {"on": bool(cfg.generation.get("lore_check")),
                       "every": int(cfg.generation.get("lore_check_every", 1)),
                       "due_next_turn": eng.lore_due()},
        "budget_tokens": budget,
        "rules_chars": len(preamble.strip()),
        "history_msgs": len(msgs) - 1,
        "history_chars": hist_chars,
        "system_chars": len(sys_txt),
        "total_chars": total,
        "approx_tokens": total // 4,
        "budget_used_pct": round(len(sys_txt) / max(1, budget * 4) * 100),
        "sections": sorted(sections, key=lambda s: -s["chars"]),
        "semantic_recall": "on" if eng.retriever is not None else "off",
        # Anything that silently fell back. Degrading is fine; degrading
        # invisibly is what costs continuity with nothing to show for it.
        "health": store.health(limit=8),
        # The provider's OWN token counts, not the /4 estimate above. Everything
        # else on this payload is what we think we sent; this is what was billed.
        "usage": usage_report(store, cfg),
    }

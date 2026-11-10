"""Run every probe against a save and collect one report.

Imports coderain, so it must only be imported after the isolated home exists
(see soak.home). `assert_isolated()` is called first as a second line of defence.
"""
from __future__ import annotations

from collections import Counter

from soak import facts as F
from soak import probes
from soak.home import assert_isolated


def _title_for(store, fact: F.Fact) -> str:
    for e in store.entries(fact.registry):
        if e.slug == fact.entity:
            return e.title or e.slug
    return fact.entity


def run_audit(store, fixture: list[F.Fact] | None = None,
              memory: dict | None = None) -> dict:
    """Measure `store` (an ISOLATED copy) and return a plain-dict report."""
    assert_isolated()
    fixture = list(fixture or [])
    F.validate_fixture(fixture)         # a bad fixture is a confident wrong baseline
    turns = store.turns()
    probe = probes.PromptProbe(store, memory)

    results = []
    for fact in fixture:
        title = _title_for(store, fact)
        names = F.entity_names(store, fact)
        ask = f"I turn to {title}."
        named = probe.presence(fact.truth, names, fact.entity, ask)
        ambient = probe.presence(fact.truth, names, fact.entity, "I wait.")
        stale_named = (probe.presence(fact.stale, names, fact.entity, ask)
                       if fact.stale else None)
        prompt = {"named_system": named["system"], "named_any": named["any"],
                  "ambient_system": ambient["system"],
                  "ambient_any": ambient["any"]}
        if stale_named is not None:
            prompt["stale_named_system"] = stale_named["system"]
        results.append(F.evaluate(store, fact, turns, prompt))

    status = Counter(r.status for r in results)
    reproduces = [r.fact.id for r in results
                  if r.fact.expect and r.status != r.fact.expect]
    return {
        "save": {"turns": len(turns),
                 "scenes": len(store.entries("memory/scenes.md")),
                 "characters": len(store.entries("characters.md"))},
        "settings": {"memory": dict(memory or {})},
        "facts": [r.as_dict() for r in results],
        "fact_summary": {"statuses": dict(status),
                         "diverged_from_expectation": reproduces},
        "structure": {
            "transient_in_identity": probes.transient_in_identity(store),
            "clock": probes.clock_audit(store),
            "arc": probes.arc_coverage(store),
        },
        "attribute_drift": probes.attribute_drift(store),
    }

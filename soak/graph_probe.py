"""Relationship and who-knows-what probes for the scripted player (D-058).

Why. The look probes (`soak.play`) ask one question about one entry: "what colour is her hair". A knowledge graph would help with two
other kinds of question, and nothing measured whether the store we have already fails them:

  relation / possession  one hop: who is Ottoline's nephew, who keeps the brass lamp key. The answer sits in ONE sheet.
  twohop                 two hops: who sells salt to the keeper of the brass lamp key. The question names nobody whose sheet holds
                         the answer, so name-keyed activation has to find the second entry through the first.
  recall / leak          who knows what. The player whispers a secret to ONE character early on. Much later we ask that character
                         what they were told (recall) and ask the others about it (leak). The script knows exactly who was told,
                         so the answer needs no judge. A single narrator writes every character, so a secret that is in the
                         prompt can come out of anyone's mouth: that is the failure a "who witnessed what" graph exists to stop.

Everything here is invented, offline and deterministic, and scoring is a plain string check on the narration. It reads nothing from
a save. The tokens ("north beacon", "marrow gull") are chosen so a narrator will not produce them by accident, and no probe's own
wording contains its answer or its token (tests pin both).

A verdict is `held`, `wrong`, `mixed` or `none` for the one-hop and two-hop kinds (held: the right character is named and no other;
wrong: only another one is; mixed: both), `held` or `none` for recall, and `leak` or `clean` for leak. Recall is the control for leak:
a leak rate means nothing when the character who WAS told cannot say it either.
"""
from __future__ import annotations

import re

# Ties as the AUTHOR states them: (a, a's relation to b, b, b's relation to a). Each character's sheet carries its own side.
TIES = [
    ("Ottoline Pike", "aunt of", "Corwin Tide", "nephew of"),
    ("Bram Halloran", "is owed money by", "Hollis Wren", "owes money to"),
    ("Dessa Quill", "sells salt to", "Maribel Voss", "buys her salt from"),
]
ITEMS = {"Maribel Voss": "keeps the brass lamp key", "Dessa Quill": "carries the salt ledger",
         "Bram Halloran": "holds the customs stamp"}

# What the player confides, and to whom. Nobody else is told, and the probes below never put a token in a question.
SECRETS = {
    "letter": {"to": "Bram Halloran", "token": "north beacon",
               "tell": "I whisper to Bram Halloran, so that no one else hears, that the sealed letter is addressed to the "
                       "keeper of the north beacon."},
    "hull": {"to": "Dessa Quill", "token": "marrow gull",
             "tell": "I tell Dessa Quill quietly, out of everyone else's hearing, that the ferry's second hull was built from "
                     "the wreck of the Marrow Gull."},
}
TELL_TURNS = {3: "letter", 5: "hull"}
GRAPH_START = 16                  # the first probe: both secrets are 11 or more turns old, far outside a squeezed window

# gid -> the question, who is asked, who the right answer is, who may be named without being the answer (the one asked, and the
# middle of a two-hop chain), and for knowledge probes the token that proves the secret came out.
PROBES = {
    "R1": {"sub": "relation", "asker": "Bram Halloran", "action": "I ask Bram Halloran who Ottoline Pike's nephew is.",
           "expect": ["Corwin Tide"], "allowed": ["Bram Halloran", "Ottoline Pike"]},
    "R2": {"sub": "relation", "asker": "Dessa Quill", "action": "I ask Dessa Quill who owes Bram Halloran money.",
           "expect": ["Hollis Wren"], "allowed": ["Dessa Quill", "Bram Halloran"]},
    "R3": {"sub": "relation", "asker": "Hollis Wren", "action": "I ask Hollis Wren who buys salt from Dessa Quill.",
           "expect": ["Maribel Voss"], "allowed": ["Hollis Wren", "Dessa Quill"]},
    "P1": {"sub": "possession", "asker": "Corwin Tide", "action": "I ask Corwin Tide who keeps the brass lamp key.",
           "expect": ["Maribel Voss"], "allowed": ["Corwin Tide"]},
    "P2": {"sub": "possession", "asker": "Hollis Wren", "action": "I ask Hollis Wren who carries the salt ledger.",
           "expect": ["Dessa Quill"], "allowed": ["Hollis Wren"]},
    "P3": {"sub": "possession", "asker": "Maribel Voss", "action": "I ask Maribel Voss who holds the customs stamp.",
           "expect": ["Bram Halloran"], "allowed": ["Maribel Voss"]},
    "H1": {"sub": "twohop", "asker": "Hollis Wren",
           "action": "I ask Hollis Wren who sells salt to the keeper of the brass lamp key.",
           "expect": ["Dessa Quill"], "allowed": ["Hollis Wren", "Maribel Voss"]},
    "H2": {"sub": "twohop", "asker": "Corwin Tide", "action": "I ask Corwin Tide who is owed money by the tavern keeper.",
           "expect": ["Bram Halloran"], "allowed": ["Corwin Tide", "Hollis Wren"]},
    "H3": {"sub": "twohop", "asker": "Dessa Quill",
           "action": "I ask Dessa Quill what the aunt of the mudlark boy is called.",
           "expect": ["Ottoline Pike"], "allowed": ["Dessa Quill", "Corwin Tide"]},
    "K1": {"sub": "recall", "asker": "Bram Halloran", "action": "I ask Bram Halloran what I told him about the sealed letter.",
           "token": "north beacon", "secret": "letter"},
    "K2": {"sub": "recall", "asker": "Dessa Quill", "action": "I ask Dessa Quill what I told her about the ferry's second hull.",
           "token": "marrow gull", "secret": "hull"},
    "L1": {"sub": "leak", "asker": "Hollis Wren", "action": "I ask Hollis Wren who the sealed letter is addressed to.",
           "token": "north beacon", "secret": "letter"},
    "L2": {"sub": "leak", "asker": "Corwin Tide", "action": "I ask Corwin Tide where the ferry's second hull came from.",
           "token": "marrow gull", "secret": "hull"},
    "L3": {"sub": "leak", "asker": "Maribel Voss", "action": "I ask Maribel Voss what she knows about the sealed letter.",
           "token": "north beacon", "secret": "letter"},
    "L4": {"sub": "leak", "asker": "Ottoline Pike", "action": "I ask Ottoline Pike what she knows about the ferry's second hull.",
           "token": "marrow gull", "secret": "hull"},
}
KINDS = ["relation", "possession", "twohop", "recall", "leak"]
BY_KIND = {k: [g for g, p in PROBES.items() if p["sub"] == k] for k in KINDS}


def ties_line(name: str) -> str:
    """The sheet line that states this character's own ties and possessions, as the author would write them. Each tie is stated
    on BOTH sheets, so a fact is not hidden from half the story by where it was written."""
    parts = []
    for a, rel_a, b, rel_b in TIES:
        if name == a:
            parts.append(f"{rel_a} {b}")
        elif name == b:
            parts.append(f"{rel_b} {a}")
    if name in ITEMS:
        parts.append(ITEMS[name])
    return f"**Ties:** {'; '.join(parts)}. " if parts else ""


def schedule(i: int, every: int = 4, start: int = GRAPH_START) -> str | None:
    """Which probe (if any) turn `i` carries. The kinds rotate, and each kind walks its own list, so a long run asks every
    question several times and no two neighbouring probes are alike."""
    if every < 1 or i < start or (i - start) % every:
        return None
    k = (i - start) // every
    ids = BY_KIND[KINDS[k % len(KINDS)]]
    return ids[(k // len(KINDS)) % len(ids)]


def tell_move(i: int) -> dict | None:
    sid = TELL_TURNS.get(i)
    if sid is None:
        return None
    return {"kind": "tell", "action": SECRETS[sid]["tell"], "who": SECRETS[sid]["to"], "slot": "", "gid": sid, "sub": "tell"}


def probe_move(i: int, every: int = 4, start: int = GRAPH_START) -> dict | None:
    gid = schedule(i, every, start)
    if gid is None:
        return None
    p = PROBES[gid]
    return {"kind": "graph", "action": p["action"], "who": p["asker"], "slot": "", "gid": gid, "sub": p["sub"]}


def names_in(text: str, cast) -> set[str]:
    """Which cast members the narration names: the full name or one of their aliases. The cast lists the first name and a role as
    aliases ("Corwin", "the mudlark"), so those count too."""
    low = text.lower()
    out = set()
    for c in cast:
        name, aliases = c[0], c[2]
        words = {name.lower(), *(a.lower() for a in aliases)}
        if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words):
            out.add(name)
    return out


def score(gid: str, text: str, cast) -> str:
    p = PROBES[gid]
    low = text.lower()
    if p["sub"] == "leak":
        return "leak" if p["token"] in low else "clean"
    if p["sub"] == "recall":
        return "held" if p["token"] in low else "none"
    named = names_in(text, cast)
    right = named & set(p["expect"])
    wrong = named - set(p["expect"]) - set(p["allowed"])
    if right and not wrong:
        return "held"
    if wrong and not right:
        return "wrong"
    return "mixed" if right and wrong else "none"


def summarize(rows) -> dict:
    """Counts per kind, and the three rates a decision needs: how often a hop was answered, how often the told character could
    say it, and how often another character said it. `leak_meaningful` is false when nobody could recall: a store that forgets
    the secret altogether looks leak-free for the wrong reason."""
    out: dict = {k: {} for k in KINDS}
    for r in rows:
        if r.get("kind") == "graph" and r.get("verdict"):
            d = out[r["sub"]]
            d[r["verdict"]] = d.get(r["verdict"], 0) + 1
    hops = [out[k] for k in ("relation", "possession", "twohop")]
    asked_hops = sum(sum(d.values()) for d in hops)
    recall_n, leak_n = sum(out["recall"].values()), sum(out["leak"].values())
    out["right_hops"] = f"{sum(d.get('held', 0) for d in hops)} of {asked_hops}"
    out["one_hop_right"] = _frac(out["relation"], out["possession"])
    out["two_hop_right"] = _frac(out["twohop"])
    out["recall_rate"] = f"{out['recall'].get('held', 0)} of {recall_n}"
    out["leak_rate"] = f"{out['leak'].get('leak', 0)} of {leak_n}"
    out["leak_meaningful"] = out["recall"].get("held", 0) > 0
    return out


def _frac(*ds) -> str:
    n = sum(sum(d.values()) for d in ds)
    return f"{sum(d.get('held', 0) for d in ds)} of {n}"


def stub_answer(last: str, mode: str, cast) -> str | None:
    """What the offline writer says to a graph move, or None when `last` is not one. `truthful` answers every question right,
    recalls the secret to the one told and tells nobody else; `leaky` is truthful and also lets everyone else say it; `wrong`
    names the wrong person and forgets the secret. A faithful stub only proves the harness runs, so the other two modes exist
    for a test to show that the scoring notices a wrong answer and a leak."""
    for s in SECRETS.values():
        if s["tell"] in last:
            return f"{s['to'].split()[0]} nods slowly and says nothing more."
    for p in PROBES.values():
        if p["action"] not in last:
            continue
        asker = p["asker"].split()[0]
        if p["sub"] in ("relation", "possession", "twohop"):
            if mode == "wrong":
                other = next(c[0] for c in cast if c[0] not in p["expect"] and c[0] not in p["allowed"])
                return f"{asker} thinks it over. 'That would be {other},' they say."
            return f"{asker} thinks it over. 'That would be {p['expect'][0]},' they say."
        if p["sub"] == "recall":
            if mode == "wrong":
                return f"{asker} frowns and shakes their head."
            return f"{asker} lowers their voice. 'You told me it was {p['token']},' they murmur."
        if mode == "leaky":
            return f"{asker} leans in. 'Everyone says it is {p['token']},' they whisper."
        return f"{asker} shrugs and says that is nothing they know."
    return None

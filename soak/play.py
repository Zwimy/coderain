"""A scripted player that plays an INVENTED story through the real engine (D-046).

Why it exists. Every comparison that needs a story played for many turns (the canon card on or off, fate on or off, a
model against another) needs the same player making the same moves, and the driver the consistency soaks used lived
outside the repo. This is that driver, made general: it builds a temp home (never the repo root), writes a squeezed
memory config, plays N turns through `Engine.turn` and `maybe_fold` exactly as the web app does, and writes one row per
turn plus a summary.

    python -m soak play --out DIR [--turns 30] [--seed 5] [--stub | --model NAME] [--fate off|preview|on]
                        [--sheets full|role] [--window 4] [--budget 5000] [--probe-every 8] [--canon off|card]
                        [--probe-set look|graph|all] [--graph-every 4] [--ask plain|open] [--facts stated|none]
                        [--stub-knowledge truthful|leaky|wrong]
                        [--provider ollama|openrouter] [--allow-paid] [--max-requests 900]

  --stub   an offline writer (deterministic prose, no model, no network): what the tests and a dry run use
  --model  a local Ollama model on this machine. It must already be running: this never starts it, and a host that is
           not this machine is refused (the invented story is the only text sent, but a habit of refusing is cheap)
  --provider openrouter (D-068): a hosted model instead, FREE ones only (the name must end in :free unless --allow-paid). The key is
           read from the OPENROUTER_API_KEY environment variable, never an argument and never written to the run's config. Requests are
           spaced (3.2 s), a busy or refused one is retried after a wait, every attempt counts against --max-requests, and the run
           stops cleanly between turns when too few are left for one more (a free model has a daily cap). The summary says how many
           requests it used and whether it stopped early (soak/hosted.py)
  --fate   the save's fate setting (D-045). off: the model is never asked; preview: asked and recorded, the Writer is
           sent nothing; on: it steers
  --sheets full: each character sheet states hair and eyes (the truth probes are scored against);
           role: only a role, so the story is scored against what it first says (soak_truth style, not built in)
  --canon  card: the canon shadow reads the story and injects the Scene State Card (needs --model: the reader is a model)

Probes: every `probe-every` turns the player studies one character's hair or eyes and the colour the narration states
is compared with the sheet (held, drift, or none). Rows and the summary hold the story's own invented text, so they
are written only to --out.

  --probe-set  look (default): the hair and eyes probes above. graph (D-058): relationship, possession, two-hop and who-knows-what
           probes instead: the characters' `relationships:` lines state ties and items.md states who holds what, the player
           whispers a secret to one character on turns 3 and 5,
           and from turn 16 every `graph-every` turns asks a question about them (soak/graph_probe.py). all: both, the look probe
           winning a turn they share.
  --facts  stated (default): the ties and possessions above are written into the story. none: nothing is, and the same questions are
           asked, so what the Writer gets right is the guessing baseline
  --follow-links  turn on `memory: follow_links` (D-059): an activated item leads to its holder, a person to their ties. Off by default,
           which is the shipped default; it changes nothing else in the run
  --tail-ties  turn on `memory: tail_ties` (D-063): the ties and holders of what the action and the last reply name, said again at
           the end of the prompt, after the action. Off by default, which is the shipped default; it changes nothing else in the run
  --tic-guard  turn on `generation: tic_guard` (D-064): the phrases the last replies keep reusing are said back to the Writer as "say it
           another way". Off by default, which is the shipped default. The summary's `repeat_share` is the measure to read
  --ask    plain (default): each graph question also asks for a straight answer in one sentence, because a model that narrates
           around the question can neither be scored right nor caught leaking; open: the bare question
  --stub-knowledge  what the OFFLINE writer does with those questions (truthful, leaky, wrong): it exists so a test can show the
           scoring notices a wrong answer and a leak
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from soak import graph_probe as gp
from soak import hosted

PREMISE = ("Brinewick is a tidal town on a saltmarsh, reached only by the ferry. Rain comes off the sea most evenings. "
           "You arrive as a stranger carrying a sealed letter for someone in town. The people you meet are Ottoline Pike, "
           "the ferrywoman; Bram Halloran, the customs officer; Dessa Quill, a salt trader; Corwin Tide, a mudlark boy; "
           "Maribel Voss, the lighthouse keeper; and Hollis Wren, the tavern keeper.")
# name, slug, aliases, hair, eyes, role
CAST = [
    ("Ottoline Pike", "ottoline-pike", ["Ottoline", "the ferrywoman"], "red", "grey", "the ferrywoman"),
    ("Bram Halloran", "bram-halloran", ["Bram", "the customs officer"], "white", "brown", "the customs officer"),
    ("Dessa Quill", "dessa-quill", ["Dessa", "the salt trader"], "blonde", "green", "a salt trader"),
    ("Corwin Tide", "corwin-tide", ["Corwin", "the mudlark"], "black", "blue", "a mudlark boy"),
    ("Maribel Voss", "maribel-voss", ["Maribel", "the lighthouse keeper"], "auburn", "violet", "the lighthouse keeper"),
    ("Hollis Wren", "hollis-wren", ["Hollis", "the tavern keeper"], "grey", "amber", "the tavern keeper"),
]
PLACES = ["the ferry deck", "the customs shed", "the salt market", "the lighthouse stair", "the mudflats", "the tavern",
          "the harbour wall", "the reed path"]
ACTIONS = [
    "I ask {n} about the next crossing.", "I tell {n} what I saw on the mudflats.", "I walk to {p} and look around.",
    "I ask {n} who the sealed letter might be for.", "I buy a drink and talk to {n}.", "I help {n} with a heavy crate.",
    "I ask {n} how long they have lived in Brinewick.", "I follow {n} to {p}.", "I listen to what {n} is saying.",
    "I show {n} the sealed letter without opening it.", "I ask {n} what the tide will do tonight.",
]
FATE_SIG = "You write ONE hidden steering line"
# Twelve directions that share no run of three content words, so the stub passes fate's own repeat check.
DIRECTIONS = [
    "A bell rings out over the water and heads turn toward the harbour.",
    "Rain hammers the shutters until the lamp gutters low.",
    "A gull steals a loaf from a nearby stall.",
    "Someone shouts a warning from the far end of the street.",
    "The ferry horn sounds twice, earlier than anyone expected.",
    "A cart wheel snaps and spills crates across the cobbles.",
    "Fog drifts in and the lights across the marsh disappear.",
    "A stranger waits in the doorway, hat pulled low.",
    "The tide turns faster than the old charts promised.",
    "Footsteps hurry past carrying a covered basket.",
    "A dog begins barking at something unseen on the reeds.",
    "The wind drops, and for a moment everything goes still.",
]
COLOUR_FAMILIES = [
    {"gray", "grey", "steel", "pewter", "slate", "ashen", "charcoal", "silver"},
    {"violet", "purple", "amethyst", "lavender", "lilac", "mauve", "plum"},
    {"raven", "black", "jet", "ebony", "onyx", "obsidian", "inky"},
    {"blond", "blonde", "gold", "golden", "yellow", "flaxen", "honey", "straw"},
    {"white", "platinum", "snowy"},
    {"red", "crimson", "scarlet", "ruby", "burgundy", "maroon", "wine"},
    {"green", "emerald", "jade", "olive", "veridian", "viridian", "mint", "teal"},
    {"blue", "azure", "cobalt", "sapphire", "navy", "indigo", "cyan", "turquoise", "aqua"},
    {"brown", "chestnut", "chocolate", "hazel", "brunette", "auburn", "copper", "ginger", "tan", "russet"},
    {"amber"},
]


class ScriptedPlayer:
    """The same moves for the same seed: a probe every `probe_every` turns, ordinary actions between."""

    def __init__(self, seed: int = 5, probe_every: int = 8, probe_set: str = "look", graph_every: int = 4, ask: str = "plain"):
        self.rng, self.probe_every, self.ask = random.Random(seed), probe_every, ask
        self.look_on, self.graph_on, self.graph_every = probe_set in ("look", "all"), probe_set in ("graph", "all"), graph_every

    def act(self, i: int) -> dict:
        name = CAST[self.rng.randrange(len(CAST))][0]            # drawn on EVERY turn, so the other moves do not shift
        if self.graph_on:
            tell = gp.tell_move(i)
            if tell:
                return tell
        if self.look_on and self.probe_every and i % self.probe_every == 0:
            slot = "hair" if (i // self.probe_every) % 2 else "eyes"
            action = f"I study {name}'s hair." if slot == "hair" else f"I meet {name}'s eyes and study them."
            return {"kind": "probe", "action": action, "who": name, "slot": slot}
        if self.graph_on:
            question = gp.probe_move(i, self.graph_every, ask=self.ask)
            if question:
                return question
        place = self.rng.choice(PLACES)
        return {"kind": "play", "action": self.rng.choice(ACTIONS).format(n=name, p=place), "who": name, "slot": ""}


class StubWriter:
    """An offline stand-in for the model. Deterministic prose; when the player studies someone's hair or eyes it states
    the sheet's colour, so the probe scoring has something to score. As a fate stage (complete) it answers with a short
    direction chosen by the action, and `calls` counts what it was asked."""
    model = "stub-writer"

    def __init__(self, sheets: str = "full", knowledge: str = "truthful", folds: bool = False):
        self.sheets, self.knowledge, self.gen, self.folds = sheets, knowledge, {}, folds
        self.calls = {"writer": 0, "fate": 0, "other": 0, "steered": 0}     # steered: Writer calls that carried a fate note

    def stream(self, messages, **k):
        self.calls["writer"] += 1
        if any(m["role"] == "system" and str(m["content"]).startswith("Hidden steering") for m in messages):
            self.calls["steered"] += 1
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        said = gp.stub_answer(last, self.knowledge, CAST)
        if said:                                                  # a relationship, possession or secret move (D-058)
            yield said
            return
        who = next((c for c in CAST if c[0] in last or c[0].split()[0] in last), CAST[0])
        m = re.search(r"study .*?(hair)|study .*?(eyes)|meet .*?(eyes)", last)
        if m and self.sheets == "full":
            hair = bool(m.group(1))
            yield f"{who[0]} meets your look. {who[0].split()[0]}'s {who[3] if hair else who[4]} {'hair' if hair else 'eyes'} " \
                  "catch the lamplight, and then the moment passes."
        else:
            yield f"{who[0]} considers your words and answers in a low voice, then the rain comes harder."

    def complete(self, messages, **k):
        if str(messages[0].get("content", "")).startswith(FATE_SIG):
            self.calls["fate"] += 1
            # In order, not by a hash of the prompt: the prompt carries text that varies between runs, and two close
            # turns picking the same sentence made fate's repeat check refuse it (a flaky test). Twelve in a row never
            # repeat within fate's look-back of three.
            n = self.calls["fate"] - 1
            return json.dumps({"stakes": "some" if n % 3 else "none", "direction": DIRECTIONS[n % len(DIRECTIONS)]})
        self.calls["other"] += 1
        if self.folds:
            # The real client's complete() is "".join(self.stream(...)), so a fold's model call goes through the same
            # stream() the prompt spy wraps. With folds on, the stub does the same, which is what lets a test see the bug
            # where the spy's "last call" was a fold's and not the Writer's (D-059 correction of D-058).
            return "".join(self.stream(messages))
        return "{}"


def _family(word: str) -> frozenset:
    return next((frozenset(f) for f in COLOUR_FAMILIES if word in f), frozenset({word}))


def probe_verdict(text: str, who: str, slot: str, truth: str) -> str:
    """held (the colour the narration states for that look is the sheet's), drift (another), or none."""
    first = who.split()[0].lower()
    nouns = {"hair": {"hair", "haired"}, "eyes": {"eyes", "eye", "eyed"}}[slot]
    found: set[str] = set()
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
        words = re.findall(r"[a-z']+", sent.lower())
        for k, w in enumerate(words):
            if w in nouns:
                found |= {x for x in words[max(0, k - 4):k + 8] if any(x in f for f in COLOUR_FAMILIES) and x != first}
    if not found:
        return "none"
    return "held" if any(_family(c) == _family(truth) for c in found) else "drift"


def sheet_body(cast_row, sheets: str) -> str:
    """One character's sheet body. `sheets` decides whether the look is stated (the look probes score against it)."""
    _name, _slug, _aliases, hair, eyes, role = cast_row
    looks = f"**Visual:** {role}, with {hair} hair and {eyes} eyes. " if sheets == "full" else f"**Role:** {role}. "
    return looks + "**Mentality:** guarded but fair. **Voice:** plain, short sentences."


def sheet_attrs(cast_row, graph_on: bool, facts: str) -> dict:
    """One character's attrs. The graph probes' ties go where the engine keeps them, the `relationships:` line; with `--facts none`
    nothing is stated, which is the guessing baseline."""
    attrs = {"status": "alive"}
    ties = gp.relationships_attr(cast_row[0]) if graph_on and facts == "stated" else ""
    if ties:
        attrs["relationships"] = ties
    return attrs


def repeat_share(texts: list[str], n: int = 8) -> float:
    """The mean share of a turn's n-word runs that were already in the turn before it: how much a Writer is feeding on its own last reply
    (D-055 read it as 103 recurring eight-word runs in one story). 0 is a new turn each time, 1 is the same turn again."""
    def runs(t: str) -> set[str]:
        w = re.findall(r"[a-z']+", t.lower())
        return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    shares = []
    for a, b in zip(texts, texts[1:]):
        rb = runs(b)
        if rb:
            shares.append(len(runs(a) & rb) / len(rb))
    return round(sum(shares) / len(shares), 4) if shares else 0.0


def _config(model: str, window: int, budget: int, canon: str, stub: bool, follow_links: bool = False,
            stub_folds: bool = False, tail_ties: bool = False, tic_guard: bool = False, provider: str = "ollama") -> str:
    profile = hosted.profile_lines(model) if provider == "openrouter" else f"""active_profile: local
profiles:
  local:
    base_url: http://localhost:11434/v1
    model: {model}
    api_key_env: OLLAMA_API_KEY
    context_tokens: 16384
"""
    cfg = profile + f"""generation:
  temperature: 0.9
  top_p: 0.95
  max_tokens: 700
  think: false
  use_memory_tool: false
  trinity_brain: false
  response_length: medium
  ai_acts_as_player: false
  chapter_outline: false
  lore_check: false
  tic_guard: {"true" if tic_guard else "false"}
memory:
  short_term_turns: {window}
  medium_fold_after: {10_000 if stub and not stub_folds else 12}
  medium_fold_size: 5
  long_fold_after: 8
  long_fold_size: 4
  context_budget_tokens: {budget}
  follow_links: {"true" if follow_links else "false"}
  tail_ties: {"true" if tail_ties else "false"}
rpg: {{}}
retrieval:
  enabled: false
"""
    if canon == "card":
        cfg += f"canon:\n  shadow: true\n  inject: true\n  backfill: all\n  model: {model}\n"
    return cfg


def _require_local(host: str) -> None:
    name = urllib.parse.urlparse(host).hostname or ""
    if name not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit(f"refused: {host!r} is not this machine; the soak player only talks to a local model")
    try:
        urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=5).read()
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"cannot reach {host} ({e}); start Ollama first, this never starts it")


def run_play(args, home: Path) -> int:
    """Play the story. `home` is the isolated CODERAIN_HOME the caller made BEFORE anything imported coderain."""
    from soak.home import assert_isolated
    assert_isolated()
    stub = bool(args.stub) or not args.model
    if args.canon == "card" and stub:
        raise SystemExit("--canon card needs --model: the reader that builds the card is a model")
    provider = getattr(args, "provider", "ollama")
    pacer = None
    if provider == "openrouter":
        hosted.check_model(args.model, bool(getattr(args, "allow_paid", False)))
        hosted.require_key()
        pacer = hosted.Pacer(max_requests=int(getattr(args, "max_requests", 900)))
    elif not stub:
        _require_local(args.host)
    model = "stub-writer" if stub else args.model
    (home / "config.yaml").write_text(
        _config(model, args.window, args.budget, args.canon, stub, bool(args.follow_links), bool(args.stub_folds),
                bool(args.tail_ties), bool(args.tic_guard), provider),
        encoding="utf-8")

    from coderain import fate
    from coderain.config import load_config
    from coderain.engine import Engine
    from coderain.memory import Entry, Library

    lib = Library(home)
    slug = lib.create_story("Brinewick", PREMISE)
    store = lib.store(slug)
    probe_set = args.probe_set
    graph_every = args.graph_every
    graph_on = probe_set in ("graph", "all")
    for row in CAST:
        store.upsert_entry("characters.md", Entry(
            title=row[0], slug=row[1], aliases=row[2], importance=4, attrs=sheet_attrs(row, graph_on, args.facts),
            body=sheet_body(row, args.sheets)))
    if graph_on and args.facts == "stated":
        for spec in gp.item_specs():
            store.upsert_entry("items.md", Entry(title=spec["title"], slug=spec["slug"], aliases=spec["aliases"], importance=3,
                                                 attrs={"holder": spec["holder"]}, body=spec["body"]))
    # A new story draws a random dice seed. Pin it to --seed so the same seed gives the same dice as well as the same
    # moves, which is what an on/off comparison of fate (or anything that rolls) needs.
    rpg = store.rpg_state()
    rpg["seed"] = args.seed
    store.set_rpg_state(rpg)
    if args.fate != "off":
        fate.set_settings(store, args.fate, True)
    undo_pacing = hosted.install(pacer) if pacer is not None else None
    eng = Engine(load_config(), store)
    writer = StubWriter(args.sheets, args.stub_knowledge, folds=bool(args.stub_folds)) if stub else None
    if writer is not None:
        eng.llm = writer
    # What the Writer actually received, for the graph probes' `seen` fields: the last call is the turn's own.
    sent: list = []
    real_stream = eng.llm.stream

    def _spy(messages, **k):
        sent.append(messages)
        return real_stream(messages, **k)

    eng.llm.stream = _spy

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    truth = {n: (h, e) for n, _s, _a, h, e, _r in CAST}
    ask = args.ask
    player = ScriptedPlayer(args.seed, args.probe_every, probe_set, graph_every, ask)
    rows, verdicts = [], {"held": 0, "drift": 0, "none": 0}
    t_all = time.time()
    stopped = None
    with (out / "turns.jsonl").open("w", encoding="utf-8") as f:
        for i in range(1, args.turns + 1):
            # A hosted free model has a daily cap, so the run stops between turns with what it has instead of dying inside one.
            if pacer is not None and pacer.left() < hosted.MIN_TURN_REQUESTS:
                stopped = f"request budget spent after {len(rows)} turns"
                break
            mv = player.act(i)
            t0 = time.time()
            calls_before = len(sent)
            text = "".join(eng.turn(mv["action"]))
            if pacer is not None and pacer.failed:
                # The provider refused for good (the pool stayed busy through every retry, or a daily cap): the text is an error
                # message, not narration, so this turn is not recorded and the run ends with what it has.
                stopped = f"the provider failed at turn {i} ({pacer.last_error}); that turn is not recorded"
                break
            # The Writer's call is picked out BEFORE the fold, which makes model calls of its own (see writer_call).
            writer_msgs = gp.writer_call(sent[calls_before:], mv["action"])
            events = eng.maybe_fold()
            secs = round(time.time() - t0, 2)
            rec = next((r for r in reversed(fate.read(store)) if r["n"] == len(store.turns()) - 1), None)
            row = {"i": i, **mv, "secs": secs, "text": text, "events": events, "words": len(text.split()),
                   "fate": ({k: rec[k] for k in ("roll", "tier", "stakes", "text")} if rec else None)}
            if mv["kind"] == "probe" and args.sheets == "full":
                row["verdict"] = probe_verdict(text, mv["who"], mv["slot"], truth[mv["who"]][0 if mv["slot"] == "hair" else 1])
                verdicts[row["verdict"]] += 1
            if mv["kind"] in ("graph", "tell"):
                row["gid"], row["sub"] = mv["gid"], mv["sub"]
                if mv["kind"] == "graph":
                    row["verdict"] = gp.score(mv["gid"], text, CAST)
                    row["prompt_found"] = writer_msgs is not None
                    row["seen"], row["seen_memory"] = gp.evidence_flags(mv["gid"], writer_msgs or [])
                    row["linked"] = gp.linked_lines(writer_msgs)
                    row["tail_ties"] = gp.tail_line(writer_msgs)
                    row["tic_line"] = gp.tic_message(writer_msgs)
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    tiers: dict[str, int] = {}
    for r in rows:
        if r["fate"]:
            key = r["fate"]["tier"] + ("" if r["fate"]["text"] else " (quiet)")
            tiers[key] = tiers.get(key, 0) + 1
    summary = {"turns": len(rows), "seed": args.seed, "stub": stub, "model": model, "fate": args.fate, "canon": args.canon,
               "sheets": args.sheets, "probes": verdicts, "fate_tiers": tiers, "fate_rows": sum(1 for r in rows if r["fate"]),
               "words_mean": round(sum(r["words"] for r in rows) / max(1, len(rows)), 1),
               "secs_mean": round(sum(r["secs"] for r in rows) / max(1, len(rows)), 2),
               "wall_secs": round(time.time() - t_all, 1),
               "tic_guard": bool(args.tic_guard),
               "repeat_share": repeat_share([r["text"] for r in rows if r.get("text")]),
               "model_calls": dict(writer.calls) if writer is not None else None,
               "health_rows": len(store.health(200)),
               "provider": provider, "requests": pacer.count if pacer is not None else None, "stopped": stopped}
    if undo_pacing is not None:
        undo_pacing()
    if graph_on:
        summary["probe_set"], summary["ask"], summary["facts"] = probe_set, ask, args.facts
        summary["follow_links"] = bool(args.follow_links)
        summary["tail_ties"] = bool(args.tail_ties)
        summary["graph"] = gp.summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0

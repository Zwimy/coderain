"""Relationship and who-knows-what probes for the scripted player (D-058).

Why they exist. A knowledge graph would help with relationships, with questions that cross two sheets, and with "who knows what", and
nothing measured whether the store we have already fails them. These probes ask those questions of the real engine, with a known answer
for each (the author states the ties and possessions where the engine keeps them; the player whispers each secret to ONE character), and score the narration by a plain string
check. This suite pins the probes themselves with the offline writer, so nothing here needs a model.

 1) the schedule: the secrets are told on turns 3 and 5 only, the first question is on turn 16, the kinds rotate, every question is asked
    again in a long run, and the look-only default has no graph rows at all
 2) the questions are fair: no question contains its own answer or its token, a told character is never asked as a leak probe, every
    secret is told to exactly one character, and every answer is a cast member
 3b) `seen` (the evidence was in the prompt the Writer got: a whole group, case and spacing aside) and `invented` (a character SAYS a
    made-up name, which is not the same failure as naming the wrong member of the cast)
 3) the scoring table: held, wrong, mixed and none for a hop (an asked or middle character may be named; a first name, a full name and an
    alias all count), held and none for recall, leak and clean for leak (case does not matter)
 4) the facts are stated where the engine keeps them (a `relationships:` line on BOTH sides of every tie, an items.md entry naming each
    holder), every possession runs against its holder's role so a guess from roles is wrong, every expected answer follows from the
    planted facts, and `--facts none` plants nothing
 5) a truthful offline run answers everything right, recalls to the one told and leaks to nobody, and reports the rates
 6) a leaky one is scored leak, a wrong one is scored wrong and forgets the secret (so `leak_meaningful` is false): the scoring notices
 7) `all` runs both families without two probes on one turn; the same seed plays the same story
 8) summarize: the counts, the fractions and the guard that a leak rate means nothing when nobody could recall
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-graphprobe-"))
_n = [0]

from soak import graph_probe as gp                     # noqa: E402
from soak.play import CAST, ScriptedPlayer, sheet_attrs, sheet_body  # noqa: E402

NAMES = [c[0] for c in CAST]


def play(*extra):
    _n[0] += 1
    out = WORK / f"run{_n[0]}"
    r = subprocess.run([sys.executable, "-m", "soak", "play", "--stub", "--out", str(out), *extra], cwd=ROOT,
                       capture_output=True, text=True, timeout=240, encoding="utf-8", errors="replace")
    assert r.returncode == 0, (extra, r.returncode, r.stdout[-300:], r.stderr[-500:])
    rows = [json.loads(x) for x in (out / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
    return rows, json.loads((out / "summary.json").read_text(encoding="utf-8"))


def test_schedule():
    assert [i for i in range(1, 60) if gp.tell_move(i)] == [3, 5]
    assert gp.tell_move(3)["who"] == "Bram Halloran" and gp.tell_move(5)["who"] == "Dessa Quill"
    turns = [i for i in range(1, 80) if gp.schedule(i)]
    assert turns[0] == 16 and turns == list(range(16, 80, 4)), turns
    kinds = [gp.PROBES[gp.schedule(i)]["sub"] for i in turns[:10]]
    assert kinds == ["relation", "possession", "twohop", "recall", "leak"] * 2, kinds
    seen = {g for g in (gp.schedule(i) for i in range(16, 16 + 4 * 5 * 4)) if g}
    assert seen == set(gp.PROBES), ("a long run must ask every question", set(gp.PROBES) - seen)
    assert gp.schedule(16, every=0) is None and gp.schedule(15) is None and gp.schedule(18) is None
    plain, bare = gp.probe_move(16), gp.probe_move(16, ask="open")
    assert plain["action"] == bare["action"] + gp.PLAIN and not bare["action"].endswith(gp.PLAIN.strip()), (plain, bare)
    assert ScriptedPlayer(5, 8, "graph").act(16)["action"] == plain["action"], "plain is the default"
    assert ScriptedPlayer(5, 8, "graph", ask="open").act(16)["action"] == bare["action"]
    p = ScriptedPlayer(5, 8)                                   # the default: look probes only, no graph move ever
    assert not any(p.act(i)["kind"] in ("graph", "tell") for i in range(1, 80))
    g = ScriptedPlayer(5, 8, "graph")
    kinds = [g.act(i)["kind"] for i in range(1, 30)]
    assert "probe" not in kinds and kinds.count("tell") == 2 and kinds.count("graph") == len(range(16, 30, 4)), kinds
    print("1. the secrets are told on turns 3 and 5, the questions start on turn 16 and rotate, and the default has none")


def test_questions_are_fair():
    for gid, p in gp.PROBES.items():
        low = p["action"].lower()
        if "token" in p:
            assert p["token"] not in low, (gid, "the question hands over the secret")
        for name in p.get("expect", []):
            assert name.lower() not in low and name.split()[0].lower() not in low, (gid, "the question names its own answer", name)
            assert name in NAMES
        assert p["asker"] in NAMES and p["asker"].lower() in low or p["asker"].split()[0].lower() in low, (gid, "asker not named")
        for name in p.get("allowed", []):
            assert name in NAMES, (gid, name)
    for sid, s in gp.SECRETS.items():
        assert s["token"] in s["tell"].lower(), (sid, "the secret is never told")
        assert s["to"] in NAMES
    for gid in gp.BY_KIND["leak"]:
        p = gp.PROBES[gid]
        assert p["asker"] != gp.SECRETS[p["secret"]]["to"], (gid, "a leak probe asks the one who WAS told")
    for gid in gp.BY_KIND["recall"]:
        p = gp.PROBES[gid]
        assert p["asker"] == gp.SECRETS[p["secret"]]["to"], (gid, "a recall probe asks someone who was not told")
    assert gp.SECRETS["letter"]["to"] != gp.SECRETS["hull"]["to"]
    low = gp.PLAIN.lower()                                     # the nudge to answer plainly must not hand over an answer either
    assert not any(t["token"] in low for t in gp.SECRETS.values()) and not any(n.lower() in low for n in NAMES), gp.PLAIN
    for gid in gp.BY_KIND["twohop"]:
        assert gp.PROBES[gid]["asker"] in gp.PROBES[gid]["allowed"] and len(gp.PROBES[gid]["allowed"]) == 2
    print("2. no question contains its own answer or token; a leak probe never asks the one told; a recall probe always does")


def test_scoring():
    s = lambda gid, text: gp.score(gid, text, CAST)        # noqa: E731
    # R1: who is Ottoline Pike's brother (Hollis Wren), asked of Dessa Quill
    assert s("R1", "Dessa thinks it over. 'Hollis Wren,' she says.") == "held"
    assert s("R1", "Dessa says it is Hollis.") == "held", "a first name counts (the cast lists it as an alias)"
    assert s("R1", "Dessa says it is the tavern keeper.") == "held", "an alias counts"
    assert s("R1", "Ottoline's brother? Dessa says it is Corwin Tide.") == "wrong", "the asked and the named sibling are allowed; Corwin is not"
    assert s("R1", "Dessa says it is Hollis, or maybe Corwin.") == "mixed"
    assert s("R1", "Dessa shrugs and looks away.") == "none"
    assert s("R1", "Dessa Quill looks at Ottoline Pike and says nothing.") == "none", "naming only the allowed is no answer"
    assert s("H1", "Dessa thinks of Hollis, whose sister is Ottoline Pike.") == "held", "the middle of the chain is allowed"
    assert s("H1", "Dessa says it is Bram Halloran.") == "wrong"
    assert s("P1", "Corwin says Hollis carries it.") == "held" and s("P1", "Corwin says Maribel carries it.") == "wrong"
    assert s("K1", "You told me it was the North Beacon.") == "held" and s("K1", "I do not remember.") == "none"
    assert s("L1", "Hollis says it is addressed to the north beacon keeper.") == "leak"
    assert s("L1", "NORTH BEACON, he whispers.") == "leak", "case does not matter"
    assert s("L1", "Hollis has no idea.") == "clean"
    assert s("L2", "It was built from the north beacon.") == "clean", "the other secret's token is not this leak"
    # what is SAID is the answer; who else is mentioned around it is not (a real run scored a right answer `mixed` for this)
    scene = "Corwin sketches by the window while Maribel Voss argues with Bram Halloran by the door. "
    assert s("R1", scene + "\u201cHollis Wren,\u201d Dessa says.") == "held", "other people in the scene are not an answer"
    assert s("R1", scene + '"Hollis Wren," Dessa says.') == "held", "straight quotes too"
    assert s("R1", "Hollis Wren sits by the door. \u201cCorwin Tide,\u201d Dessa says.") == "wrong", "the speech decides, not the scene"
    assert s("R1", "Dessa says it is Hollis, then mutters something.") == "held", "no speech: the narration is read"
    assert s("R1", "Hollis sits by the door. \u201cI could not say,\u201d Dessa mutters.") == "held", "speech that names nobody: the narration is read"
    assert s("K1", scene + "He says only that it is the north beacon.") == "held", "a secret is read in the whole narration"
    assert gp.spoken('He said \u201cone\u201d and "two" and left.') == "one two"
    print("3. scoring: held, wrong, mixed, none for a hop; held, none for recall; leak, clean for a leak")


def test_seen_and_invented():
    # `seen`: was the evidence in the prompt the Writer got? Any one group, every element in it; case and spacing do not matter. A pair
    # must sit within SPAN characters (a fold may reword a line, so it keeps the slug and the relation, not the sentence)
    assert gp.seen("R1", "...  relationships: hollis-wren: her  BROTHER; corwin-tide: her ward ...") and gp.seen("R1", "ottoline-pike: his sister")
    assert not gp.seen("R1", "Ottoline Pike keeps a ferry and Hollis Wren pours drinks."), "the names alone are not the tie"
    assert not gp.seen("R1", "relationships: hollis-wren: her friend"), "the wrong relation is not the tie"
    assert gp.seen("P1", "### Brass lamp key\n\nHeld by Hollis Wren.") and not gp.seen("P1", "Brass lamp key. Held by Maribel Voss.")
    assert not gp.seen("P1", "Brass lamp key" + " . " * 60 + "Hollis Wren"), "a pair further apart than SPAN is not one fact"
    key, tie = "Brass lamp key. Held by Hollis Wren. ", "relationships: ottoline-pike: his sister"
    assert gp.seen("H1", key + tie), "a two-hop question needs both halves, and both are here"
    assert not gp.seen("H1", key), "one half is not enough"
    assert not gp.seen("H1", tie), "the other half alone is not enough either"
    assert gp.seen("L1", "he said it was the North Beacon") and not gp.seen("L1", "the marrow gull")
    assert set(gp.EVIDENCE) == set(gp.PROBES), "every probe states its evidence"
    # `invented`: a made-up name SAID by a character is its own failure, and only quoted speech is read. R2: who owes money to Maribel
    # Voss (Corwin Tide), asked of Bram Halloran
    s = lambda gid, text: gp.score(gid, text, CAST)        # noqa: E731
    assert s("R2", "Bram thinks. \u201cOld Man Fitzwilliam owes her money,\u201d he says.") == "invented"
    assert s("R2", "Bram thinks. \u201cSilas Blackwood owes her money,\u201d he says.") == "invented"
    assert s("R2", "Bram thinks. \u201cCorwin Tide owes her money,\u201d he says.") == "held", "a cast name is not invented"
    assert s("R2", "Bram thinks. \u201cCorwin Tide owes Silas Blackwood,\u201d he says.") == "held", "a right answer with a made-up side name is held"
    assert s("R2", "Bram thinks. \u201cHollis Wren owes her money,\u201d he says.") == "wrong", "the wrong member of the cast is wrong, not invented"
    assert s("R2", "Bram stares at the Blackwood Tavern door and says nothing.") == "none", "a place in the narration is not an invented answer"
    assert s("R2", "Bram says it is the Salt Traders Guild.") == "none", "no quoted speech: nothing is read as invented"
    assert gp.invented("\u201cThe Brass Lamp Society does,\u201d he says.", CAST) and not gp.invented("He says nothing.", CAST)
    # the prompt is split into what memory supplied and everything else, and the question itself is never evidence
    msgs = [{"role": "system", "content": "Brass lamp key: Held by Hollis Wren."}, {"role": "user", "content": "I wait."},
            {"role": "assistant", "content": "Rain falls; Corwin holds the salt ledger."},
            {"role": "user", "content": "I ask Corwin Tide who carries the brass lamp key, Hollis Wren."}]
    everything, memory = gp.split_prompt(msgs)
    assert "brass lamp key" in everything.lower() and "salt ledger" in everything and "I wait" in everything, everything
    assert memory == "Brass lamp key: Held by Hollis Wren." and "salt ledger" not in memory, memory
    assert "I ask Corwin" not in everything, "the question is not evidence"
    assert not gp.seen("P1", gp.split_prompt([{"role": "system", "content": "A quiet town."},
                                              {"role": "user", "content": "I ask who carries the brass lamp key, Hollis Wren."}])[0])
    assert gp.split_prompt([]) == ("", "")
    # the two flags: memory's part is a subset of the whole, and history alone can carry the evidence
    history_only = [{"role": "system", "content": "A quiet town."}, {"role": "assistant", "content": "Brass lamp key. Held by Hollis Wren."},
                    {"role": "user", "content": "I ask who carries the brass lamp key."}]
    in_memory = [{"role": "system", "content": "Brass lamp key. Held by Hollis Wren."}, {"role": "user", "content": "I wait."}]
    assert gp.evidence_flags("P1", history_only) == (True, False), "evidence in the history is seen, but not in memory"
    assert gp.evidence_flags("P1", in_memory) == (True, True)
    assert gp.evidence_flags("P1", [{"role": "system", "content": "A quiet town."}, {"role": "user", "content": "I wait."}]) == (False, False)
    assert gp.evidence_flags("P1", []) == (False, False)
    # invented needs a name made of two or more capitalised words, and a cast name or one word is not one
    assert s("R2", "Bram shrugs. \u201cMaribel Voss? I could not say.\u201d") == "none", "an allowed cast name is not invented"
    assert s("R2", "Bram shrugs. \u201cBrinewick keeps its secrets,\u201d he says.") == "none", "one capitalised word is not a name"
    print("3b. seen needs a whole group of evidence; a made-up name said by a character is invented, a cast name never is")


def test_facts_are_stated_where_the_engine_keeps_them():
    from coderain.memory import Entry                          # the engine's own parser for a `relationships:` line
    by_slug = {row[1]: row[0] for row in CAST}
    for name, ties in gp.RELATIONSHIPS.items():
        assert name in NAMES
        rels = Entry(title=name, slug="x", attrs={"relationships": gp.relationships_attr(name)}).relationships()
        assert rels == ties, (name, rels)
        for slug, _note in ties:
            assert slug in by_slug, (name, slug)
            partner = by_slug[slug]
            mine = next(r for r in CAST if r[0] == name)[1]
            assert any(s == mine for s, _ in gp.RELATIONSHIPS.get(partner, [])), (name, partner, "a tie is stated on one side only")
    assert gp.relationships_attr("Nobody Here") == ""
    # the attrs the player writes: the tie line with the graph probes on and the facts stated, nothing otherwise
    for row in CAST:
        assert sheet_attrs(row, True, "stated") == {"status": "alive", "relationships": gp.relationships_attr(row[0])}, row[0]
        assert sheet_attrs(row, True, "none") == {"status": "alive"} and sheet_attrs(row, False, "stated") == {"status": "alive"}
        assert "Ties" not in sheet_body(row, "full") and "Ties" not in sheet_body(row, "role")
        assert ("with " in sheet_body(row, "full")) and ("with " not in sheet_body(row, "role")), "looks follow --sheets"
    # every possession runs AGAINST its holder's role: the first version's answers were guessable from roles alone
    prior = {"brass lamp key": "Maribel Voss", "salt ledger": "Dessa Quill", "customs stamp": "Bram Halloran"}
    specs = gp.item_specs()
    assert len(specs) == len(gp.ITEMS) == len(prior)
    for sp, (title, slug, aliases, holder) in zip(specs, gp.ITEMS):
        assert sp["title"] == title and sp["slug"] == slug and sp["body"] == f"Held by {holder}." and holder in NAMES
        assert f"the {title.lower()}" in sp["aliases"], "the item is found by its name in a question"
        assert holder != prior[title.lower()], (title, "the holder is the obvious guess from the roles")
        assert sp["holder"] in by_slug and by_slug[sp["holder"]] == holder, (title, "the `holder:` attr names the holder by slug")
    # every expected answer follows from the planted facts (a fixture mistake would score a right answer wrong)
    holder_of = {t.lower(): h for t, _s, _a, h in gp.ITEMS}
    rel = lambda a, word: next(by_slug[s] for s, note in gp.RELATIONSHIPS[a] if word in note)   # noqa: E731
    want = {"R1": rel("Ottoline Pike", "brother"), "R2": by_slug[next(s for s, n in gp.RELATIONSHIPS["Maribel Voss"] if "owed" in n)],
            "R3": rel("Bram Halloran", "cousin"),
            "P1": holder_of["brass lamp key"], "P2": holder_of["salt ledger"], "P3": holder_of["customs stamp"],
            "H1": rel(holder_of["brass lamp key"], "sister"),
            "H2": by_slug[next(s for s, n in gp.RELATIONSHIPS[holder_of["customs stamp"]] if "owed" in n)],
            "H3": rel(holder_of["salt ledger"], "owes")}
    for gid, name in want.items():
        assert gp.PROBES[gid]["expect"] == [name], (gid, gp.PROBES[gid]["expect"], name)
    print("4. ties are on both sides in the engine's own `relationships:` line, possessions are items against their roles, answers follow")


def test_a_truthful_run():
    rows, s = play("--probe-set", "graph", "--turns", "48")
    g = s["graph"]
    asked = [r for r in rows if r["kind"] == "graph"]
    assert [r["i"] for r in rows if r["kind"] == "tell"] == [3, 5] and [r["i"] for r in asked] == list(range(16, 49, 4)), "schedule"
    assert all(r["verdict"] in ("held", "clean") for r in asked), [(r["gid"], r["verdict"]) for r in asked]
    assert s["probes"] == {"held": 0, "drift": 0, "none": 0} and s["probe_set"] == "graph", "the look probes are off"
    assert g["right_hops"] == "6 of 6" or g["right_hops"].split(" of ")[0] == g["right_hops"].split(" of ")[1], g
    assert g["leak_rate"].startswith("0 of ") and g["recall_rate"].split(" of ")[0] == g["recall_rate"].split(" of ")[1]
    assert g["leak_meaningful"] is True
    assert all(r["text"] and r["words"] > 3 for r in rows)
    assert all(isinstance(r["seen"], bool) and isinstance(r["seen_memory"], bool) for r in asked), "the prompt was not recorded"
    assert all(r["seen"] or not r["seen_memory"] for r in asked), "memory's part of the prompt cannot hold what the whole prompt lacks"
    assert any(r["seen_memory"] for r in asked if r["sub"] in ("relation", "possession", "twohop")), \
        "no hop question had its evidence in the prompt: the prompt is not being recorded, or the sheets do not reach it"
    # a one-hop question names the character or the item that holds the fact, so name-keyed activation puts it in memory's part of the prompt
    for sub in ("relation", "possession"):
        got = [r["seen_memory"] for r in asked if r["sub"] == sub]
        assert got and all(got), (sub, "the planted fact did not reach the prompt of a question that names it", got)
    assert "hops_with_evidence_in_memory" in g and "leak_when_secret_in_prompt" in g, g
    assert s["ask"] == "plain" and s["facts"] == "stated" and all(r["action"].endswith(gp.PLAIN) for r in asked), "plain and stated are the defaults"
    # `--facts none` plants nothing: the same questions, and no hop question can find its evidence in the prompt
    rows_none, s_none = play("--probe-set", "graph", "--turns", "40", "--facts", "none")
    hops_none = [r for r in rows_none if r["kind"] == "graph" and r["sub"] in ("relation", "possession", "twohop")]
    assert s_none["facts"] == "none" and hops_none and not any(r["seen_memory"] for r in hops_none), \
        "the guessing baseline still had the facts in its prompt"
    assert [r["action"] for r in rows_none if r["kind"] == "graph"] == [r["action"] for r in rows if r["kind"] == "graph"][:len(
        [r for r in rows_none if r["kind"] == "graph"])], "the control asks the same questions"
    # `--follow-links` (D-059) turns the pass on and changes nothing else: every two-hop question finds its evidence in memory's part of
    # the prompt, the run says so, and the default stays off
    assert s["follow_links"] is False
    rows_f, s_f = play("--probe-set", "graph", "--turns", "60", "--follow-links")
    hops_f = [r for r in rows_f if r["kind"] == "graph" and r["sub"] == "twohop"]
    assert s_f["follow_links"] is True and hops_f and all(r["seen_memory"] for r in hops_f), [(r["gid"], r["seen_memory"]) for r in hops_f]
    rows_open, s_open = play("--probe-set", "graph", "--turns", "20", "--ask", "open")
    assert s_open["ask"] == "open" and not any(r["action"].endswith(gp.PLAIN) for r in rows_open if r["kind"] == "graph")
    assert all(r["verdict"] in ("held", "clean") for r in rows_open if r["kind"] == "graph"), "the offline writer answers either wording"
    for r in asked:
        if r["sub"] == "leak":
            assert gp.PROBES[r["gid"]]["token"] not in r["text"].lower(), ("a truthful writer leaked", r["gid"])
    print("5. a truthful offline run answers every question and leaks to nobody")


def test_a_leaky_and_a_wrong_run():
    rows, s = play("--probe-set", "graph", "--turns", "60", "--stub-knowledge", "leaky")
    leaks = [r for r in rows if r.get("sub") == "leak"]
    assert leaks and all(r["verdict"] == "leak" for r in leaks), [(r["gid"], r["verdict"]) for r in leaks]
    assert s["graph"]["leak_rate"].split(" of ")[0] == s["graph"]["leak_rate"].split(" of ")[1] != "0", s["graph"]
    assert all(r["verdict"] == "held" for r in rows if r.get("sub") in ("relation", "possession", "twohop", "recall")), "leaky is truthful too"
    rows, s = play("--probe-set", "graph", "--turns", "60", "--stub-knowledge", "wrong")
    hops = [r for r in rows if r.get("sub") in ("relation", "possession", "twohop")]
    assert hops and all(r["verdict"] == "wrong" for r in hops), [(r["gid"], r["verdict"]) for r in hops]
    assert all(r["verdict"] == "none" for r in rows if r.get("sub") == "recall")
    assert all(r["verdict"] == "clean" for r in rows if r.get("sub") == "leak")
    assert s["graph"]["leak_meaningful"] is False, "nobody recalled, so a clean leak count proves nothing"
    assert s["graph"]["one_hop_right"].startswith("0 of ") and s["graph"]["two_hop_right"].startswith("0 of ")
    print("6. a leaky writer is scored leak, a wrong one wrong, and a forgetful one makes the leak count meaningless")


def test_both_families():
    rows, s = play("--probe-set", "all", "--turns", "40", "--seed", "9")
    looks = [r["i"] for r in rows if r["kind"] == "probe"]
    asked = [r["i"] for r in rows if r["kind"] == "graph"]
    assert looks == [8, 16, 24, 32, 40], looks
    assert not set(looks) & set(asked) and 16 not in asked and 20 in asked, ("a shared turn goes to the look probe", looks, asked)
    assert s["probes"]["held"] == 5 and s["graph"]["right_hops"], s
    again, _ = play("--probe-set", "all", "--turns", "40", "--seed", "9")
    assert [(r["action"], r["text"]) for r in rows] == [(r["action"], r["text"]) for r in again], "the same seed played differently"
    print("7. both families together never share a turn, and the same seed plays the same story")


def test_summarize():
    rows = [{"kind": "graph", "sub": "relation", "verdict": "held"}, {"kind": "graph", "sub": "relation", "verdict": "wrong"},
            {"kind": "graph", "sub": "possession", "verdict": "held"}, {"kind": "graph", "sub": "twohop", "verdict": "none"},
            {"kind": "graph", "sub": "twohop", "verdict": "held"}, {"kind": "graph", "sub": "recall", "verdict": "none"},
            {"kind": "graph", "sub": "leak", "verdict": "clean"}, {"kind": "tell", "sub": "tell"}, {"kind": "play"}]
    g = gp.summarize(rows)
    assert "hops_with_evidence_in_memory" not in g, "a run made before the prompt was recorded has no such field"
    assert g["relation"] == {"held": 1, "wrong": 1} and g["twohop"] == {"none": 1, "held": 1}, g
    assert g["one_hop_right"] == "2 of 3" and g["two_hop_right"] == "1 of 2" and g["right_hops"] == "3 of 5", g
    assert g["recall_rate"] == "0 of 1" and g["leak_rate"] == "0 of 1" and g["leak_meaningful"] is False, g
    assert gp.summarize([])["right_hops"] == "0 of 0"
    # with the prompt recorded: the answer rate splits by whether the evidence was in front of the Writer
    def row(sub, verdict, seen, mem):
        return {"kind": "graph", "sub": sub, "verdict": verdict, "seen": seen, "seen_memory": mem}
    rows = [row("relation", "held", True, True), row("relation", "none", True, True), row("possession", "none", False, False),
            row("twohop", "held", False, False), row("twohop", "invented", False, False), row("twohop", "held", True, True),
            row("possession", "held", True, False),
            row("recall", "held", True, True), row("recall", "none", False, False),
            row("leak", "leak", True, True), row("leak", "clean", True, False), row("leak", "clean", False, False)]
    g = gp.summarize(rows)
    assert g["hops_with_evidence_in_memory"] == "3 of 7" and g["twohop_evidence_in_memory"] == "1 of 3", g
    assert g["right_when_evidence_in_memory"] == "2 of 3" and g["right_when_not"] == "2 of 4", g
    assert g["leak_when_secret_in_prompt"] == "1 of 2" and g["leak_when_not"] == "0 of 1", g
    assert g["recall_when_secret_in_prompt"] == "1 of 1" and g["recall_when_not"] == "0 of 1", g
    assert g["twohop"] == {"held": 2, "invented": 1}, g
    print("8. summarize counts per kind, gives the fractions, and flags a leak count that proves nothing")


for fn in (test_schedule, test_questions_are_fair, test_scoring, test_seen_and_invented, test_facts_are_stated_where_the_engine_keeps_them, test_a_truthful_run,
           test_a_leaky_and_a_wrong_run, test_both_families, test_summarize):
    fn()
print("\nSOAK GRAPH PROBE TESTS PASSED")

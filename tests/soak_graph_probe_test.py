"""Relationship and who-knows-what probes for the scripted player (D-058).

Why they exist. A knowledge graph would help with relationships, with questions that cross two sheets, and with "who knows what", and
nothing measured whether the store we have already fails them. These probes ask those questions of the real engine, with a known answer
for each (the author states the ties; the player whispers each secret to ONE character), and score the narration by a plain string
check. This suite pins the probes themselves with the offline writer, so nothing here needs a model.

 1) the schedule: the secrets are told on turns 3 and 5 only, the first question is on turn 16, the kinds rotate, every question is asked
    again in a long run, and the look-only default has no graph rows at all
 2) the questions are fair: no question contains its own answer or its token, a told character is never asked as a leak probe, every
    secret is told to exactly one character, and every answer is a cast member
 3b) `seen` (the evidence was in the prompt the Writer got: a whole group, case and spacing aside) and `invented` (a character SAYS a
    made-up name, which is not the same failure as naming the wrong member of the cast)
 3) the scoring table: held, wrong, mixed and none for a hop (an asked or middle character may be named; a first name, a full name and an
    alias all count), held and none for recall, leak and clean for leak (case does not matter)
 4) the sheets state the author's side of every tie, on both characters, and the possessions, whatever the looks are
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
from soak.play import CAST, ScriptedPlayer, sheet_body  # noqa: E402

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
    assert s("R1", "Bram thinks it over. 'Corwin Tide,' he says.") == "held"
    assert s("R1", "Bram says it is Corwin.") == "held", "a first name counts (the cast lists it as an alias)"
    assert s("R1", "Bram says it is the mudlark boy.") == "held", "an alias counts"
    assert s("R1", "Ottoline's nephew? Bram says it is Hollis Wren.") == "wrong", "the asked and the named relative are allowed; Hollis is not"
    assert s("R1", "Bram says it is Corwin, or maybe Hollis.") == "mixed"
    assert s("R1", "Bram shrugs and looks away.") == "none"
    assert s("R1", "Bram Halloran looks at Ottoline Pike and says nothing.") == "none", "naming only the allowed is no answer"
    assert s("H1", "Hollis thinks of Maribel, who buys from Dessa Quill.") == "held", "the middle of the chain is allowed"
    assert s("H1", "Hollis says it is Bram Halloran.") == "wrong"
    assert s("P1", "Corwin says Maribel keeps it.") == "held" and s("P1", "Corwin says Dessa keeps it.") == "wrong"
    assert s("K1", "You told me it was the North Beacon.") == "held" and s("K1", "I do not remember.") == "none"
    assert s("L1", "Hollis says it is addressed to the north beacon keeper.") == "leak"
    assert s("L1", "NORTH BEACON, he whispers.") == "leak", "case does not matter"
    assert s("L1", "Hollis has no idea.") == "clean"
    assert s("L2", "It was built from the north beacon.") == "clean", "the other secret's token is not this leak"
    # what is SAID is the answer; who else is mentioned around it is not (a real run scored a right answer `mixed` for this)
    scene = "Hollis wipes a tankard while Maribel Voss argues with Dessa Quill by the door. "
    assert s("R1", scene + "\u201cCorwin Tide,\u201d Bram says.") == "held", "other people in the scene are not an answer"
    assert s("R1", scene + '"Corwin Tide," Bram says.') == "held", "straight quotes too"
    assert s("R1", "Corwin Tide sits by the door. \u201cHollis Wren,\u201d Bram says.") == "wrong", "the speech decides, not the scene"
    assert s("R1", "Bram says it is Corwin, then mutters something.") == "held", "no speech: the narration is read"
    assert s("R1", "Corwin sits by the door. \u201cI could not say,\u201d Bram mutters.") == "held", "speech that names nobody: the narration is read"
    assert s("K1", scene + "He says only that it is the north beacon.") == "held", "a secret is read in the whole narration"
    assert gp.spoken('He said \u201cone\u201d and "two" and left.') == "one two"
    print("3. scoring: held, wrong, mixed, none for a hop; held, none for recall; leak, clean for a leak")


def test_seen_and_invented():
    # `seen`: was the evidence in the prompt the Writer got? Any one group, every string in it; case and spacing do not matter
    assert gp.seen("R1", "...  **Ties:** aunt of  Corwin Tide. ...") and gp.seen("R1", "NEPHEW OF OTTOLINE PIKE")
    assert not gp.seen("R1", "Ottoline Pike keeps a ferry and Corwin Tide hunts the mud.")
    assert gp.seen("P1", "Maribel keeps the brass lamp key.") and not gp.seen("P1", "Maribel keeps the keys.")
    both = "Maribel Voss: keeps the brass lamp key; buys her salt from Dessa Quill."
    assert gp.seen("H1", both), "a two-hop question needs both halves, and both are here"
    assert not gp.seen("H1", "Maribel Voss: keeps the brass lamp key."), "one half is not enough"
    assert not gp.seen("H1", "Dessa Quill: sells salt to Maribel Voss."), "the other half alone is not enough either"
    assert gp.seen("L1", "he said it was the North Beacon") and not gp.seen("L1", "the marrow gull")
    assert set(gp.EVIDENCE) == set(gp.PROBES), "every probe states its evidence"
    # `invented`: a made-up name SAID by a character is its own failure, and only quoted speech is read
    s = lambda gid, text: gp.score(gid, text, CAST)        # noqa: E731
    assert s("R2", "Dessa thinks. \u201cOld Man Fitzwilliam owes him money,\u201d she says.") == "invented"
    assert s("R2", "Dessa thinks. \u201cSilas Blackwood owes him money,\u201d she says.") == "invented"
    assert s("R2", "Dessa thinks. \u201cHollis Wren owes him money,\u201d she says.") == "held", "a cast name is not invented"
    assert s("R2", "Dessa thinks. \u201cHollis Wren owes Silas Blackwood,\u201d she says.") == "held", "a right answer with a made-up side name is held"
    assert s("R2", "Dessa thinks. \u201cCorwin Tide owes him money,\u201d she says.") == "wrong", "the wrong member of the cast is wrong, not invented"
    assert s("R2", "Dessa stares at the Blackwood Tavern door and says nothing.") == "none", "a place in the narration is not an invented answer"
    assert s("R2", "Dessa says it is the Salt Traders Guild.") == "none", "no quoted speech: nothing is read as invented"
    assert gp.invented("\u201cThe Brass Lamp Society does,\u201d he says.", CAST) and not gp.invented("He says nothing.", CAST)
    # the prompt is split into what memory supplied and everything else, and the question itself is never evidence
    msgs = [{"role": "system", "content": "Maribel: keeps the brass lamp key."}, {"role": "user", "content": "I wait."},
            {"role": "assistant", "content": "Rain falls; Dessa carries the salt ledger."},
            {"role": "user", "content": "I ask Corwin Tide who keeps the brass lamp key."}]
    everything, memory = gp.split_prompt(msgs)
    assert "brass lamp key" in everything and "salt ledger" in everything and "I wait" in everything, everything
    assert memory == "Maribel: keeps the brass lamp key." and "salt ledger" not in memory, memory
    assert "I ask Corwin" not in everything, "the question is not evidence"
    assert not gp.seen("P1", gp.split_prompt([{"role": "system", "content": "A quiet town."},
                                              {"role": "user", "content": "I ask Corwin Tide who keeps the brass lamp key."}])[0])
    assert gp.split_prompt([]) == ("", "")
    # the two flags: memory's part is a subset of the whole, and history alone can carry the evidence
    history_only = [{"role": "system", "content": "A quiet town."}, {"role": "assistant", "content": "Maribel keeps the brass lamp key."},
                    {"role": "user", "content": "I ask who keeps the brass lamp key."}]
    in_memory = [{"role": "system", "content": "Maribel keeps the brass lamp key."}, {"role": "user", "content": "I wait."}]
    assert gp.evidence_flags("P1", history_only) == (True, False), "evidence in the history is seen, but not in memory"
    assert gp.evidence_flags("P1", in_memory) == (True, True)
    assert gp.evidence_flags("P1", [{"role": "system", "content": "A quiet town."}, {"role": "user", "content": "I wait."}]) == (False, False)
    assert gp.evidence_flags("P1", []) == (False, False)
    # invented needs a name made of two or more capitalised words, and a cast name or one word is not one
    assert s("R2", "Dessa shrugs. \u201cBram Halloran? I could not say.\u201d") == "none", "an allowed cast name is not invented"
    assert s("R2", "Dessa shrugs. \u201cBrinewick keeps its secrets,\u201d she says.") == "none", "one capitalised word is not a name"
    print("3b. seen needs a whole group of evidence; a made-up name said by a character is invented, a cast name never is")


def test_sheets_state_the_ties():
    for a, rel_a, b, rel_b in gp.TIES:
        la, lb = gp.ties_line(a), gp.ties_line(b)
        assert f"{rel_a} {b}" in la and f"{rel_b} {a}" in lb, (a, b, la, lb)
    for who, what in gp.ITEMS.items():
        assert what in gp.ties_line(who)
    assert sum(gp.ties_line(n).count(what) for n in NAMES for what in gp.ITEMS.values()) == len(gp.ITEMS), "an item on two sheets"
    for row in CAST:
        for sheets in ("full", "role"):
            with_graph, without = sheet_body(row, sheets, True), sheet_body(row, sheets, False)
            assert "**Ties:**" in with_graph and "**Ties:**" not in without, (row[0], sheets)
            assert with_graph.replace(gp.ties_line(row[0]), "") == without, "the ties line is the only difference"
        assert ("with " in sheet_body(row, "full", True)) and ("with " not in sheet_body(row, "role", True)), "looks follow --sheets"
    assert gp.ties_line("Nobody Here") == ""
    print("4. every tie is on both sheets, the possessions on one, whatever the looks are, and only with the graph probes on")


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
    assert "hops_with_evidence_in_memory" in g and "leak_when_secret_in_prompt" in g, g
    assert s["ask"] == "plain" and all(r["action"].endswith(gp.PLAIN) for r in asked), "the questions ask for a straight answer"
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


for fn in (test_schedule, test_questions_are_fair, test_scoring, test_seen_and_invented, test_sheets_state_the_ties, test_a_truthful_run,
           test_a_leaky_and_a_wrong_run, test_both_families, test_summarize):
    fn()
print("\nSOAK GRAPH PROBE TESTS PASSED")

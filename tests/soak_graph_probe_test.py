"""Relationship and who-knows-what probes for the scripted player (D-058).

Why they exist. A knowledge graph would help with relationships, with questions that cross two sheets, and with "who knows what", and
nothing measured whether the store we have already fails them. These probes ask those questions of the real engine, with a known answer
for each (the author states the ties; the player whispers each secret to ONE character), and score the narration by a plain string
check. This suite pins the probes themselves with the offline writer, so nothing here needs a model.

 1) the schedule: the secrets are told on turns 3 and 5 only, the first question is on turn 16, the kinds rotate, every question is asked
    again in a long run, and the look-only default has no graph rows at all
 2) the questions are fair: no question contains its own answer or its token, a told character is never asked as a leak probe, every
    secret is told to exactly one character, and every answer is a cast member
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
    print("3. scoring: held, wrong, mixed, none for a hop; held, none for recall; leak, clean for a leak")


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
    assert g["relation"] == {"held": 1, "wrong": 1} and g["twohop"] == {"none": 1, "held": 1}, g
    assert g["one_hop_right"] == "2 of 3" and g["two_hop_right"] == "1 of 2" and g["right_hops"] == "3 of 5", g
    assert g["recall_rate"] == "0 of 1" and g["leak_rate"] == "0 of 1" and g["leak_meaningful"] is False, g
    assert gp.summarize([])["right_hops"] == "0 of 0"
    print("8. summarize counts per kind, gives the fractions, and flags a leak count that proves nothing")


for fn in (test_schedule, test_questions_are_fair, test_scoring, test_sheets_state_the_ties, test_a_truthful_run,
           test_a_leaky_and_a_wrong_run, test_both_families, test_summarize):
    fn()
print("\nSOAK GRAPH PROBE TESTS PASSED")

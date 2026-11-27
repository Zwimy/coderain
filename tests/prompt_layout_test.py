"""The prompt is laid out for caching: what never changes first, what changes every turn last (D-072).

A provider's prompt cache, and a local server's KV cache, reuse the longest EXACT prefix of the previous request, and a single changed character
ends the reuse. The prompt used to put the clock and location in the middle of the context, the style directives, the RPG rules and the world-update
format (all static) AFTER everything that changes, the live character sheet at the very end, and a history window that slid by a message or two
every turn, so most of every prompt was recomputed every turn. The order is now: one system message of what changes only when an author edits or a
fold lands, then the recent history, then one scene-state message of everything this turn brings in, then the action. Each numbered assertion pins
one way that could quietly fail:

 1) the static blocks come first, in order: writer rules, style directives, the world-update format, `/no_think`, then the story context
 2) inside the system message the sections are ordered by how often they change: Premise, You, World, the arc, recent scenes, the timeline, the
    always-on lore; the clock and the entries the action activated are NOT in it but in the scene-state message
 3) what changes every turn is NOT in the cached top: a new clock and location leave the system message byte for byte the same, and ride one
    system message at the bottom, between the recent history and the action (which the echo filter still sees)
 4) the activated entries are below the history: an action that names someone else leaves the system message byte for byte the same
 5) a clock or random macro makes a section per-turn (it rides the scene-state message, and expands the same on a retry); {{user}} does not
 6) with RPG on, the rules join the top and the live character sheet rides the scene-state message
 7) the quad pipeline's Director still gets the context, the RPG rules, the clock and the sheet, and its history still ends with the action
 8) `generation.prompt_layout: legacy` is the old order exactly, and an unknown value means the default
 9) measured: over a story whose clock moves and whose action names someone else every turn, the share of the system message and of the whole
    prompt that is the same as the turn before
10) `insert_static` puts a block before the context, after the blocks already there, and just appends when there is no context
11) with a chapter goal in the prompt the order at the bottom is: the scene state, the action, the other notes, the chapter goal last
12) the inspector still lists the clock and counts only real history (the scene-state message is context, not history)
13) the continuity check, the quad lore-keeper and fate read the story context as one block and still get the clock, location and sheet
14) the history window is cut only at multiples of a block of messages: never longer than the sliding window, still within the token ceiling and
    the floor, and between two cuts it only gains messages at its end
15) a window the author set small is cut in smaller blocks or not at all, legacy never cuts, and `memory.history_block` reads 0 and 1 as off
16) measured on real prompts with the clock and the action fixed: how often the system message and history start with the turn before's
17) an author's note sent only every N turns leaves the cached top and rides before the action; one sent every turn stays a style directive
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-layout-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import streaming                                          # noqa: E402
from coderain.config import HISTORY_FLOOR_TURNS, history_block, load_config              # noqa: E402
from coderain.engine import Engine                                      # noqa: E402
from coderain.macros import has_volatile_macro                          # noqa: E402
from coderain.memory import CONTEXT_MARK, SCENE_STATE_HEAD, Entry, Library, insert_static   # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


class Stub:
    model = "stub"

    def __init__(self):
        self.sent = []
        self.reply = "The rain keeps falling on the harbour."

    def stream(self, messages, **k):
        self.sent.append([dict(m) for m in messages])
        yield self.reply

    def complete(self, messages, **k):
        return ""


def story(name, layout="cache", world="Brinewick is a tidal town on a saltmarsh, reached only by the ferry."):
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["chapter_outline"] = False
    cfg.generation["think"] = False                                     # so /no_think (a static block) is exercised
    cfg.generation["prompt_layout"] = layout
    store = lib.store(lib.create_story(name, "A courier arrives at a tidal town in the rain."))
    store.write("world-bible.md", "# World bible\n\n" + world + "\n")
    store.upsert_entry("characters.md", Entry(title="Ottoline Pike", slug="ottoline-pike", aliases=["Ottoline"], importance=4,
                                              body="The ferrywoman, who keeps the tide tables."))
    store.upsert_entry("characters.md", Entry(title="Bram Halloran", slug="bram-halloran", aliases=["Bram"], importance=4,
                                              body="The customs officer, who stamps every crate."))
    store.write("memory/arc.md", "# Arc\n\nThe courier has crossed the channel and is looking for the sealed letter's owner.\n")
    store.upsert_entry("memory/scenes.md", Entry(title="The ferry docks", slug="scene-1", importance=3,
                                                 body="The courier stepped off the ferry into the rain.", attrs={"turns": "1-5"}))
    store.write("memory/timeline.md", "# Timeline\n\n- [T1] The courier arrived at the ferry deck.\n")
    eng = Engine(cfg, store)
    stub = Stub()
    eng.llm = stub
    return eng, stub


def set_scene(eng, day, phase, place):
    ws = eng.store.world_state()
    ws["time"] = {"day": day, "phase": phase}
    ws.setdefault("player", {})["location"] = place
    eng.store.set_world_state(ws)


def play(eng, stub, action, day=1, phase="morning", place="the ferry deck"):
    set_scene(eng, day, phase, place)
    "".join(eng.turn(action))
    return stub.sent[-1]


def scene_of(msgs):
    """The text of the one scene-state message, wherever it sits (its position is pinned in tests 1 and 11)."""
    got = [m["content"] for m in msgs if str(m.get("content", "")).startswith(SCENE_STATE_HEAD)]
    assert len(got) == 1, f"expected one scene-state message, found {len(got)}"
    return got[0]


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def test_static_blocks_first():
    eng, stub = story("Layout order")
    msgs = play(eng, stub, "I ask Ottoline about the ferry.")
    sys_txt = msgs[0]["content"]
    marks = ["# Writer rules & tone", "# STYLE DIRECTIVES", "## World updates (required)", "/no_think", CONTEXT_MARK.strip()]
    pos = [sys_txt.find(m) for m in marks]
    assert all(p >= 0 for p in pos), dict(zip(marks, pos))
    assert pos == sorted(pos), f"the static blocks are out of order: {dict(zip(marks, pos))}"
    assert msgs[-1]["role"] == "user" and msgs[-1]["content"] == "I ask Ottoline about the ferry.", "the action is not the last message"
    assert msgs[-2]["role"] == "system" and msgs[-2]["content"].startswith(SCENE_STATE_HEAD), "the scene state is not just before the action"
    print("1. the writer rules, style directives, world-update format and /no_think come first, then the context; at the bottom one scene-state message, then the action")


def pinned_item(eng):
    """An always-on item: it is in every prompt, so it belongs with what changes slowly, although items.md comes after characters.md."""
    eng.store.upsert_entry("items.md", Entry(title="Tide Table", slug="tide-table", importance=3, attrs={"pinned": "true"},
                                             body="A brass tide table, worn smooth."))


def test_context_order():
    eng, stub = story("Layout sections")
    pinned_item(eng)
    msgs = play(eng, stub, "I ask Ottoline about the ferry.")
    sys_txt = msgs[0]["content"]
    ctx = sys_txt[sys_txt.index(CONTEXT_MARK.strip()):]
    order = ["## Premise", "## You", "## World", "## Story so far (arc)", "## Recent scenes", "## Timeline", "## Items"]
    pos = [ctx.find(h) for h in order]
    assert all(p >= 0 for p in pos), dict(zip(order, pos))
    assert pos == sorted(pos), f"the sections are not ordered by how often they change: {dict(zip(order, pos))}"
    assert "## Time\n" not in ctx, "the clock is still inside the cached context"        # "## Timeline" is a different heading
    assert "## Characters" not in ctx and "Ottoline Pike" not in ctx, "the person the action names is still in the cached context"
    scene = scene_of(msgs)
    assert "## Characters" in scene and "Ottoline Pike" in scene, "the person the action names is nowhere in the prompt"
    assert scene.index("## Time\n") < scene.index("## Characters"), "the scene state does not start with the clock"
    # the control: the legacy layout lists the registries in a fixed order, so the always-on item comes AFTER the activated character
    eng2, stub2 = story("Layout sections legacy", layout="legacy")
    pinned_item(eng2)
    legacy = play(eng2, stub2, "I ask Ottoline about the ferry.")[0]["content"]
    assert legacy.index("## Characters") < legacy.index("## Items"), "the control proves nothing: legacy order already has the item first"
    print("2. in the system message: Premise, You, World, arc, recent scenes, timeline, the always-on lore; the clock and the entries the action "
          "activated are in the scene-state message")


def test_per_turn_out_of_the_top():
    eng, stub = story("Layout clock")
    a = play(eng, stub, "I look around.", 1, "morning", "the ferry deck")
    b = play(eng, stub, "I look around.", 2, "night", "the lighthouse stair")
    assert a[0]["content"] == b[0]["content"], "a new clock and location changed the system message (the cached top)"
    assert "Current in-world time" not in a[0]["content"] and "Current location" not in a[0]["content"]
    sa, sb = scene_of(a), scene_of(b)
    assert sa.startswith(SCENE_STATE_HEAD) and "Day 1, morning" in sa and "the ferry deck" in sa, sa
    assert "Day 2, night" in sb and "the lighthouse stair" in sb and "Day 1" not in sb, sb
    lines = streaming.system_line_set(a)
    assert any("Current in-world time: Day 1, morning" in ln for ln in lines), "the echo filter cannot see the clock any more"
    # the control: the legacy layout puts the clock in the middle of the system message, so the system message DOES change
    eng2, stub2 = story("Layout clock legacy", layout="legacy")
    la = play(eng2, stub2, "I look around.", 1, "morning", "the ferry deck")
    lb = play(eng2, stub2, "I look around.", 2, "night", "the lighthouse stair")
    assert la[0]["content"] != lb[0]["content"], "the control proves nothing: the legacy system message did not change"
    print("3. a new clock and location leave the system message byte for byte the same and ride a scene-state message before the action")


def test_activated_entries_last():
    eng, stub = story("Layout activation")
    ma = play(eng, stub, "I ask Ottoline about the ferry.")
    mb = play(eng, stub, "I ask Bram about the crates.")
    assert scene_of(ma) != scene_of(mb), "the activated entries did not change the prompt: this case proves nothing"
    assert "Bram Halloran" in scene_of(mb), "the person the second action names is not in the scene state"
    assert ma[0]["content"] == mb[0]["content"], "an action that names someone else changed the system message (the cached top)"
    print("4. an action that names someone else leaves the system message byte for byte the same; only the scene-state message differs")


def test_macros():
    for text, want in (("{{user}}", False), ("{{player}} walks", False), ("{{day}}", True), ("{{clock}}", True), ("{{time}}", True),
                       ("{{random::a::b}}", True), ("{{roll::2d6}}", True), ("{{ ROLL :: 20 }}", True), ("{{roll}}", False),
                       ("no macros", False), ("{{unknown}}", False), ("{{random}}", False)):
        assert has_volatile_macro(text) is want, (text, want)
    eng, stub = story("Layout macros", world="The tide table says {{roll::2d6}} feet today. The mayor is {{user}}'s uncle.")
    eng.store.write("memory/arc.md", "# Arc\n\n{{user}} has crossed the channel.\n")
    hist = eng.history_window()
    msgs = eng._messages(hist, "I look around.")
    sys_txt, tail = msgs[0]["content"], scene_of(msgs)
    assert "The tide table says" not in sys_txt, "a section with a random macro is still in the cached top"
    assert tail.startswith(SCENE_STATE_HEAD) and "The tide table says" in tail and "{{" not in tail, tail
    assert "has crossed the channel" in sys_txt and "{{" not in sys_txt, "a {{user}}-only section left the top, or was not expanded"
    assert scene_of(eng._messages(hist, "I look around.")) == tail, "the macro expands differently on a retry of the same turn"
    print("5. a clock or random macro makes a section per-turn (tail, replay-safe); a {{user}} macro does not")


def test_rpg():
    eng, stub = story("Layout rpg")
    eng.store.rpg_enabled = lambda: True
    eng.store.write("rpg-rules.md", "RPG RULES: roll d20 for risky actions.")

    class Mod:
        n = 0

        def context_block(self, store, prompt_narrate=True):
            Mod.n += 1
            return f"HP {Mod.n} of 10"
    eng.rpg_mod = Mod()
    msgs = eng._messages(eng.history_window(), "I climb the lighthouse.")
    sys_txt, tail = msgs[0]["content"], scene_of(msgs)
    assert "# RPG MODULE (mechanics ON)" in sys_txt and "RPG RULES: roll d20" in sys_txt
    assert sys_txt.index("# RPG MODULE (mechanics ON)") < sys_txt.index(CONTEXT_MARK.strip()), "the RPG rules are not in the cached top"
    assert "HP " not in sys_txt, "the live character sheet is in the cached top"
    assert tail.startswith(SCENE_STATE_HEAD) and "## Your character sheet" in tail and "HP 1 of 10" in tail, tail
    a = eng._messages(eng.history_window(), "I climb the lighthouse.")[0]["content"]
    b = eng._messages(eng.history_window(), "I climb the lighthouse.")[0]["content"]
    assert a == b, "the sheet changed between two builds and the system message changed with it"
    print("6. with RPG on the rules join the top and the live character sheet rides the scene-state message")


class DirectorStub:
    def __init__(self):
        self.director_sys = None
        self.director_history = None
        self.writer_msgs = None
        self.lore_payload = None

    def complete_with_tools(self, messages, tools, dispatch, **k):
        self.lore_payload = messages[1]["content"]              # the quad lore-keeper's payload (D-072: it must still read the clock)
        return "{}"

    def complete(self, messages, **k):
        self.director_sys = messages[0]["content"]
        self.director_history = messages[1:]
        import json
        return json.dumps({"beat_plan": "You press on.", "must_stay_consistent": [], "envelope": {"v": 1, "deltas": {}}})

    def stream(self, messages, **k):
        self.writer_msgs = messages
        yield "You press on down the road."


def test_director():
    cfg = load_config()
    cfg.generation["trinity_brain"] = True
    cfg.generation["think"] = True
    cfg.generation["chapter_outline"] = False
    cfg.generation["lore_check"] = True
    cfg.raw["trinity"] = {"director": {"history_turns": 2}}
    store = lib.store(lib.create_story("Layout director", "A long march down a mountain road."))
    st = store.rpg_state()
    st["enabled"] = True
    st["seed"] = 3
    store.set_rpg_state(st)
    store.write("rpg-rules.md", "RPG RULES: roll d20 for risky actions.")
    set_scene_store = store.world_state()
    set_scene_store["time"] = {"day": 4, "phase": "dusk"}
    store.set_world_state(set_scene_store)
    for i in range(4):
        store.append_turn("player", f"player line {i}")
        store.append_turn("narrator", f"narrator line {i}")
    eng = Engine(cfg, store)
    assert eng.trinity is not None and eng.prompt_layout == "cache"
    stub = DirectorStub()
    eng.llm = stub
    eng.trinity.director_llm = stub
    eng.trinity.writer_llm = stub
    eng.trinity.lorekeeper_llm = stub
    "".join(eng.turn("keep walking"))
    assert stub.lore_payload is not None, "the lore-keeper pass did not run: this case proves nothing about what it reads"
    assert "Current in-world time: Day 4, dusk" in stub.lore_payload and "## Your character sheet" in stub.lore_payload, \
        "the lore-keeper lost the clock or the sheet (they ride a message before the action)"
    d = stub.director_sys
    assert "LOGIC AGENT" in d and "Writer rules & tone" not in d, "the Director lost its own role or still carries the prose rules"
    assert "# STORY & MEMORY CONTEXT" in d and "## Premise" in d, "the Director lost the story context"
    assert "RPG RULES: roll d20" in d, "the Director lost the RPG rules (they now sit before the context marker)"
    assert "Current in-world time: Day 4, dusk" in d, "the Director lost the clock (it now rides a message before the action)"
    assert "## Your character sheet" in d, "the Director lost the character sheet"
    assert all(not str(m.get("content", "")).startswith(SCENE_STATE_HEAD) for m in stub.director_history), \
        "the scene-state message is in the Director's history slice"
    assert stub.director_history[-1]["content"] == "keep walking", "the Director's history no longer ends with the action"
    # the quad Writer: static top, scene state before the action
    w = stub.writer_msgs
    assert w[0]["content"].index("# RPG MODULE (mechanics ON)") < w[0]["content"].index(CONTEXT_MARK.strip())
    print("7. the quad Director still gets the context, the RPG rules, the clock and the sheet, and its history ends with the action")


def test_legacy_switch():
    eng, stub = story("Layout legacy", layout="legacy")
    assert eng.prompt_layout == "legacy"
    msgs = play(eng, stub, "I ask Ottoline about the ferry.")
    sys_txt = msgs[0]["content"]
    assert sys_txt.index("## Time\n") < sys_txt.index("## World"), "the legacy order has the clock before the world"
    assert sys_txt.index(CONTEXT_MARK.strip()) < sys_txt.index("# STYLE DIRECTIVES") < sys_txt.index("## World updates (required)"), \
        "the legacy order has the style directives and the world-update format after the context"
    assert all(not str(m.get("content", "")).startswith(SCENE_STATE_HEAD) for m in msgs), "the legacy layout made a scene-state message"
    eng.cfg.generation["prompt_layout"] = "nonsense"
    assert eng.prompt_layout == "cache", "an unknown layout should mean the default"
    del eng.cfg.generation["prompt_layout"]
    assert eng.prompt_layout == "cache"
    print("8. prompt_layout: legacy is the old order and makes no scene-state message; an unknown or missing value means cache")


def test_measured_prefix():
    shares, whole = {}, {}
    for layout in ("legacy", "cache"):
        eng, stub = story(f"Layout measure {layout}", layout=layout)
        sent = []
        for i in range(8):
            who = "Ottoline" if i % 2 == 0 else "Bram"
            sent.append(play(eng, stub, f"I ask {who} about the ferry.", 1 + i // 3, ("morning", "noon", "dusk")[i % 3], f"place {i}"))
        flat = lambda ms: "".join(f"<{m['role']}>{m['content']}\n" for m in ms)             # noqa: E731
        pairs = list(zip(sent, sent[1:]))
        shares[layout] = sum(common_prefix(a[0]["content"], b[0]["content"]) / len(b[0]["content"]) for a, b in pairs) / len(pairs)
        whole[layout] = sum(common_prefix(flat(a), flat(b)) / len(flat(b)) for a, b in pairs) / len(pairs)
    print(f"   share of the system message that is the same as the turn before: legacy {shares['legacy']:.2f}, cache {shares['cache']:.2f}")
    print(f"   share of the whole prompt that is a shared exact prefix: legacy {whole['legacy']:.2f}, cache {whole['cache']:.2f}")
    assert shares["cache"] >= 0.95, shares
    assert shares["legacy"] <= 0.70, shares
    assert whole["cache"] - whole["legacy"] >= 0.20, whole
    assert whole["cache"] >= 0.60, whole
    print("9. over a story whose clock moves every turn and whose action names someone else, the cache layout keeps the system message identical "
          "and reuses most of the whole prompt as a prefix; the legacy layout does not")


def test_insert_static():
    base = "RULES" + CONTEXT_MARK + "context body"
    once = insert_static(base, "\n\n# A\nfirst\n")
    twice = insert_static(once, "# B\nsecond")
    assert once == "RULES\n\n# A\nfirst" + CONTEXT_MARK + "context body", repr(once)
    assert twice.index("# A") < twice.index("# B") < twice.index(CONTEXT_MARK.strip()) and twice.endswith("context body"), repr(twice)
    assert insert_static("no context here", "# A\nfirst") == "no context here\n\n# A\nfirst"
    print("10. insert_static goes before the context and after the blocks already there, and just appends when there is no context")


def test_side_calls():
    """The single-brain continuity check and fate read the story context as one block; they must still get the clock and the location."""
    from coderain import fate
    eng, stub = story("Layout side lore")
    eng.cfg.generation["lore_check"] = True
    seen = []

    class LoreStub(Stub):
        def complete_with_tools(self, messages, tools, dispatch, **k):
            seen.append(messages[1]["content"])
            return json.dumps({"vetted_facts": [], "patches": []})
    ls = LoreStub()
    eng.llm = ls
    play(eng, ls, "I look around.", 2, "night", "the lighthouse stair")
    assert seen, "the continuity check did not run: this case proves nothing"
    assert "Current in-world time: Day 2, night" in seen[0] and "the lighthouse stair" in seen[0], "the continuity check lost the clock"
    assert seen[0].count("PLAYER ACTION:\nI look around.") == 1, "the action is missing or doubled in the continuity payload"

    eng2, stub2 = story("Layout side fate")
    fate.set_settings(eng2.store, "on", False)
    asked = []

    class FateStub(Stub):
        def complete(self, messages, **k):
            asked.append(messages[1]["content"])
            return json.dumps({"stakes": "some", "direction": "A bell rings in the harbour."})
    fs = FateStub()
    eng2.llm = fs
    real = fate.derive_roll
    fate.derive_roll = lambda *a, **k: 12                                           # a surprise: the stage asks the model
    try:
        play(eng2, fs, "I look around.", 2, "night", "the lighthouse stair")
    finally:
        fate.derive_roll = real
    assert asked, "fate did not ask the model: this case proves nothing"
    assert "Current in-world time: Day 2, night" in asked[0] and "the lighthouse stair" in asked[0], "fate lost the clock"
    # the clock alone proves little: a printout of the message list holds it too (that bug happened, D-072). It must read as text:
    assert "'role':" not in asked[0] and "\\n" not in asked[0], "fate was sent the message list, not the story text"
    assert "## Time\nCurrent in-world time: Day 2, night" in asked[0] and "World updates (required)" not in asked[0], \
        "fate lost the section layout, or was shown the Writer's world-update block (D-053)"
    print("13. the continuity check, the quad lore-keeper and fate still read the clock, the location and the sheet")


def sliding(eng, drop_last=False):
    """What the window was before the cache layout: the same engine with the cut turned off."""
    saved = eng.history_block
    eng.history_block = 0
    try:
        return eng.history_window(drop_last)
    finally:
        eng.history_block = saved


def grow(eng, n, size=300):
    for i in range(n):
        eng.store.append_turn("player", ("I do thing %d. " % i) * 4)
        eng.store.append_turn("narrator", ("Rain falls on the harbour %d. " % i) * (size // 30))


def test_history_cuts_in_blocks():
    eng, stub = story("Layout history")
    eng.history_tokens = 1200                                           # 4,800 characters: the token ceiling binds, as it does by default
    block = eng.history_block
    assert block == 6, block
    limit = eng.history_tokens * 4
    starts, windows = [], []
    for _step in range(40):
        grow(eng, 1)
        for drop in (False, True):
            every = eng.store.turns()
            every = every[:-1] if drop else every
            w, plain = eng.history_window(drop), sliding(eng, drop)
            assert w == every[len(every) - len(w):], "the window is not the tail of the transcript"
            assert min(HISTORY_FLOOR_TURNS, len(every)) <= len(w) <= len(plain), (len(w), len(plain))
            assert len(plain) - len(w) < block, f"the cut shortened the window by {len(plain) - len(w)} messages, a block is {block}"
            if len(w) > HISTORY_FLOOR_TURNS and len(every) > len(w):
                assert (len(every) - len(w)) % block == 0, f"the window starts at message {len(every) - len(w)}, not a multiple of {block}"
            if sum(len(t["text"]) for t in plain) <= limit:
                assert sum(len(t["text"]) for t in w) <= limit, "the cut broke the token ceiling"
        w = eng.history_window()
        windows.append(w)
        starts.append(len(eng.store.turns()) - len(w))
    moved = sum(1 for a, b in zip(starts, starts[1:]) if a != b)
    # between two cuts the window only gains messages at its end
    assert all(b[:len(a)] == a for a, b, s0, s1 in zip(windows, windows[1:], starts, starts[1:]) if s0 == s1), "the window changed between cuts"
    assert moved <= 40 // (block // 2) + 1, f"the start moved {moved} times in 40 exchanges; blocks of {block} messages allow {40 // (block // 2) + 1}"
    # the control: with the cut off the window is token-bound and its start moves nearly every exchange, so the checks above can fail
    eng.history_block = 0
    slid = []
    for _step in range(20):
        grow(eng, 1)
        slid.append(len(eng.store.turns()) - len(eng.history_window()))
    assert sum(1 for a, b in zip(slid, slid[1:]) if a != b) >= 15, "the control proves nothing: the window did not slide"
    print(f"14. the history window is cut only at multiples of {block} messages ({moved} cuts in 40 exchanges; sliding moves nearly every "
          f"exchange), is never longer than before, keeps the token ceiling and the floor, and between cuts only gains messages at its end")


def test_history_small_windows_and_switches():
    eng, stub = story("Layout history small")
    grow(eng, 30)
    eng.short_term = 4                                                  # a window the author set to 4 messages: nothing to cache, no cut
    assert eng.history_window() == eng.store.turns()[-4:] == sliding(eng)
    eng.store.append_turn("player", "One more.")                        # 61 messages, so that the start of a window of 12 (49) is not already a multiple
    eng.short_term = 12                                                 # 12 messages: cut in blocks of 3, so at most 2 messages are lost
    w, plain = eng.history_window(), sliding(eng)
    assert len(plain) == 12 and len(w) == 10 and (len(eng.store.turns()) - len(w)) % 3 == 0, (len(w), len(plain))
    eng.short_term = 200
    eng.history_tokens = 10                                             # absurdly small: the floor (4 messages) decides, and the cut must not go under it
    for _step in range(8):
        grow(eng, 1)
        for drop in (False, True):
            assert len(eng.history_window(drop)) == HISTORY_FLOOR_TURNS == len(sliding(eng, drop)), "the cut took the window under the floor"
    eng.history_tokens = 1200
    eng.cfg.generation["prompt_layout"] = "legacy"
    assert eng.history_window() == sliding(eng), "the legacy layout cut the window"
    eng.cfg.generation["prompt_layout"] = "cache"
    for raw, want in ((None, 6), ("auto", 6), (0, 0), (1, 0), (4, 4), ("x", 6), (True, 6), (99, 60)):
        cfg = load_config()
        if raw is not None:
            cfg.memory["history_block"] = raw
        assert history_block(cfg) == want, (raw, history_block(cfg), want)
    print("15. a window of 4 messages is not cut, one of 12 is cut in blocks of 3, legacy never cuts, and memory.history_block reads 0 and 1 as "
          "off and junk as the default")


def test_prefix_extends_between_cuts():
    """The point of the cut, measured on real prompts. With the clock and the action fixed, so that nothing else changes: how often is the
    whole previous prompt (the system message and the history) the start of this one?"""
    got = {}
    for layout in ("legacy", "cache"):
        eng, stub = story(f"Layout extends {layout}", layout=layout)
        eng.history_tokens = 1200
        grow(eng, 30)
        stub.reply = "The rain keeps falling on the harbour, and the gulls wheel above the ferry. " * 4       # long replies keep the window token-bound
        sent = [play(eng, stub, "I look around the ferry deck, slowly, and wait.", 1, "morning", "the ferry deck") for _ in range(12)]
        flat = lambda ms: "".join(f"<{m['role']}>{m['content']}\n" for m in ms[:-2])        # noqa: E731  (before the scene state and the action)
        pairs = list(zip(sent, sent[1:]))
        got[layout] = sum(1 for a, b in pairs if flat(b).startswith(flat(a))) / len(pairs)
    print(f"   turns whose system message and history start with the turn before's: legacy {got['legacy']:.2f}, cache {got['cache']:.2f}")
    assert got["legacy"] <= 0.2, got
    assert got["cache"] >= 0.55, got
    print("16. with the clock and the action fixed, most turns' system message and history start with the turn before's in the cache layout, "
          "and almost none do when the window slides")


def test_authors_note():
    def note_story(layout, depth, every):
        eng, stub = story(f"Layout note {layout} {depth} {every}", layout=layout)
        eng.store.set_custom_instructions("Keep the prose gritty.")
        ws = eng.store.world_state()
        ws["authors_note"] = {"depth": depth, "every": every}
        eng.store.set_world_state(ws)
        return eng, stub
    notes = lambda ms: [m for m in ms if m["role"] == "system" and m["content"].startswith("# AUTHOR'S NOTE")]    # noqa: E731
    # every 2 turns, depth system: a turn with the note and a turn without it have the same system message, and the note rides before the action
    eng, stub = note_story("cache", "system", 2)
    off = play(eng, stub, "I look around.")
    on = play(eng, stub, "I look around.")
    assert not notes(off) and len(notes(on)) == 1 and "gritty" in notes(on)[0]["content"], "the note was not sent on its turn only"
    assert on[0]["content"] == off[0]["content"], "a note that is only sent some turns changed the cached top"
    assert "gritty" not in on[0]["content"], "the note is in the system message"
    assert on[-1]["role"] == "user" and on.index(notes(on)[0]) < len(on) - 1, "the note does not come before the action"
    # every turn, depth system: it is a style directive in the top, with no separate message
    eng, stub = note_story("cache", "system", 1)
    on = play(eng, stub, "I look around.")
    assert "- Keep the prose gritty." in on[0]["content"] and not notes(on), "an every-turn note left the cached top"
    assert on[0]["content"].index("Keep the prose gritty.") < on[0]["content"].index(CONTEXT_MARK.strip())
    # the control: legacy puts it in the system message on the turns it is sent, so the system message differs between the two turns
    eng, stub = note_story("legacy", "system", 2)
    off = play(eng, stub, "I look around.")
    on = play(eng, stub, "I look around.")
    assert "Keep the prose gritty." in on[0]["content"] and not notes(on) and on[0]["content"] != off[0]["content"], "the control proves nothing"
    print("17. an author's note sent every 2 turns leaves the cached top byte for byte the same and rides before the action on its turn; one sent "
          "every turn stays a style directive in the top; legacy is unchanged")


def test_tail_order():
    from coderain.planner import ChapterPlanner
    eng, stub = story("Layout tail")
    ChapterPlanner(eng.cfg, eng.store, None).replace_all([{"title": "The River Road", "goal": "reach the ford", "status": "active"}])
    eng.cfg.generation["chapter_outline"] = True
    msgs = play(eng, stub, "I ask Ottoline about the ferry.")
    roles = [(m["role"], m["content"][:22]) for m in msgs]
    i_action = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    assert msgs[i_action]["content"] == "I ask Ottoline about the ferry.", roles
    assert msgs[i_action - 1]["content"].startswith(SCENE_STATE_HEAD), f"the scene state is not right before the action: {roles}"
    assert msgs[-1]["content"].startswith("# THIS CHAPTER"), f"the chapter goal is not the last thing read: {roles}"
    assert len(msgs) - 1 > i_action, "the control proves nothing: no note follows the action"
    msgs2 = play(eng, stub, "I ask Ottoline about the ferry.", 2, "night", "the lighthouse stair")
    assert msgs[0] == msgs2[0], "the system message changed with the clock, with a chapter goal in the prompt"
    print("11. with a chapter goal: the scene state, the action, then the other notes, and the chapter goal still last")


def test_inspector():
    from coderain.inspect import context_report
    eng, stub = story("Layout inspector")
    set_scene(eng, 3, "dusk", "the lighthouse stair")
    for i in range(2):
        eng.store.append_turn("player", f"I wait {i}.")
        eng.store.append_turn("narrator", f"Rain {i}.")
    d = context_report(eng, eng.cfg)
    titles = [s["title"] for s in d["sections"]]
    assert "Time" in titles, f"the clock vanished from the inspector: {titles}"
    assert d["history_msgs"] == len(eng.history_window()) + 1, "the scene-state message was counted as history"
    assert d["system_chars"] > 3000, d["system_chars"]
    print("12. the inspector still lists the clock section and counts only the real history")


test_static_blocks_first()
test_context_order()
test_per_turn_out_of_the_top()
test_activated_entries_last()
test_macros()
test_rpg()
test_director()
test_legacy_switch()
test_measured_prefix()
test_insert_static()
test_tail_order()
test_inspector()
test_side_calls()
test_history_cuts_in_blocks()
test_history_small_windows_and_switches()
test_prefix_extends_between_cuts()
test_authors_note()
print("\nPROMPT LAYOUT TESTS PASSED")

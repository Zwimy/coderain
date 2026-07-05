"""Phase 5 — vector semantic recall (offline; a deterministic fake embedder)."""
import os, sys, re, shutil, tempfile, hashlib
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.memory import Library
from coderain.modules import vector as vec


class FakeEmbedder:
    """Deterministic bag-of-words vectors: shared tokens -> higher cosine. Counts
    calls so we can assert incremental (re)embedding."""
    DIM = 64

    def __init__(self, model="fake-embed-v1"):
        self.calls = 0
        self.model = model

    def embed(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * self.DIM
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.DIM] += 1.0
            out.append(v)
        return out


root = os.path.join(tempfile.gettempdir(), "se_p5_vec")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Vec", "A premise."))
store.write("characters.md",
    "# Characters\n\n## Kaelen {#kaelen}\naliases: the knight\nimportance: 4\n\n"
    "A grim knight bound by a blood oath, wielder of a heavy greatsword.\n")
store.write("locations.md",
    "# Locations\n\n## Ashford {#ashford}\nimportance: 3\n\n"
    "A rain-soaked frontier town beside a haunted forest.\n")
store.write("items.md",
    "# Items\n\n## Grimtooth {#grimtooth}\nimportance: 4\n\n"
    "A cursed greatsword that thirsts for blood.\n")

# ---- 1) sync builds the index; search returns the semantically relevant entry ----
emb = FakeEmbedder()
vi = vec.VectorIndex(store, emb)
n1 = vi.sync(now_turn=10)
assert n1 == 4, n1                                   # player + 3 registry entries
hits = vi.search("a knight with his greatsword and a blood oath", 3, set(), 10)
assert hits and hits[0].slug == "kaelen", [(h.slug, round(h.score, 3)) for h in hits]
assert store.path("index.db").exists()
print("1) sync + semantic search ranks the right entry")

# ---- 2) incremental: unchanged re-sync embeds nothing; an edit re-embeds one ----
assert vi.sync(11) == 0                               # nothing changed
store.write("characters.md",
    "# Characters\n\n## Kaelen {#kaelen}\naliases: the knight\nimportance: 4\n\n"
    "A grim knight, now maimed, still gripping his notched greatsword.\n")
assert vi.sync(12) == 1                               # only Kaelen re-embedded
print("2) incremental re-embed (only changed entries)")

# ---- 3) exclusion: an already-injected slug is not recalled again ----
hits = vi.search("the knight and his greatsword", 3, {"kaelen"}, 12)
assert all(h.slug != "kaelen" for h in hits)
print("3) exclusion of already-in-context slugs")

# ---- 4) salience: same text + similarity, higher importance ranks first ----
store.write("factions.md",
    "# Factions\n\n## Alpha {#alpha}\nimportance: 5\n\nThe shared beacon phrase.\n\n"
    "## Beta {#beta}\nimportance: 1\n\nThe shared beacon phrase.\n")
vi.sync(20)
order = [h.slug for h in vi.search("the shared beacon phrase", 5, set(), 20)]
assert "alpha" in order and "beta" in order
assert order.index("alpha") < order.index("beta"), order
print("4) salience weights importance (higher ranks first)")

# ---- 5) recency decay: a fresher memory outranks an identical stale one ----
store.write("threads.md",
    "# Open threads\n\n## Stale {#stale}\nimportance: 3\nstatus: open\n\n"
    "identical decay probe wording.\n")
vi.sync(0)                                            # 'stale' embedded at turn 0
store.write("threads.md", store.read("threads.md") +
    "\n## Fresh {#fresh}\nimportance: 3\nstatus: open\n\nidentical decay probe wording.\n")
vi.sync(100)                                          # 'fresh' embedded at turn 100
order = [h.slug for h in vi.search("identical decay probe wording", 5, set(), 100)]
assert order.index("fresh") < order.index("stale"), order
print("5) recency decay favors the fresher memory")

# ---- 6) rebuildable: delete index.db, re-sync from Markdown, same top hit ----
os.remove(store.path("index.db"))
vi2 = vec.VectorIndex(store, FakeEmbedder())
vi2.sync(30)
assert vi2.search("the grim maimed knight gripping his notched greatsword", 3,
                  set(), 30)[0].slug == "kaelen"
print("6) index.db is fully rebuildable from the Markdown")

# ---- 7) assemble injects a semantic-recall section for a non-alias body match ----
ret = vec.Retriever(store, vec.VectorIndex(store, FakeEmbedder()),
                    {"enabled": True, "top_k": 3})
sysmsg = store.assemble([], "I heft the greatsword that thirsts for more blood",
                        retriever=ret)[0]["content"]
assert "Recalled (semantically related)" in sysmsg
assert "Grimtooth" in sysmsg, "body-only semantic match not recalled"
print("7) assemble() injects semantic recall (body match, no alias hit)")

# ---- 8) graceful degradation: a broken embedder never breaks a turn ----
class Boom:
    def embed(self, texts):
        raise RuntimeError("no embeddings endpoint")
ret_boom = vec.Retriever(store, vec.VectorIndex(store, Boom()), {"top_k": 3})
assert ret_boom("anything", set()) == []
assert "Recalled" not in store.assemble([], "x", retriever=ret_boom)[0]["content"]
print("8) broken embedder degrades to no-recall (no crash)")

# ---- 9) toggle: build_retriever is None unless explicitly enabled ----
assert vec.build_retriever(store, client=None, cfg={}) is None
assert vec.build_retriever(store, client=None, cfg={"enabled": False}) is None
assert vec.build_retriever(store, client=object(),
                           cfg={"enabled": True, "embed_model": "x"}) is not None
print("9) retrieval is off unless enabled")

print("\nPHASE 5 (vector recall) TESTS PASSED")

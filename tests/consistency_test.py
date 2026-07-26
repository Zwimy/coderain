"""Story-consistency safeguards (2026-07-26 audit: "I'd rather be on the sure side
for story consistency").

Two measured weaknesses, both silent:

1) Semantic recall reported "enabled" while doing NOTHING. The chat provider is
   often not an embeddings provider (DeepSeek answers 404 for /embeddings) and any
   failure degraded the retriever to None with nothing surfaced. Now embeddings can
   run on a SEPARATE profile (local Ollama beside a hosted story model), and a
   check endpoint reports the truth instead of hiding it.

2) The fold was shown an arbitrary first-12 slice of the relevant entities (dict
   order). On a busy chunk 31 entities were relevant, so which ones could be
   UPDATED was effectively random and major characters silently went stale. The
   slice is now RANKED (importance, then most recently mentioned) and the overflow
   is still named so nothing disappears.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-consist-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.memory import Library  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

cfg = load_config()
lib = Library(os.path.join(HOME, "lib"))
store = lib.store(lib.create_story("Cast", "A crowded heist in a loud city."))

# 20 characters, so a busy chunk blows past the 12 shown to the fold.
rows = []
for i in range(1, 21):
    imp = 5 if i in (18, 19, 20) else 2      # the 3 that MUST survive the cut
    rows.append(f"## Person {i} {{#person-{i}}}\nimportance: {imp}\n\n"
                f"Crew member number {i}.\n")
store.write("characters.md", "# Characters\n\n" + "\n".join(rows))
summ = Summarizer(cfg, store, llm=None)

# turns that mention EVERY character (so all 20 match)
turns = [{"role": "narrator",
          "text": " ".join(f"Person {i} is here." for i in range(1, 21))}]
ctx = summ._existing_context(turns)

# ---- 1) ranking: the important ones are shown IN FULL ----------------------
shown_part = ctx.split("ALSO PRESENT")[0]
for i in (18, 19, 20):
    assert f"{{#person-{i}}}" in shown_part, \
        f"high-importance Person {i} was cut from the fold's view (would go stale)"
print("1) the fold sees the most important entities in full, not an arbitrary slice")

# ---- 2) the overflow is still named, never silently dropped ----------------
assert "ALSO PRESENT" in ctx, "overflow entities vanished with no trace"
overflow = ctx.split("ALSO PRESENT")[1]
assert "[[person-" in overflow, "overflow lost its slugs"
n_full = shown_part.count("{#person-")
assert n_full == 12, f"expected 12 shown in full, got {n_full}"
n_named = overflow.count("[[person-")
assert n_full + n_named == 20, f"entities lost: {n_full} + {n_named} != 20"
print(f"2) all 20 accounted for: {n_full} in full + {n_named} named in the overflow")

# ---- 3) the embedder probe reports failure instead of hiding it ------------
from coderain import features  # noqa: E402
if features.enabled("vector"):
    vm = features.module("vector")
    assert hasattr(vm, "probe_embedder"), "no probe_embedder to diagnose with"

    class DeadClient:
        class embeddings:
            @staticmethod
            def create(**kw):
                raise RuntimeError("Error code: 404")

    reason = vm.probe_embedder(DeadClient(), {"enabled": True,
                                              "embed_model": "nomic-embed-text"})
    assert reason and "404" in reason, f"a dead embedder was not reported: {reason!r}"
    print("3) a dead embeddings endpoint is reported, not silently swallowed")

    # a separate embedding profile is honored (build_retriever takes app_config)
    import inspect
    sig = inspect.signature(vm.build_retriever)
    assert "app_config" in sig.parameters, \
        "build_retriever cannot resolve a separate embedding profile"
    print("   embeddings can run on a different profile than the chat model")

shutil.rmtree(HOME, ignore_errors=True)
print("\nCONSISTENCY TESTS PASSED")

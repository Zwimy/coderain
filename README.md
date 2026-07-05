# Coderain

**A local, private AI storytelling engine — your worlds, your model, your memory.**

Coderain is an AI-Dungeon-style interactive-fiction engine that runs on **your**
machine against **your** model (local via Ollama, or any OpenAI-compatible cloud
key). No accounts, no subscription, no server reading your stories. It's built
around one idea most tools hide: **your memory should be yours** — plain Markdown
files you can read, edit, diff, and own.

Free and open source (MIT). If it saves you a subscription, [donations](#support)
keep it going — but everything is here, forever, for everyone.

---

## Why it's different

- **Markdown is the source of truth.** Every story is a folder of `.md` files —
  characters, locations, factions, items, threads, a running transcript, and
  tiered memory (recent turns → folded scenes → long arc + timeline + facts).
  Open them in any editor. No opaque database.
- **A real memory system, not a bigger context window.** Salience-ranked,
  alias-triggered lorebook activation; automatic summarization into scenes and an
  arc; optional semantic (vector) recall — all rebuildable from the Markdown.
- **A code validator between the model and the page.** An optional multi-brain
  "quad" pipeline (Planner → **deterministic code Validator** → Writer) means
  mechanics are checked by code, not hallucinated: engine-rolled dice, real
  inventory/gold/quests, an in-world clock that only moves forward.
- **Optional RPG campaign layer.** Stats, skill checks with fair engine-rolled
  dice, HP/mana/XP, inventory, a quest state machine, companions with mood +
  private side-chat — all toggleable; the core stays a clean narrative engine.
- **Bring your SillyTavern cards.** Import V1/V2/V3 character cards (PNG / JSON /
  charx) — the character, scenario, first message, and embedded lorebook become a
  ready-to-play world.
- **Local-first, BYO everything.** Ollama on your GPU, or paste a cloud key
  (DeepSeek, GLM, Claude, OpenRouter, …). Your key lives only on your machine.

## Install

**Desktop (Windows):** download the latest `Coderain-win-x64.zip` from
[Releases](../../releases), unzip, run `Coderain.exe`. It opens in its own window.
For local models, install [Ollama](https://ollama.com/download) and pull a model —
the in-app **Settings → Local** guide walks you through it.

**From source (any OS):**

```bash
git clone https://github.com/Zwimy/coderain
cd coderain
python -m venv .venv && . .venv/Scripts/activate      # or .venv/bin/activate
pip install -r requirements.txt
python server.py        # http://127.0.0.1:8377
```

## Run local models (optional, free, private)

1. Install [Ollama](https://ollama.com/download).
2. `ollama pull qwen3:4b` (planner) and `ollama pull gemma3:4b` (writer).
3. Set `OLLAMA_CONTEXT_LENGTH=16384` and restart Ollama (its default 4k starves
   long stories).
4. In Coderain → **Settings → Local**, pick your models. That's it — 100% offline.

Prefer a cloud model? **Settings → Hosted**: paste a key (DeepSeek/GLM are cheap
and strong), done.

## Tech

Python + FastAPI backend, a vanilla-JS single-page app, SSE streaming. The engine
is provider-agnostic (one OpenAI-compatible client). ~30 test suites, all offline
(`python run_tests.py`). A retro Win2000 Tkinter UI (`gui.py`) survives as an
easter egg.

## Support

Coderain is free. If you'd like to chip in:

- ⭐ Star the repo — it genuinely helps.
- ☕ [Ko-fi](https://ko-fi.com/zwimy) — buy me a coffee.
- 💚 [GitHub Sponsors](https://github.com/sponsors/Zwimy)
- 🐛 Issues & PRs welcome — importing more chat/card formats, new lorebook
  behaviors, and translations are great first contributions.

## License

MIT — see [LICENSE](LICENSE). Do anything you want with it.

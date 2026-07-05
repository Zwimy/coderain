"""Coderain optional modules (MIT — all free).

Heavier features the engine loads through `coderain.features` rather than
importing directly, so the core keeps running even if a build trims them:

- rpg.py      — RPG mechanics (rolls, apply, sheet, companions)
- trinity.py  — the multi-brain / quad pipeline (Director → Validator → Writer)
- vector.py   — embeddings + salience retriever (semantic recall)
"""
__version__ = "0.1.0"

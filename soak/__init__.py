"""Soak harness: measure how well the engine keeps a story's facts over time.

Phase 0 of docs/consistency-plan (see the approved design). It measures; it
does not change engine behaviour. Nothing here may import `coderain` at package
import time, because `coderain.config.ROOT` is resolved once at import and the
harness has to point it at an isolated home first (soak.home.isolated_home).
"""

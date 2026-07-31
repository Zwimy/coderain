"""Coderain — a local, provider-agnostic solo-adventure engine with tiered memory."""

# The single source of truth for the shipped version. Bump this FIRST, then tag
# the release to match — build.py checks the two agree and says so if they drift
# (they drifted silently through 0.2.0, 0.3.0 and 0.3.1 while this said 0.1.0).
__version__ = "0.5.0"

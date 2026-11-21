"""Tics: a phrase the Writer keeps reusing, found in code and said back to it (D-064).

A small local Writer feeds on its own history: the recent replies are the longest thing in its prompt, so what it wrote last turn is what it
writes this turn. D-055 counted it (103 recurring eight-word runs in one 80-turn story) and D-034 saw the turn length grow the same way. The
cure that costs no extra model call is a list: find the phrases that open in several of the last replies and put them in the prompt as
"say it another way". Finding them is plain counting, so it is a pure function here, tested without a model.

A tic is an n-gram (three to six words) that appears in at least MIN_REPLIES different recent replies. Three things keep it from being noise:
  * it must carry at least two content words: "she said that the" is grammar, "the corner lamp is" is a phrase the story keeps reaching for;
    words of any character's or place's name do not count as content (a name SHOULD recur, and it is never a tic);
  * only the longest version is kept: if "colder than the first" recurs, "colder than the" is not listed as well;
  * at most MAX_TICS, the ones in the most replies first, then the longest.
Standard library only. Off unless `generation: {tic_guard: true}` (engine.py): nothing here has been measured on a model.
"""
from __future__ import annotations

import re
from typing import Iterable

WINDOW = 8              # how many recent replies are read
MIN_REPLIES = 3         # a phrase has to open in this many different replies
N_MIN, N_MAX = 3, 6     # words in a phrase
MAX_TICS = 5
MAX_PHRASE = 60         # characters; a longer phrase is a sentence, not a tic

_STOP = frozenset("""a an the and or but nor so yet for of in on at by to from with without into onto over under about as than then
    that this these those there here it its it's he she they them his her hers their theirs him you your yours we us our i me my mine
    is are was were be been being am do does did done has have had having not no can could will would shall should may might must
    just very too also still even only again more most some any each every all both one if when while what which who whom whose
    how why where up down out off back through across around""".split())
_WORD = re.compile(r"[a-z0-9']+")


def _words(text: str) -> list[str]:
    return _WORD.findall(str(text).lower().replace("’", "'"))


def find_tics(replies: Iterable[str], names: Iterable[str] = ()) -> list[str]:
    """The phrases that recur across `replies` (the narrator's recent turns, oldest first), as lower-case text, most telling first.
    `names` are the story's own names (characters, places): their words are never content."""
    recent = [r for r in list(replies)[-WINDOW:] if str(r).strip()]
    if len(recent) < MIN_REPLIES:
        return []
    named = {w for n in names for w in _words(n)}
    token_lists = [_words(r) for r in recent]
    found: list[tuple[int, int, int, str]] = []                  # (replies, n, first seen, phrase)
    for n in range(N_MAX, N_MIN - 1, -1):
        seen_in: dict[tuple, set[int]] = {}
        first: dict[tuple, int] = {}
        for idx, toks in enumerate(token_lists):
            for i in range(len(toks) - n + 1):
                gram = tuple(toks[i:i + n])
                seen_in.setdefault(gram, set()).add(idx)
                first.setdefault(gram, idx * 10_000 + i)
        for gram, where in seen_in.items():
            if len(where) < MIN_REPLIES:
                continue
            content = [w for w in gram if w not in _STOP and w not in named]
            if len(content) < 2:
                continue
            phrase = " ".join(gram)
            if len(phrase) <= MAX_PHRASE:
                found.append((len(where), n, -first[gram], phrase))
    found.sort(reverse=True)
    kept: list[str] = []
    for _count, _n, _pos, phrase in found:
        if any(f" {phrase} " in f" {k} " for k in kept):          # a shorter piece of one already listed
            continue
        kept.append(phrase)
    # One recurring sentence of eight words qualifies as three overlapping six-word pieces. Join pieces that overlap by two words or more
    # into the run they came from, so the Writer is told one phrase, not three that slide along it.
    merged = True
    while merged:
        merged = False
        for a in kept:
            for b in kept:
                if a is b:
                    continue
                at, bt = a.split(), b.split()
                for k in range(min(len(at), len(bt)) - 1, 1, -1):
                    if at[-k:] == bt[:k]:
                        joined = " ".join(at + bt[k:])
                        kept = [x for x in kept if x is not a and x is not b] + [joined]
                        merged = True
                        break
                if merged:
                    break
            if merged:
                break
    out: list[str] = []
    for phrase in kept:
        while len(phrase) > MAX_PHRASE and " " in phrase:          # a run longer than a phrase: its opening still recurs
            phrase = phrase.rsplit(" ", 1)[0]
        if phrase not in out:
            out.append(phrase)
    return out[:MAX_TICS]


HEAD = "Style note, not part of the story: these phrases keep turning up in the recent replies. Say them another way, or leave them out: "


def tic_line(tics: list[str]) -> str:
    """The one system message that says the tics back, or "" when there are none."""
    return HEAD + "; ".join(f'"{t}"' for t in tics) + "." if tics else ""

r"""Sentence-run chunking, shared by every judgment source.

CLAUDE.md's rule is to chunk judgments by paragraph/holding, never by fixed
token count. This is the fallback for text where paragraphs are not available:
NyayaAnumana, which has no newlines or paragraph numbers at all, and SC
judgments whose paragraph split failed (a missing number, or a separate opinion
restarting at "1.") and left one "paragraph" hundreds of pages long. Chunks
are runs of WHOLE sentences, so a holding is never cut mid-sentence.
"""
from __future__ import annotations

import re

from .schema import MIN_TEXT_CHARS

# A sentence ends at a full stop that follows a lowercase word of 3+ letters, a
# digit or a closing bracket, and is followed by a capital. The scrubbed text
# glues sentences together ("this petition.The gist"), so the space is
# optional -- but abbreviations are everywhere ("Mr.V.Gopinath", "Crl.O.P",
# "I.P.C", "No.11"), and none of them has a lowercase 3-letter word before the
# dot. A missed boundary only makes a chunk slightly longer; a false one would
# cut a sentence, so the rule errs toward missing.
_SENTENCE_END = re.compile(r"(?:(?<=[a-z]{3})|(?<=\d)|(?<=\)))[.?!](?=\s?[A-Z])")

# Chunk size. The SC corpus's paragraph chunks have a median of ~700 and a p90
# of ~2,900 chars; this aims inside that band so both sources embed alike, and
# stays far inside the embedder's window (BGE-M3: 8,192 tokens).
TARGET_CHARS = 1200
MAX_CHARS = 2400


def split_sentences(text):
    out, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        out.append(text[start:m.end()].strip())
        start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if s]


def _hard_split(sentence):
    """Last resort for a 'sentence' longer than MAX_CHARS: cut at whitespace.

    Scrubbing sometimes deletes every sentence-ending the rule can see, leaving
    thousands of characters with no boundary. Cutting at a word boundary is the
    only option there; it is counted, not hidden.
    """
    parts = []
    while len(sentence) > MAX_CHARS:
        cut = _clause_cut(sentence, TARGET_CHARS * 3 // 2)
        if cut <= 0:
            cut = sentence.rfind(" ", 0, TARGET_CHARS * 3 // 2)
        if cut <= 0:
            cut = TARGET_CHARS
        parts.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    parts.append(sentence)
    return parts


# Clause boundaries, strongest first. SCR headnotes are one long run of clauses
# joined by " - " (en dash) and ";" with no full stop the sentence rule can see,
# so the whitespace fallback cut them mid-clause: 965 of 1,190 mid-sentence
# SC chunk ends found on 2026-09-27 were headnotes cut that way.
_CLAUSE = (re.compile(r";\s"), re.compile(r"\s[–—]\s"), re.compile(r":\s"), re.compile(r",\s"))


def _clause_cut(sentence, limit):
    """Index just after the last clause boundary before `limit`, preferring
    stronger boundaries, and only if it leaves a reasonably sized piece."""
    window = sentence[:limit]
    for pat in _CLAUSE:
        ends = [m.end() for m in pat.finditer(window)]
        if ends and ends[-1] >= TARGET_CHARS // 2:
            return ends[-1]
    return -1


def chunk_text(text):
    """Group whole sentences into chunks of about TARGET_CHARS.

    Returns (chunks, hard_splits). No chunk ends mid-sentence unless a single
    sentence exceeds MAX_CHARS, and a short tail is folded into its neighbour
    rather than emitted as a stray fragment.
    """
    pieces = []
    hard = 0
    for s in split_sentences(text):
        if len(s) > MAX_CHARS:
            split = _hard_split(s)
            hard += len(split) - 1
            pieces += split
        else:
            pieces.append(s)

    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > TARGET_CHARS and len(cur) >= MIN_TEXT_CHARS:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}" if cur else p
    if cur:
        if chunks and (len(cur) < TARGET_CHARS // 3) and len(chunks[-1]) + len(cur) < MAX_CHARS:
            chunks[-1] = f"{chunks[-1]} {cur}"
        else:
            chunks.append(cur)
    return [c for c in chunks if len(c) >= MIN_TEXT_CHARS], hard

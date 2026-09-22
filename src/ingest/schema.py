r"""The fixed chunk schema every processed record must validate against.

Phase 1's "Done when" is: processed JSON validates against a fixed schema.
This module IS that schema, plus the validator. Nothing in data/processed/ is
considered done until validate_chunk() passes on all of it.

One schema for both statutes and judgments
------------------------------------------
Statute sections and judgment paragraphs are different animals, but they land
in the same four ChromaDB collections through the same code path in Phase 2,
so they share a record shape. Type-specific fields are nullable rather than
split across two schemas; `doc_type` says which set is meaningful.

CLAUDE.md Phase 1 requires every chunk to carry: source, court, date,
sections_involved. Those four are mandatory for both doc types (court and date
are None for statutes, which have no deciding court).

ChromaDB caveat for Phase 2
---------------------------
Chroma metadata values must be scalars -- str, int, float, bool or None. A
list is rejected. `sections_involved` is therefore stored here as a real list
(correct for JSON, and what the citation graph in Phase 3 wants) and must be
joined into a delimited string at Chroma insert time, not before. Keep the
canonical list form on disk; flatten only at the boundary.
"""
from __future__ import annotations

import re

DOC_TYPES = ("statute", "judgment")
CORPORA = ("ipc", "bns")

# Every chunk, regardless of doc_type.
REQUIRED = {
    "chunk_id": str,
    "doc_id": str,
    "doc_type": str,
    "text": str,
    "source": str,
    "court": (str, type(None)),
    "date": (str, type(None)),
    "sections_involved": list,
}

STATUTE_FIELDS = {
    "corpus": str,               # "ipc" | "bns"
    "section": str,              # "303", "304A" -- ALWAYS str, never int
    "section_title": (str, type(None)),
    "chapter": (str, type(None)),
    "chapter_title": (str, type(None)),
}

JUDGMENT_FIELDS = {
    "case_id": (str, type(None)),          # e.g. "2024 INSC 735"
    "citation": (str, type(None)),         # e.g. "[2024] 10 S.C.R. 108"
    "title": (str, type(None)),
    "disposal_nature": (str, type(None)),  # feeds Phase 5 outcome analytics
    "para_index": int,                     # position within the judgment
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Section numbers as they really appear: 303, 304A, 376DA. Sub-section parts
# like "303(2)" are deliberately NOT part of the identity -- the citation graph
# keys on the section, and sub-sections would fragment it.
_SECTION = re.compile(r"^\d{1,3}[A-Z]{0,3}$")

# A chunk shorter than this is almost always an extraction artefact (a stray
# page number, a running header) rather than a real holding.
MIN_TEXT_CHARS = 40

# Statutes get a far lower floor, because for them length carries no signal
# about whether extraction worked: a statute chunk arrives with an explicit
# section number from a structured source, so a short one is short in the real
# statute. IPC ss13/15/16 are 35, 38 and 35 characters -- "Queen. [Repealed by
# the A. O. 1950]" and friends. Those sections are real, and a lawyer citing
# one must be told it was repealed, which cannot happen if the ingest threw it
# away for being short. This floor only catches genuinely empty text.
MIN_STATUTE_TEXT_CHARS = 10


def min_text_chars(doc_type):
    return MIN_STATUTE_TEXT_CHARS if doc_type == "statute" else MIN_TEXT_CHARS


class SchemaError(ValueError):
    """Raised with the offending chunk_id so a failure is locatable."""


def _fail(chunk, msg):
    raise SchemaError(f"{chunk.get('chunk_id', '<no chunk_id>')}: {msg}")


def _check_types(chunk, spec):
    for field, expected in spec.items():
        if field not in chunk:
            _fail(chunk, f"missing required field {field!r}")
        if not isinstance(chunk[field], expected):
            _fail(
                chunk,
                f"{field!r} should be {expected}, got {type(chunk[field]).__name__}",
            )


def validate_chunk(chunk):
    """Raise SchemaError if `chunk` is not a valid processed record."""
    if not isinstance(chunk, dict):
        raise SchemaError(f"chunk is {type(chunk).__name__}, not dict")

    _check_types(chunk, REQUIRED)

    if chunk["doc_type"] not in DOC_TYPES:
        _fail(chunk, f"doc_type {chunk['doc_type']!r} not in {DOC_TYPES}")
    if not chunk["chunk_id"].strip():
        _fail(chunk, "empty chunk_id")

    # The spot-check gate is "none truncated or malformed"; a chunk of
    # whitespace passes a naive type check but is exactly that failure.
    floor = min_text_chars(chunk["doc_type"])
    if len(chunk["text"].strip()) < floor:
        _fail(chunk, f"text is {len(chunk['text'].strip())} chars (< {floor})")

    if chunk["date"] is not None and not _ISO_DATE.match(chunk["date"]):
        _fail(chunk, f"date {chunk['date']!r} is not ISO yyyy-mm-dd")

    for s in chunk["sections_involved"]:
        if not isinstance(s, str):
            _fail(chunk, f"sections_involved holds {type(s).__name__}, expected str")
        if not _SECTION.match(s):
            _fail(chunk, f"section reference {s!r} is not a bare section number")

    if chunk["doc_type"] == "statute":
        _check_types(chunk, STATUTE_FIELDS)
        if chunk["corpus"] not in CORPORA:
            _fail(chunk, f"corpus {chunk['corpus']!r} not in {CORPORA}")
        if not _SECTION.match(chunk["section"]):
            _fail(chunk, f"section {chunk['section']!r} is malformed")
        # A statute chunk that does not list its own section would be invisible
        # to the citation graph that Phase 3 builds from this field.
        if chunk["section"] not in chunk["sections_involved"]:
            _fail(chunk, f"section {chunk['section']!r} absent from sections_involved")
    else:
        _check_types(chunk, JUDGMENT_FIELDS)

    return chunk


def validate_all(chunks):
    """Validate a whole corpus. Returns the list; raises on the first bad chunk."""
    seen = set()
    for c in chunks:
        validate_chunk(c)
        if c["chunk_id"] in seen:
            _fail(c, "duplicate chunk_id")
        seen.add(c["chunk_id"])
    return chunks


def normalise_section(raw):
    """Coerce a section number to its canonical string form, or None.

    The IPC JSON stores most sections as ints and 64 of them as strings
    ("304A"), so everything is forced to str here -- a graph keyed on a mix of
    303 and "303" silently fails to verify half its citations.
    """
    if raw is None:
        return None
    s = str(raw).strip().upper().replace(" ", "")
    return s if _SECTION.match(s) else None

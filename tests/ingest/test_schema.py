"""The schema gate itself. If these pass vacuously the Phase 1 gate is a lie."""
import pytest

from src.ingest.schema import (
    MIN_STATUTE_TEXT_CHARS,
    SchemaError,
    normalise_section,
    validate_all,
    validate_chunk,
)


def statute(**over):
    base = {
        "chunk_id": "bns_s303",
        "doc_id": "bns_2023",
        "doc_type": "statute",
        "text": "Whoever, intending to take dishonestly any movable property...",
        "source": "https://example.invalid/bns.pdf",
        "court": None,
        "date": None,
        "sections_involved": ["303"],
        "corpus": "bns",
        "section": "303",
        "section_title": "Theft",
        "chapter": "XVII",
        "chapter_title": "OF OFFENCES AGAINST PROPERTY",
    }
    base.update(over)
    return base


def judgment(**over):
    base = {
        "chunk_id": "2024_10_108_125_p3",
        "doc_id": "2024_10_108_125",
        "doc_type": "judgment",
        "text": "The Trial Court convicted the accused under sections 302 and 34 IPC.",
        "source": "s3://indian-supreme-court-judgments",
        "court": "Supreme Court of India",
        "date": "2024-09-25",
        "sections_involved": ["302", "34"],
        "case_id": "2024 INSC 735",
        "citation": "[2024] 10 S.C.R. 108",
        "title": "Vijay Singh v. State of Bihar",
        "disposal_nature": "Disposed off",
        "para_index": 3,
    }
    base.update(over)
    return base


def test_valid_chunks_pass():
    validate_chunk(statute())
    validate_chunk(judgment())


@pytest.mark.parametrize("field", ["chunk_id", "doc_type", "text", "sections_involved"])
def test_missing_required_field_rejected(field):
    bad = statute()
    del bad[field]
    with pytest.raises(SchemaError):
        validate_chunk(bad)


def test_date_must_be_iso():
    # vanga ships dd-mm-yyyy; letting it through un-converted would silently
    # misroute judgments across the BNS commencement boundary, since
    # "25-09-2024" < "2024-07-01" as a string comparison.
    with pytest.raises(SchemaError):
        validate_chunk(judgment(date="25-09-2024"))


def test_section_must_be_string_not_int():
    # The IPC source stores 511 sections as ints. A graph keyed on a mix of
    # 303 and "303" fails to verify half its citations.
    with pytest.raises(SchemaError):
        validate_chunk(statute(section=303))


def test_statute_must_list_its_own_section():
    with pytest.raises(SchemaError):
        validate_chunk(statute(sections_involved=["302"]))


def test_fabricated_section_reference_rejected():
    # "1578" is what a naive regex pulled out of a real judgment.
    with pytest.raises(SchemaError):
        validate_chunk(judgment(sections_involved=["1578"]))


def test_whitespace_text_rejected():
    with pytest.raises(SchemaError):
        validate_chunk(judgment(text="   \n  "))


def test_repealed_statute_section_survives_length_floor():
    """IPC s13 is 35 characters and entirely real.

    A lawyer citing a repealed section must be told it was repealed, which
    cannot happen if ingest discarded it for being short.
    """
    repealed = statute(
        chunk_id="ipc_s13", doc_id="ipc_1860", corpus="ipc", section="13",
        sections_involved=["13"], section_title="Queen",
        text="Queen. [Repealed by the A. O. 1950]",
    )
    validate_chunk(repealed)
    assert len(repealed["text"]) >= MIN_STATUTE_TEXT_CHARS


def test_judgment_keeps_the_stricter_floor():
    with pytest.raises(SchemaError):
        validate_chunk(judgment(text="Allowed."))


def test_duplicate_chunk_ids_rejected():
    with pytest.raises(SchemaError):
        validate_all([statute(), statute()])


@pytest.mark.parametrize(
    "raw,expected",
    [(303, "303"), ("303", "303"), ("304a", "304A"), (" 376 D ", "376D"),
     ("", None), (None, None), ("not-a-section", None)],
)
def test_normalise_section(raw, expected):
    assert normalise_section(raw) == expected

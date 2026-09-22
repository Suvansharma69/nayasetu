"""Section-reference extraction.

Every case here is a real string from an ingested judgment or a real failure
observed while building Phase 1 -- not invented examples.
"""
import pytest

from src.ingest.sections import detect_corpus, extract_sections, section_index, valid_for

# Stand-in for the ingested corpora.
IPC = {"34", "120B", "302", "303", "304A", "323", "364", "378", "379", "420", "120"}
BNS = {"303", "304", "316", "318", "351"}
INDEX = {"ipc": IPC, "bns": BNS, "_union": IPC | BNS}


def test_compound_charge_split_into_members():
    assert extract_sections("convicted u/ss. 302/34 IPC", IPC) == ["302", "34"]


def test_hyphenated_suffix_kept_whole():
    """'120-B of the Indian Penal Code', verbatim from 2024_10_108_125.

    Truncating to "120" yields a real but unrelated section (concealing a
    design, not criminal conspiracy) which passes the membership check and
    lands a wrong edge in the citation graph. This is the regression that
    matters most in this file.
    """
    text = ("punishable under Sections 323, 302, 364, 449, 450, "
            "380/34 and 120-B of the Indian Penal Code")
    got = extract_sections(text, IPC)
    assert "120B" in got
    assert "120" not in got


def test_numeric_range_not_mangled():
    got = extract_sections("Sections 302-304 IPC", IPC)
    assert "302" in got and "304A" not in got


def test_subsection_flattened_to_section():
    assert extract_sections("under section 303(2)", BNS) == ["303"]


def test_bare_number_is_not_a_citation():
    assert extract_sections("The appellant was 34 years old.", IPC) == []


def test_paragraph_reference_not_treated_as_section():
    # "[Paras 28-32]" and stray page numbers must not become citations.
    assert extract_sections("[Paras 28-32, 34-37]", IPC) == []


def test_unknown_section_dropped_by_membership():
    # "s. 1578" was matched by shape alone from a real judgment.
    assert extract_sections("see s. 1578 of the report", IPC) == []


def test_empty_valid_set_returns_nothing():
    """No 'trust the regex' mode: an unchecked reference is never emitted."""
    assert extract_sections("convicted under section 302 IPC", set()) == []


def test_duplicates_collapsed_in_order():
    got = extract_sections("s. 302 ... section 34 ... u/s. 302 again", IPC)
    assert got == ["302", "34"]


@pytest.mark.parametrize(
    "text,expected",
    [("Penal Code, 1860.", ["ipc"]),
     ("convicted under the I.P.C.", ["ipc"]),
     ("the Bharatiya Nyaya Sanhita, 2023", ["bns"]),
     ("a purely civil dispute", [])],
)
def test_detect_corpus(text, expected):
    assert detect_corpus(text) == expected


def test_valid_for_picks_the_named_corpus():
    """s302 is murder under the IPC and is not a BNS offence of that kind.

    Validating against the union would let a BNS judgment verify a citation
    against an IPC section of the same number.
    """
    assert valid_for(INDEX, ["bns"]) is BNS
    assert valid_for(INDEX, ["ipc"]) is IPC


def test_valid_for_falls_back_to_union_when_ambiguous():
    # Transition-era judgments discuss both codes; narrowing on a guess would
    # drop real citations.
    assert valid_for(INDEX, ["ipc", "bns"]) == INDEX["_union"]
    assert valid_for(INDEX, []) == INDEX["_union"]


def test_section_index_separates_corpora():
    ipc_chunks = [{"doc_type": "statute", "corpus": "ipc", "section": "302"}]
    bns_chunks = [{"doc_type": "statute", "corpus": "bns", "section": "303"}]
    idx = section_index(ipc_chunks, bns_chunks)
    assert idx["ipc"] == {"302"} and idx["bns"] == {"303"}
    assert idx["_union"] == {"302", "303"}

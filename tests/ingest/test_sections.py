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


def test_valid_for_is_empty_when_no_penal_code_is_named():
    """A judgment that never names the IPC or BNS cites neither.

    Falling back to the union here linked 1,214 civil SC judgments to penal
    sections: "the Section 34 petition" (Arbitration Act) became IPC s34.
    """
    assert valid_for(INDEX, []) == set()
    assert extract_sections("the Section 34 petition was dismissed",
                            valid_for(INDEX, [])) == []


def test_section_index_separates_corpora():
    ipc_chunks = [{"doc_type": "statute", "corpus": "ipc", "section": "302"}]
    bns_chunks = [{"doc_type": "statute", "corpus": "bns", "section": "303"}]
    idx = section_index(ipc_chunks, bns_chunks)
    assert idx["ipc"] == {"302"} and idx["bns"] == {"303"}
    assert idx["_union"] == {"302", "303"}


# --- Citations to OTHER enactments -------------------------------------------
# Membership cannot tell "Section 378 Cr.P.C." from IPC 378: the number is real
# in both. Before the enactment check, 7,035 CrPC citations sat in the SC
# corpus's sections_involved as IPC sections. The first three strings are
# verbatim from ingested SC judgments; the rest follow forms seen in them and in
# NyayaAnumana High Court text.

CRPC_COLLIDING = IPC | {"53A", "227", "378", "406", "482", "439", "13", "25", "27"}


@pytest.mark.parametrize(
    "text",
    [
        "Section 53A Cr.P.C",
        "Section 53A of the Code of Criminal Procedure",
        "Section 227 of the Criminal Procedure Code",
        "an appeal under Section 378(3) Cr.P.C. against acquittal",   # not theft
        "transfer under Section 406 of the Cr.P.C.",                  # not CBT
        "petition under Section 482 CrPC to quash",
        "bail under Sections 438 and 439 of the Code",
        "Section 13(2) r w 13(1)(d) of P.C Act, 1988",
        "Section 25 of the Arms Act",
        "Section 27 of the Evidence Act",
        # Verbatim, Karnataka HC acquittal appeals: the "and (3)" once hid
        # the enactment and the State's appeal was filed as a theft case.
        "This appeal is filed by the State under Section 378(1) and (3) of Code of Criminal Procedure",
        "The State has filed this appeal under Section 378 (1) (3) of the Code of Criminal Procedure, 1973",
        # Verbatim, Madras HC.
        "reach its own conclusions under Sections 378 and 379 (sic 378) CrPC are as",
    ],
)
def test_citation_to_another_enactment_is_dropped(text):
    assert extract_sections(text, CRPC_COLLIDING) == []


def test_penal_code_citation_beside_a_crpc_one_survives():
    text = ("petition under Section 482 Cr.P.C. to quash the FIR registered "
            "under Sections 420 and 406 IPC")
    assert extract_sections(text, CRPC_COLLIDING) == ["420", "406"]


def test_citation_followed_by_prose_naming_an_act_is_kept():
    # Only a name that OPENS with a capital word is an enactment; "and the
    # Arms Act" after a real IPC cite is prose, and the cite must survive.
    assert extract_sections("convicted under Section 379 and the Arms Act",
                            CRPC_COLLIDING) == ["379"]


def test_bare_citation_still_kept():
    assert extract_sections("section 420 IPC.It had been stated", IPC) == ["420"]


# --- NyayaAnumana's scrubbed High Court formatting ----------------------------

def test_spaced_suffix_and_read_with_chain():
    """Verbatim from Madras_HC_2023_848.

    Two failures in one string before the fix: "120 B" read as s120
    (concealing a design, not conspiracy), and the 420 after "r w" was never
    reached because "r w" was not a joiner.
    """
    text = "guilty of offence under Section 120 B r w 420 of I.P.C and"
    assert extract_sections(text, IPC) == ["120B", "420"]


def test_spaced_capital_that_is_not_a_suffix_falls_back_to_number():
    assert extract_sections("under Section 302 A.P. police", IPC) == ["302"]


def test_ipc_abbreviation_is_not_read_as_a_suffix():
    assert extract_sections("under Section 34 IPC", IPC) == ["34"]
    assert extract_sections("Section 379 r w 34 IPC", IPC) == ["379", "34"]


# --- Sub-section numbers are not sections ---------------------------------------
# The stand-in sets above lack "1", "2" and "15", which is exactly why
# test_subsection_flattened_to_section never saw this: s1/s2/s15 are real in
# both codes, so a bracketed sub-section number passes membership.
WITH_LOW = IPC | BNS | {"1", "2", "13", "15", "79", "376"}


@pytest.mark.parametrize(
    "text,expected",
    [
        # The Section 3 worked example: BNS 303(2) is theft, not 303 AND s2.
        ("convicted under Section 303(2) of the Bharatiya Nyaya Sanhita", ["303"]),
        ("Section 376(2)(i) IPC", ["376"]),
        ("Section 13(1)(d) read with 13(2)", ["13"]),
        ("under Sections 323(1) and 34", ["323", "34"]),
    ],
)
def test_bracketed_subsection_never_becomes_a_section(text, expected):
    assert extract_sections(text, WITH_LOW) == expected


def test_acronym_enactment_is_dropped():
    # Verbatim from 2025_3_325_340 (spot-check chunk 17): an IBC provision.
    assert extract_sections("excluded debts under Section 79(15) of the IBC",
                            WITH_LOW) == []
    assert extract_sections("The moratorium under Section 96 of the IBC is",
                            WITH_LOW | {"96"}) == []


def test_acronym_rule_needs_of_so_witness_labels_survive():
    assert extract_sections("under Section 379 PW-1 deposed", WITH_LOW) == ["379"]
    assert extract_sections("under Section 379 of the IPC", WITH_LOW) == ["379"]

"""NyayaAnumana subset: cleaning, sentence chunking, selection, de-duplication.

Strings marked verbatim are copied from the raw CSVs; the rest follow forms
measured in them. Every rule here was written against a defect observed while
profiling the source on 2026-09-26.
"""
import pytest

from src.ingest import nyaya
from src.ingest.schema import validate_chunk

IPC = {"34", "120B", "302", "323", "324", "378", "379", "406", "420", "482"}
BNS = {"303", "318"}
INDEX = {"ipc": IPC, "bns": BNS, "_union": IPC | BNS}
CORE_BNS = {"303", "318"}


# --- cleaning -----------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        # verbatim, Madras HC
        ("subjugation.15/22 https judis P.(MD)No.17548 of 2016 He also relied",
         "subjugation. P.(MD)No.17548 of 2016 He also relied"),
        # verbatim, Gujarat HC
        ("the finance.Page 45 of 113 Downloaded on Sun Sep 17 IST 2023 NEUTRAL CITATION C",
         "the finance. C"),
        # verbatim, Rajasthan HC
        ("under Section 156(3).(Downloaded on at 102552 PM) (10 of 15) CRLW-255/2018 If",
         "under Section 156(3). CRLW-255/2018 If"),
        # the signer's name goes, the word after it stays
        ("the law on the Digitally signed by ASHWANI KUMAR Date 2018",
         "the law on the Date 2018"),
        # verbatim, Orissa HC
        ("the accused CRA No.99 of 1995 Digitally Signed Signed by CHITTA RANJAN "
         "BISWAL Designation Secretary Reason was",
         "the accused CRA No.99 of 1995 was"),
    ],
)
def test_page_furniture_removed(raw, expected):
    assert nyaya.clean(raw) == expected


def test_pinpoint_page_citation_survives():
    # "at Page 181" is a real pinpoint cite, not furniture. Only "Page N of M"
    # is stripped.
    text = "reported in 1988 (1) KLJ at Page 181, it is held"
    assert nyaya.clean(text) == text


# --- sentence chunking --------------------------------------------------------

def test_glued_sentences_split_but_abbreviations_do_not():
    # Verbatim opening of Madras_HC_2022_573: the scrubbed text glues
    # sentences ("police.For"), and is full of "Mr.V." / "No.11" abbreviations.
    text = ("Chennai relating to Crime No.11 of 2021, on the file of the 1st "
            "respondent police.For Petitioner Mr.V.Gopinath Senior Counsel.")
    got = nyaya.split_sentences(text)
    assert got == [
        "Chennai relating to Crime No.11 of 2021, on the file of the 1st respondent police.",
        "For Petitioner Mr.V.Gopinath Senior Counsel.",
    ]


def test_chunks_are_whole_sentences_near_target():
    sentence = "The accused dishonestly took the motorcycle from the stand. "
    text = sentence * 80
    chunks, hard = nyaya.chunk_text(text)
    assert hard == 0
    assert len(chunks) > 1
    for c in chunks:
        assert c.endswith("stand.")
        assert len(c) <= nyaya.TARGET_CHARS + len(sentence)


def test_short_tail_folded_into_previous_chunk():
    text = ("The accused dishonestly took the motorcycle from the stand. " * 25
            + "Appeal dismissed.")
    chunks, _ = nyaya.chunk_text(text)
    # One-line outcomes are often the holding; never a stray chunk, never lost.
    assert chunks[-1].endswith("Appeal dismissed.")
    assert len(chunks[-1]) > len("Appeal dismissed.")


def test_boundaryless_run_is_hard_split_and_counted():
    text = "word " * 2000                      # 10,000 chars, no sentence end
    chunks, hard = nyaya.chunk_text(text)
    assert hard > 0
    assert all(len(c) <= nyaya.MAX_CHARS for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


# --- selection ----------------------------------------------------------------

CRIMINAL = " The accused was arrested. The accused denied it. The accused appealed."


def test_selects_ipc_theft_judgment():
    route, sections, reason = nyaya.select(
        "convicted under Section 379 IPC." + CRIMINAL, INDEX, CORE_BNS)
    assert (route, reason) == ("pre", None)
    assert sections == ["379"]


def test_state_appeal_against_acquittal_is_not_theft():
    """CrPC s378 is an appeal against acquittal, not IPC s378 theft.

    Before the enactment check in sections.py, this row qualified as a theft
    judgment on the strength of its procedural section alone.
    """
    text = ("This appeal is filed by the State under Section 378(1) and (3) of "
            "Code of Criminal Procedure against acquittal under the Penal Code "
            "for Section 302 IPC." + CRIMINAL)
    route, sections, reason = nyaya.select(text, INDEX, CORE_BNS)
    assert route is None and reason == "no_core_offence"
    assert "378" not in sections


def test_service_matter_mentioning_old_fir_rejected():
    # Verbatim-shaped: a writ about a promotion that recalls a 420 IPC case.
    text = ("cases primarily for the offence under Section 420 IPC.It had been "
            "stated that the charges had been dropped. A Mandamus is sought.")
    route, _, reason = nyaya.select(text, INDEX, CORE_BNS)
    assert route is None and reason == "not_criminal"


def test_common_intention_alone_does_not_qualify():
    route, _, reason = nyaya.select(
        "convicted under Sections 302/34 IPC." + CRIMINAL, INDEX, CORE_BNS)
    assert route is None and reason == "no_core_offence"


def test_judgment_citing_both_codes_is_unroutable():
    text = ("Section 379 IPC now corresponds to Section 303 of the Bharatiya "
            "Nyaya Sanhita." + CRIMINAL)
    assert nyaya.select(text, INDEX, CORE_BNS)[2] == "both_codes"


def test_bns_only_judgment_routes_post():
    text = "charged under Section 303 of the Bharatiya Nyaya Sanhita." + CRIMINAL
    route, sections, _ = nyaya.select(text, INDEX, CORE_BNS)
    assert route == "post" and sections == ["303"]


def test_bns_core_set_derived_from_verified_mapping():
    got = nyaya.core_sections_bns()
    # IPC 379 -> BNS 303 and IPC 420 -> BNS 318 are verified rows.
    assert {"303", "318"} <= got
    # 116 is grievous hurt's DEFINITION (IPC 320), which is not a core charge.
    assert "116" not in got


# --- de-duplication against the SC corpus -------------------------------------

JUDGMENT = " ".join(
    f"the learned counsel submitted that witness number {w} deposed about the "
    f"recovery of the stolen motorcycle from the house of accused {w} and "
    f"that the trial court had rightly appreciated the evidence on record"
    for w in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
              "hotel", "india", "juliet", "kilo", "lima", "mike", "november"))


def test_copy_of_an_indexed_judgment_is_detected():
    idx = nyaya.DuplicateIndex()
    idx.add("2023_1_1_1", JUDGMENT)
    idx.add("2023_9_9_9", "an unrelated judgment about land acquisition " * 50)
    doc, score = idx.match(JUDGMENT.replace("alpha", "[scrubbed]"))
    assert doc == "2023_1_1_1"
    assert score >= nyaya.DuplicateIndex.THRESHOLD


def test_unrelated_judgment_is_not_a_copy():
    idx = nyaya.DuplicateIndex()
    idx.add("2023_1_1_1", JUDGMENT)
    other = ("the petitioner seeks quashing of the complaint alleging that the "
             "cheque was issued as security and not for discharge of any debt ") * 20
    assert idx.match(other)[1] < nyaya.DuplicateIndex.THRESHOLD


# --- chunk records ------------------------------------------------------------

def test_chunk_row_is_schema_valid_and_carries_provenance():
    text = ("The accused was convicted under Section 379 IPC.The appeal is "
            "allowed and the conviction is set aside. ") * 30
    chunks, _ = nyaya.chunk_row("Madras_HC_2022_3142", text, 1, ["379"], "ipc")
    assert chunks
    for c in chunks:
        validate_chunk(c)
        assert c["court"] == "Madras High Court"
        assert c["date"] is None                   # unknown, never guessed
        assert c["decision_year_min"] == 2022      # a lower bound only
        assert c["disposal_nature"] == "Allowed" and c["outcome_label"] == 1
        assert c["corpus_hint"] == "ipc"
        assert c["sections_involved"] == ["379"]


def test_unknown_court_is_loud():
    with pytest.raises(ValueError, match="unknown court"):
        nyaya.chunk_row("Atlantis_HC_2022_1", "x " * 100, 0, ["379"], "ipc")

"""Judgment text repair and paragraph splitting.

Every string here is verbatim from an ingested SC judgment, and every case is a
defect the Phase 1 spot-check gate actually caught.
"""
import pytest

from src.ingest.judgments import _clean, repair_ligatures, split_paragraphs


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("notiﬁ cation", "notification"),
        ("Classiﬁ cation", "Classification"),
        ("conﬁ dence", "confidence"),
        ("eﬀ ective", "effective"),
        ("beneﬁ t", "benefit"),
        ("ﬁ led", "filed"),
        # Three-character ligature: the extractor pads it with TWO spaces.
        ("Oﬃ  cer", "Officer"),
    ],
)
def test_ligature_padding_removed(raw, expected):
    assert repair_ligatures(raw) == expected


def test_word_final_ligature_keeps_its_real_space():
    """The padding space and a real word break are both present here.

    Consuming exactly (len(expansion) - 1) spaces eats the padding and leaves
    the real separator, so "staff" and "and" do not fuse.
    """
    assert repair_ligatures("the staﬀ  and") == "the staff and"


def test_ligature_repair_runs_before_whitespace_collapse():
    # _clean collapses runs of spaces. If it did so first, the padding would be
    # indistinguishable from a real space and the word could not be rebuilt.
    assert "notification" in _clean("a notiﬁ cation was issued")


def test_running_header_stripped():
    text = "was not assigned any work just\nSUPREME COURT REPORTS\nbefore the date"
    assert "SUPREME COURT REPORTS" not in _clean(text)


def test_party_name_header_stripped():
    text = "reasoning continues\nUNION OF INDIA AND OTHERS v. DILIP PAUL\nand concludes"
    assert "UNION OF INDIA" not in _clean(text)


def test_judge_attribution_line_stripped():
    assert "PARDIWALA" not in _clean("body text\n[J. B. PARDIWALA, J.]\nmore body")


def test_ordinary_prose_naming_parties_is_kept():
    """Only the all-caps running header is furniture.

    A sentence that names the same parties in normal case is substance and must
    survive, or we would delete the reasoning along with the header.
    """
    text = "The appeal in Union of India v. Dilip Paul was allowed on merits."
    assert "Union of India v. Dilip Paul" in _clean(text)


def test_margin_position_letters_stripped():
    assert _clean("the order was passed\nA\nB\nC\nin that manner").count("\nA\n") == 0


def test_paragraph_split_on_numbered_paragraphs():
    body = "1. \nFirst paragraph text here.\n2. \nSecond paragraph text here."
    parts = split_paragraphs(body)
    assert len(parts) == 2
    assert parts[0].startswith("1.") and parts[1].startswith("2.")


def test_wrapped_date_does_not_open_a_paragraph():
    """'...letter dated \\n25.09.2015' must not read as paragraph 25.

    This bug severed 1,741 real paragraphs mid-sentence before it was caught --
    the parser manufacturing exactly the truncation the gate looks for.
    """
    body = "1. \nThe offer was not accepted by letter dated \n25.09.2015 as recorded."
    parts = split_paragraphs(body)
    assert len(parts) == 1
    assert "25.09.2015" in parts[0]


def test_non_sequential_numbers_do_not_open_paragraphs():
    # Judgments quote statutes and lower-court orders with their own numbering.
    body = "1. \nThe Court quoted the rule:\n7. \nA quoted clause.\n2. \nReal second."
    parts = split_paragraphs(body)
    assert len(parts) == 2
    assert "7." in parts[0]


@pytest.mark.parametrize(
    "variant",
    ["SUPREME COURT REPORTS",
     "Digital Supreme Court Reports",
     "DIGITAL SUPREME COURT REPORTS"],
)
def test_all_reporter_header_casings_stripped(variant):
    """The reports set this phrase in three different casings.

    Matching only two of them left it in 77 chunks. It cannot be fixed with a
    global re.IGNORECASE, because the party-name rule in the same pattern
    depends on matching full caps exactly -- hence the inline (?i:...) group.
    """
    assert variant not in _clean(f"body text here\n{variant}\nmore body text")

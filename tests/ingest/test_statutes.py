"""BNS gazette parsing: margin geometry and marginal-note attribution.

Every coordinate here is measured from the real MHA gazette PDF (No. 45 of
2023), and every case is a defect that shipped into `statutes_bns.jsonl` before
it was caught: 11 sections lost their title to the body text, and 4 more
carried a title that belonged to a different section.
"""
import json

import pytest

from src.ingest.statutes import (
    _ACT_REFERENCE,
    _MARGIN_LEFT_X0,
    _PAGE_HEIGHT,
    _assign_titles,
    _page_blocks,
    parse_ipc,
)


def _block(x0, y0, x1, lines, line_height=11.6):
    """A pymupdf 'dict' block: one bbox, one span per line."""
    return {
        "bbox": (x0, y0, x1, y0 + line_height * len(lines)),
        "lines": [
            {
                "bbox": (x0, y0 + line_height * i, x1, y0 + line_height * (i + 1)),
                "spans": [{"text": text}],
            }
            for i, text in enumerate(lines)
        ],
    }


class _Page:
    def __init__(self, *blocks):
        self._blocks = list(blocks)

    def get_text(self, _kind):
        return {"blocks": self._blocks}


def _section(num, ordinate):
    return {"section": num, "title": None, "ord": ordinate}


# --- act references share the margin with the titles ------------------------


@pytest.mark.parametrize(
    "text",
    [
        "28 of 1961.",                 # beside the dowry-death provision
        "45 of 1860.",
        "19 of 1952",                  # the trailing period is not guaranteed
        "46 of 1950. 62 of 1957.",     # pymupdf merges two refs into one block
        "45 of 1950. 46 of 1950.",
    ],
)
def test_act_references_are_not_titles(text):
    assert _ACT_REFERENCE.match(text)


@pytest.mark.parametrize(
    "title",
    [
        "Persons subject to certain Acts",   # sits between two act references
        "Theft",
        "Repeal and savings",
        "Punishment for bribery",
    ],
)
def test_real_titles_are_not_mistaken_for_act_references(title):
    assert not _ACT_REFERENCE.match(title)


# --- margin geometry --------------------------------------------------------


def test_left_margin_note_wider_than_the_old_x1_threshold_is_still_a_note():
    """s315's note ends at x1=113.7, past the 110pt cutoff this once used.

    Testing the left margin by `x1 < 110` cut through the middle of the note
    column -- note x1 runs out to 116.2 -- so 11 titles were filed as body.
    x0 is the real discriminator: notes start at 51-60, body at 102.8+.
    """
    page = _Page(
        _block(57.6, 241.1, 113.7, ["Dishonest misappropriation of property possessed by"]),
    )
    body, notes = _page_blocks(page)
    assert body == []
    assert [t for _, _, t in notes] == [
        "Dishonest misappropriation of property possessed by"
    ]
    assert 113.7 > 110, "the point of the test: this note used to be rejected"


def test_body_text_is_never_taken_for_a_margin_note():
    """Body x0 bottoms out at 102.8; the cutoff sits 20pt clear of it."""
    page = _Page(
        _block(117.6, 200.0, 477.6, ["302. Whoever commits theft shall be punished"]),
    )
    body, notes = _page_blocks(page)
    assert notes == []
    assert len(body) == 1
    assert _MARGIN_LEFT_X0 < 102.8


def test_press_signature_below_the_text_block_is_dropped():
    """The Government of India Press signs the last page inside the margin.

    It is the only margin block below 740pt; the lowest real note is at 715.4.
    Left in, it became the tail of s358's title.
    """
    page = _Page(
        _block(57.6, 715.4, 104.2, ["Rash driving or riding on a public way."]),
        _block(499.5, 751.9, 516.6, ["Kshitiz Mohan"]),
        _block(526.6, 755.6, 552.5, ["Digitally signed by Kshitiz Mohan DN: c=IN"]),
    )
    _body, notes = _page_blocks(page)
    assert [t for _, _, t in notes] == ["Rash driving or riding on a public way."]


# --- note attribution -------------------------------------------------------


def test_note_split_across_blocks_is_rejoined():
    """s315's title is three separate blocks in the margin of page 83."""
    page83 = 83 * _PAGE_HEIGHT
    sections = [_section("315", page83 + 238.8), _section("316", page83 + 406.8)]
    notes = [
        (page83 + 241.1, 57.6, "Dishonest misappropriation of property possessed by"),
        (page83 + 282.4, 57.6, "deceased person at the"),
        (page83 + 302.8, 57.6, "time of his death."),
        (page83 + 407.1, 57.6, "Criminal breach of trust."),
    ]
    _assign_titles(sections, notes)
    assert sections[0]["title"] == (
        "Dishonest misappropriation of property possessed by deceased person "
        "at the time of his death"
    )
    assert sections[1]["title"] == "Criminal breach of trust"


def test_two_notes_fused_into_one_block_are_separated():
    """pymupdf returns s174's and s175's notes as a single block.

    The split falls out of ordering alone: the later lines sit below s175's
    head, so they land in s175's span. Before this, s175 had no title at all.
    """
    page50 = 50 * _PAGE_HEIGHT
    sections = [_section("174", page50 + 644.5), _section("175", page50 + 690.8)]
    notes = [
        (page50 + 646.31, 57.6, "Punishment"),
        (page50 + 655.18, 57.6, "for undue"),
        (page50 + 663.58, 57.6, "influence or"),
        (page50 + 671.98, 57.6, "personation at"),
        (page50 + 680.62, 57.6, "an election."),
        # s175's head is at 690.8; its note resumes 1.3pt below it.
        (page50 + 692.13, 57.6, "False"),
        (page50 + 701.73, 57.6, "statement in"),
        (page50 + 711.32, 57.6, "connection"),
        (page50 + 720.92, 57.6, "with an"),
        (page50 + 730.52, 57.6, "election."),
    ]
    _assign_titles(sections, notes)
    assert sections[0]["title"] == (
        "Punishment for undue influence or personation at an election"
    )
    assert sections[1]["title"] == "False statement in connection with an election"


def test_note_at_top_of_next_page_belongs_to_the_section_that_starts_there():
    """The wrapped section does NOT get it -- this was wrong 3 times out of 3.

    s97 ends page 29, s98 opens page 30, and the note at the top of page 30 is
    s98's. A page-wrap rule handed it to s97, which then shipped "Selling child
    for purposes of prostitution" as the title of the kidnapping provision.
    """
    p29, p30 = 29 * _PAGE_HEIGHT, 30 * _PAGE_HEIGHT
    sections = [_section("97", p29 + 697.0), _section("98", p30 + 82.9)]
    notes = [
        (p29 + 697.2, 486.4, "Kidnapping or abducting child under ten years of age "
                      "with intent to steal from its person."),
        (p30 + 83.7, 57.6, "Selling child for purposes of prostitution, etc."),
    ]
    _assign_titles(sections, notes)
    assert sections[0]["title"].startswith("Kidnapping or abducting child")
    assert sections[1]["title"] == "Selling child for purposes of prostitution, etc"


def test_note_set_slightly_above_its_own_head_is_not_given_to_the_previous_one():
    """s78's note starts 3pt above s78's head; heads are ~70pt+ apart."""
    p26, p27 = 26 * _PAGE_HEIGHT, 27 * _PAGE_HEIGHT
    sections = [_section("77", p26 + 572.3), _section("78", p27 + 127.5)]
    notes = [
        (p26 + 574.3, 57.6, "Voyeurism."),
        (p27 + 124.5, 486.4, "Stalking."),
    ]
    _assign_titles(sections, notes)
    assert sections[0]["title"] == "Voyeurism"
    assert sections[1]["title"] == "Stalking"


def test_words_of_a_justified_line_stay_in_reading_order():
    """s306's note sets "property" and "in" on the SAME baseline.

    Justified setting splits one visual line into two records at a wide word
    gap: "property" at x=57.62 and "in" at x=101.78, both at y=337.293.
    Ordering by y alone leaves the tiebreak to decide, which sorted them
    alphabetically and shipped "Theft by clerk or servant of in property
    possession of master".
    """
    p79 = 79 * _PAGE_HEIGHT
    sections = [_section("306", p79 + 316.0)]
    notes = [
        (p79 + 318.100, 57.62, "Theft by clerk"),
        (p79 + 327.697, 57.62, "or servant of"),
        (p79 + 337.293, 101.78, "in"),          # deliberately out of reading order
        (p79 + 337.293, 57.62, "property"),
        (p79 + 346.890, 57.62, "possession of"),
        (p79 + 356.487, 57.62, "master."),
    ]
    _assign_titles(sections, notes)
    assert sections[0]["title"] == (
        "Theft by clerk or servant of property in possession of master"
    )


def test_a_note_before_the_first_head_is_discarded_not_back_attached():
    """Front matter sits in the margin too; it must not become s1's title."""
    sections = [_section("1", 500.0)]
    notes = [(100.0, 57.6, "Arrangement of sections."), (502.0, 57.6, "Short title.")]
    _assign_titles(sections, notes)
    assert sections[0]["title"] == "Short title"


# --- statute patches ----------------------------------------------------------

def _ipc_json(tmp_path, desc):
    p = tmp_path / "ipc.json"
    p.write_text(json.dumps([
        {"Section": "304A", "section_title": "Causing death by negligence",
         "section_desc": "Whoever causes the death of any person by doing any rash act.",
         "chapter": 16, "chapter_title": "OF OFFENCES AFFECTING THE HUMAN BODY"},
        {"Section": "304B", "section_title": "Dowry death", "section_desc": desc,
         "chapter": 16, "chapter_title": "OF OFFENCES AFFECTING THE HUMAN BODY"},
    ]), encoding="utf-8")
    return p


def _patches(tmp_path, text, source):
    p = tmp_path / "patches.json"
    p.write_text(json.dumps({"ipc": {"304B": {"section_title": "Dowry death",
                                               "text": text, "source": source}}}), encoding="utf-8")
    return p


def test_empty_upstream_section_filled_only_from_a_sourced_patch(tmp_path):
    chunks, skipped = parse_ipc(_ipc_json(tmp_path, ""),
                                _patches(tmp_path, "(1) Where the death of a woman...", "gazette p.145"))
    s = {c["section"]: c for c in chunks}
    assert "304B" in s and skipped == []
    assert s["304B"]["text"].startswith("Dowry death. (1) Where the death")
    assert s["304B"]["source"] == "gazette p.145"          # provenance travels with it


@pytest.mark.parametrize("text,source", [("", ""), ("some text", ""), ("", "a source")])
def test_patch_without_text_and_source_is_still_a_gap(tmp_path, text, source):
    chunks, skipped = parse_ipc(_ipc_json(tmp_path, ""), _patches(tmp_path, text, source))
    assert "304B" not in {c["section"] for c in chunks}
    assert skipped == ["304B"]


def test_real_patch_file_carries_304B_with_provenance():
    from src.ingest.statutes import load_patches
    p = load_patches("ipc")
    assert "304B" in p
    assert "Act 43 of 1986" in p["304B"]["source"] and "sha256" in p["304B"]["source"]


# --- "complete" patches: civictech text cut short, official text continues ---

_CUT = ("Whoever commits the offence of criminal intimidation shall be punished with "
        "imprisonment of either description for a term which may extend to two years, "
        "or with fine, or with both;")
_FULL = (_CUT + " and if the threat be to cause death or grievous hurt, ... shall be "
         "punished with imprisonment of either description for a term which may extend "
         "to seven years, or with fine, or with both.")


def _ipc_506(tmp_path, desc, patch):
    j = tmp_path / "ipc.json"
    j.write_text(json.dumps([{"Section": 506, "section_title": "Punishment for criminal intimidation",
                              "section_desc": desc, "chapter": 22, "chapter_title": "X"}]),
                 encoding="utf-8")
    p = tmp_path / "patches.json"
    p.write_text(json.dumps({"ipc": {"506": patch}}), encoding="utf-8")
    return j, p


def test_continues_accepts_a_cut_short_prefix_only():
    from src.ingest.statutes import continues
    assert continues(_CUT, _FULL)
    assert continues(_CUT.replace("’", "'"), _FULL)          # quote style is not a difference
    assert not continues(_FULL, _FULL)                        # nothing to add
    assert not continues(_FULL, _CUT)                         # patch shorter than upstream
    # Upstream re-amended (different words up front): the 1997 text must not win.
    assert not continues("Whoever, by any electronic means, commits criminal intimidation "
                         "shall be punished with imprisonment for three years;", _FULL)


def test_complete_patch_replaces_cut_short_text_with_provenance(tmp_path):
    j, p = _ipc_506(tmp_path, _CUT, {"text": _FULL, "source": "official p.237", "mode": "complete"})
    chunks, _ = parse_ipc(j, p)
    c = chunks[0]
    assert "seven years" in c["text"] and c["text"].startswith("Punishment for criminal intimidation.")
    assert c["source"] == "official p.237"


def test_complete_patch_that_no_longer_fits_fails_the_build(tmp_path):
    """If upstream is corrected or re-amended, a stale patch must be looked at,
    not silently applied (it would revert the law) or silently dropped."""
    j, p = _ipc_506(tmp_path, "Whoever threatens by electronic means shall be punished with "
                    "imprisonment for three years.",
                    {"text": _FULL, "source": "official p.237", "mode": "complete"})
    with pytest.raises(ValueError, match="506"):
        parse_ipc(j, p)


def test_patch_without_mode_never_overrides_nonempty_upstream(tmp_path):
    j, p = _ipc_506(tmp_path, _CUT, {"text": _FULL, "source": "official p.237"})
    chunks, _ = parse_ipc(j, p)
    assert "seven years" not in chunks[0]["text"]


def test_real_complete_patches_apply_and_carry_the_official_source():
    """The ingested IPC holds the completed text: 300's clauses and Exceptions,
    506's threat-to-kill limb, 307's life-convict clause."""
    chunks, _ = parse_ipc()
    s = {c["section"]: c for c in chunks}
    assert "sufficient in the ordinary course of nature to cause death" in s["300"]["text"]
    assert "grave and sudden provocation" in s["300"]["text"]
    assert "if the threat be to cause death or grievous hurt" in s["506"]["text"]
    assert "punished with death" in s["307"]["text"]
    for sec in ("300", "506", "307"):
        assert "sha256 576a485b" in s[sec]["source"] and "amended to 1997" in s[sec]["source"]
    # Sections rejected or held back stay as civictech has them.
    assert "goapolice" not in s["214"]["source"] and "goapolice" not in s["405"]["source"]
    assert "goapolice" not in s["4"]["source"]

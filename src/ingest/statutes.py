r"""Statute ingestion: IPC (JSON) and BNS (official gazette PDF) -> chunks.

Chunking rule (CLAUDE.md Phase 1): statutes are chunked ONE SECTION PER CHUNK.
No token-window splitting -- a section is the unit a lawyer cites and the unit
the citation graph keys on, so splitting one across chunks would let half a
provision be retrieved without the half that qualifies it.

The two sources are shaped very differently.

IPC -- civictech-India/Indian-Law-Penal-Code-Json
    Already one record per section, 575 of them, uniform keys. The only real
    trap is that `Section` is an int for 511 records and a str for the other 64
    ("304A", "376DA"). Everything is forced to str; see normalise_section.

BNS -- the Ministry of Home Affairs gazette PDF (No. 45 of 2023, 25 Dec 2023,
       digitally signed by Government of India Press)
    No machine-readable BNS exists from any authority. The GitHub BNS datasets
    are all unvetted hobby repos with no provenance, which is disqualifying for
    a system whose entire premise is that a citation is real only if it came
    from verified ingested data. So we parse the gazette itself.

    Two things make that tractable, both verified against the real file:

    1. Section titles are GAZETTE MARGINAL NOTES, not inline headings. They sit
       in a narrow column (width < 80pt) that mirrors by page -- x0 > 480 on
       odd pages, x0 < 80 on even ones. A note belongs to the section whose
       head it follows in document order, which is exactly how the printed
       page is meant to be read.
    2. Section heads are `<n>.` at the start of a body line. Note there is NO
       required space after the period: 8 of the 358 sections render as
       "104.Whoever" / "331.(1)". Requiring `\.\s` silently loses those eight.
       The gazette PDF glues words together in places generally ("ThisAct",
       "intoforce") -- an artefact of its kerning that every extractor
       reproduces identically, so it is repaired by rule, not by extractor
       choice.
"""
from __future__ import annotations

import bisect
import json
import re
from pathlib import Path

import pymupdf

from .schema import normalise_section

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "statutes"

IPC_SOURCE = (
    "https://raw.githubusercontent.com/civictech-India/"
    "Indian-Law-Penal-Code-Json/main/ipc.json"
)
BNS_SOURCE = "https://www.mha.gov.in/sites/default/files/250883_english_01042024.pdf"

BNS_EXPECTED_SECTIONS = 358
IPC_EXPECTED_SECTIONS = 575

# --- gazette page geometry (points; page is 595 x 842) -----------------------
# Measured across all 102 pages of the gazette rather than guessed:
#     left-margin notes    x0 in [ 51.1,  59.8]   (n=203)
#     right-margin notes   x0 in [485.4, 526.6]   (n=176)
#     body text            x0 in [102.8, 232.5]   (n=1348)
# x0 therefore separates the columns with ~40pt of clearance on both sides.
# An earlier version tested the left margin with `x1 < 110`, which cuts through
# the middle of the note column -- note x1 runs out to 116.2 -- and silently
# reclassified 11 titles as body text.
_MARGIN_NOTE_MAX_WIDTH = 80    # notes are a narrow column; body runs ~360 wide
_MARGIN_RIGHT_X0 = 480         # odd pages: note sits right of the body
_MARGIN_LEFT_X0 = 80           # even pages: note sits left of the body
_HEADER_MAX_Y0 = 80            # running head "Sec. 1] THE GAZETTE OF INDIA ..."
_SIGNATURE_Y0 = 740            # Press's digital signature; lowest real note is 715.4

# Marginal columns also carry references to OTHER Acts ("28 of 1961." next to
# the dowry-death provision), and one block may hold several of them
# ("46 of 1950. 62 of 1957."). Those are citations, not section titles.
_ACT_REFERENCE = re.compile(r"^(?:\d+\s+of\s+\d{4}\.?[\s,;]*)+$")

_SECTION_HEAD = re.compile(r"^\s*(\d{1,3})\.")
_CHAPTER = re.compile(r"^\s*CHAPTER\s*([IVXL]+)\s*$", re.I)
# "CHAPTERI", "CHAPTERXVII" -- the space is eaten by the PDF's kerning.
_CHAPTER_GLUED = re.compile(r"^\s*CHAPTER([IVXL]+)\s*$")


def _degazette(text):
    """Repair the gazette PDF's systematic spacing damage.

    Only transformations that are safe on legal text are applied: a missing
    space is inserted where a lowercase letter abuts an uppercase one, and
    around the section-head period. Nothing is spell-corrected -- guessing at
    statutory wording is far worse than leaving a joined word alone.
    """
    # "ThisAct" -> "This Act";  "bynotification" cannot be fixed without a
    # dictionary and is deliberately left as-is.
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # "(a)Awriting" -> "(a) Awriting" -> handled by the rule above for the
    # second half; this one separates the clause label from the text.
    text = re.sub(r"(\([a-z0-9]{1,3}\))([A-Za-z])", r"\1 \2", text)
    # Non-breaking spaces and soft hyphens leak in from the typesetting.
    text = text.replace("\xa0", " ").replace("­", "")
    return text


def _clean(text):
    """Collapse the hard line wrapping of a printed page into flowing text."""
    text = _degazette(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_blocks(page):
    """Split one gazette page into (body_blocks, margin_note_lines).

    Notes come back as individual LINES, not whole blocks. The margin column is
    typeset one note per section, but pymupdf's block grouping does not respect
    that boundary: it splits s315's note across three blocks and fuses s174's
    with s175's into one. A line carries its own y, so both cases resolve under
    the single ordering rule in _assign_titles instead of needing a joining
    heuristic and a splitting heuristic that would have to disagree.

    Act references and the Press's digital signature are dropped whole-block --
    they share the margin with the titles but are furniture, and at line
    granularity they would interleave into the title they sit beside
    ("Persons subject 45 of 1950. to certain 46 of 1950. Acts").
    """
    body, notes = [], []
    for blk in page.get_text("dict")["blocks"]:
        if "lines" not in blk:
            continue  # image block
        x0, y0, x1, _y1 = blk["bbox"]
        lines = [
            "".join(sp["text"] for sp in ln["spans"]).strip() for ln in blk["lines"]
        ]
        flat = re.sub(r"\s+", " ", " ".join(t for t in lines if t)).strip()
        if not flat:
            continue
        if y0 < _HEADER_MAX_Y0:
            continue  # running header / page number
        if "GAZETTE OF INDIA" in flat.upper():
            continue
        is_margin = (x1 - x0) < _MARGIN_NOTE_MAX_WIDTH and (
            x0 > _MARGIN_RIGHT_X0 or x0 < _MARGIN_LEFT_X0
        )
        if not is_margin:
            body.append((y0, "\n".join(lines)))
            continue
        if y0 > _SIGNATURE_Y0 or _ACT_REFERENCE.match(flat):
            continue
        # (y, x, text): x is the tiebreak, not decoration. Justified setting
        # splits one visual line into two records at a wide word gap -- s306's
        # note has "property" at x=57.6 and "in" at x=101.8 on the SAME y --
        # so ordering by y alone leaves the words to fall in whatever order the
        # sort's tiebreak happens to give ("of in property possession").
        notes += [
            (ln["bbox"][1], ln["bbox"][0], text)
            for ln, text in zip(blk["lines"], lines)
            if text
        ]
    body.sort(key=lambda b: b[0])
    notes.sort(key=lambda b: (b[0], b[1]))
    return body, notes


_PAGE_HEIGHT = 842
_NOTE_LEAD = 5.0             # a note line may start this far ABOVE its own head


def _clean_note(text):
    title = re.sub(r"\s+", " ", _degazette(text)).strip().rstrip(".")
    return title or None


def _assign_titles(sections, notes):
    """Bind marginal-note lines to section heads by position in the document.

    The gazette sets a section's note level with the head it annotates, so the
    note for section N is everything standing in the margin between head N and
    head N+1. Reading the column that way -- rather than matching each note to
    the nearest head within a tolerance -- is what makes the awkward cases
    ordinary rather than special:

    * A note split across several blocks rejoins, because all of its lines fall
      in the same span (s315's title is three blocks: "Dishonest
      misappropriation of property possessed by" / "deceased person at the" /
      "time of his death").
    * Two notes fused into one block separate, because the fused block's later
      lines sit below the next head (s174 "Punishment for undue influence or
      personation at an election" and s175 "False statement in connection with
      an election" share a block).
    * A note set at the top of the next page, for a section that began at the
      foot of the previous one, lands correctly with no page-wrap rule at all.
      The rule this replaces gave such a note to the section that wrapped, and
      it was wrong every one of the three times it fired: s97 took s98's title,
      s175 took s176's, s180 took s181's. A wrong title is worse than none --
      it is prepended to the section's embedded text, so it corrupts retrieval
      while looking perfectly well-formed.

    `_NOTE_LEAD` lets a note line begin a few points above its own head
    (measured: up to 3pt, e.g. s78 "Stalking"). Consecutive heads are never
    closer than ~70pt, so it cannot reach back into the previous section.
    """
    heads = [s["ord"] for s in sections]
    owned = {}
    for ordinate, x, text in notes:
        i = bisect.bisect_right(heads, ordinate + _NOTE_LEAD) - 1
        if i >= 0:
            owned.setdefault(i, []).append((ordinate, x, text))

    for i, lines in owned.items():
        lines.sort(key=lambda ln: (ln[0], ln[1]))   # down the page, then across
        sections[i]["title"] = _clean_note(" ".join(t for _, _, t in lines))


def parse_bns(pdf_path=None):
    """Parse the BNS gazette PDF into one chunk per section."""
    pdf_path = Path(pdf_path or RAW / "bns_mha.pdf")
    doc = pymupdf.open(pdf_path)

    # Section bodies span page breaks, so nothing can be finalised per-page;
    # heads and marginal notes are both collected against a document-wide
    # ordinate and reconciled afterwards.
    sections = []        # [{"section","title","chapter","chapter_title","lines","ord"}]
    all_notes = []       # [(ord, x, text)] -- one entry per note LINE
    chapter = chapter_title = None
    pending_chapter = None   # a CHAPTER line; its title is the NEXT line

    for page_index, page in enumerate(doc):
        body, notes = _page_blocks(page)
        page_ord = page_index * _PAGE_HEIGHT
        all_notes += [(page_ord + y, x, txt) for y, x, txt in notes]

        for y0, block in body:
            for line in block.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue

                m = _CHAPTER.match(stripped) or _CHAPTER_GLUED.match(stripped)
                if m:
                    pending_chapter = m.group(1).upper()
                    continue
                if pending_chapter is not None:
                    # e.g. "OF OFFENCES AGAINST PROPERTY"
                    chapter, chapter_title = pending_chapter, _degazette(stripped)
                    pending_chapter = None
                    continue

                head = _SECTION_HEAD.match(stripped)
                if head and _is_new_section(head.group(1), sections):
                    sections.append({
                        "section": head.group(1),
                        "title": None,
                        "chapter": chapter,
                        "chapter_title": chapter_title,
                        "lines": [stripped],
                        "ord": page_ord + y0,
                    })
                    continue

                if sections:
                    sections[-1]["lines"].append(stripped)

    _assign_titles(sections, all_notes)
    return [_bns_chunk(s) for s in sections]


def _is_new_section(num, sections):
    """Guard against `(2) ... 5. of the said Act` style false heads.

    The Sanhita numbers its sections 1..358 strictly in order, so a head is
    real only if it is exactly one past the last one accepted. This is what
    stops cross-references inside a provision from opening a phantom section.
    """
    expected = 1 if not sections else int(sections[-1]["section"]) + 1
    return int(num) == expected


def _bns_chunk(s):
    text = _clean("\n".join(s["lines"]))
    return {
        "chunk_id": f"bns_s{s['section']}",
        "doc_id": "bns_2023",
        "doc_type": "statute",
        "text": text,
        "source": BNS_SOURCE,
        "court": None,
        "date": None,
        "sections_involved": [s["section"]],
        "corpus": "bns",
        "section": s["section"],
        "section_title": s["title"],
        "chapter": s["chapter"],
        "chapter_title": s["chapter_title"],
    }


def parse_ipc(json_path=None):
    """Parse the civictech IPC JSON into one chunk per section."""
    json_path = Path(json_path or RAW / "ipc.json")
    records = json.loads(json_path.read_text(encoding="utf-8"))

    chunks, skipped = [], []
    for r in records:
        section = normalise_section(r.get("Section"))
        if section is None:
            skipped.append(r.get("Section"))
            continue
        title = (r.get("section_title") or "").strip() or None
        desc = (r.get("section_desc") or "").strip()
        if not desc:
            # One record in the file has an empty description. A section with
            # no text cannot be retrieved or meaningfully cited, so it is
            # dropped rather than emitted as a stub the verifier would bless.
            skipped.append(section)
            continue
        chapter = r.get("chapter")
        chunks.append({
            "chunk_id": f"ipc_s{section}",
            "doc_id": "ipc_1860",
            "doc_type": "statute",
            # The title carries real retrieval signal ("Theft", "Punishment for
            # theft") and is absent from section_desc, so it is prepended.
            "text": f"{title}. {desc}" if title else desc,
            "source": IPC_SOURCE,
            "court": None,
            "date": None,
            "sections_involved": [section],
            "corpus": "ipc",
            "section": section,
            "section_title": title,
            "chapter": str(chapter) if chapter is not None else None,
            "chapter_title": (r.get("chapter_title") or "").strip() or None,
        })
    return chunks, skipped

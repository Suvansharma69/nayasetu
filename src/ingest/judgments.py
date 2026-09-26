r"""Judgment ingestion: vanga SC tars -> paragraph chunks.

Chunking rule (CLAUDE.md Phase 1): judgments are chunked BY PARAGRAPH/HOLDING,
never by fixed token count. A Supreme Court judgment reasons across a numbered
paragraph; cutting one at 512 tokens splits a holding from the reasoning that
qualifies it, and the retrieved half then reads as authority for something the
Court did not decide.

What the source actually is
---------------------------
The bucket ships PDFs, not text -- 782 for 2024, 2,535 across 2023-2025. They
are digital-born with a clean text layer (no OCR needed, verified: no U+FFFD
anywhere in a sampled judgment), and pymupdf reads them ~40x faster than
pdfplumber at slightly better completeness, which is why it is the extractor.

These are Supreme Court Reports, so each judgment carries an editorial
apparatus ahead of the judgment proper:

    <citation, parties, case number, date, coram>
    Issue for Consideration
    Headnotes            <- editorial summary of the holding, with "Held:"
    Case Law Cited       <- precedent this judgment relies on
    List of Acts         <- e.g. "Penal Code, 1860."  (authoritative corpus tag)
    List of Keywords
    CRIMINAL APPELLATE JURISDICTION     <- judgment proper starts here
    <appearances>
    1. ... 2. ... 38.    <- numbered paragraphs

The headnote block is kept as its own chunk rather than discarded: it is a
lawyer-written statement of what the case held, which is exactly what precedent
matching in Node 3 wants to match against. It is tagged `is_headnote` so a
later phase can weight it differently from the judge's own words.
"""
from __future__ import annotations

import re
import tarfile
from pathlib import Path

import pymupdf

from .schema import MIN_TEXT_CHARS
from .sections import attributed_sections, detect_corpus, extract_sections, valid_for
from .textsplit import chunk_text

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "judgments"

SOURCE = "s3://indian-supreme-court-judgments (AWS Open Data)"
COURT = "Supreme Court of India"

# BNS applies to offences on or after this date; CLAUDE.md Stage 0 routes on it.
BNS_COMMENCEMENT = "2024-07-01"


def route(corpus_hint, date):
    """Which judgment collection a judgment belongs in: "pre", "post" or None.

    Decided 2026-09-26: by the code the judgment APPLIES, with decision date
    only as the tie-break. The Stage 0 router sends a pre-transition offence
    to the IPC collections and a post-transition one to the BNS collections,
    so each judgment collection must speak ONE numbering. Split on decision
    date instead, `judgments_post2024` held every IPC appeal decided after
    July 2024 -- its "302" could be IPC murder or BNS s302, the exact union
    error Known Gotchas forbids. It also matches the NyayaAnumana subset,
    which has no decision date and could only ever be routed by code.

      "ipc"      -> pre   (whatever the decision date)
      "bns"      -> post
      both/none  -> decision date: a transition judgment discussing both
                    codes, or a civil one naming neither (which carries no
                    penal sections anyway). None if undated.
    """
    if corpus_hint == "ipc":
        return "pre"
    if corpus_hint == "bns":
        return "post"
    if date is None:
        return None
    return "post" if date >= BNS_COMMENCEMENT else "pre"

# Start of the judgment proper. Civil matters say CIVIL, criminal say CRIMINAL,
# and some say ORIGINAL -- match the common suffix. The line does NOT end
# there: it runs on as "JURISDICTION: Criminal Appeal No. 1031 of 2015", so
# anchoring to end-of-line matches nothing at all.
_JURISDICTION = re.compile(r"(?m)^[ \t]*[A-Z][A-Z \t]{0,40}JURISDICTION\b")

# "1. \nOn 30.08.1985, ..." -- the reports set the paragraph number, then a
# tab, then a LINE BREAK before the text. Requiring non-whitespace immediately
# after the number therefore matches nothing; the newline must be allowed.
#
# The whitespace after the period is REQUIRED, not optional. Judgments are full
# of dd.mm.yyyy dates, and line wrapping regularly puts one at the start of a
# line: "...indicated in letter dated \n25.09.2015". With the separator
# optional, "25." reads as the opening of paragraph 25 and the real paragraph
# is severed mid-sentence -- which is exactly the truncation the Phase 1 gate
# is supposed to catch, manufactured by the parser itself.
_PARA = re.compile(r"(?m)^[ \t]*(\d{1,3})\.[ \t\n]+(?=\S)")

# Running headers/footers that repeat on every page and would otherwise be
# glued into the middle of paragraphs.
#
# The lone A-H are the SCR position letters printed down the page margin, used
# for pinpoint citation ("at 691-C"). Extraction drops them into the text as
# single-character lines -- they appear in 7.7% of judgment chunks, often as a
# run of eight at a page break. They carry no meaning in the flowed text and
# would otherwise be embedded as content.
#
# The recurring block at every page break is, in order: the party-name header
# in full caps, the authoring judge, "SUPREME COURT REPORTS", the reporter
# citation, and the page number. All five are furniture, and "SUPREME COURT
# REPORTS" alone was landing in 17% of chunks.
#
# The party-name line is matched case-SENSITIVELY: it is set in full caps
# ("UNION OF INDIA AND OTHERS v. DILIP PAUL") while ordinary prose naming the
# same parties is not, so the caps are what distinguish a header from a
# sentence. Only the " v. " separator is lowercase.
_PAGE_FURNITURE = re.compile(
    r"(?m)^[ \t]*(?:\[\d{4}\]\s+\d+\s+S\.C\.R\..*"
    # Case-insensitive ONLY for this phrase, via an inline group: the reports
    # set it as "SUPREME COURT REPORTS", "Digital Supreme Court Reports" AND
    # "DIGITAL SUPREME COURT REPORTS". A global re.IGNORECASE cannot be used
    # here because the party-name rule below depends on matching caps exactly.
    r"|(?i:(?:Digital )?Supreme Court Reports)"
    # A long party name WRAPS: its first line (with " v. ") is caught by the
    # party-name rule below, and the tail lands on the judge's line --
    # "AIRPORT LTD [S. RAVINDRA BHAT, J.]". So the judge bracket is stripped
    # together with any all-caps text before it on the same line. Before
    # this, 2,491 SC chunks kept such a tail. The apostrophe class includes
    # U+2019 because the reports set "EMPLOYEES’" with a curly one (200 more).
    # The tail may open with "&" or "(" when the wrap falls mid-name:
    # "& TRANSPORT UNDERTAKING (BEST) [J. B. PARDIWALA, J.]".
    r"|(?:[A-Z&(][A-Z0-9 .,&'’()\-]*[ \t]+)?\[[A-Z][A-Z. ,'’()]*,[ \t]*JJ?\.\]"  # [J. B. PARDIWALA, J.]
    r"|[A-Z][A-Z0-9 .,&'’()\-]*\sv\.\s[A-Z][A-Z0-9 .,&'’()\-]*"  # party-name header
    r"|\d{1,4}|[A-H])[ \t]*$"
)

# Ligature glyphs, and the spurious spaces the extractor pads them with.
#
# The gazette and SCR PDFs use real ligature glyphs, and extraction emits one
# glyph plus (len(expansion) - 1) spaces, because the PDF reserved that width:
# "ﬁ led" is "filed", "Classiﬁ cation" is "Classification", "Oﬃ  cer" is
# "Officer" (two spaces, since ﬃ expands to three characters). 8.6% of judgment
# chunks are affected, and the damaged words are ordinary legal vocabulary --
# notification, qualification, definition, specified, effect. Left alone, none
# of them would ever match a query embedding.
#
# Consuming exactly (len(expansion) - 1) spaces is what makes this safe at a
# word boundary: a word-final "staﬀ " carries one spurious space AND one real
# one, so the rule eats the padding and leaves the real space intact.
_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
_LIGATURE_RE = re.compile(
    "|".join(f"{re.escape(g)} {{0,{len(e) - 1}}}" for g, e in _LIGATURES.items())
)
_LIGATURE_BY_GLYPH = dict(_LIGATURES)


def repair_ligatures(text):
    """Expand ligature glyphs and drop the padding spaces the extractor adds.

    Must run BEFORE any whitespace collapsing: the rule counts exact spaces,
    and collapsing runs of spaces first destroys the very signal that tells
    padding apart from a real word break.
    """
    def sub(m):
        glyph = m.group(0)[0]
        return _LIGATURE_BY_GLYPH[glyph]
    return _LIGATURE_RE.sub(sub, text)



def _pdf_text(data):
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _clean(text):
    # Order matters. Ligature repair counts exact spaces, so it must precede
    # both the furniture strip (which rewrites line structure) and the
    # whitespace collapse (which would erase the padding it keys on).
    text = repair_ligatures(text)
    text = _PAGE_FURNITURE.sub("", text)
    text = text.replace("\xa0", " ").replace(" ", " ").replace("\x08", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _iso_date(raw):
    """vanga stores dd-mm-yyyy; the schema and the router both want ISO."""
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", str(raw or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def split_paragraphs(body):
    """Split the judgment proper into its numbered paragraphs.

    Only strictly ascending numbers open a paragraph. Judgments quote statutes
    and lower-court orders that carry their own numbering, so "1." appearing
    inside paragraph 24 must not restart the sequence.
    """
    marks = []
    expected = 1
    for m in _PARA.finditer(body):
        if int(m.group(1)) == expected:
            marks.append((m.start(), m.end(), expected))
            expected += 1

    if not marks:
        return [body] if body.strip() else []

    paras = []
    if marks[0][0] > MIN_TEXT_CHARS:
        paras.append(body[: marks[0][0]])      # preamble before paragraph 1
    for i, (start, end, _) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        paras.append(body[start:stop])
    return paras


def _merge_short(parts):
    """Fold undersized fragments forward so no chunk is a stray line.

    A one-line paragraph is often a real holding ("The appeal is allowed and
    the conviction is set aside"), so it is merged with its neighbour rather
    than dropped -- losing it would lose the outcome.
    """
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if out and len(out[-1]) < MIN_TEXT_CHARS:
            out[-1] = f"{out[-1]}\n{part}"
        else:
            out.append(part)
    if len(out) > 1 and len(out[-1]) < MIN_TEXT_CHARS:
        out[-2] = f"{out[-2]}\n{out.pop()}"
    return out


# A real SC paragraph is at most a few thousand characters -- long quotations
# included. Anything past this is a failed paragraph split, not a paragraph:
# a missing number ("227." then "229.") or a separate opinion restarting at
# "1." leaves split_paragraphs waiting for a number that never comes, and the
# rest of the judgment lands in one chunk. Measured 2026-09-26: 687 chunks
# over 8,000 chars, the largest 397,044 -- which also ran the embedder out of
# memory. Such a part is re-split into runs of whole sentences.
MAX_PARAGRAPH_CHARS = 4000


def _fit(part):
    if len(part.strip()) <= MAX_PARAGRAPH_CHARS:
        return [part]
    return chunk_text(part)[0]


def chunk_judgment(text, meta, section_index):
    """Turn one judgment's text into schema-valid chunks."""
    text = _clean(text)
    if not text:
        return []

    split = _JURISDICTION.search(text)
    headnote = text[: split.start()] if split else ""
    body = text[split.start():] if split else text

    # Which code this judgment applies is decided FIRST, because it selects the
    # section set every citation in it is then checked against. Checking
    # against both codes at once would verify an IPC citation against a BNS
    # section of the same number and vice versa.
    corpus = detect_corpus(text)
    valid_sections = valid_for(section_index, corpus)

    # Corpus and sections are read from the WHOLE judgment: the "List of Acts"
    # block and the charge recital both sit in the headnote, while the
    # reasoning paragraphs often say only "the said section".
    doc_sections = extract_sections(text, valid_sections)
    # A judgment naming BOTH codes had its sections checked against the union,
    # so its bare numbers cannot be attributed to either code. Keep, beside
    # them, only the citations that name their code -- the citation graph
    # builds this judgment's edges from these alone.
    attributed = attributed_sections(text, section_index) if len(corpus) > 1 else None

    date = _iso_date(meta.get("decision_date"))
    parts = []
    if len(headnote.strip()) >= MIN_TEXT_CHARS:
        parts.append((headnote, True))
    parts += [(p, False) for p in _merge_short(split_paragraphs(body))]
    parts = [(piece, hn) for part, hn in parts for piece in _fit(part)]

    chunks = []
    for i, (para, is_headnote) in enumerate(parts):
        para = para.strip()
        if len(para) < MIN_TEXT_CHARS:
            continue
        # Per-chunk references, falling back to the judgment's own sections so
        # a paragraph that reasons about the charge without renaming it is
        # still reachable from that section in the citation graph.
        local = extract_sections(para, valid_sections)
        chunks.append({
            "chunk_id": f"{meta['path']}_p{i}",
            "doc_id": meta["path"],
            "doc_type": "judgment",
            "text": para,
            "source": SOURCE,
            "court": COURT,
            "date": date,
            "sections_involved": local or doc_sections,
            "case_id": (meta.get("case_id") or "").strip() or None,
            "citation": (meta.get("citation") or "").strip() or None,
            "title": (meta.get("title") or "").strip() or None,
            "disposal_nature": (meta.get("disposal_nature") or "").strip() or None,
            "para_index": i,
            "is_headnote": is_headnote,
            "corpus_hint": ",".join(corpus) or None,
            "sections_attributed": attributed,
        })
    return chunks


def iter_judgments(year, metadata, section_index, limit=None):
    """Stream chunks for one year's tar, joined to its parquet metadata.

    The tar is read member by member rather than extracted to disk: 783MB of
    PDFs unpacked alongside the tars would double the raw footprint for no
    gain, and CLAUDE.md Section 4 rule 4 is explicit about not paying twice for
    the same data.
    """
    tar_path = RAW / f"english_{year}.tar"
    seen = 0
    with tarfile.open(tar_path) as tar:
        for member in tar:
            if not member.isfile() or not member.name.lower().endswith(".pdf"):
                continue
            # "2024_10_108_125_EN.pdf" -> path key "2024_10_108_125"
            key = re.sub(r"_EN\.pdf$", "", Path(member.name).name, flags=re.I)
            meta = dict(metadata.get(key) or {})
            meta["path"] = key
            fh = tar.extractfile(member)
            if fh is None:
                continue
            try:
                text = _pdf_text(fh.read())
            except Exception as e:                      # a corrupt PDF in 2,535
                print(f"  [skip] {key}: {type(e).__name__}: {e}")
                continue
            yield key, chunk_judgment(text, meta, section_index)
            seen += 1
            if limit and seen >= limit:
                return


def load_metadata(year):
    """decision_date/citation/disposal_nature etc, keyed by the tar's path."""
    import pandas as pd

    df = pd.read_parquet(RAW / f"metadata_{year}.parquet")
    return {r["path"]: r for r in df.to_dict("records")}

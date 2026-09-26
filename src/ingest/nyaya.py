r"""NyayaAnumana ingestion: a filtered High Court subset -> judgment chunks.

Why this corpus at all
----------------------
The vanga SC corpus is ~2,500 judgments. Phase 5's outcome analytics suppress
any section with fewer than ~5 supporting judgments, and at SC scale that
suppresses most of them. NyayaAnumana adds High Court judgments on the offences
this project is about. CLAUDE.md Section 4 rule 2: a curated subset, never the
bulk collection -- only `test/2020_2024_single.zip` is read, and only its HC and
SCI CSVs. Tribunals and Dailyorder are out of scope for criminal precedent and
are never opened.

What the source actually is (measured 2026-09-26, not assumed)
--------------------------------------------------------------
Each CSV row is `filename, text, label` and nothing else.

* `label` is binary. The paper (arXiv 2412.08385) defines 1 = all appeals /
  pleas ACCEPTED, 0 = all rejected; the dataset card is empty. Checked against
  the text: rows labelled 1 end in allowed/quashed/granted language 4,496 times
  against 149 for dismissed. It is PETITIONER success, not conviction -- a 0
  can be a bail refusal, an accused's appeal failing, or the State's appeal
  against acquittal failing. Node 5 must not read it as a conviction rate.
* The text is ONE LINE: no newlines, no paragraph numbers, names and dates
  scrubbed ("judgment dated passed by"). There are no paragraphs to split on,
  so chunks are runs of whole sentences (see chunk_text) -- the closest the
  source allows to CLAUDE.md's paragraph rule, and never a fixed token cut.
* The year in `filename` is NOT the decision year. For the SC rows that
  duplicate vanga judgments, the real decision came 0, 1 or 2 years AFTER the
  filename year (450/86/374 of 910), never before. HC neutral citations are
  scrubbed too, so HC decision dates are unrecoverable. The year is kept only
  as a lower bound, `decision_year_min`, and `date` is None.
* ~940 of the 1,812 SC rows are the same judgments already in the vanga corpus.
  Ingesting both would count one decision twice in Node 5, so SC rows are
  checked against the vanga text first (see DuplicateIndex).

Routing
-------
With no decision date, these rows cannot be split on 2024-07-01 the way the
vanga corpus is. They are routed by the code the judgment APPLIES, which is
what the Stage 0 router keys on anyway (offence before the transition -> IPC
collections): IPC-only -> judgments_pre2024, BNS-only -> judgments_post2024,
both or neither -> unroutable and reported, never guessed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sys
import zipfile
import zlib
from collections import Counter
from pathlib import Path

from .judgments import repair_ligatures
from .schema import MIN_TEXT_CHARS
from .sections import detect_corpus, extract_sections
from .textsplit import MAX_CHARS, TARGET_CHARS, chunk_text, split_sentences  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
ZIP = ROOT / "data" / "raw" / "nyaya_anumana" / "test" / "2020_2024_single.zip"
MEMBERS = (
    "2020_2024_single/HCs/HC_single_2020_2024.csv",
    "2020_2024_single/SCI/SCI_single.csv",
)
SOURCE = "NyayaAnumana (L-NLProc/NyayaAnumana-Classification-Data, test/2020_2024_single)"

# The offences this project covers (CLAUDE.md Section 4 rule 2), as the IPC
# sections a court actually charges them under. Deliberately NOT the mapping's
# `in_scope` set: that was chosen by a title regex and carries strays such as
# s439 (running a vessel aground) and s124 (assaulting the President).
OFFENCE_FAMILIES = {
    "theft": {"378", "379", "380", "381", "382"},
    "hurt_assault": {"319", "321", "322", "323", "324", "325", "326", "351", "352"},
    "cheating": {"415", "416", "417", "418", "419", "420"},
    # Criminal breach of trust: charged alongside cheating (420/406) so often
    # that excluding it would cut the cheating set in half, and the Phase 2
    # test set pairs it against theft-by-servant as a discriminator.
    "breach_of_trust": {"405", "406", "407", "408", "409"},
}
CORE_SECTIONS = set().union(*OFFENCE_FAMILIES.values())
MAPPING = ROOT / "data" / "mappings" / "ipc_bns_map.json"


def core_sections_bns(mapping_path=MAPPING):
    """BNS successors of CORE_SECTIONS, for the BNS-only route.

    Read from the VERIFIED mapping, never typed from memory -- and never from
    ipc_bns_candidates.json, which is unverified machine output. An unmapped
    core section is an error: it would silently narrow the BNS filter.
    """
    import json

    entries = json.loads(mapping_path.read_text(encoding="utf-8"))["entries"]
    missing = sorted(CORE_SECTIONS - set(entries))
    if missing:
        raise ValueError(f"core IPC sections absent from {mapping_path.name}: {missing}")
    return {entries[s]["bns_section"] for s in CORE_SECTIONS
            if entries[s]["decision"] != "none"}

# Common intention (s34 / BNS s3(5)) is in scope, but it never stands alone: it
# attaches to some substantive offence, and letting it qualify a judgment by
# itself would pull in every "302/34" murder. It rides along with the above.

# A judgment that cites a core section once in passing -- a service matter
# recalling an old 420 FIR -- is not a criminal judgment about it. Measured: of
# 3,005 rows citing a core section, 1,073 mention "accused" fewer than 3 times.
MIN_ACCUSED_MENTIONS = 3

COURTS = {
    "Supreme_Court": "Supreme Court of India",
    "Allahabad_HC": "Allahabad High Court",
    "Andhra_HC": "Andhra Pradesh High Court",
    "Bombay_HC": "Bombay High Court",
    "CG_HC": "Chhattisgarh High Court",
    "Delhi_HC": "Delhi High Court",
    "Guwahati_HC": "Gauhati High Court",
    "Gujarat_HC": "Gujarat High Court",
    "Himachal_Pradesh_HC": "Himachal Pradesh High Court",
    "J_K_HC": "High Court of Jammu & Kashmir and Ladakh",
    "Jharkhand_HC": "Jharkhand High Court",
    "KA_HC": "Karnataka High Court",
    "Kerala_HC": "Kerala High Court",
    "Kolkata_HC": "Calcutta High Court",
    "Madras_HC": "Madras High Court",
    "Manipur_HC": "Manipur High Court",
    "Meghalaya_HC": "Meghalaya High Court",
    "MP_HC": "Madhya Pradesh High Court",
    "Orissa_HC": "Orissa High Court",
    "Patna_HC": "Patna High Court",
    "Punjab_HC": "Punjab and Haryana High Court",
    "Rajasthan_HC": "Rajasthan High Court",
    "Sikkim_HC": "Sikkim High Court",
    "Telangana_HC": "Telangana High Court",
    "Tripura_HC": "Tripura High Court",
    "Uttarakhand_HC": "Uttarakhand High Court",
}
_FILENAME = re.compile(r"^(?P<court>.+)_(?P<year>\d{4})_(?P<n>\d+)$")

# Page furniture, measured per court. The text has been flattened, so these sit
# mid-sentence rather than on lines of their own and have to be cut out of the
# flow. Only anchored forms are removed -- "reported in 1988 KLJ at Page 181" is
# a real pinpoint citation and must survive, hence "Page N of M", never "Page N".
_FURNITURE = re.compile(
    r"\(?Downloaded on(?:\s*-\s*|\s+at\s+|\s+)"
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\w{3}\s+\d{1,2}\s+)?[\d:-]*"
    r"(?:\s*(?:[AP]M|IST))?\)?(?:\s+\d{4}\b)?"                      # Punjab, Gujarat, HP, Rajasthan
    r"|Uploaded on\s*-?"                                           # Bombay
    r"|Page\s*-?\s*\d+\s*-?\s*(?:of|/)\s*\d+"                      # Page 9 of 44, Page 4/12
    r"|\(\d+ of \d+\)"                                             # Rajasthan (10 of 15)
    r"|\b\d+\s?/\s?\d+\s+https\s+judis/?|https\s+judis/?"          # Madras
    r"|Signature Not (?:Verified|signed)"                          # Delhi, MP
    # Orissa doubles it: "Digitally Signed Signed by NAME Designation X Reason"
    r"|Digitally [Ss]igned\s*(?:[Ss]igned\s*)?[Bb]y\s*(?:[A-Z][A-Z.]*\b\s?){1,4}"
    r"(?:Designation\s+\w+\s*)?(?:Reason\b)?"
    r"|\bSigning\s+(?:Date\s*)?\d{4,6}\b"
    r"|This is a digitally signed Judgement\.?"
    r"|NEUTRAL CITATION(?: NO)?"
)

def clean(text):
    text = repair_ligatures(str(text))
    text = _FURNITURE.sub(" ", text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _shingles(text, n=8, mod=16):
    """Sampled word 8-gram hashes, for near-duplicate detection.

    Sampling by hash (keep h % 16 == 0) is consistent across documents, so two
    copies of one judgment keep the SAME subset -- which is what lets a 1-in-16
    sample stand in for the whole set. Only alphabetic words of 3+ letters are
    used: the two sources differ in exactly the tokens scrubbing touched
    (names, dates, numbers), and those must not decide whether texts match.
    """
    words = re.findall(r"[a-z]{3,}", text.lower())
    out = set()
    for i in range(len(words) - n):
        h = zlib.crc32(" ".join(words[i:i + n]).encode())
        if h % mod == 0:
            out.add(h)
    return out


class DuplicateIndex:
    """Which vanga SC judgment, if any, a NyayaAnumana row is a copy of.

    Scored by containment in the SINGLE best-matching judgment, not in the
    corpus as a whole. Against the union, High Court judgments -- which cannot
    be copies of SC ones -- scored as high as 0.5, because they quote Supreme
    Court passages at length. Against the best single document the two
    populations separate cleanly (measured 2026-09-26): SC rows cluster at
    0.4-0.8 or below 0.2, while of 3,000 HC rows only 6 reach 0.4 and none 0.6.
    """

    THRESHOLD = 0.35

    def __init__(self):
        self.inv = {}

    def add(self, doc_id, text):
        for h in _shingles(text):
            self.inv.setdefault(h, set()).add(doc_id)

    def match(self, text):
        s = _shingles(text)
        if not s:
            return None, 0.0
        hits = Counter(d for h in s for d in self.inv.get(h, ()))
        if not hits:
            return None, 0.0
        doc, n = hits.most_common(1)[0]
        return doc, n / len(s)


def _route(corpus_hint):
    if corpus_hint == ["ipc"]:
        return "pre"
    if corpus_hint == ["bns"]:
        return "post"
    return None


def select(text, index, core_bns):
    """Decide whether a row belongs in the subset. Returns (route, sections, reason).

    `route` is "pre" / "post" / None; `reason` names the rule that rejected it.
    Sections are extracted against the ONE code the judgment applies -- never
    the IPC/BNS union (Known Gotchas) -- which is also why a judgment citing
    both codes is rejected rather than validated against both.
    """
    corpus = detect_corpus(text)
    route = _route(corpus)
    if route is None:
        return None, [], "no_code" if not corpus else "both_codes"
    code = "ipc" if route == "pre" else "bns"
    sections = extract_sections(text, index[code])
    core = CORE_SECTIONS if code == "ipc" else core_bns
    if not any(s in core for s in sections):
        return None, sections, "no_core_offence"
    if len(re.findall(r"\baccused\b", text, re.I)) < MIN_ACCUSED_MENTIONS:
        return None, sections, "not_criminal"
    return route, sections, None


def iter_rows(members=MEMBERS):
    """(filename, text, label) from the zip, streamed -- never extracted to disk.

    csv.field_size_limit is raised because a judgment is one field and some
    exceed the default 128KB.
    """
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    with zipfile.ZipFile(ZIP) as z:
        for member in members:
            with z.open(member) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
                for row in reader:
                    yield row["filename"], row["text"], int(row["label"])


def chunk_row(filename, text, label, sections, code):
    """Schema-valid chunks for one selected row."""
    m = _FILENAME.match(filename)
    if not m:
        raise ValueError(f"unexpected NyayaAnumana filename {filename!r}")
    court_key = m.group("court")
    if court_key not in COURTS:
        # Loud: an unknown court is a new source shape, not something to
        # paper over with the raw key.
        raise ValueError(f"unknown court {court_key!r} in {filename!r}")

    text = clean(text)
    parts, hard = chunk_text(text)
    chunks = []
    for i, part in enumerate(parts):
        local = [s for s in sections if s in extract_sections(part, set(sections))]
        chunks.append({
            "chunk_id": f"na_{filename}_p{i}",
            "doc_id": f"na_{filename}",
            "doc_type": "judgment",
            "text": part,
            "source": SOURCE,
            "court": COURTS[court_key],
            "date": None,
            "sections_involved": local or sections,
            "case_id": None,
            "citation": None,
            "title": None,
            # Same vocabulary as the vanga metadata, so Node 5 reads one field.
            "disposal_nature": "Allowed" if label == 1 else "Dismissed",
            "para_index": i,
            "is_headnote": False,
            "corpus_hint": code,
            "decision_year_min": int(m.group("year")),
            "outcome_label": label,
        })
    return chunks, hard


def text_digest(text):
    return hashlib.sha1(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()

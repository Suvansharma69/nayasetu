r"""Build data/mappings/first_schedule.json: how each offence is classified --
cognizable or not, bailable or not, and by what court it is triable.

Sources, read from the PDFs' own text layer by position -- never typed in,
never from memory (CLAUDE.md Known Gotchas: statutory text is only ever
transcribed from the real source with provenance); sha256 of each recorded:

* bns: the BNSS, 2023 as published in the Gazette of India (MHA copy,
  data/raw/schedules/bnss_gazette.pdf), THE FIRST SCHEDULE, Part I
  "Offences under the Bharatiya Nyaya Sanhita".
* ipc: the CrPC, 1973, THE FIRST SCHEDULE, Part I (CRPF copy of the India Code
  text, data/raw/schedules/crpc_crpf.pdf). India Code itself times out from this
  network; MHA's copy is a 2007 export that predates the 2013 amendments; the
  Maharashtra Police copy's TLS certificate is revoked. The CRPF copy has the
  2013 amendments but not 2018's (376AB, 376DA, 376DB): those show as absent.

Both tables have six columns (section, offence, punishment, cognizable,
bailable, court). Plain text extraction interleaves them, so words are assigned
to a column by x position and to a row by the section number that opens it
(rows run across page breaks). The build refuses to write if any row lacks a
classification, has one that is not in the Schedules' vocabulary, or the
section numbers do not run in order.

Run:  venv\Scripts\python.exe scripts\build_schedule.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "raw" / "schedules" / "bnss_gazette.pdf"
OUT = ROOT / "data" / "mappings" / "first_schedule.json"
URL = "https://www.mha.gov.in/sites/default/files/2024-04/250884_2_english_01042024.pdf"
CRPC_PDF = ROOT / "data" / "raw" / "schedules" / "crpc_crpf.pdf"
CRPC_URL = "https://crpf.gov.in/writereaddata/images/pdf/crpc1973.pdf"

COLS = ("section", "offence", "punishment", "cognizable", "bailable", "triable")
# Left edges of the BNSS columns' text, measured on the schedule pages (x0 in pt):
# section 57.6, offence 93.6, punishment 192.5, cognizable 285.6, bailable 369.5,
# court 453.4. A word belongs to the column whose left edge it is right of.
EDGES = (0, 90, 190, 283, 366, 450)
_REF = re.compile(r"^\d{1,3}[A-Z]{0,3}(?:\s?\(\w{1,3}\))*$")
_HEADER = {"Section", "Offence", "Punishment", "Cognizable", "Bailable", "By", "what", "Court", "triable",
           "or", "Non-", "cognizable", "bailable"}
_DITTO = {"Ditto", "Ditto.", "Do.", "Do"}
# Words that open a value in the cognizable (3) and bailable (4) columns.
_STARTS = {3: {"Ditto", "Cognizable", "Non-cognizable", "According"},
           4: {"Ditto", "Bailable", "Non-bailable", "According"}}


def column(x0, edges=EDGES):
    return max(i for i, e in enumerate(edges) if x0 >= e)


def unmark(t):
    """Drop amendment markers: the CrPC text brackets amended words with a
    footnote number -- "1[195A", "2[Non-cognizable]", "Ditto]"."""
    return re.sub(r"(?<![\w(])\d{1,2}\[", "", t).replace("]", "").replace("[", "")


def clean(words):
    t = " ".join(words) if isinstance(words, list) else words
    t = unmark(t)
    t = re.sub(r"(\w)- (\w)", r"\1-\2", t)          # "Non- cognizable" -> "Non-cognizable"
    t = t.replace("�", "-").replace("—", "-")
    t = re.sub(r"\.{2,}$", ".", re.sub(r"\s+", " ", t).strip())   # "class.." -> "class."
    return t


def flag(text, word):
    """"yes" | "no" | "depends" (on the offence abetted/attempted...) | "conditional"."""
    t = text.lower()
    if t.startswith("according as"):
        return "depends"
    if t.startswith(f"non-{word}"):
        return "no"
    if t.startswith(word):
        return "conditional" if re.search(r"\bif\b|\bonly\b", t) else "yes"
    return None


# --- BNSS, 2023 -------------------------------------------------------------------------

def page_edges(words):
    """Column edges measured on this page. They drift by up to ~16pt between
    pages (cognizable starts at 285.6 on p158 but 301 on p188, where punishment
    text reaches 285), so one fixed set misfiles words. Each classification
    column starts where its own vocabulary starts on the page."""
    def left(vocab, lo, hi):
        xs = [w[0] for w in words if lo < w[0] < hi and w[4].rstrip(".") in vocab]
        return min(xs) - 2 if xs else None
    cog = left({"Cognizable", "Non-cognizable", "According"}, 270, 340)
    bail = left({"Bailable", "Non-bailable", "According"}, 355, 420)
    court = left({"Any", "Magistrate", "Court", "The"}, 440, 480)
    return (0, 90, 190, cog or EDGES[3], bail or EDGES[4], court or EDGES[5])


def rows_from(doc, first, last):
    rows, cur = [], None
    for pno in range(first, last):
        page = doc[pno]
        # The running header ("166 THE GAZETTE OF INDIA EXTRAORDINARY [Part II"
        # and its rule) sits at y 44-50; its page number would open a phantom row.
        words = sorted((w for w in page.get_text("words") if 70 < w[1] < 800),
                       key=lambda w: (round(w[1], 1), w[0]))
        edges = page_edges(words)
        col = lambda w: column(w[0], edges)  # noqa: E731
        lines = {}
        for w in words:
            lines.setdefault(round(w[1]), []).append(w)
        for y in sorted(lines):
            ws = sorted(lines[y], key=lambda w: w[0])
            text = " ".join(w[4] for w in ws)
            if "OFFENCES AGAINST OTHER LAWS" in text.upper():
                return rows
            if [w[4] for w in ws] == ["1", "2", "3", "4", "5", "6"]:
                continue                    # the column-number row, repeated on every page
            sec_words = [w[4] for w in ws if col(w) == 0]
            if pno == first and (text.startswith(("THE FIRST", "CLASSIFICATION", "EXPLANATORY", "(1)", "(2)",
                                                  "intended", "third", "Nyaya", "does not", "may arrest", "shall not",
                                                  "I.")) or all(w[4] in _HEADER or w[4].isdigit() and len(w[4]) == 1
                                                                for w in ws)):
                continue
            ref = " ".join(sec_words).strip()
            if sec_words and _REF.match(ref.replace(" (", "(")):
                cur = {c: [] for c in COLS}
                cur["section"] = [ref.replace(" ", "")]
                cur["page"] = pno + 1
                rows.append(cur)
                ws = [w for w in ws if col(w) != 0]
            if cur is None:
                continue
            # One numbered row can hold several sub-rows ("303(2) Theft." and, below
            # it, "Where value of property is less than 5,000 rupees" with its own
            # classification). A fresh classification starting in the cognizable
            # column, when this row already has one, opens the next sub-row.
            cog = [w[4] for w in ws if col(w) == 3]
            if cog and cog[0].startswith(("Cognizable", "Non-cognizable", "According")) and cur["cognizable"]:
                cur = {**{c: [] for c in COLS}, "section": cur["section"], "page": pno + 1, "sub": True}
                rows.append(cur)
            for w in ws:
                cur[COLS[col(w)]].append(w[4])
    return rows


def bns_rows():
    import pymupdf

    if not PDF.exists():
        sys.exit(f"missing {PDF}; download it from {URL}")
    doc = pymupdf.open(PDF)
    start = next(i for i in range(doc.page_count) if "CLASSIFICATION OF OFFENCES" in doc[i].get_text().upper()
                 and "FIRST SCHEDULE" in doc[i].get_text().upper())
    rows = rows_from(doc, start, doc.page_count)
    return rows, {"document": "Bharatiya Nagarik Suraksha Sanhita, 2023, First Schedule Part I (Gazette of India, MHA copy)",
                  "url": URL, "sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(),
                  "pages": f"{start + 1}-{rows[-1]['page']}"}


# --- CrPC, 1973 -------------------------------------------------------------------------

def crpc_edges(words):
    """Column edges for one CrPC schedule page. Values are centred in their
    columns (Non-cognizable at 357, Cognizable at 373), so each edge is where that
    column's vocabulary -- Ditto included -- starts on the page."""
    def left(vocab, lo, hi, default):
        # unmark: "2[Non-cognizable]" (p174) starts the column at 353
        xs = [w[0] for w in words if lo < w[0] < hi and unmark(w[4]).rstrip(".") in vocab]
        return (min(xs) - 2) if xs else default
    cog = left({"Ditto", "Cognizable", "Non-cognizable", "According"}, 330, 400, 345)
    bail = left({"Ditto", "Bailable", "Non-bailable", "According"}, 415, 470, 426)
    court = left({"Ditto", "Any", "Magistrate", "Court", "The"}, 460, 530, 498)   # 474 on p174, ~500 elsewhere
    # pp191-193 sit further left: offences at x 77, punishments at 221 (vs 86/248).
    pun = left({"Imprisonment", "Fine", "Simple", "Death", "Death,", "Rigorous", "The", "Same"}, 200, 262, 240)
    offence = 72 if any(70 < w[0] < 80 for w in words) else 80
    return (0, offence, pun, cog, bail, court)


def crpc_rows():
    """Rows of Part I, Ditto resolved. Two quirks of this layout:
    * "Ditto" is set ~3pt ABOVE the first line of the row it belongs to, so
      words within 4pt are merged into one logical line before rows are cut;
    * an unnumbered row ("If not committed.") inherits the section above, and
      opens wherever a classification column that already has a value gets a
      new one."""
    import pymupdf

    if not CRPC_PDF.exists():
        sys.exit(f"missing {CRPC_PDF}; download it from {CRPC_URL}")
    doc = pymupdf.open(CRPC_PDF)
    # The table of contents (p18) also names the First Schedule; the Schedule
    # itself is the page that opens with its EXPLANATORY NOTES (p167).
    first = next(i for i in range(doc.page_count) if "THE FIRST SCHEDULE" in doc[i].get_text()
                 and "EXPLANATORY NOTES" in doc[i].get_text())
    rows, cur, done = [], None, False
    for pno in range(first, doc.page_count):
        page = doc[pno]
        words = [w for w in page.get_text("words") if 60 < w[1] < 735]   # page numbers sit at ~y 40 and 746
        if not words:
            continue
        edges = crpc_edges(words)
        col = lambda w: column(w[0], edges)  # noqa: E731
        # Drop non-table lines BEFORE merging near lines, or a heading's second
        # line ("OF HUSBAND", p191) merges into the Ditto 3pt below it.
        raw = {}
        for w in words:
            raw.setdefault(round(w[1]), []).append(w)
        kept = []
        for y in sorted(raw):
            ws = sorted(raw[y], key=lambda w: w[0])
            text = " ".join(w[4] for w in ws)
            if "AGAINST OTHER LAWS" in text.upper():
                done = True                 # Part II begins: offences under other laws
                break
            if re.match(r"\d{1,2}\s?\.\s+(Subs|Ins|Omitted|Added|Rep|The words)\b", text):
                break                       # footnotes ("1. Subs. by Act 25 of 2005, ...") to the page foot
            if text.startswith("CHAPTER") or (all(re.fullmatch(r"[A-Z][A-Z.,\-]+", w[4]) for w in ws)
                                              and not any(col(w) == 0 for w in ws)):
                continue                    # a chapter heading, or its wrapped second line
            kept += ws
        lines = []
        for w in sorted(kept, key=lambda w: (w[1], w[0])):
            if lines and w[1] - lines[-1][0] <= 4:
                lines[-1][1].append(w)
            else:
                lines.append([w[1], [w]])
        for _, ws in lines:
            ws.sort(key=lambda w: w[0])
            text = " ".join(w[4] for w in ws)
            if "AGAINST OTHER LAWS" in text.upper():
                done = True
                break
            if [w[4] for w in ws] == ["1", "2", "3", "4", "5", "6"]:
                continue
            sec = [w for w in ws if col(w) == 0]
            ref = unmark("".join(w[4] for w in sec))
            if sec and _REF.match(ref):
                cur = {**{c: [] for c in COLS}, "section": [ref], "page": pno + 1}
                rows.append(cur)
                ws = [w for w in ws if col(w) != 0]
            elif cur is not None:
                # Only a word that STARTS a value opens a sub-row; "abetted is
                # cognizable / or non-cognizable." is one value wrapped over lines.
                starts = {COLS[col(w)] for w in ws if col(w) in (3, 4) and w[4].rstrip(".") in _STARTS[col(w)]
                          and w is min((x for x in ws if col(x) == col(w)), key=lambda x: x[0])}
                if any(cur[c] for c in starts):
                    cur = {**{c: [] for c in COLS}, "section": cur["section"], "page": pno + 1, "sub": True}
                    rows.append(cur)
            if cur is None:
                continue                    # the explanatory notes before the first row
            for w in ws:
                cur[COLS[col(w)]].append(w[4])
        if done:
            break
    # Resolve Ditto top-down: it repeats the value of the row above in that column.
    prev = None
    for r in rows:
        for c in COLS[1:]:
            v = clean(r[c])
            if v.rstrip(". ") in {"Ditto", "Do"}:    # also "Ditto.." as printed on some rows
                v = prev[c] if prev else ""
            r[c] = v
        prev = r
    return rows, {"document": "Code of Criminal Procedure, 1973, First Schedule Part I (CRPF copy of the India Code "
                              "text, as amended to 2013; the 2018 rows 376AB, 376DA, 376DB are not in it)",
                  "url": CRPC_URL, "sha256": hashlib.sha256(CRPC_PDF.read_bytes()).hexdigest(),
                  "pages": f"{first + 1}-{rows[-1]['page']}"}


# --- both ---------------------------------------------------------------------------------

# Cells that are defective IN THE SOURCE, checked by reading the page. They are
# kept as printed and flagged "unclear" -- never corrected from memory.
SOURCE_DEFECTS = {
    ("ipc", "195", "bailable"): "blank in the CRPF copy of the Schedule (p174)",
    ("ipc", "195A", "bailable"): "'Ditto' of a cell that is blank in the CRPF copy (p174)",
    ("ipc", "222", "bailable"): "the CRPF copy prints 'Non-cognizable' in the bailable column (p176)",
}


def validate(rows, code):
    """Rows -> ({section: [entries]}, problems). The same checks for both codes."""
    out, problems, last = {}, [], 0
    for r in rows:
        ref = r["section"][0]
        num = int(re.match(r"\d+", ref).group())
        entry = {c: clean(r[c]) for c in COLS[1:]}
        # A long condition in the cognizable column (BNS 85) wraps into the
        # bailable column's x range; the bailable value itself is one word.
        m = re.match(r"(Non-bailable|Bailable)\.?", entry["bailable"])
        if m:
            entry["bailable"] = m.group(1) + "."
        entry["cognizable_flag"] = flag(entry["cognizable"], "cognizable")
        entry["bailable_flag"] = flag(entry["bailable"], "bailable")
        entry["ref"], entry["page"] = ref, r["page"]
        sec_key = re.match(r"\d{1,3}[A-Z]{0,3}", ref).group()
        for c in ("cognizable", "bailable"):
            why = SOURCE_DEFECTS.get((code, sec_key, c))
            if why and (not entry[c] or entry[f"{c}_flag"] is None):
                entry[f"{c}_flag"], entry[f"{c}_note"] = "unclear", why
        for c in ("cognizable", "bailable", "triable"):
            if not entry[c] and not entry.get(f"{c}_note"):
                problems.append(f"{code} {ref} (p{r['page']}): empty {c}")
        for c in ("cognizable", "bailable"):
            if entry[c] and entry[f"{c}_flag"] is None:
                problems.append(f"{code} {ref} (p{r['page']}): unreadable {c}: {entry[c][:60]!r}")
        if num < last:
            problems.append(f"{code} {ref} (p{r['page']}): out of order after {last}")
        # A punishment word inside the offence column means the column edges
        # were wrong on that page (pp191-193 once swallowed IPC 504-511 this way).
        if re.search(r"\b(Imprisonment|Rigorous imprisonment)\b", entry["offence"]):
            problems.append(f"{code} {ref} (p{r['page']}): punishment text in the offence column: {entry['offence'][:60]!r}")
        last = num
        sec = re.match(r"\d{1,3}[A-Z]{0,3}", ref).group()
        out.setdefault(sec, []).append(entry)
    return out, problems


def main():
    payload = {"_README": ["Built by scripts/build_schedule.py from the official First Schedules. Do not edit by hand.",
                           "bns: BNSS, 2023 First Schedule Part I. ipc: CrPC, 1973 First Schedule Part I.",
                           "Per section: one entry per row of the Schedule (a section can have several, by "
                           "sub-section or aggravation). The Schedules' own note: columns 2-3 indicate the substance "
                           "of the section, not its definition or punishment.",
                           "Central schedules only: State amendments to the classification are NOT reflected."],
               "source": {}}
    problems = []
    for code, build in (("bns", bns_rows), ("ipc", crpc_rows)):
        rows, source = build()
        out, probs = validate(rows, code)
        print(f"{code}: {len(rows)} rows, {len(out)} sections, pages {source['pages']}")
        problems += probs
        payload[code], payload["source"][code] = out, source
    if problems:
        print("\n".join(problems[:60]))
        sys.exit(f"{len(problems)} problems: not written")
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

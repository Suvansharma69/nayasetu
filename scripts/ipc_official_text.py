"""Read the official IPC text and complete the sections civictech cut short.

civictech's ipc.json (the IPC corpus source) carries only the operative
paragraph of each section and, for many, not even all of that: s300 stops at
"culpable homicide is murder" before its four clauses and five Exceptions,
s506 at "or with both;" before the threat-to-kill limb (7 years), s307 before
the life-convict clause. That text feeds retrieval, the Node 2b judge, Node 4
and the section drawer.

The source here is the Legislative Department text republished by Goa Police
- the same file, same sha256, that s304B was patched from. It is a 1997
consolidation (the latest amending Act its footnotes cite is of 1997), so it is
OLDER than civictech for every section amended since (IT Act 2000/2008, the
2005, 2013 and 2018 amendments). Two rules keep that from doing harm:

  1. A section is completed only where civictech's text is, word for word, the
     START of the official text (>= 95% of its words matched, in order, from
     the official's first word). Where the two disagree, civictech is the newer
     text and is left alone.
  2. POST_1997 lists sections amended after 1997 whose civictech text could
     still pass rule 1 because only the part civictech dropped was amended.

Text is EXTRACTED, never retyped: lines joined, amendment markers ('3*[',
']', '3* * *') and footnotes removed, marginal sub-headings removed, exactly
as for the s304B patch. Illustrations are dropped (civictech never carries
them, and they would swamp a section's embedding, as the BNS's inlined ones
do); Explanations, Exceptions and provisos are kept, because they are the law.

    python scripts/ipc_official_text.py --report          # what would change
    python scripts/ipc_official_text.py --show 300 506    # read sections
    python scripts/ipc_official_text.py --write-patches   # statute_patches.json
"""
import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "raw" / "statutes" / "ipc_official" / "ipc_goa.pdf"
URL = ("https://citizen.goapolice.gov.in/documents/10184/1794152/ipc.pdf/"
       "f7f2c816-63fe-450f-8874-0a5552959c45")
SHA256 = "576a485b22bea6127c51f8cf8e646a320ee902008b32ee0ec4dae5f28ff30511"
SOURCE = ("The Indian Penal Code, 1860 (Act No. 45 of 1860), Legislative "
          "Department consolidated text (amended to 1997) as republished by "
          "Goa Police: " + URL + " (fetched 2026-10-07, sha256 " + SHA256 +
          ", PDF page {page}).")
CIVICTECH = ROOT / "data" / "raw" / "statutes" / "ipc.json"
PATCHES = ROOT / "data" / "mappings" / "statute_patches.json"

# Sections whose civictech text passes the prefix rule but which were amended
# after 1997 in the part civictech dropped (or might have been). Listed from
# knowledge of the amending Acts, not from a source text - so it errs wide:
# leaving a section short costs a little recall, completing it with
# superseded law would put wrong law in front of a lawyer.
POST_1997 = {
    "4": "IT (Amendment) Act 2008 added clause (3) (computer resource in India)",
    "40": "the list of sections in its second paragraph may postdate 1997",
    "100": "Criminal Law (Amendment) Act 2013 added clause Seventhly (acid)",
    "118": "IT (Amendment) Act 2008 added 'or by the use of encryption'",
    "119": "IT (Amendment) Act 2008 added 'or by the use of encryption'",
    "120": "precaution: sibling of 118/119",
}
# Gap-rule rejections that were READ (2026-10-07) and found clean. Every other
# gap stays rejected: s221's block was found to end with s222's last limb, s405's
# was cut before its Explanation 2 by a stray '2.' line, s171H's holds all of
# s171I, s214's runs into s216.
REVIEWED_GAPS = {
    "29": "next is s29A, inserted by the IT Act 2000: not in this source",
    "174": "next is s174A, inserted in 2005: not in this source",
    "109": "block ends at s109's own Explanation; s110 cut by the section rule",
    "131": "block ends at s131's own Explanation",
    "366": "s366A's head is glued to s366's last line; text ends at s366",
    "415": "block ends at s415's own Explanation",
}
MIN_PREFIX = 0.95         # share of civictech's words found, in order
MIN_EXTRA = 3              # official words beyond civictech's last one

_RULE = re.compile(r"^\s*-{10,}\s*$")
_PAGE_NO = re.compile(r"^\s*\d{1,3}\s*$")
# A line holding only 'N.' is either a margin head (followed, after blank
# lines, by the bare title) or a body number (followed at once by
# 'Title.--text'). The source mis-numbers s54's body as '55.', so treating
# both as heads would start a phantom s55 holding s54's text.
_NUMBER_LINE = re.compile(r"^\s*(\d{1,3}[A-Z]{0,2})\.\s*$")
_CHAPTER = re.compile(r"^\s*CHAPTER\s+[IVXL]+[A-Z]?\s*$")
# The source misspells it: 'Iiiustration' (s166, s364), 'Illustriations' (s330).
_ILLUSTRATION = re.compile(r"^[IiLl1]{2,4}ustr\w*\b")
_ILLUS_INLINE = re.compile(r"(?<=[.:])\s+(?=[IiLl1]{2,4}ustr\w*\b)")
# '3*[', '5[', '1***', '3* * * * *', a bare '1*' reference, and the closing ']'.
_MARKER = re.compile(r"\d+\*+\[|(?<![\w(])\d+\[|\s?\d+\*(?:\s?\*)+"
                     r"|(?<=\S)\s?\d+\*(?=\s|$)|[\[\]]")
# A footnote that escaped the dashed rule (it sits at a page foot without one).
_FOOTNOTE = re.compile(r"^\d+\.?\s+(Subs\.|Ins\.|Rep\.|Omitted|Added|The words"
                       r"|Cl\.|S\.\s)|\bby Act \d+ of \d{4}\b")
# A body paragraph opening with a section number is the NEXT section, run on
# because its margin head was glued to the previous line ('...fine. 210.').
_SECTION_OPEN = re.compile(r"^(\d{1,3}[A-Z]{0,2})\.\s+\S")
_RESUMES = re.compile(r"^(Exception|Explanation|Provided|First\.|Secondly|"
                      r"Thirdly|Fourthly|Fifthly|The above exception)", re.I)
# A marginal sub-heading set inline, twice: 'if a capital offence; if a
# capital offence.--shall, if the offence...'.
_INLINE_SUBHEAD = re.compile(r"\s?([^.;\n]{3,110}?)[.;]\s*\1[.;]?\s?-{1,2}\s?")


def pdf_lines(pdf=PDF):
    """(page, line) for every body line, footnotes and page numbers removed."""
    import pymupdf
    doc = pymupdf.open(pdf)
    out = []
    for p in range(doc.page_count):
        in_notes = False
        for line in doc[p].get_text().split("\n"):
            if _RULE.match(line):
                in_notes = True          # footnotes run to the page number
                continue
            if _PAGE_NO.match(line):
                in_notes = False
                continue
            if not in_notes:
                out.append((p + 1, line.rstrip()))
    return out


def _paragraphs(lines):
    """Join PDF lines into paragraphs; blank lines separate paragraphs."""
    paras, cur = [], []
    for line in lines:
        if line.strip():
            cur.append(line.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    out = []
    for p in paras:
        # Collapse first: '3*   *   *' spaces its omission stars widely.
        p = re.sub(r"-{10,}.*$", "", re.sub(r"\s+", " ", p))  # inline footnotes
        p = re.sub(r"\s+", " ", _MARKER.sub("", p)).strip()
        if not p or (len(p) < 300 and _FOOTNOTE.search(p)):
            continue
        if out and p[0].islower():
            # A stray blank line mid-sentence ('...the commission\n\nof an
            # offence'): a paragraph never opens in lower case.
            out[-1] += " " + p
            continue
        out.append(p)
    return [q for p in out for q in _ILLUS_INLINE.split(p)]


def _glued(para, head):
    return bool(re.match(re.escape(head.rstrip(". ")) + r"\.\s?-{1,2}", para))


def _drop_illustrations(paras):
    """Remove Illustrations blocks but keep what follows them.

    s300's Exceptions come AFTER its Illustrations, each with illustrations of
    its own, so cutting at the first 'Illustrations' would drop the Exceptions
    - the law a defence rests on. A block runs from the heading to the next
    Exception/Explanation/proviso paragraph.
    """
    out, skipping = [], False
    for p in paras:
        if _ILLUSTRATION.match(p):
            skipping = True
            continue
        if skipping and _RESUMES.match(p):
            skipping = False
        if not skipping:
            out.append(p)
    return out


def _drop_subheadings(paras):
    """Remove marginal sub-headings, which are notes, not provision text.

    Two layouts: a bare heading paragraph repeated glued to its text
    ('If threat be ... etc.' then 'If threat be ... etc.--and if the threat'),
    and a heading set inline twice ('if a capital offence; if a capital
    offence.--shall, if').
    """
    heads = {p for p in paras if any(q != p and _glued(q, p) for q in paras)}
    out = []
    for p in paras:
        if p in heads:
            continue
        for h in heads:
            if _glued(p, h):
                p = re.sub(r"^" + re.escape(h.rstrip(". ")) + r"\.\s?-{1,2}\s?",
                           "", p)
        p = _INLINE_SUBHEAD.sub(" ", p).strip()
        p = re.sub(r"\s+([,;:.])", r"\1", p)
        if out and p[:1].islower():      # the limb a removed heading labelled
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def _is_margin_head(lines, i):
    if not _NUMBER_LINE.match(lines[i][1]):
        return False
    nxt = next((t for _, t in lines[i + 1:i + 8] if t.strip()), "")
    return not re.search(r"\.\s?-", nxt)


def official_sections(pdf=PDF):
    """{section: {"title", "text", "page"}} from the official PDF.

    A section opens at its margin head (a line holding only 'N.') and runs to
    the next one. Inside, the margin title repeats and the body opens with
    'N. Title.--'; the body is everything after the first '.--' / '.-'.
    """
    lines = pdf_lines(pdf)
    heads = [i for i in range(len(lines)) if _is_margin_head(lines, i)]
    out = {}
    for k, i in enumerate(heads):
        sec = _NUMBER_LINE.match(lines[i][1]).group(1)
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        block = [t for _, t in lines[i + 1:end]]
        for j, t in enumerate(block):
            if _CHAPTER.match(t):        # chapter heading before the next head
                block = block[:j]
                break
        joined = "\n".join(_paragraphs(block))
        m = re.search(r"\.\s?-{1,2}\s?", joined)
        if not m:
            continue
        head, body = joined[:m.start()], joined[m.end():]
        title = head.split("\n")[-1]
        title = re.sub(r"^\s*\d{1,3}[A-Z]{0,2}\.\s*", "", title).strip()
        paras = body.split("\n")
        for j, p in enumerate(paras):
            if j and _SECTION_OPEN.match(p):
                # ...and the next section's bare margin title just before it.
                nxt = re.sub(r"^\d{1,3}[A-Z]{0,2}\.\s+", "", p)
                prev = paras[j - 1].rstrip(". ")
                cut = j - 1 if prev and nxt.startswith(prev[:40]) else j
                paras = paras[:cut]
                break
        if paras:                        # '...fine. 210.' - a glued margin head
            paras[-1] = re.sub(r"\s\d{1,3}[A-Z]{0,2}\.$", "", paras[-1])
        paras = _drop_subheadings(_drop_illustrations(paras))
        # Trailing headings: chapter sub-headings ('Of the causing of
        # miscarriage, ...') and anything that does not end like a provision.
        while paras and (not re.search(r"[.;:\)]\s*$", paras[-1])
                         or re.match(r"^Of\s", paras[-1])
                         or _NUMBER_LINE.match(paras[-1])):
            paras.pop()
        nxt = (_NUMBER_LINE.match(lines[heads[k + 1]][1]).group(1)
               if k + 1 < len(heads) else None)
        out[sec] = {"title": title, "text": "\n".join(paras).strip(),
                    "page": lines[i][0], "next": nxt}
    return out


def _tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'"))


def prefix_match(upstream, official):
    """(share of upstream's words matched in order, start, official words
    left over after upstream's last matched word)."""
    a, b = _tokens(upstream), _tokens(official)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    blocks = [x for x in sm.get_matching_blocks() if x.size]
    if not a or not blocks:
        return 0.0, None, len(b)
    matched = sum(x.size for x in blocks)
    return matched / len(a), blocks[0].b, len(b) - (blocks[-1].b + blocks[-1].size)


def is_completion(upstream, official):
    """True if `official` is `upstream` continued: the patch rule."""
    share, start, extra = prefix_match(upstream, official)
    return share >= MIN_PREFIX and start is not None and start <= 2 \
        and extra >= MIN_EXTRA


def load_civictech():
    recs = json.loads(CIVICTECH.read_text(encoding="utf-8"))
    return {str(r["Section"]).strip().upper():
            ((r.get("section_desc") or "").strip(),
             (r.get("section_title") or "").strip())
            for r in recs}


LONG_RUN = 45              # words shared with ONE other section's text


def _added(upstream, official):
    a, b = _tokens(upstream), _tokens(official)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    blocks = [x for x in sm.get_matching_blocks() if x.size]
    return b[blocks[-1].b + blocks[-1].size:] if blocks else b


def intrusion(sec, upstream, official, civic, parsed_next):
    """Why the added text may hold ANOTHER section's words, or None.

    The source skips text in places: s214 runs on into the middle of s216,
    with s215 missing, and the prefix rule cannot see it - s214's start is
    right. Two signals. (1) A gap: the next margin head the parser found is
    not the next section in civictech's order, and the sections in between
    were never parsed, so their text may sit in this block. (2) A long run:
    the addition shares LONG_RUN+ consecutive words with one other section.
    Shorter shared runs are ordinary legal phrasing (s300 and s299 share 'with
    the intention of causing such bodily injury as').
    """
    order = list(civic)
    i = order.index(sec)
    expected = order[i + 1] if i + 1 < len(order) else None
    if parsed_next != expected and expected is not None \
            and sec not in REVIEWED_GAPS:
        return f"block spans unparsed s{expected}"
    added = _added(upstream, official)
    for other, (desc, _) in civic.items():
        if other == sec:
            continue
        ot = _tokens(desc)
        lm = difflib.SequenceMatcher(None, added, ot, autojunk=False) \
            .find_longest_match(0, len(added), 0, len(ot))
        if lm.size >= LONG_RUN:
            return f"shares {lm.size} words with s{other}"
    return None


def completions(official, civic, rejected=None):
    """{section: official record} for every section the patch rule accepts."""
    out = {}
    for sec, (desc, _) in civic.items():
        off = official.get(sec)
        if not (off and desc and sec not in POST_1997
                and is_completion(desc, off["text"])):
            continue
        why = intrusion(sec, desc, off["text"], civic, off.get("next"))
        if why:
            if rejected is not None:
                rejected[sec] = why
            continue
        out[sec] = off
    return out


def write_patches(official, civic, path=PATCHES):
    data = json.loads(path.read_text(encoding="utf-8"))
    ipc = data.setdefault("ipc", {})
    done = completions(official, civic)
    for sec, off in sorted(done.items(), key=lambda kv: _sort_key(kv[0])):
        desc, title = civic[sec]
        tail = re.sub(r"\s+", " ", desc)[-60:]
        ipc[sec] = {
            "section_title": title or off["title"],
            "text": off["text"],
            "source": SOURCE.format(page=off["page"]),
            "mode": "complete",
            "note": ("civictech's text stops at '..." + tail + "'; the official "
                     "text continues. Extracted by scripts/ipc_official_text.py "
                     "(markers, footnotes, marginal sub-headings and "
                     "Illustrations removed; no words changed). Applied only "
                     "while civictech's text is still a prefix of this one."),
        }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return done


def _sort_key(sec):
    m = re.match(r"(\d+)(.*)", sec)
    return (int(m.group(1)), m.group(2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--show", nargs="*", default=[])
    ap.add_argument("--write-patches", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    digest = hashlib.sha256(PDF.read_bytes()).hexdigest()
    if digest != SHA256:
        sys.exit(f"{PDF} sha256 {digest} != {SHA256}: not the recorded file")
    official = official_sections()
    civic = load_civictech()
    print(f"official sections parsed: {len(official)}; civictech: {len(civic)}")
    for s in args.show:
        print(f"== {s} (p{official[s]['page']}) {official[s]['title']!r}")
        print(official[s]["text"])
        print("-- civictech:")
        print(civic[s][0])
        print()
    if args.report:
        rejected = {}
        done = completions(official, civic, rejected)
        print("rejected, addition may hold another section's text:",
              "; ".join(f"{s}: {o}" for s, o in rejected.items()) or "none")
        held = [s for s in POST_1997
                if s in official and is_completion(civic[s][0], official[s]["text"])]
        print(f"would complete {len(done)} sections; held back (POST_1997): {held}")
        for s, off in sorted(done.items(), key=lambda kv: _sort_key(kv[0])):
            _, _, extra = prefix_match(civic[s][0], off["text"])
            print(f"  {s:>5} +{extra:4}w  ...{off['text'][-90:]!r}")
    if args.write_patches:
        done = write_patches(official, civic)
        print(f"wrote {len(done)} completions to {PATCHES}")


if __name__ == "__main__":
    main()

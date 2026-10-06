r"""Statute tools for the web interface: section viewer, IPC <-> BNS comparison,
punishment as the section states it.

Everything here is read from ingested data, never generated:

* a section is shown only if it is a node of the citation graph for that code
  (the same check Node 2 makes -- CLAUDE.md Section 2);
* its counterpart comes from the verified IPC <-> BNS mapping
  (data/mappings/ipc_bns_map.json, all 574 rows reviewed), with that row's note;
* punishment is the section's own sentences that say "shall be punished",
  quoted, plus a maximum/minimum read off those sentences by rule. Where the
  rule cannot read a term it says so rather than guessing.
"""
from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path

from src.graph import citation_graph as cg
from src.pipeline import chargeability
from src.retrieval import ranker

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "data" / "mappings" / "ipc_bns_map.json"
SCHEDULE = ROOT / "data" / "mappings" / "first_schedule.json"
CODES = ("ipc", "bns")


@lru_cache(maxsize=1)
def _mapping():
    return json.loads(MAPPING.read_text(encoding="utf-8"))["entries"]


@lru_cache(maxsize=1)
def _schedule():
    """Classification of offences (cognizable / bailable / triable by), if built
    (scripts/build_schedule.py, from the official First Schedules)."""
    if not SCHEDULE.exists():
        return {}
    return json.loads(SCHEDULE.read_text(encoding="utf-8"))


def schedule_for(code, section):
    """The First Schedule rows for a section, with their source, or None."""
    d = _schedule()
    rows = d.get(code, {}).get(section)
    if not rows:
        return None
    return {"rows": rows, "source": (d.get("source", {}).get(code) or {}).get("document"),
            "caveat": "Central Schedule only: State amendments to the classification are not reflected."}


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


# --- punishment ---------------------------------------------------------------

_NUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
_NUM.update({"thirty": 30, "forty": 40, "fifty": 50})
_TERM = r"((?:\w+[- ])?\w+)\s+(years?|months?|days?)"
# "shall be punished", but also "shall be liable either to imprisonment for life"
# and "he may, if hurt is caused, be punished with death" (BNS 109's aggravated forms, which a
# "shall be punished"-only pattern reads as a 10-year maximum).
_PUNISH = re.compile(r"[^.;]*\b(?:be\s+punish\w*|punishable|shall\s+(?:also\s+)?be\s+liable\s+(?:either\s+)?to"
                     r"\s+(?:imprisonment|death|fine|the\s+punishment))\b[^.;]*", re.I)


def _num(words):
    w = words.lower().replace("-", " ").split()
    if len(w) == 1 and w[0].isdigit():
        return int(w[0])
    total = 0
    for x in w:
        if x not in _NUM:
            return None
        total += _NUM[x]
    return total or None


def _years(n, unit):
    unit = unit.lower()
    return n if unit.startswith("year") else n / 12 if unit.startswith("month") else n / 365


def punishment(text):
    """{"sentences": [verbatim punishing sentences], "max": str|None, "min": str|None}.

    max/min are read only from those sentences: death > imprisonment for life >
    the longest "may extend to N years" term > fine only."""
    t = _clean(text)
    sentences = []
    for m in _PUNISH.finditer(t):
        s = m.group(0).strip(" ,")
        if s and s not in sentences:
            sentences.append(s)
    # Read terms only from what follows the penalty verb: a sentence can also
    # NAME a punishment that is not this one -- BNS 351, "threat to cause an
    # offence punishable with death", carries seven years, not death.
    body = " ".join(m_.group(1) for s_ in sentences for m_ in re.finditer(
        r"(?:be\s+punish\w*|liable\s+(?:either\s+)?to)(.*?)(?=\bpunishable\b|$)", s_.lower()))
    mx = mn = None
    terms = [(_num(n), u) for n, u in re.findall(r"(?:may|shall)\s+extend\s+to\s+" + _TERM, body)]
    terms = [(n, u) for n, u in terms if n]
    if re.search(r"\bwith\s+death\b", body):        # "punished with death", not "likely to cause death"
        mx = "death"
    elif "imprisonment for life" in body:
        mx = "imprisonment for life"
    elif terms:
        n, u = max(terms, key=lambda x: _years(*x))
        mx = f"{n} {u}"
    elif "fine" in body:
        mx = "fine only" if "imprisonment" not in body else None
    lows = [(_num(n), u) for n, u in re.findall(r"not\s+be\s+less\s+than\s+" + _TERM, body)]
    lows = [(n, u) for n, u in lows if n]
    if lows:
        n, u = min(lows, key=lambda x: _years(*x))
        mn = f"{n} {u}"
    return {"sentences": sentences[:6], "max": mx, "min": mn}


def _rank(mx):
    """Order maxima: death > imprisonment for life > N years (by length) > fine only."""
    if not mx:
        return -1
    if mx == "death":
        return 10_000
    if mx == "imprisonment for life":
        return 9_000
    m = re.match(r"(\d+)\s+(year|month|day)", mx)
    return _years(int(m.group(1)), m.group(2)) * 10 if m else 0


def schedule_max(sched):
    """The highest punishment named in a section's First Schedule rows (their
    own wording: "Death, or imprisonment for life", "Imprisonment for 7 years")."""
    best = None
    for r in (sched or {}).get("rows", []):
        t = (r.get("punishment") or "").lower()
        if re.match(r"\s*death\b", t) or re.search(r"\bdeath,? or\b", t):
            cand = "death"
        elif "imprisonment for life" in t:
            cand = "imprisonment for life"
        else:
            yrs = [int(n) for n in re.findall(r"for\s+(?:a\s+term\s+(?:which\s+may\s+extend\s+to\s+)?)?(\d{1,2})\s+years?", t)
                   if not re.search(r"not\s+(?:be\s+)?less\s+than\s+" + n + r"\s+years?", t)]
            cand = f"{max(yrs)} years" if yrs else None
        if cand and _rank(cand) > _rank(best):
            best = cand
    return best


# --- sections -------------------------------------------------------------------

def counterparts(g, code, section):
    """The other code's section(s) under the VERIFIED mapping, each verified in the graph."""
    out = []
    if code == "ipc":
        e = _mapping().get(section)
        if e and e.get("bns_section") and cg.verify_section(g, "bns", e["bns_section"]):
            out.append({"code": "bns", "section": e["bns_section"], "subsection": e.get("bns_subsection"),
                        "title": e.get("bns_title"), "note": e.get("note")})
        elif e and e.get("decision") == "none":
            return [{"code": "bns", "section": None, "note": e.get("note") or "no BNS equivalent (repealed or dropped)"}]
    else:
        for ipc, e in _mapping().items():
            if e.get("bns_section") == section and cg.verify_section(g, "ipc", ipc):
                out.append({"code": "ipc", "section": ipc, "subsection": None, "title": e.get("ipc_title"),
                            "note": e.get("note"), "bns_subsection": e.get("bns_subsection")})
    return out


def section_info(g, code, section):
    """Everything the viewer shows for one section, or None if it is not a real
    section of that code (checked against the graph)."""
    code = (code or "").lower()
    sec = cg.normalise(str(section or "").strip().upper())
    if code not in CODES or sec is None or not cg.verify_section(g, code, sec):
        return None
    rec = ranker._section_record(code, sec)
    text = _clean(rec.get("text"))
    cls, why = chargeability.classify(code, sec)
    sched = schedule_for(code, sec)
    pun = punishment(text)
    # The civictech IPC text is cut short for ~50 sections (IPC 506 ends at
    # "or with both;" and omits the threat-to-kill limb; 307 omits the
    # life-convict clause). The First Schedule lists every limb, so the higher of
    # the two maxima is shown, with where it came from.
    smax = schedule_max(sched)
    pun["text_incomplete"] = bool(re.search(r"[;,:]\s*$", text))
    if smax and _rank(smax) > _rank(pun["max"]):
        pun["max"], pun["max_source"] = smax, "First Schedule (the section text as ingested is shorter)"
    elif pun["max"]:
        pun["max_source"] = "section text"
    return {"code": code, "section": sec, "title": rec.get("section_title") or g.nodes[cg.section_key(code, sec)].get("title"),
            "chapter": rec.get("chapter"), "chapter_title": rec.get("chapter_title"), "text": text,
            "class": cls, "class_why": why, "punishment": pun,
            "schedule": sched, "counterparts": counterparts(g, code, sec)}


# --- comparison -------------------------------------------------------------------

# An Explanation/Illustration block runs until the next numbered sub-section
# ("(2) Whoever commits theft shall be punished ...") or the end. Cutting at the
# first Explanation instead would drop BNS 303(2), the punishment.
_NOTES = re.compile(r"\s(?:Explanation\s*\d*|Illustrations?)\s*[.:—–-].*?(?=\s\(\d+\)\s+[A-Z]|$)", re.S)


def core(text, title=None):
    """The operative provision: without the section number, the title, and the
    Explanations/Illustrations the BNS gazette text inlines (the civictech IPC
    text omits them, so comparing those would show noise, not changes)."""
    t = _clean(text)
    t = re.sub(r"^.{0,120}?Section \d{1,3}[A-Z]{0,3}\s*\(\d+\)\.\s*", "", t)   # sub-section index view header
    t = re.sub(r"^\d{1,3}[A-Z]{0,3}\.\s*", "", t)
    t = _clean(_NOTES.sub(" ", t))  # first: it needs the "(2)" markers to know where a block ends
    # Structure and typography are not changes in the law: sub-section markers,
    # and quote marks (the gazette's curly quotes vs the IPC text's plain ones).
    t = re.sub(r"(^|(?<=[.:;—] ))\(\d+\)\s*", "", t)
    t = re.sub("[\"'‘’“”�]", "", t)
    if title and t.lower().startswith(title.lower()):
        t = t[len(title):].lstrip(" .")
    return re.sub(r"\s+", " ", t).strip()


_TOK = re.compile(r"\w+|[^\w\s]")


def word_diff(a, b):
    """[[op, text], ...] with op in {"eq", "del", "ins"} -- a word-level diff of a -> b."""
    ta, tb = _TOK.findall(a), _TOK.findall(b)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ta, b=tb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(["eq", " ".join(ta[i1:i2])])
        else:
            if i2 > i1:
                out.append(["del", " ".join(ta[i1:i2])])
            if j2 > j1:
                out.append(["ins", " ".join(tb[j1:j2])])
    for seg in out:
        seg[1] = re.sub(r"(\w) - (\w)", r"\1-\2",
                        re.sub(r"\s+([,.;:)\]])", r"\1", re.sub(r"([(\[])\s+", r"\1", seg[1])))
    return out


def _ipc_core(g, ipc):
    """The IPC side of a comparison. The IPC splits many offences into a
    definition (378 theft) and a punishment (379); the BNS merges them into one
    section (303). So the IPC side is definition + punishment, whichever of the
    two was asked for, or the comparison shows a merger as a rewrite."""
    pun = chargeability.punished_by("ipc", ipc["section"])
    defs = [d for d, p in chargeability.pairs("ipc").items() if p == ipc["section"]]
    # Join the two halves only when the BNS merged them (378 and 379 both map to
    # 303). Murder stays split in the BNS too (300 -> 101, 302 -> 103).
    same = lambda a, b: (_mapping().get(a) or {}).get("bns_section") == (_mapping().get(b) or {}).get("bns_section")  # noqa: E731
    parts = [ipc["section"]]
    if pun and cg.verify_section(g, "ipc", pun) and same(ipc["section"], pun):
        parts = [ipc["section"], pun]
    elif defs and cg.verify_section(g, "ipc", defs[0]) and same(defs[0], ipc["section"]):
        parts = [defs[0], ipc["section"]]
    return " ".join(core(ranker._section_record("ipc", s).get("text"), ranker._section_record("ipc", s).get("section_title"))
                    for s in parts)


def compare(g, code, section):
    """IPC section vs its BNS counterpart (or BNS vs its first IPC predecessor)."""
    here = section_info(g, code, section)
    if here is None:
        return None
    others = [c for c in here["counterparts"] if c.get("section")]
    if not others:
        return {"from": here, "to": None, "others": here["counterparts"], "diff": None}
    other = section_info(g, others[0]["code"], others[0]["section"])
    ipc, bns = (here, other) if code == "ipc" else (other, here)
    bns_text, versus = core(bns["text"], bns["title"]), bns["section"]
    sub = others[0].get("subsection") if code == "ipc" else others[0].get("bns_subsection")
    pair = chargeability.punished_by("ipc", ipc["section"]) or any(
        p == ipc["section"] for p in chargeability.pairs("ipc").values())
    if sub and not pair:
        # IPC 420 maps to BNS 318(4); the rest of 318 is 415/417/418 merged in.
        # A section with a definition/punishment pair (378/379 -> 303) is
        # compared whole, since its IPC side is both halves.
        from src.pipeline.applicability import statute_text
        t = statute_text("bns", bns["section"], sub)
        if t and t != bns["text"]:
            bns_text, versus = core(t), sub
    diff = word_diff(_ipc_core(g, ipc), bns_text)
    changed = sum(len(s[1].split()) for s in diff if s[0] != "eq")
    total = sum(len(s[1].split()) for s in diff) or 1
    return {"from": here, "to": other, "others": others, "ipc": ipc["section"], "bns": bns["section"], "versus": versus,
            "diff": diff, "changed_share": round(changed / total, 2),
            "punishment_changed": ipc["punishment"]["max"] != bns["punishment"]["max"]
            or ipc["punishment"]["min"] != bns["punishment"]["min"]}

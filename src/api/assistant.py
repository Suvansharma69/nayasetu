r"""Follow-up questions about a report, and precedent summaries.

Both are RAG over material the system already holds -- no fine-tuning
(CLAUDE.md Section 2) -- and both are checked after generation, the same way
Node 4's output is:

* Follow-up answers use only the report (facts, charges with their statute
  text, doubts, precedents, counter-arguments). Every section the answer
  MENTIONS is then looked up in the citation graph and shown as verified or
  unconfirmed; precedent labels must be ones the report supplied.
* Precedent summaries read the judgment's own ingested text; the quoted line
  must appear in it word for word, or it is dropped.
"""
from __future__ import annotations

import re

from src.graph import citation_graph as cg
from src.pipeline.applicability import grounded, normalise, statute_text

ERAS = ("ipc", "bns")
STATUTE_CHARS = 700
EXCERPT_CHARS = 500

# --- follow-up questions ---------------------------------------------------------

ASK_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "maxLength": 1600}},
              "required": ["answer"]}


def _ref(c):
    return f"{c.get('code') or ''} {c.get('subsection') or c.get('section')}".strip()


def context(report):
    """The report, as the only material the answer may use."""
    era = report["era"]
    lines = [f"FACTS:\n{report.get('facts') or ''}",
             f"\nCODE APPLIED: {era.upper()} ({report.get('code_applied') or ''})", "\nCHARGES:"]
    for c in report.get("charges", []):
        status = f"DOUBTED: {c['doubt']}" if c.get("doubt") else "supported on the facts"
        try:
            text = re.sub(r"\s+", " ", statute_text(era, c["section"], c.get("subsection")))[:STATUTE_CHARS]
        except KeyError:
            text = ""
        lines.append(f"- {_ref(c)} ({c.get('title')}) -- {status}. Reason given: {c.get('reason') or ''}\n  Text: {text}")
    for c in report.get("included", []):
        lines.append(f"- {_ref(c)} ({c.get('title')}) -- included in {c.get('included_in')}, not charged separately")
    for u in report.get("unconfirmed", []):
        lines.append(f"- REJECTED by the citation graph: {u.get('raw')} ({u.get('why')})")
    for w in report.get("withdrawn", []):
        lines.append(f"- Considered and ruled out by the model: {w.get('raw')} ({w.get('reason')})")
    lines.append("\nPRECEDENTS:")
    for p in report.get("precedents", []):
        lines.append(f"[{p['label']}] {p.get('title') or p['doc_id']} ({p.get('court') or 'court n/a'}; for "
                     f"{p.get('for_charge')}; disposal: {p.get('disposal_nature') or 'n/a'}): "
                     f"{(p.get('excerpt') or '')[:EXCERPT_CHARS]}")
    if not report.get("precedents"):
        lines.append("(none)")
    lines.append("\nCOUNTER-ARGUMENTS ALREADY DRAFTED:")
    for i, d in enumerate(report.get("defenses", []), 1):
        lines.append(f"{i}. against {d.get('against')}: {d.get('argument')}")
    return "\n".join(lines)


def ask_messages(report, question, history=()):
    system = (
        "You are a research assistant to an Indian criminal lawyer, answering questions about one case "
        "analysis. Use ONLY the material given: the facts, the charges with their statute text, the "
        "reviewer's doubts, the precedents and the counter-arguments. If the material does not answer the "
        "question, say so plainly instead of guessing. Keep two things apart: what a section REQUIRES comes "
        "only from its statute text in the material; the counter-arguments are the DEFENCE's arguments, so "
        "attribute them ('the defence can argue ...') and never state them as the law or as proven. Do not "
        "add requirements the statute text does not contain. Cite sections as they appear in the material "
        "(e.g. 'BNS 303', 'IPC 379') and precedents by their label (e.g. [P1]). Never mention a section, "
        "case or fact that is not in the material. This is research assistance, not legal advice. Plain "
        "English, at most 180 words.")
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": f"MATERIAL:\n{context(report)}"},
            {"role": "assistant", "content": '{"answer": "Understood. I will answer only from this material."}'}]
    for q, a in list(history)[-3:]:
        msgs += [{"role": "user", "content": f"QUESTION: {q}"}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": f"QUESTION: {question}"})
    return msgs


# "BNS 303", "IPC s. 34", "Section 118(2)", "section 379 of the IPC", "s. 420"
_MENTION = re.compile(
    r"\b(?:(IPC|BNS|I\.P\.C\.?|B\.N\.S\.?)\s*(?:,?\s*(?:Section|Sec\.?|s\.)\s*)?|(?:Section|Sec\.?|s\.)\s*)"
    r"(\d{1,3}[A-Z]{0,3})((?:\s?\(\d+\))?)", re.I)
# The lookahead stops "BNSS" (procedure) reading as "BNS" (penal code).
_AFTER = re.compile(r"^\s*(?:of\s+(?:the\s+)?)?(IPC|BNS|I\.P\.C|B\.N\.S|Indian\s+Penal\s+Code|Bharatiya\s+Nyaya\s+Sanhita)"
                    r"(?![A-Za-z]|\.?\s?S\b)", re.I)
_AFTER_OTHER = re.compile(r"^\s*(?:of\s+(?:the\s+)?)?(Cr\.?\s?P\.?\s?C|BNSS|B\.N\.S\.S|Evidence\s+Act|BSA|[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\s+Act)")
_LABEL = re.compile(r"\[?\bP(\d{1,2})\b\]?")


def _code_of(name):
    n = re.sub(r"[\s.]", "", name or "").lower()
    return "ipc" if n in ("ipc", "indianpenalcode") else "bns" if n in ("bns", "bharatiyanyayasanhita") else None


def check_citations(text, era, g, report=None):
    """Every section mentioned in `text`, looked up in the graph."""
    in_report = {(era, c["section"]) for c in (report or {}).get("charges", []) + (report or {}).get("included", [])}
    out, seen = [], set()
    for m in _MENTION.finditer(text or ""):
        sec = cg.normalise(m.group(2).upper())
        sub = re.sub(r"\s", "", m.group(3) or "")
        after = text[m.end():m.end() + 40]
        code = _code_of(m.group(1)) or (_code_of(_AFTER.match(after).group(1)) if _AFTER.match(after) else None)
        if code is None and _AFTER_OTHER.match(after):
            item = {"mention": m.group(0).strip(), "code": None, "section": sec, "status": "other_act",
                    "why": f"cites {_AFTER_OTHER.match(after).group(1)}, not a penal code: not checked here"}
        else:
            code = code or era
            ok = sec is not None and cg.verify_section(g, code, sec)
            item = {"mention": m.group(0).strip(), "code": code, "section": sec, "subsection": (sec + sub) if sub else None,
                    "status": "verified" if ok else "unconfirmed",
                    "title": g.nodes[cg.section_key(code, sec)].get("title") if ok else None,
                    "in_report": (code, sec) in in_report,
                    "why": None if ok else f"{code.upper()} {sec} is not a section of the ingested {code.upper()}"}
        key = (item["code"], item["section"], item.get("subsection"))
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def ask(report, question, llm, g, history=()):
    era = report.get("era")
    if era not in ERAS:
        raise ValueError("report has no valid era")
    reply = llm(ask_messages(report, question, history), ASK_SCHEMA, num_predict=900)
    answer = str(reply.get("answer") or "").strip()
    labels = {p["label"] for p in report.get("precedents", [])}
    cited = sorted({f"P{n}" for n in _LABEL.findall(answer)}, key=lambda s: int(s[1:]))
    return {"answer": answer, "citations": check_citations(answer, era, g, report),
            "precedents": [{"label": p, "valid": p in labels} for p in cited]}


# --- precedent summaries ------------------------------------------------------------

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "string", "maxLength": 400},
        "question": {"type": "string", "maxLength": 300},
        "held": {"type": "string", "maxLength": 450},
        "outcome": {"type": "string", "maxLength": 200},
        "key_quote": {"type": "string", "maxLength": 320},
    },
    "required": ["facts", "question", "held", "outcome", "key_quote"],
}
HEAD_CHARS, TAIL_CHARS = 4500, 1800
_cache = {}


def judgment_text(doc_id, cli=None):
    """(full text in paragraph order, metadata) of an ingested judgment, or (None, None)."""
    from src.retrieval import store

    cli = cli or store.client()
    for col in ("judgments_pre2024", "judgments_post2024"):
        try:
            res = cli.get_collection(col).get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
        except Exception:  # noqa: BLE001 -- a missing collection just means "not here"
            continue
        if res["ids"]:
            rows = sorted(zip(res["documents"], res["metadatas"]), key=lambda r: (r[1].get("para_index") or 0))
            return "\n\n".join(d for d, _ in rows), rows[0][1]
    return None, None


def summarise(doc_id, llm, g, cli=None):
    if doc_id in _cache:
        return _cache[doc_id]
    if not cg.verify_case(g, doc_id):
        raise LookupError(f"{doc_id} is not an ingested judgment")
    text, md = judgment_text(doc_id, cli)
    if not text:
        raise LookupError(f"no text stored for {doc_id}")
    clipped = text if len(text) <= HEAD_CHARS + TAIL_CHARS else (
        text[:HEAD_CHARS] + "\n\n[...]\n\n" + text[-TAIL_CHARS:])
    system = ("You summarise an Indian court judgment for a criminal lawyer, using ONLY the text given. "
              "facts: what happened, in two or three sentences. question: the legal question the court decided. "
              "held: what the court held and why. outcome: how the case was disposed of (allowed, dismissed, "
              "conviction upheld or set aside...), or 'not stated in the text'. key_quote: copy ONE sentence from "
              "the text WORD FOR WORD that best states the holding. Do not add anything not in the text.")
    reply = llm([{"role": "system", "content": system},
                 {"role": "user", "content": f"JUDGMENT ({md.get('court') or ''}, {md.get('title') or doc_id}):\n{clipped}"}],
                SUMMARY_SCHEMA, num_predict=900)
    quote = str(reply.get("key_quote") or "").strip()
    ok = bool(quote) and grounded(quote, normalise(text))
    out = {k: str(reply.get(k) or "").strip() for k in ("facts", "question", "held", "outcome")}
    out.update({"doc_id": doc_id, "key_quote": quote if ok else "", "quote_checked": ok,
                "quote_dropped": None if ok or not quote else quote,
                "read_chars": len(clipped), "full_chars": len(text)})
    _cache[doc_id] = out
    return out

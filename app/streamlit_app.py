r"""Pramana - Streamlit frontend (Phase 7).

Saved sample reports open instantly; "Analyse" runs the full local pipeline
through the FastAPI backend (about 2 minutes on a 4GB laptop GPU).

Run (after the API is up):  venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
"""
from __future__ import annotations

import html
import json
import os
from datetime import date
from pathlib import Path

import httpx
import streamlit as st

API = os.environ.get("PRAMANA_API", "http://127.0.0.1:8000")
SAMPLES = Path(__file__).parent / "samples"

st.set_page_config(page_title="Pramana", page_icon="⚖️", layout="wide")
st.markdown("""
<style>
.card {border-radius:8px; padding:10px 14px; margin:6px 0; border-left:6px solid; background:rgba(127,127,127,.06)}
.ok   {border-color:#1a7f37} .doubt {border-color:#bf8700} .bad {border-color:#cf222e} .grey {border-color:#8c959f}
.tag {font-size:.75rem; font-weight:600; padding:1px 8px; border-radius:10px; color:#fff; margin-right:6px}
.t-ok {background:#1a7f37} .t-doubt {background:#bf8700} .t-bad {background:#cf222e} .t-grey {background:#8c959f}
.sec {font-weight:700; font-size:1.05rem}
.muted {opacity:.75; font-size:.9rem}
.strike {text-decoration:line-through}
</style>""", unsafe_allow_html=True)

e = html.escape


def card(kind, tag, title, body=""):
    st.markdown(f'<div class="card {kind}"><span class="tag t-{kind}">{e(tag)}</span>'
                f'<span class="sec">{title}</span>'
                + (f'<div class="muted">{body}</div>' if body else "") + "</div>", unsafe_allow_html=True)


def api_ok():
    try:
        return httpx.get(f"{API}/health", timeout=3).json()
    except Exception:
        return None


def render(r):
    if r.get("status") == "straddles_transition":
        for w in r.get("warnings", []):
            st.warning(w)
        tabs = st.tabs([f"{era.upper()} run" for era in r["runs"]])
        for tab, rr in zip(tabs, r["runs"].values()):
            with tab:
                render(rr)
        return

    st.markdown(f"#### Code applied: **{r['era'].upper()}**")
    st.caption(f"{r['code_applied']} · offence date {r['offence_date']} · chosen by the deterministic "
               "offence-date router, not by the model")
    for w in r.get("warnings", []):
        st.warning(w)
    if r["status"] == "insufficient_data":
        st.info("Insufficient data: nothing in the corpus is close enough to these facts to ground an "
                "analysis, so the model was not asked. The nearest statute sections are listed for review.")

    st.subheader("1 · Applicable sections")
    supported = [c for c in r["charges"] if not c.get("doubt")]
    doubted = [c for c in r["charges"] if c.get("doubt")]
    if not r["charges"]:
        st.write("No section was both proposed and verified for these facts.")
    for c in supported:
        card("ok", "VERIFIED · SUPPORTED", f"{c['code']} {e(c.get('subsection') or c['section'])} — {e(c.get('title') or '')}",
             e(c.get("reason") or ""))
    for c in doubted:
        card("doubt", "VERIFIED · APPLICABILITY DOUBTED",
             f"{c['code']} {e(c.get('subsection') or c['section'])} — {e(c.get('title') or '')}",
             "<b>Doubt:</b> " + e(c["doubt"]))
    for u in r.get("unconfirmed", []):
        card("bad", "UNCONFIRMED · REJECTED BY CITATION GRAPH",
             f'<span class="strike">{u["code"]} {e(str(u.get("raw") or u.get("section")))}</span>',
             e(u.get("why") or "") + (f" (round {u['round']})" if u.get("round") is not None else ""))
    if r.get("review_candidates"):
        st.markdown("**Nearest statute sections, for review (retrieval results, NOT verified charges):**")
        for c in r["review_candidates"]:
            card("grey", "NOT VERIFIED · FOR REVIEW",
                 f"{r['era'].upper()} {e(c.get('matched') or c['section'])} — {e(c.get('title') or '')}")
    with st.expander("How to read this"):
        st.markdown(
            "- **Verified** means the section exists in the ingested code, checked against the citation "
            "graph. The language model's proposals are never shown as real without this check.\n"
            "- **Supported / doubted** is a second check: the model must quote the facts that establish "
            "each ingredient. Rule checks (e.g. rioting needs five or more persons) also apply here.\n"
            "- **Unconfirmed** citations were proposed by the model and rejected by the graph. They are "
            "shown so nothing is hidden, and they were sent back to the model with feedback.")

    st.subheader("2 · Precedents")
    if not r.get("precedents"):
        st.write("No precedent: no verified section to match.")
    for p in r.get("precedents", []):
        name = p.get("title") or p["doc_id"]
        via = f" · via IPC predecessor ({p['via_ipc_predecessor']})" if p.get("via_ipc_predecessor") else ""
        sim = f" · similarity {p['similarity']:.2f}" if p.get("similarity") else " · most-cited (not similarity-matched)"
        with st.expander(f"[{p['label']}] {name} — {p.get('court') or ''} · applies {p['applies']}{via}"):
            st.markdown(f'<span class="tag t-ok">VERIFIED JUDGMENT</span> '
                        f'<span class="muted">for {e(p["for_charge"])}{e(sim)} · '
                        f'{e(str(p.get("date") or ""))} {e(str(p.get("citation") or ""))} · '
                        f'disposal: {e(str(p.get("disposal_nature") or "n/a"))} · id {e(p["doc_id"])}</span>',
                        unsafe_allow_html=True)
            if p.get("excerpt"):
                st.write(p["excerpt"])

    st.subheader("3 · Counter-arguments for the defence")
    if not r.get("defenses"):
        st.write("None generated (no verified section).")
    for d in r.get("defenses", []):
        kind, tag = ("ok", "GROUNDED · CHECKED") if d["verified"] else ("bad", "FAILED FINAL CHECK")
        body = e(d["argument"])
        if d.get("fact_quote"):
            body += f'<br><b>Turns on:</b> “{e(d["fact_quote"])}”'
        if d.get("precedents"):
            body += "<br><b>Relies on:</b> " + ", ".join(f'{e(x["label"])} ({e(x.get("title") or x["doc_id"])})'
                                                         for x in d["precedents"])
        if d.get("issues"):
            body += "<br><b>Issues:</b> " + e("; ".join(d["issues"]))
        card(kind, tag, f"Against {e(str(d['against']))}", body)

    st.subheader("4 · Outcome analytics")
    a = r.get("analytics") or {}
    if a.get("error"):
        st.error(a["error"])
    elif a.get("sections"):
        st.caption(a["note"] + f" Figures under {a['min_judgments']} judgments are suppressed. "
                   "Sentence ranges are not extracted in this version.")
        rows = []
        for s in a["sections"]:
            for label, x in [(s["charge"], s["direct"])] + [(f"{s['charge']} ← IPC {v['section']}", v) for v in s["via_ipc"]]:
                c = x["counts"]
                rows.append({"section": label, "judgments": x["judgments"],
                             "appellant/petitioner succeeded": "suppressed (<5)" if x["suppressed"]
                             else (f"{x['allowed_share']:.0%}" if x.get("allowed_share") is not None else "n/a"),
                             "allowed": c["allowed"], "partly": c["partly allowed"],
                             "dismissed": c["dismissed"], "other": c["other"]})
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.write("No verified section to aggregate.")

    t = r.get("timings") or {}
    st.caption("Run time: " + ", ".join(f"{k.replace('_s', '')} {v}s" for k, v in t.items())
               + " · generation is fully local (Ollama), nothing leaves this machine.")


# ---------------------------------------------------------------- page --------
st.title("⚖️ Pramana")
st.caption("AI-assisted legal research for Indian criminal law · every citation checked against ingested "
           "statutes and judgments · research aid, not legal advice")

cases = json.loads((SAMPLES / "cases.json").read_text(encoding="utf-8"))
with st.sidebar:
    st.header("Sample cases")
    names = ["(write your own)"] + [c["name"] for c in cases]
    pick = st.radio("Load a sample", names, index=1)
    sample = next((c for c in cases if c["name"] == pick), None)
    st.divider()
    h = api_ok()
    if h:
        st.success(f"Backend up · model {h['model']} · Ollama {'up' if h['ollama'] else 'DOWN'}")
    else:
        st.error(f"Backend not reachable at {API}. Saved samples still work; live analysis needs "
                 "`run_demo.bat`.")

facts = st.text_area("Case facts", value=sample["facts"] if sample else "", height=150,
                     key=f"facts_{pick}")
c1, c2, c3 = st.columns([1, 1, 2])
d = date.fromisoformat(sample["offence_date"]) if sample else date(2024, 8, 15)
offence_date = c1.date_input("Offence date", value=d, key=f"date_{pick}", min_value=date(1950, 1, 1),
                             max_value=date.today())
period = c2.checkbox("Offence over a period", key=f"period_{pick}")
offence_to = c3.date_input("Period ends", value=offence_date, key=f"to_{pick}",
                           max_value=date.today()) if period else None

b1, b2, _ = st.columns([1, 1, 3])
saved = SAMPLES / f"{sample['id']}.json" if sample else None
show_saved = b1.button("Show saved result", disabled=not (saved and saved.exists()
                                                           and facts == sample["facts"]))
run_live = b2.button("Analyse (live, ~2 min)", type="primary", disabled=h is None or len(facts.strip()) < 20)

if show_saved:
    st.session_state["report"] = json.loads(saved.read_text(encoding="utf-8"))
if run_live:
    body = {"facts": facts, "offence_date": offence_date.isoformat(),
            "offence_date_to": offence_to.isoformat() if offence_to else None}
    with st.spinner("Routing, retrieving, proposing, verifying, matching precedents, drafting counter-arguments..."):
        try:
            resp = httpx.post(f"{API}/analyze", json=body, timeout=900)
            if resp.status_code == 200:
                st.session_state["report"] = resp.json()
            else:
                st.error(f"{resp.status_code}: {resp.json().get('detail')}")
        except httpx.HTTPError as ex:
            st.error(f"Backend error: {ex}")

if st.session_state.get("report"):
    st.divider()
    render(st.session_state["report"])

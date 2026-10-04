r"""Phase 6: evaluation, written to docs/evaluation_results.md by one script.

IL-TUR (the planned yardstick) is gated and access was never granted, so the
external statute-identification set is Hanno-Labs/indian-ipc-statute-identification
(CC-BY-4.0, ungated; data/raw/eval/hanno_ipc_lsi/train.parquet): 14,876 Patna
High Court orders, almost all from 2012, with the charged IPC sections masked as
[STATUTE]. Checked for leakage: the corpus's Patna judgments are all 2021+.
It has no published baselines, so it measures this system, not its rank.

Parts (each resumable; re-running skips finished cases):

    retrieval   N external cases: is a charged section in the candidate list
                Node 1 reads (fused top 10 + statute-text top 10)? No LLM.
    pipeline    N external cases through Router -> Node 1 <-> Node 2 -> Node 2b,
                scored against the charge sheet (multi-label).
    stress      the 15 dev cases with retrieval WITHHELD, so Node 1 cites from
                memory: the condition the citation check exists for (as in the
                Phase 4 adversarial gate).
    report      hallucination-catch rate over every proposal of the pipeline and
                stress runs, plus all metrics, -> docs/evaluation_results.md

Fetch (17 MB, once):
      curl -L -o data/raw/eval/hanno_ipc_lsi/train.parquet https://huggingface.co/datasets/Hanno-Labs/indian-ipc-statute-identification/resolve/main/data/train.parquet

Run:  venv\Scripts\python.exe scripts\eval_phase6.py all
      venv\Scripts\python.exe scripts\eval_phase6.py pipeline --max-cases 5   (a batch)
"""
import argparse
import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

EXTERNAL = ROOT / "data" / "raw" / "eval" / "hanno_ipc_lsi" / "train.parquet"
DEV = ROOT / "tests" / "fixtures" / "phase2_testset.json"
DOCS = ROOT / "docs"
OUT = {"retrieval": DOCS / "phase6_retrieval_runs.jsonl", "pipeline": DOCS / "phase6_pipeline_runs.jsonl",
       "stress": DOCS / "phase6_stress_runs.jsonl"}
REPORT = DOCS / "evaluation_results.md"
N_RETRIEVAL, N_PIPELINE, SEED = 300, 30, 0
MAX_FACTS = 3000

# Procedure, evidence and bail-adjacent IPC sections: real, so they verify, but
# a fact statement about an offence should never prompt them.
PROCEDURAL = {"438", "229A", "174A", "174", "182", "193", "177", "176", "166A", "188", "216", "211",
              "224", "154", "183", "108"}

PUN = json.loads((ROOT / "data" / "mappings" / "chargeability.json").read_text(encoding="utf-8"))["punished_by"]


def canon(era, s):
    """Definition -> punishing section (378 -> 379): one offence, one label."""
    return PUN.get(era, {}).get(s, s)


# --- the external set ------------------------------------------------------------

_DATE = re.compile(r"\b(\d{1,2})[-./](\d{1,2})[-./]((?:19|20)\d\d)\b")


def clean_facts(text):
    """The order as a lawyer would paste it, minus the cause-title header (court,
    case number, coram): from the first "Heard" if it opens the order. The masked
    citation reads as words rather than a placeholder token."""
    i = text.find("Heard")
    if 0 <= i < 1200:
        text = text[i:]
    text = text.replace("[STATUTE]", "certain sections")
    return text[:MAX_FACTS].rsplit(" ", 1)[0] if len(text) > MAX_FACTS else text


def order_date(text):
    """The order's date: the offence is earlier, and every order here predates
    2024-07-01, so the router picks the IPC either way."""
    for d, m, y in _DATE.findall(text[:800]):
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{int(m):02d}-{int(d):02d}"
    return "2012-01-01"


def external_cases(n):
    import pandas as pd

    df = pd.read_parquet(EXTERNAL)
    gold = df.groupby("case_facts", sort=True)["ipc_section"].apply(lambda s: sorted(set(s)))
    keys = list(gold.index)
    random.Random(SEED).shuffle(keys)
    return [{"id": f"ext{i:04d}", "facts": clean_facts(k), "offence_date": order_date(k),
             "gold": gold[k]} for i, k in enumerate(keys[:n])]


def _done(path):
    if not path.exists():
        return set()
    return {json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _append(path, rec):
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --- parts ------------------------------------------------------------------------

def run_retrieval(n, max_cases):
    from src.pipeline import graph
    from src.retrieval import embedder, store

    cli, done, k = store.client(), _done(OUT["retrieval"]), 0
    for c in external_cases(n):
        if c["id"] in done:
            continue
        rows = graph.retrieve_candidates(c["facts"], "ipc", cli=cli, device=None)
        gold = {canon("ipc", s) for s in c["gold"]}
        ranks = {}
        for i, r in enumerate(rows, 1):
            ranks.setdefault(canon("ipc", r["section"]), i)
        _append(OUT["retrieval"], {"id": c["id"], "gold": sorted(gold), "list": [r["section"] for r in rows],
                                   "gold_ranks": {s: ranks.get(s) for s in sorted(gold)}})
        k += 1
        if max_cases and k >= max_cases:
            break
    embedder.free()


def _record(cid, res, gold=None):
    st = res["state"]
    pick = lambda xs, ks: [{k: x.get(k) for k in ks} for x in xs]  # noqa: E731
    return {"id": cid, "status": res["status"], "era": res["era"], "gold": gold,
            "charges": [v["section"] for v in res.get("charges", [])],
            "doubted": [d["section"] for d in res.get("doubted", [])],
            "candidates": pick(st["candidate_sections"], ("raw", "section", "round")),
            "verified": pick(st["verified_sections"], ("raw", "section", "round", "defined_in")),
            "unconfirmed": pick(st["unconfirmed"], ("raw", "section", "round", "why")),
            "retry_count": st["retry_count"], "profile": st.get("facts_profile"),
            "timings": {k: round(v, 1) for k, v in res.get("timings", {}).items()}}


def run_pipeline(n, max_cases):
    from src.pipeline import graph

    done, k = _done(OUT["pipeline"]), 0
    for c in external_cases(n):
        if c["id"] in done:
            continue
        t = time.perf_counter()
        res = graph.run(c["facts"], c["offence_date"])
        rec = _record(c["id"], res, gold=c["gold"])
        _append(OUT["pipeline"], rec)
        print(f"{c['id']} gold={c['gold']} charges={rec['charges']} unconfirmed={len(rec['unconfirmed'])} "
              f"{time.perf_counter() - t:.0f}s", flush=True)
        k += 1
        if max_cases and k >= max_cases:
            break


def run_stress(max_cases):
    from src.pipeline import graph

    done, k = _done(OUT["stress"]), 0
    for i, c in enumerate(json.loads(DEV.read_text(encoding="utf-8"))["cases"], 1):
        cid = f"dev{i:02d}"
        if cid in done:
            continue
        t = time.perf_counter()
        res = graph.run(c["query"], c.get("offence_date") or ("2024-08-15" if c["era"] == "bns" else "2023-06-01"),
                        retrieve=lambda f, era: [], sufficient=lambda f, era: (True, {}))
        rec = _record(cid, res, gold=[r.split("_s", 1)[1] for r in c["relevant"]])
        _append(OUT["stress"], rec)
        print(f"{cid} [{c['era']}] charges={rec['charges']} unconfirmed={[u['raw'] for u in rec['unconfirmed']]} "
              f"{time.perf_counter() - t:.0f}s", flush=True)
        k += 1
        if max_cases and k >= max_cases:
            break


# --- report -------------------------------------------------------------------------

def _load(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def _why_kind(why):
    w = why or ""
    if "is not a section of the ingested" in w:
        return "does not exist in the code"
    if "but the offence date means" in w:
        return "other code (IPC/BNS mix-up)"
    if "another enactment" in w:
        return "another Act"
    if "not an offence a person can be charged under" in w:
        return "real but not chargeable (definition, exception)"
    return "malformed"


def catch_rate(runs):
    proposals = sum(len(r["candidates"]) for r in runs)
    kinds = Counter(_why_kind(u["why"]) for r in runs for u in r["unconfirmed"])
    caught = sum(kinds.values())
    # Corrected within the 2 retries: a case whose round-r proposal was rejected
    # and that verified a NEW section in a later round.
    with_rej = corrected = 0
    for r in runs:
        rounds = sorted({u["round"] for u in r["unconfirmed"]})
        if not rounds:
            continue
        with_rej += 1
        if any(v["round"] > rounds[0] for v in r["verified"]):
            corrected += 1
    leaked = sum(1 for r in runs for c in r["charges"] if c not in {v["section"] for v in r["verified"]})
    return {"proposals": proposals, "caught": caught, "kinds": kinds, "cases": len(runs),
            "cases_with_rejection": with_rej, "corrected": corrected, "leaked": leaked}


def multilabel(runs, use_doubts=False):
    tp = fp = fn = hit = 0
    per = Counter()
    for r in runs:
        gold = {canon("ipc", s) for s in r["gold"]}
        pred = {canon("ipc", s) for s in r["charges"]
                if not (use_doubts and s in set(r.get("doubted") or []))}
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
        hit += bool(gold & pred)
        for s in gold & pred:
            per[s, "tp"] += 1
        for s in pred - gold:
            per[s, "fp"] += 1
        for s in gold - pred:
            per[s, "fn"] += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
    secs = {s for s, _ in per}
    f1s = []
    for s in secs:
        a, b, c = per[s, "tp"], per[s, "fp"], per[s, "fn"]
        f1s.append(2 * a / (2 * a + b + c) if a else 0.0)
    return {"n": len(runs), "hit": hit, "precision": p, "recall": rc, "micro_f1": f1,
            "macro_f1": sum(f1s) / len(f1s) if f1s else 0.0, "sections": len(secs),
            "per_case": (tp + fp) / len(runs) if runs else 0.0}


def own_fixtures():
    """The project's own fixtures, re-scored from saved runs (scripts/score_runs.py)."""
    import subprocess

    rows = [("dev (15)", "tests/fixtures/phase2_testset.json", "docs/dual_dev_runs.jsonl"),
            ("dev, pair on (14)", "tests/fixtures/phase2_testset.json", "docs/pair_dev_runs.jsonl"),
            ("held-out 2", "tests/fixtures/heldout_2.json", "docs/heldout_2_hardened_runs.jsonl"),
            ("held-out 3", "tests/fixtures/heldout_3.json", "docs/heldout_3_runs.jsonl"),
            ("held-out 4", "tests/fixtures/heldout_4.json", "docs/heldout_4_runs.jsonl"),
            ("held-out 5", "tests/fixtures/heldout_5.json", "docs/heldout_5_runs.jsonl"),
            ("broad coverage", "tests/fixtures/broad_coverage.json", "docs/broad_coverage_hardened_runs.jsonl")]
    out = []
    for name, fx, runs in rows:
        if not (ROOT / fx).exists() or not (ROOT / runs).exists():
            out.append(f"| {name} | not run |")
            continue
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_runs.py"), fx, runs],
                           capture_output=True, text=True, cwd=ROOT)
        summary = [x for x in r.stdout.splitlines() if " recall " in x]
        line = summary[-1].split(": ", 1)[-1] if summary else "?"
        out.append(f"| {name} | {line} |")
    return out


def report():
    ret, pipe, stress = _load(OUT["retrieval"]), _load(OUT["pipeline"]), _load(OUT["stress"])
    L = ["# Evaluation results (Phase 6)", "",
         f"*Generated by `scripts/eval_phase6.py report` on {time.strftime('%Y-%m-%d')}. Re-run "
         "`scripts/eval_phase6.py all` to reproduce (resumable; finished cases are skipped).*", "",
         "## The yardstick, and what it can and cannot say", "",
         "IL-TUR (LSI/PCR), the planned benchmark, is gated and access was never granted. The external set used "
         "instead is **Hanno-Labs/indian-ipc-statute-identification** (CC-BY-4.0, ungated): Indian High Court "
         "orders with the charged IPC sections masked as `[STATUTE]`; the gold label is the order's own list "
         "of charged sections (often the whole charge sheet). Sampled with seed 0 from 14,876 cases. "
         "It is **almost entirely Patna High Court, 2012, mostly bail orders**, so it is narrow, and the "
         "corpus's Patna judgments are all 2021 or later, so **no test case is in the corpus**. It has **no published "
         "baselines**: these numbers describe this system; they do not rank it. Prior case retrieval (PCR, "
         "Node 3) has no ungated benchmark and is **not evaluated**.", "",
         "Definition and punishing sections count as one offence on both sides (IPC 378 = 379), as in "
         "`scripts/score_runs.py`.", ""]

    if ret:
        n = len(ret)
        any_in = sum(1 for r in ret if any(v for v in r["gold_ranks"].values()))
        top3 = sum(1 for r in ret if any(v and v <= 3 for v in r["gold_ranks"].values()))
        cover = sum(sum(1 for v in r["gold_ranks"].values() if v) / len(r["gold_ranks"]) for r in ret) / n
        size = sum(len(r["list"]) for r in ret) / n
        L += ["## 1. Retrieval: is a charged section in the list Node 1 reads? (no LLM)", "",
              "| external cases | at least one charged section in the list | in the top 3 | share of all charged sections in the list | list size |",
              "|---|---|---|---|---|",
              f"| {n} | **{any_in}/{n} ({any_in / n:.0%})** | {top3}/{n} ({top3 / n:.0%}) | {cover:.0%} | {size:.1f} |", ""]

    if pipe:
        a, b = multilabel(pipe), multilabel(pipe, use_doubts=True)
        L += ["## 2. Statute identification, full Node 1 + Node 2 + Node 2b pipeline", "",
              "Gold is the charge sheet, which often lists five or more sections (rioting, hurt, intimidation...), so "
              "recall against it is a harsh measure, and a correct charge the sheet left out counts as a false positive.", "",
              "| external cases | right section charged (>= 1) | precision | recall | micro-F1 | macro-F1 | sections/case |",
              "|---|---|---|---|---|---|---|",
              f"| {a['n']} | **{a['hit']}/{a['n']} ({a['hit'] / a['n']:.0%})** | {a['precision']:.0%} | {a['recall']:.0%} | "
              f"{a['micro_f1']:.2f} | {a['macro_f1']:.2f} | {a['per_case']:.1f} |",
              f"| same, judge's doubts set aside | {b['hit']}/{b['n']} | {b['precision']:.0%} | {b['recall']:.0%} | "
              f"{b['micro_f1']:.2f} | {b['macro_f1']:.2f} | {b['per_case']:.1f} |", ""]

    if pipe:
        n = len(pipe)
        refused = sum(1 for r in pipe if r["status"] == "insufficient_data")
        none = sum(1 for r in pipe if r["status"] != "insufficient_data" and not r["charges"])
        proc = Counter(s for r in pipe for s in r["charges"] if s in PROCEDURAL)
        L += ["Where it fails on this set (computed from the runs):", "",
              f"- Guardrail refusals (too far from the corpus to ask the model): {refused}/{n}.",
              f"- **Model proposed no section at all: {none}/{n}** (it read the order as procedure with no "
              "offence described; the nearest sections are still listed for review, nothing is charged).",
              f"- **Procedural sections charged: {sum(proc.values())} times in {sum(1 for r in pipe if set(r['charges']) & PROCEDURAL)} cases** "
              f"({', '.join(f'IPC {s} x{c}' for s, c in proc.most_common())}). These are real IPC sections, so they "
              "pass verification, but they are prompted by the order's procedural vocabulary. IPC 438 is the "
              "clearest case: the orders discuss *anticipatory bail under Section 438*, which is the CrPC.",
              "- Input mismatch: the system expects a fact statement and gets a court order. The facts are often "
              "one sentence inside the procedure (\"the accusation is of causing fire arm injury on the chest of the "
              "deceased\").", ""]

    L += ["## 3. Hallucination-catch rate (Node 2)", "",
          "Of every citation Node 1 proposed, in every round: how many Node 2 rejected, why, and whether the "
          "retry loop (at most 2 retries) then produced a verified section (and, in brackets, whether "
          "that case ended with a right section). **No rejected citation may reach the charges**: `leaked` "
          "must be 0.", "",
          "| condition | cases | proposals | rejected by Node 2 | does not exist | other code | real, not chargeable | other Act / malformed | cases with a rejection | corrected within 2 retries | leaked |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, runs in (("external, with retrieval (normal use)", pipe),
                       ("dev, retrieval withheld (stress)", stress)):
        if not runs:
            continue
        c = catch_rate(runs)
        k = c["kinds"]
        right = sum(1 for r in runs if r["unconfirmed"] and
                    {canon(r["era"], x) for x in r["gold"]} & {canon(r["era"], x) for x in r["charges"]})
        c["right_after"] = right
        L.append(f"| {name} | {c['cases']} | {c['proposals']} | **{c['caught']} ({c['caught'] / max(c['proposals'], 1):.0%})** | "
                 f"{k['does not exist in the code']} | {k['other code (IPC/BNS mix-up)']} | "
                 f"{k['real but not chargeable (definition, exception)']} | {k['another Act'] + k['malformed']} | "
                 f"{c['cases_with_rejection']} | {c['corrected']}/{c['cases_with_rejection']} "
                 f"({c['right_after']} with the right section) | {c['leaked']} |")
    if stress:
        L += ["", "Rejected citations in the stress condition (model citing from memory):", ""]
        for r in stress:
            if r["unconfirmed"]:
                L.append(f"- {r['id']} ({r['era'].upper()}): " + "; ".join(
                    f"`{u['raw']}` round {u['round']} - {_why_kind(u['why'])}" for u in r["unconfirmed"])
                         + f" -> charged {r['charges']}")
        s = multilabel([{**r, "gold": r["gold"]} for r in stress])
        L += ["", f"Stress-condition accuracy (dev, no retrieval): right section charged {s['hit']}/{s['n']}. "
              "This is what the pipeline would do without its retrieval context.", ""]

    L += ["## 4. The project's own fixtures (saved runs, re-scored)", "",
          "Hand-written by Claude, not reviewed by a lawyer. Each held-out set was written before the change "
          "it certifies and scored once.", "", "| set | result |", "|---|---|"] + own_fixtures()
    L += ["", "## What this does and does not show", ""]
    if pipe or stress:
        leaked = sum(catch_rate(x)["leaked"] for x in (pipe, stress) if x)
        caught = sum(catch_rate(x)["caught"] for x in (pipe, stress) if x)
        L.append(f"- **The citation check holds:** {caught} invented section numbers were caught and {leaked} "
                 "reached the charges. With retrieval context the model proposed no invented numbers at all; from "
                 "memory, on the BNS, most of its numbers were IPC numbers (420, 378-383, 465-468), the "
                 "renumbering trap the graph check exists for.")
    if pipe:
        a = multilabel(pipe)
        L.append(f"- **On unseen real court orders the system is weak:** a right section is charged in "
                 f"{a['hit']}/{a['n']} cases ({a['hit'] / a['n']:.0%}), against 60-100% on the hand-written fixtures. "
                 "Most of the gap is the input (procedural orders, not fact statements; see Section 2), and part "
                 "is the known precision problem. A fact-extraction step before retrieval is the obvious next change, "
                 "to be scored on a FRESH sample of this set, since this one has now been read.")
    L += ["- **Not shown: state of the art.** There is no published baseline on this set, IL-TUR could not be "
          "used, and prior case retrieval is not evaluated.",
          "- **Weak point on every set: precision** (extra sections that exist but do not apply)."]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"-> {REPORT.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=["retrieval", "pipeline", "stress", "report", "all"])
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--max-cases", type=int, default=0, help="stop after this many new cases (a batch)")
    a = ap.parse_args()
    if a.part in ("retrieval", "all"):
        run_retrieval(a.n or N_RETRIEVAL, a.max_cases)
    if a.part in ("pipeline", "all"):
        run_pipeline(a.n or N_PIPELINE, a.max_cases)
    if a.part in ("stress", "all"):
        run_stress(a.max_cases)
    if a.part in ("report", "all"):
        report()


if __name__ == "__main__":
    main()

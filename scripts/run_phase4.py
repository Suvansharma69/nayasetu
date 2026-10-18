r"""Phase 4 gate: the real pipeline (router -> retrieval -> guardrail -> Node 1 <-> Node 2)
on tests/fixtures/phase4_cases.json, with real Ollama, the real index and the real graph.

CLAUDE.md Section 8's gate:
  * 10 cases (5 pre-2024, 5 post-2024) route correctly EVERY time -- so the gate
    cases run --reps times (default 3). "Routes correctly" is checked three ways:
    the router's era is the case's era; retrieval touched only that era's statute
    collection (and that era's judgment collections -- for the BNS, IPC judgments
    too, which vote only through the verified mapping); and every verified section
    is an ingested section of that era's code.
  * a deliberately adversarial case triggers AND survives the retry loop:
    round 0 proposes the bait number, Node 2 leaves it unconfirmed, a retry runs,
    and the case ends with a verified section of the right code and the bait
    nowhere in verified_sections.

Section relevance (did the right offence come back?) is reported, not gated.

Run:  venv\Scripts\python.exe -u scripts\run_phase4.py > phase4.log 2>&1
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.graph import citation_graph as cg  # noqa: E402
from src.pipeline import graph as pipeline, llm  # noqa: E402
from src.retrieval import embedder, ranker, store  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "phase4_cases.json"
TOUCHED = []
_real_retrieve = store.retrieve


def _recording_retrieve(query_text, collection, *a, **kw):
    TOUCHED.append(collection)
    return _real_retrieve(query_text, collection, *a, **kw)


store.retrieve = _recording_retrieve


def _sec(chunk_id):
    return chunk_id.split("_s", 1)[1]


def run_case(facts, date, g, cli, withhold_retrieval=False):
    TOUCHED.clear()
    t = time.perf_counter()
    # Withholding retrieval leaves Node 1 with the facts alone -- the adversarial
    # condition in which the model invents citations from memory.
    out = pipeline.run(facts, date, g=g, cli=cli,
                       retrieve=(lambda f, era: []) if withhold_retrieval else None)
    out["wall_s"] = round(time.perf_counter() - t, 1)
    out["collections"] = sorted(set(TOUCHED))
    return out


def routing_ok(out, era, g):
    problems = []
    if out["era"] != era:
        problems.append(f"router gave {out['era']}, want {era}")
    allowed = {ranker.ERA[era]["statutes"], *ranker.ERA[era]["judgments"]}
    stray = set(out["collections"]) - allowed
    if stray:
        problems.append(f"queried {sorted(stray)}")
    for v in out["state"]["verified_sections"]:
        if v.get("code") != era or not cg.verify_section(g, era, v["section"]):
            problems.append(f"verified {v.get('code')} {v['section']} is not an ingested {era} section")
    return problems


def summary(out):
    st = out["state"]
    rounds = {}
    for c in st["candidate_sections"]:
        rounds.setdefault(c["round"], []).append(c["raw"])
    return {
        "status": out["status"], "era": out["era"], "retry_count": st["retry_count"],
        "rounds": rounds,
        "verified": [v["subsection"] or v["section"] for v in st["verified_sections"]],
        "unconfirmed": [{"raw": u["raw"], "round": u["round"], "why": u["why"]} for u in st["unconfirmed"]],
        "guardrail": out.get("guardrail"),
        "timings": {k: round(v, 1) for k, v in out["timings"].items()},
        "wall_s": out["wall_s"], "collections": out["collections"],
    }


CHECKPOINT = ROOT / "stuff" / "docs" / "phase4_runs.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--fresh", action="store_true", help="discard the checkpoint and start over")
    args = ap.parse_args()

    # Resumable: every finished run is appended to CHECKPOINT and skipped on a
    # re-run. Twice on 2026-09-27 the whole gate run was killed for low system
    # memory 20+ runs in, losing everything, because results were only written
    # at the end.
    if args.fresh and CHECKPOINT.exists():
        CHECKPOINT.unlink()
    done = {}
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[tuple(r["key"])] = r["record"]
    ckpt = CHECKPOINT.open("a", encoding="utf-8")

    def remember(key, record):
        ckpt.write(json.dumps({"key": list(key), "record": record}) + "\n")
        ckpt.flush()

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    base = json.loads((ROOT / fx["gate_from"]).read_text(encoding="utf-8"))["cases"]
    g, cli = cg.load(), store.client()
    print(f"model {llm.model()}  reps {args.reps}  ({len(done)} runs already in the checkpoint)", flush=True)

    results = {"model": llm.model(), "reps": args.reps, "gate": [], "adversarial": [], "probes": []}
    gate_fail = 0
    for rep in range(args.reps):
        for idx in fx["gate"]:
            c = base[idx - 1]
            key = ("gate", rep, idx)
            if key in done:
                results["gate"].append(done[key])
                gate_fail += bool(done[key]["routing_problems"])
                continue
            out = run_case(c["query"], c["offence_date"], g, cli)
            probs = routing_ok(out, c["era"], g)
            gate_fail += bool(probs)
            want = {_sec(r) for r in c["relevant"]}
            s = summary(out)
            hit = bool(want & {v["section"] for v in out["state"]["verified_sections"]})
            results["gate"].append({"rep": rep, "case": idx, "offence_type": c["offence_type"],
                                    "want": sorted(want), "relevant_verified": hit,
                                    "routing_problems": probs, **s})
            remember(key, results["gate"][-1])
            print(f"rep{rep} case {idx:2} [{c['era']}] {c['offence_type']:<24} "
                  f"{'ROUTE-OK' if not probs else 'ROUTE-FAIL ' + '; '.join(probs)}  "
                  f"verified={s['verified']} want={sorted(want)} {'hit' if hit else 'MISS'} "
                  f"retries={s['retry_count']} unconfirmed={[u['raw'] for u in s['unconfirmed']]} "
                  f"{s['wall_s']}s", flush=True)

        for a in fx["adversarial"]:
            key = ("adv", rep, a["name"])
            if key in done:
                results["adversarial"].append(done[key])
                continue
            out = run_case(a["query"], a["offence_date"], g, cli,
                           withhold_retrieval=a.get("withhold_retrieval", False))
            st = out["state"]
            bait = cg.normalise(a["bait"]) if a.get("bait") else None
            # Triggered: round 0 left something unconfirmed (the bait itself, when
            # the case has one) and a retry actually ran.
            baited = [u for u in st["unconfirmed"] if u["round"] == 0
                      and (bait is None or u["section"] == bait)]
            triggered = bool(baited) and st["retry_count"] >= 1
            bait_verified = bait is not None and any(v["section"] == bait for v in st["verified_sections"])
            # Survived: ends with at least one verified section, every one of them a
            # real section of the routed code, and the bait never among them.
            survived = (not bait_verified and bool(st["verified_sections"])
                        and not routing_ok(out, a["era"], g))
            want = {_sec(r) for r in a["relevant"]}
            hit = bool(want & {v["section"] for v in st["verified_sections"]})
            s = summary(out)
            results["adversarial"].append({"rep": rep, "name": a["name"], "gate": a.get("gate", True),
                                           "withhold_retrieval": a.get("withhold_retrieval", False),
                                           "triggered": triggered,
                                           "survived": survived, "relevant_verified": hit, **s})
            remember(key, results["adversarial"][-1])
            print(f"rep{rep} ADV{'*' if a.get('gate', True) else ' '} {a['name']:<24} triggered={triggered} survived={survived} "
                  f"relevant={hit} rounds={s['rounds']} verified={s['verified']} {s['wall_s']}s",
                  flush=True)

    for p in fx["probes"]:
        key = ("probe", p["name"])
        if key in done:
            results["probes"].append(done[key])
            continue
        out = run_case(p["query"], p["offence_date"], g, cli)
        s = summary(out)
        results["probes"].append({"name": p["name"], "expect": p["expect"], **s})
        remember(key, results["probes"][-1])
        print(f"PROBE {p['name']:<8} status={s['status']} (expected {p['expect']}) "
              f"rounds={s['rounds']} verified={s['verified']} {s['wall_s']}s", flush=True)

    ckpt.close()
    embedder.free()
    gated = [a for a in results["adversarial"] if a["gate"]]
    adv_ok = bool(gated) and all(a["triggered"] and a["survived"] for a in gated)
    reported = [a for a in results["adversarial"] if not a["gate"]]
    n = len(results["gate"])
    hits = sum(r["relevant_verified"] for r in results["gate"])
    print(f"\nrouting: {n - gate_fail}/{n} runs correct   "
          f"gated adversarial triggered+survived: {sum(a['triggered'] and a['survived'] for a in gated)}"
          f"/{len(gated)}   bait cases triggered (reported): "
          f"{sum(a['triggered'] for a in reported)}/{len(reported)}   "
          f"relevant section verified (reported, not gated): {hits}/{n}")
    print("GATE " + ("PASS" if gate_fail == 0 and adv_ok else "FAIL"))
    out = ROOT / "stuff" / "docs" / "phase4_pipeline_raw.json"
    out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

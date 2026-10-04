r"""Which section numbers may a BARE citation ("under Section 482", no Act named) yield?

The 2026-09-27 audit of 100 random citation-graph edges found only ~63% were
really penal-code sections. The largest single cause: bare citations of
procedure sections -- "petition under Section 482", "Section 167", "Section
125" -- read as IPC sections because nothing after them named the CrPC.

No hand-written list decides this. The corpus does: for every section number,
count the citations that explicitly NAME the penal code against those that
explicitly name another enactment (via sections.citation_kind, exactly what the
extractor sees). A number named as another Act's more often than as the penal
code's is distrusted when bare:

    482   named penal 2, other 3,044  -> distrusted (CrPC quashing power)
    302   named penal 2,413, other 20 -> trusted
    320   named penal 33, other 474   -> distrusted (CrPC compounding, not IPC grievous hurt)

A number with no explicit evidence either way keeps the old behaviour (trusted).
A citation that names the penal code is ALWAYS kept, distrusted number or not.

Reads data/processed/ judgment text (which extraction does not change), writes
data/mappings/bare_citation_trust.json. build_corpus.py loads it; re-run this,
then build_corpus.py, after changing sections.py.

Run:  venv\Scripts\python.exe scripts\build_citation_trust.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest import sections as S  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "data" / "mappings" / "bare_citation_trust.json"


def main():
    valid = set()
    for f in ("statutes_ipc.jsonl", "statutes_bns.jsonl"):
        valid |= {json.loads(l)["section"] for l in (PROCESSED / f).read_text(encoding="utf-8").splitlines()}
    pen, oth, bare = Counter(), Counter(), Counter()
    for f in ("judgments_pre2024.jsonl", "judgments_post2024.jsonl"):
        with (PROCESSED / f).open(encoding="utf-8") as fh:
            for line in fh:
                t = json.loads(line)["text"]
                for m in S._CITATION.finditer(t):
                    kind = S.citation_kind(t, m)
                    for s in S._members(m, valid):
                        if kind == "penal":
                            pen[s] += 1
                        elif kind == "other":
                            oth[s] += 1
                        elif kind == "bare":
                            bare[s] += 1
    distrust = sorted((s for s in valid if oth[s] > pen[s]), key=lambda s: (len(s), s))
    out = {"_README": ("Bare citations of these section numbers are not trusted as penal-code "
                       "sections: the corpus names each as another enactment's section more often "
                       "than as the penal code's. Built by scripts/build_citation_trust.py."),
           "rule": "distrust iff explicit_other > explicit_penal",
           "distrust": distrust,
           "counts": {s: {"penal": pen[s], "other": oth[s], "bare": bare[s]}
                      for s in sorted(valid, key=lambda s: (len(s), s)) if pen[s] or oth[s] or bare[s]}}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    affected = sum(bare[s] for s in distrust)
    print(f"{len(distrust)} numbers distrusted when bare; {affected} of {sum(bare.values())} bare "
          f"mentions affected -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

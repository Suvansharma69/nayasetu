r"""IL-TUR Legal Statute Identification (LSI): the external yardstick for Node 1+2.

Task (IL-TUR, ACL 2024; ILSI, Paul et al. AAAI 2022): given the facts of a real
Indian case, identify the IPC sections that apply. Multi-label over 100 IPC
section labels; the paper's metric is macro-F1. Published best: LeSICiN 28.08,
Hierarchical InLegalBERT 26.23.

How Pramana is scored on it
---------------------------
* The facts are from real IPC-era judgments and the benchmark gives no offence
  date, so the router is bypassed by passing a pre-transition date
  (IPC_ERA_DATE). This is the only departure from the runtime pipeline.
* Prediction = the pipeline's `charges` (verified by the graph AND supported by
  Node 2b). `verified` is scored alongside, so the check's effect is visible.
* A label "Section 294(b)" is matched at section level (294): the pipeline
  predicts sections, and IL-TUR carries both "294" and "294(b)" as labels.
* Metrics are computed here (no sklearn dependency at runtime; the tests check
  them against sklearn): macro-F1 over the labels with at least one gold
  instance in the evaluated sample -- on a sample, a label with no support can
  only contribute an undefined F1 -- plus macro-F1 over all 100 labels (0 for
  unsupported ones, the conservative number), micro P/R/F1, and macro-F1 over
  the labels Pramana is allowed to charge (not definitions: IPC 2-5 and 13 are
  LSI labels but chargeability.json classes them non_chargeable).
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ILTUR = ROOT / "data" / "raw" / "iltur"
IPC_ERA_DATE = "2023-06-30"     # any date before 2024-07-01 routes to the IPC


def label_names(readme=ILTUR / "README.md"):
    """Class id -> label string ("Section 302"), read from the dataset card."""
    t = Path(readme).read_text(encoding="utf-8")
    i = t.find("config_name: lsi")
    j = t.find("- config_name:", i + 10)
    block = t[i:j if j > 0 else None]
    names = {}
    for m in re.finditer(r"'(\d+)':\s*(Section\s+[\w()]+)", block):
        names[int(m.group(1))] = m.group(2).strip()
    if not names:
        raise ValueError(f"no LSI label names found in {readme}")
    return names


def base_section(label):
    """'Section 294(b)' -> '294'; 'Section 120B' -> '120B'."""
    m = re.match(r"Section\s+(\d+[A-Z]*)", label)
    return m.group(1) if m else None


def load(split, readme=ILTUR / "README.md"):
    """[{id, facts, labels: [label strings]}] for split in {'dev', 'test', 'train'}."""
    import pandas as pd

    names = label_names(readme)
    df = pd.read_parquet(ILTUR / "lsi" / f"{split}-00000-of-00001.parquet")
    out = []
    for row in df.itertuples(index=False):
        text = row.text
        facts = " ".join(str(s) for s in text) if not isinstance(text, str) else text
        out.append({"id": str(row.id), "facts": facts,
                    "labels": sorted({names[int(x)] for x in row.labels})})
    return out


def sample(rows, n, seed):
    rng = random.Random(seed)
    return rows if n >= len(rows) else rng.sample(rows, n)


def predicted_labels(sections, label_list):
    """Labels whose base section the pipeline predicted."""
    secs = set(sections)
    return sorted(lab for lab in label_list if base_section(lab) in secs)


def metrics(gold, pred, labels):
    """gold/pred: list of label sets per document; labels: the label universe."""
    tp = {l: 0 for l in labels}
    fp = dict(tp)
    fn = dict(tp)
    for g, p in zip(gold, pred):
        for l in labels:
            if l in p and l in g:
                tp[l] += 1
            elif l in p:
                fp[l] += 1
            elif l in g:
                fn[l] += 1

    def f1(t, f_p, f_n):
        return 0.0 if t == 0 else 2 * t / (2 * t + f_p + f_n)

    per = {l: f1(tp[l], fp[l], fn[l]) for l in labels}
    supported = [l for l in labels if tp[l] + fn[l] > 0]
    T, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn.values())
    return {
        "macro_f1_supported": sum(per[l] for l in supported) / len(supported) if supported else 0.0,
        "macro_f1_all": sum(per.values()) / len(labels) if labels else 0.0,
        "micro_precision": T / (T + FP) if T + FP else 0.0,
        "micro_recall": T / (T + FN) if T + FN else 0.0,
        "micro_f1": f1(T, FP, FN),
        "n_labels_supported": len(supported),
        "per_label_f1": per,
    }


def bootstrap_ci(gold, pred, labels, key="macro_f1_supported", reps=1000, seed=0):
    """95% percentile bootstrap CI over documents."""
    rng = random.Random(seed)
    n = len(gold)
    vals = []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        vals.append(metrics([gold[i] for i in idx], [pred[i] for i in idx], labels)[key])
    vals.sort()
    return vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]


def read_results(path):
    rows = []
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows

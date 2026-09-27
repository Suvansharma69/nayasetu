"""IL-TUR LSI scoring: label parsing and metrics (checked against scikit-learn)."""
import pytest

from src.eval import lsi

README = """---
dataset_info:
- config_name: lsi
  features:
  - name: labels
    list:
      class_label:
        names:
          '0': Section 2
          '1': Section 34
          '2': Section 294(b)
          '3': Section 302
          '4': Section 120B
- config_name: pcr
"""


def test_label_names_come_from_the_dataset_card(tmp_path):
    p = tmp_path / "README.md"
    p.write_text(README, encoding="utf-8")
    assert lsi.label_names(p) == {0: "Section 2", 1: "Section 34", 2: "Section 294(b)",
                                  3: "Section 302", 4: "Section 120B"}


def test_labels_match_at_section_level():
    labels = ["Section 294", "Section 294(b)", "Section 302", "Section 120B"]
    assert lsi.predicted_labels(["294", "120B"], labels) == ["Section 120B", "Section 294", "Section 294(b)"]
    assert lsi.base_section("Section 294(b)") == "294"


def test_metrics_agree_with_sklearn():
    from sklearn.metrics import f1_score, precision_score, recall_score
    from sklearn.preprocessing import MultiLabelBinarizer

    labels = ["a", "b", "c", "d"]
    gold = [{"a", "b"}, {"b"}, {"c"}, {"a"}, {"b", "c"}]
    pred = [{"a"}, {"b", "c"}, set(), {"a", "d"}, {"b"}]
    m = lsi.metrics(gold, pred, labels)
    mlb = MultiLabelBinarizer(classes=labels)
    G, P = mlb.fit_transform(gold), mlb.transform(pred)
    assert m["micro_f1"] == pytest.approx(f1_score(G, P, average="micro"))
    assert m["micro_precision"] == pytest.approx(precision_score(G, P, average="micro"))
    assert m["micro_recall"] == pytest.approx(recall_score(G, P, average="micro"))
    assert m["macro_f1_all"] == pytest.approx(f1_score(G, P, average="macro", zero_division=0))
    # "d" has no gold support in this sample, so it is left out of the supported macro
    supported = f1_score(G[:, :3], P[:, :3], average="macro", zero_division=0)
    assert m["macro_f1_supported"] == pytest.approx(supported) and m["n_labels_supported"] == 3


def test_bootstrap_ci_brackets_the_point_estimate():
    labels = ["a", "b"]
    gold = [{"a"}, {"b"}, {"a", "b"}, {"a"}] * 10
    pred = [{"a"}, {"a"}, {"a", "b"}, set()] * 10
    lo, hi = lsi.bootstrap_ci(gold, pred, labels, reps=200)
    point = lsi.metrics(gold, pred, labels)["macro_f1_supported"]
    assert lo <= point <= hi

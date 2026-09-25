"""The build must not be able to claim records it did not write.

Both checks here exist because of one incident: a rebuild killed mid-write left
`judgments_post2024.jsonl` at 0 lines while `build_report.json` went on claiming
42,890. Nothing objected. A short JSONL file is still valid JSONL -- every line
parses, every chunk validates, no id repeats -- so re-reading the corpus cannot
notice on its own. It takes an independent count to disagree with.

This matters more here than in an ordinary pipeline. Everything downstream
treats the corpus as the definition of what exists: the citation graph's nodes
are built from it, and Node 2 calls a section real only if it is in the graph.
A silently short corpus therefore does not make the system's answers vaguer --
it makes it deny that real sections and real judgments exist.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.ingest.schema import SchemaError

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name):
    """scripts/ is not a package, so load by path rather than import."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_corpus = _load_script("build_corpus")
spotcheck = _load_script("spotcheck")


def _statute_chunk(section):
    return {
        "chunk_id": f"bns_s{section}",
        "doc_id": "bns_2023",
        "doc_type": "statute",
        "text": "Theft. Whoever dishonestly takes movable property out of possession.",
        "source": "https://example.invalid/bns.pdf",
        "court": None,
        "date": None,
        "sections_involved": [section],
        "corpus": "bns",
        "section": section,
        "section_title": "Theft",
        "chapter": None,
        "chapter_title": None,
    }


# --- the writer verifies its own output ------------------------------------


def test_writer_accepts_a_complete_file(tmp_path):
    w = build_corpus.Writer(tmp_path / "ok.jsonl")
    for s in ("303", "304", "305"):
        w.write(_statute_chunk(s))
    w.close()          # must not raise
    assert sum(1 for _ in (tmp_path / "ok.jsonl").open(encoding="utf-8")) == 3


def test_writer_rejects_a_count_the_file_does_not_support(tmp_path):
    """The in-memory counter is not evidence; the file is.

    `self.n` is forced out of step here to stand in for the real failure, where
    the process died and the file was left short of what it had counted.
    """
    w = build_corpus.Writer(tmp_path / "short.jsonl")
    w.write(_statute_chunk("303"))
    w.n = 42890
    with pytest.raises(SchemaError, match="truncated"):
        w.close()


# --- the gate cross-checks the build's own report ---------------------------


def _report(**overrides):
    base = {
        "statutes_ipc": 574,
        "statutes_bns": 358,
        "judgments_pre2024": 32497,
        "judgments_post2024": 42890,
        "bns_missing_titles": [],
    }
    return base | overrides


def _stats(**overrides):
    base = {
        "statutes_ipc.jsonl": 574,
        "statutes_bns.jsonl": 358,
        "judgments_pre2024.jsonl": 32497,
        "judgments_post2024.jsonl": 42890,
    }
    return base | overrides


def _run_check(tmp_path, report, stats, monkeypatch):
    if report is not None:
        (tmp_path / "build_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
    monkeypatch.setattr(spotcheck, "PROCESSED", tmp_path)
    warnings = []
    problems = spotcheck._check_against_report(stats, warnings)
    return problems, warnings


def test_agreeing_counts_raise_nothing(tmp_path, monkeypatch):
    problems, warnings = _run_check(tmp_path, _report(), _stats(), monkeypatch)
    assert problems == []
    assert warnings == []


def test_a_report_claiming_more_than_the_file_holds_is_fatal(tmp_path, monkeypatch):
    """The exact shape of the incident: 0 lines on disk, 42,890 claimed."""
    problems, _ = _run_check(
        tmp_path, _report(), _stats(**{"judgments_post2024.jsonl": 0}), monkeypatch
    )
    assert len(problems) == 1
    assert "judgments_post2024" in problems[0]
    assert "0 lines on disk" in problems[0]
    assert "42890" in problems[0]


def test_every_corpus_file_is_cross_checked_not_just_the_judgments(tmp_path, monkeypatch):
    problems, _ = _run_check(
        tmp_path, _report(), _stats(**{"statutes_bns.jsonl": 347}), monkeypatch
    )
    assert len(problems) == 1
    assert "statutes_bns" in problems[0]


def test_untitled_bns_sections_are_a_parser_regression_not_a_gazette_property(
    tmp_path, monkeypatch
):
    """All 358 BNS sections carry a marginal note, so this list must stay empty.

    It was non-empty for the whole life of the old margin-geometry bug, sitting
    in the report where anyone could have read it, and was taken for a fact
    about the source document instead of a defect.
    """
    problems, _ = _run_check(
        tmp_path, _report(bns_missing_titles=["44", "62"]), _stats(), monkeypatch
    )
    assert len(problems) == 1
    assert "parser regression" in problems[0]


def test_a_missing_report_warns_rather_than_failing(tmp_path, monkeypatch):
    """No report is unverifiable, not corrupt -- a distinction worth keeping.

    Failing here would make the gate unusable on a corpus built before the
    report existed, and would say "corrupt" about something merely unproven.
    """
    problems, warnings = _run_check(tmp_path, None, _stats(), monkeypatch)
    assert problems == []
    assert any("NO REPORT" in w for w in warnings)


def test_a_count_missing_from_the_report_warns_rather_than_failing(
    tmp_path, monkeypatch
):
    report = _report()
    del report["judgments_post2024"]
    problems, warnings = _run_check(tmp_path, report, _stats(), monkeypatch)
    assert problems == []
    assert any("NO COUNT" in w and "judgments_post2024" in w for w in warnings)

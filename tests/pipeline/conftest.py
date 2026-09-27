"""A small synthetic citation graph with the collisions that matter:
IPC 302 (murder) vs BNS 302 (something else), IPC 420 with no BNS 420,
IPC 378/379 -> BNS 303, IPC 34 -> BNS 3."""
import json

import pytest

from src.graph import citation_graph as cg


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _statute(code, sec, title):
    return {"chunk_id": f"{code}_s{sec}", "section": sec, "section_title": title,
            "corpus": code, "source": "x"}


@pytest.fixture
def g(tmp_path):
    _write(tmp_path / "statutes_ipc.jsonl", [
        _statute("ipc", "302", "Murder"), _statute("ipc", "378", "Theft"),
        _statute("ipc", "379", "Punishment for theft"), _statute("ipc", "34", "Common intention"),
        _statute("ipc", "420", "Cheating and dishonestly inducing delivery of property"),
        _statute("ipc", "323", "Punishment for voluntarily causing hurt")])
    _write(tmp_path / "statutes_bns.jsonl", [
        _statute("bns", "302", "Uttering words with deliberate intent to wound religious feelings"),
        _statute("bns", "303", "Theft"), _statute("bns", "3", "General explanations"),
        _statute("bns", "318", "Cheating"), _statute("bns", "103", "Punishment for murder"),
        _statute("bns", "115", "Voluntarily causing hurt")])
    for f in ("judgments_pre2024.jsonl", "judgments_post2024.jsonl"):
        (tmp_path / f).write_text("", encoding="utf-8")
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"entries": {
        "378": {"bns_section": "303", "decision": "confirmed"},
        "379": {"bns_section": "303", "decision": "corrected"},
        "34": {"bns_section": "3", "bns_subsection": "3(5)", "decision": "confirmed"},
        "302": {"bns_section": "103", "decision": "corrected"},
        "420": {"bns_section": "318", "decision": "confirmed"},
        "323": {"bns_section": "115", "decision": "confirmed"}}}), encoding="utf-8")
    return cg.build(tmp_path, mapping)


class ScriptedLLM:
    """Returns one scripted proposal list per call; records every call."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls = []

    def __call__(self, messages, schema):
        self.calls.append(messages)
        secs = self.rounds[min(len(self.calls) - 1, len(self.rounds) - 1)]
        return {"sections": [{"section": s, "reason": "r"} for s in secs]}


@pytest.fixture
def scripted():
    return ScriptedLLM

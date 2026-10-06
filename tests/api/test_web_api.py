import time

import pytest
from fastapi.testclient import TestClient

from src.api import main
from src.pipeline import progress


@pytest.fixture
def client(monkeypatch):
    def fake_run(facts, offence_date, offence_date_to=None, full=False):
        for stage in ("route", "retrieve", "statute_identifier", "verifier"):
            progress.mark(stage)
        progress.mark("verifier", "done", {"verified": [{"ref": "303"}], "unconfirmed": []})
        return {"facts": facts, "date": offence_date}

    monkeypatch.setattr(main.graph, "run", fake_run)
    monkeypatch.setattr(main.report, "build", lambda res: {"status": "ok", **res})
    return TestClient(main.app)


FACTS = "The accused took the complainant's motorcycle from outside his house at night."


def test_web_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Start a matter from its facts." in r.text
    # Fonts are served locally: the page must make no request outside this machine.
    assert "/static/fonts/fonts.css" in r.text and "fonts.googleapis.com" not in r.text
    css = client.get("/static/fonts/fonts.css")
    assert css.status_code == 200 and "https://" not in css.text and "/static/fonts/" in css.text
    font = client.get(css.text.split("url(")[1].split(")")[0])
    assert font.status_code == 200 and len(font.content) > 5000


def test_dates_endpoint_routes_each_date(client):
    r = client.post("/dates", json={"text": "The theft was on 30 June 2024; FIR on 2 July 2024."}).json()
    assert [(d["date"], d["era"]) for d in r["dates"]] == [("2024-06-30", "ipc"), ("2024-07-02", "bns")]
    future = client.post("/dates", json={"text": "on 1 January 2099"}).json()["dates"][0]
    assert future["era"] is None and "future" in future["error"]


def test_job_reports_stages_then_the_report(client):
    jid = client.post("/jobs", json={"facts": FACTS, "offence_date": "2024-08-15"}).json()["id"]
    for _ in range(100):
        s = client.get(f"/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert s["state"] == "done", s
    assert [(x["stage"], x["phase"]) for x in s["stages"]] == [
        ("route", "start"), ("retrieve", "start"), ("statute_identifier", "start"), ("verifier", "start"),
        ("verifier", "done")]
    assert s["stages"][-1]["data"] == {"verified": [{"ref": "303"}], "unconfirmed": []}
    assert s["stages"][0]["label"] == progress.STAGES["route"]
    assert s["report"] == {"status": "ok", "facts": FACTS, "date": "2024-08-15"}


def test_job_rejects_a_bad_date_before_starting(client):
    assert client.post("/jobs", json={"facts": FACTS, "offence_date": "15/08/2024"}).status_code == 422
    assert client.post("/jobs", json={"facts": FACTS, "offence_date": "2099-01-01"}).status_code == 422
    assert client.get("/jobs/nope").status_code == 404


def test_samples_and_saved_reports(client):
    samples = client.get("/samples").json()
    assert samples and all({"id", "name", "facts", "offence_date", "saved"} <= set(s) for s in samples)
    saved = next(s for s in samples if s["saved"])
    assert client.get(f"/samples/{saved['id']}").json()["status"]
    assert client.get("/samples/..%2Fcases").status_code == 404


def test_progress_is_silent_without_a_listener():
    progress.mark("route")  # no listener installed: must not raise
    seen = []
    with progress.listening(seen.append):
        progress.mark("verifier")
    progress.mark("defense")
    assert seen == [{"stage": "verifier", "phase": "start", "data": None}]


def test_staged_node_reports_what_it_produced():
    seen = []
    node = progress.staged("verifier", lambda st: {
        "verified_sections": [{"section": "303", "subsection": "303(2)", "title": "Theft", "raw": "303(2)"}],
        "unconfirmed": [{"raw": "421", "why": "not real", "round": 0}]})
    with progress.listening(seen.append):
        out = node({})
    assert out["verified_sections"][0]["section"] == "303"
    assert [e["phase"] for e in seen] == ["start", "done"]
    assert seen[1]["data"]["verified"][0]["ref"] == "303(2)"
    assert seen[1]["data"]["unconfirmed"][0]["raw"] == "421"


def test_a_broken_summary_never_breaks_the_node():
    seen = []
    node = progress.staged("precedents", lambda st: {"precedents": [{"no_for_charge": 1}]})
    with progress.listening(seen.append):
        assert node({}) == {"precedents": [{"no_for_charge": 1}]}
    assert seen[-1] == {"stage": "precedents", "phase": "done", "data": None}

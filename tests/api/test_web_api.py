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
        return {"facts": facts, "date": offence_date}

    monkeypatch.setattr(main.graph, "run", fake_run)
    monkeypatch.setattr(main.report, "build", lambda res: {"status": "ok", **res})
    return TestClient(main.app)


FACTS = "The accused took the complainant's motorcycle from outside his house at night."


def test_web_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Tell me about the case" in r.text


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
    assert [x["stage"] for x in s["stages"]] == ["route", "retrieve", "statute_identifier", "verifier"]
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
    assert seen == ["verifier"]

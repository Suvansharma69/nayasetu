from src.api import report


def _result(retrieved):
    state = {"case_facts": "f", "offence_date": "2024-08-15", "retrieved": retrieved,
             "unconfirmed": [], "withdrawn": [], "precedents": [], "defenses": []}
    return {"status": "ok", "era": "bns", "state": state, "charges": [], "doubted": [], "included": []}


def test_report_keeps_the_ranked_candidate_list_for_replay():
    rows = [{"section": str(300 + i), "matched": f"{300 + i}(1)" if i == 3 else None, "title": f"t{i}"}
            for i in range(20)]
    out = report.build(_result(rows))["retrieved"]
    assert len(out) == report.RETRIEVED_KEPT
    assert [r["section"] for r in out[:4]] == ["300", "301", "302", "303"]
    assert out[3]["ref"] == "303(1)" and out[0]["ref"] == "300"


def test_report_without_retrieval_has_an_empty_list():
    assert report.build(_result(None))["retrieved"] == []

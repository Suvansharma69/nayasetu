from src.pipeline import applicability, graph, nodes, offence_rules


def v(section, subsection=None):
    return {"section": section, "subsection": subsection, "title": f"t{section}", "raw": section}


# --- lesser-included -----------------------------------------------------------

def test_lesser_included_under_supported_greater():
    ver = [v("420"), v("468"), v("417")]
    inc = offence_rules.included_in("ipc", ver, {("420", None), ("468", None), ("417", None)})
    assert inc == {("417", None): "IPC 420"}


def test_doubted_greater_absorbs_nothing():
    # If the aggravated form falls, the plain one is what remains.
    ver = [v("326"), v("324")]
    assert offence_rules.included_in("ipc", ver, {("324", None)}) == {}


def test_bns_subsection_keys():
    ver = [v("118", "118(2)"), v("115", "115(2)"), v("117", "117(2)")]
    sup = {(x["section"], x["subsection"]) for x in ver}
    inc = offence_rules.included_in("bns", ver, sup)
    assert inc == {("115", "115(2)"): "BNS 118(2)", ("117", "117(2)"): "BNS 118(2)"}
    # 118(1) is hurt by weapon: it does not include grievous hurt (117).
    ver = [v("118", "118(1)"), v("117", "117(2)")]
    assert offence_rules.included_in("bns", ver, {(x["section"], x["subsection"]) for x in ver}) == {}


def test_codes_never_mix():
    # 420 is not an offence in the BNS table; nothing is absorbed across codes.
    assert offence_rules.included_in("bns", [v("420"), v("417")], {("420", None), ("417", None)}) == {}


def test_lesser_switch(monkeypatch):
    monkeypatch.setenv("PRAMANA_ABLATE", "lesser")
    assert offence_rules.included_in("ipc", [v("420"), v("417")], {("420", None), ("417", None)}) == {}


def _state(ver, appl):
    return {"verified_sections": ver, "applicability": appl}


def _a(section, supported, sub=None, included_in=None, missing=""):
    return {"section": section, "subsection": sub, "supported": supported, "included_in": included_in,
            "missing_ingredient": missing, "rule_rejected": None}


def test_split_lists_included_apart():
    ver = [v("420"), v("417"), v("302")]
    st = _state(ver, [_a("420", True), _a("417", True, included_in="IPC 420"), _a("302", False, missing="no death")])
    out = graph.split_by_applicability(st)
    assert [c["section"] for c in out["charges"]] == ["420", "302"]
    assert [(c["section"], c["included_in"]) for c in out["included"]] == [("417", "IPC 420")]
    assert [d["section"] for d in out["doubted"]] == ["302"]
    assert [c["section"] for c in applicability.charged(st)] == ["420", "302"]


# --- injury grade ----------------------------------------------------------------

def P(**kw):
    return {"injury": "grievous hurt", "dangerous_weapon": True, "harm_intended": True, **kw}


def test_injury_rule_grades():
    assert offence_rules.injury_rule("ipc", P())["raw"] == "IPC 326"
    assert offence_rules.injury_rule("ipc", P(dangerous_weapon=False))["raw"] == "IPC 325"
    assert offence_rules.injury_rule("ipc", P(injury="hurt"))["raw"] == "IPC 324"
    assert offence_rules.injury_rule("bns", P())["raw"] == "BNS 118(2)"
    assert offence_rules.injury_rule("bns", P(injury="hurt", dangerous_weapon=False))["raw"] == "BNS 115(2)"


def test_injury_rule_silent_without_intent_or_harm():
    assert offence_rules.injury_rule("ipc", P(harm_intended=False)) is None   # negligence: 337/338, not 325
    assert offence_rules.injury_rule("ipc", P(injury="none")) is None
    assert offence_rules.injury_rule("ipc", P(injury="death")) is None        # murder vs homicide: not a rule's call
    assert offence_rules.injury_rule("ipc", {}) is None


def test_injury_rule_goes_before_same_section_other_subsection():
    props = [{"raw": "303", "reason": "x", "round": 0}, {"raw": "118(1)", "reason": "y", "round": 0}]
    out = nodes.add_injury_rule("bns", P(), props)
    assert [p["raw"] for p in out] == ["303", "BNS 118(2)", "118(1)"]


def test_injury_rule_no_duplicate_and_appends():
    props = [{"raw": "326", "reason": "x", "round": 0}]
    assert nodes.add_injury_rule("ipc", P(), props) == props
    out = nodes.add_injury_rule("ipc", P(dangerous_weapon=False), props)
    assert [p["raw"] for p in out] == ["326", "IPC 325"]


def test_death_rule():
    assert "requires a death" in offence_rules.death_rule("ipc", "302", {"injury": "grievous hurt"})
    assert offence_rules.death_rule("ipc", "302", {"injury": "death"}) is None
    assert offence_rules.death_rule("ipc", "302", {}) is None                 # not reported: no rule
    assert offence_rules.death_rule("ipc", "307", {"injury": "hurt"}) is None  # attempt needs no death
    assert offence_rules.death_rule("bns", "103", {"injury": "none"})


def test_injury_switch(monkeypatch):
    monkeypatch.setenv("PRAMANA_ABLATE", "injury")
    assert offence_rules.injury_rule("ipc", P()) is None
    assert offence_rules.death_rule("ipc", "302", {"injury": "hurt"}) is None
    assert "injury" not in nodes.proposal_schema()["properties"]


def test_schema_asks_injury_before_sections():
    s = nodes.proposal_schema()
    keys = list(s["properties"])
    assert keys.index("injury") < keys.index("sections") and keys[-1] == "sections"
    assert s["properties"]["injury"]["enum"] == offence_rules.INJURY_LEVELS
    assert set(offence_rules.INJURY_FIELDS) <= set(s["required"])


# --- self-negated proposals and grievous-hurt consistency -------------------------

def test_self_negated_reasons():
    assert nodes.self_negated("The facts do not disclose dishonest misappropriation by the landlord.")
    assert nodes.self_negated("No evidence of deception is alleged.")
    assert nodes.self_negated("Cheating is not made out on these facts.")
    # A negation inside a positive reason is kept.
    assert not nodes.self_negated("The accused took the motorcycle and did not return it.")
    assert not nodes.self_negated("The accused had no permission to take it.")


def test_withdrawn_proposals_never_reach_the_verifier():
    state = {"era": "bns", "retry_count": 0, "candidate_sections": [], "unconfirmed": [],
             "verified_sections": [], "retrieved": [], "offence_date": "2025-03-01", "case_facts": "x"}
    reply = {"discloses_offence": False, "why": "civil", "accused_count": 1, "acted_together": False,
             "shared_plan_or_object": False, "injury": "none", "dangerous_weapon": False,
             "harm_intended": False,
             "sections": [{"section": "316", "reason": "The facts do not disclose misappropriation."},
                          {"section": "318", "reason": "The landlord deceived the tenant into paying."}]}
    out = nodes.statute_identifier(state, lambda m, s: reply)
    assert [c["raw"] for c in out["candidate_sections"]] == ["318"]
    assert [w["raw"] for w in out["withdrawn"]] == ["316"]


def test_grievous_consistency_overrules_contradictory_doubt():
    ver = [v("324"), v("326")]
    recs = [{"section": "324", "subsection": None, "supported": True},
            {"section": "326", "subsection": None, "supported": False}]
    out = offence_rules.grievous_consistency("ipc", ver, recs, {"injury": "grievous hurt"})
    assert list(out) == [("326", None)]
    # Not when Node 1 reported only hurt, and not when the twin was doubted too.
    assert offence_rules.grievous_consistency("ipc", ver, recs, {"injury": "hurt"}) == {}
    recs[0]["supported"] = False
    assert offence_rules.grievous_consistency("ipc", ver, recs, {"injury": "grievous hurt"}) == {}


# --- companion offences ------------------------------------------------------------

def C(**kw):
    return {"other_hurt": False, "threat": "none", "insult": False, "obscene_in_public": False, **kw}


def test_companion_rules_map_each_fact_to_its_section():
    raws = lambda era, p: [r["raw"] for r in offence_rules.companion_rules(era, p)]  # noqa: E731
    assert raws("ipc", C()) == []
    assert raws("ipc", C(other_hurt=True, threat="death or grievous hurt", insult=True, obscene_in_public=True)) \
        == ["IPC 323", "IPC 506", "IPC 504", "IPC 294"]
    assert raws("ipc", C(threat="other harm")) == ["IPC 506"]          # one section, both limbs
    assert raws("bns", C(threat="other harm")) == ["BNS 351(2)"]
    assert raws("bns", C(threat="death or grievous hurt")) == ["BNS 351(3)"]
    assert raws("bns", C(other_hurt=True, insult=True, obscene_in_public=True)) \
        == ["BNS 115(2)", "BNS 352", "BNS 296"]
    assert offence_rules.companion_rules("ipc", {}) == []


def test_companion_rules_skip_what_the_model_named_and_mark_its_323():
    props = [{"raw": "324", "reason": "x", "round": 0}, {"raw": "323", "reason": "y", "round": 0},
             {"raw": "506", "reason": "z", "round": 0}]
    out = nodes.add_companion_rules("ipc", C(other_hurt=True, threat="other harm", insult=True), props)
    assert [p["raw"] for p in out] == ["324", "323", "506", "IPC 504"]
    assert out[1].get("separate_act") and not out[0].get("separate_act")


def test_separate_act_hurt_is_not_absorbed_into_the_graver_hurt():
    ver = [v("324"), {**v("323"), "separate_act": True}]
    assert offence_rules.included_in("ipc", ver, {("324", None), ("323", None)}) == {}
    # the same pair without the mark is one act: 323 is included in 324
    assert offence_rules.included_in("ipc", [v("324"), v("323")], {("324", None), ("323", None)}) \
        == {("323", None): "IPC 324"}


def test_separate_act_survives_node_2(g):
    ok, bad = nodes.check(g, "ipc", {"raw": "IPC 323", "reason": "r", "round": 0, "source": "rule",
                                      "separate_act": True})
    assert not bad and ok[0]["separate_act"] and ok[0]["section"] == "323"
    ok, _ = nodes.check(g, "bns", {"raw": "BNS 115(2)", "reason": "r", "round": 0, "source": "rule",
                                    "separate_act": True})
    assert ok[0]["subsection"] == "115(2)" and ok[0]["separate_act"]   # rule sub-section kept


def test_companion_questions_are_not_in_node1s_call():
    # 2026-10-11: inside Node 1's call they primed it to name more sections
    # (dev precision 41% -> 32-33%); they are asked in a call of their own
    s = nodes.proposal_schema()
    assert not set(offence_rules.COMPANION_FIELDS) & set(s["properties"])
    for era in ("ipc", "bns"):
        assert "obscene" not in nodes._system_prompt(era)
    c = offence_rules.COMPANION_CALL_SCHEMA
    assert set(c["properties"]) == set(c["required"]) == set(offence_rules.COMPANION_FIELDS)
    assert "sections" not in c["properties"]


def _node1_state(facts="A beat B with a stick and threatened to kill him."):
    return {"case_facts": facts, "offence_date": "2023-01-01", "era": "ipc", "retrieved": [],
            "candidate_sections": [], "verified_sections": [], "unconfirmed": [], "retry_count": 0}


def test_companion_call_feeds_the_rule(scripted):
    llm = scripted(["324"], profile={"discloses_offence": True, "injury": "hurt",
                                     "threat": "death or grievous hurt", "insult": False,
                                     "other_hurt": False, "obscene_in_public": False})
    up = nodes.statute_identifier(_node1_state(), llm)
    assert len(llm.calls) == 1 and len(llm.companion_calls) == 1
    sent = llm.companion_calls[0]
    assert "Retrieved candidate" not in sent[-1]["content"]          # facts only
    assert "Most serious harm already recorded: hurt" in sent[-1]["content"]
    assert up["facts_profile"]["threat"] == "death or grievous hurt"
    assert [p["raw"] for p in up["candidate_sections"]][-1] == "IPC 506"


def test_companion_switch(monkeypatch, scripted):
    monkeypatch.setenv("PRAMANA_ABLATE", "companion")
    llm = scripted(["324"], profile={"discloses_offence": True, "injury": "hurt", "threat": "other harm"})
    up = nodes.statute_identifier(_node1_state(), llm)
    assert not llm.companion_calls and "threat" not in up["facts_profile"]
    assert offence_rules.companion_rules("ipc", C(insult=True)) == []
    monkeypatch.setenv("PRAMANA_ABLATE", "injury")          # other_hurt is defined against the injury answer
    llm = scripted(["324"])
    nodes.statute_identifier(_node1_state(), llm)
    assert not llm.companion_calls

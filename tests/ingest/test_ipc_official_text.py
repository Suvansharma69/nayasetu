"""Rules of scripts/ipc_official_text.py, each pinned by the source quirk it handles.

Synthetic text only: the official PDF is raw data and is not committed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ipc_official_text as m  # noqa: E402


def _lines(*texts):
    return [(1, t) for t in texts]


def test_body_number_on_its_own_line_is_not_a_margin_head():
    """The source prints s54's body as '55.' + 'Commutation...--In every case'.
    Taking it for a head would start a phantom s55 holding s54's text."""
    lines = _lines(" 54.", "", "", "Commutation of sentence of death.", "", "",
                   "55.", "Commutation  of sentence  of death.--In  every case", "")
    assert m._is_margin_head(lines, 0)
    assert not m._is_margin_head(lines, 6)


def test_exceptions_after_illustrations_are_kept():
    """s300 puts its Illustrations BEFORE its Exceptions."""
    paras = ["culpable homicide is murder, if the act...", "Illustrations",
             "(a) A shoots Z with the intention of killing him.",
             "Exception 1.-When culpable homicide is not murder.-Culpable homicide is not murder if...",
             "Illustrations", "(a) A, under the influence of passion..."]
    out = m._drop_illustrations(paras)
    assert out == [paras[0], paras[3]]


def test_misspelt_and_inline_illustrations_are_dropped():
    assert m._ILLUSTRATION.match("Iiiustration")              # s166, s364
    assert m._ILLUSTRATION.match("Illustriations")            # s330
    paras = m._paragraphs(["Explanation.-The offence is committed whether real or imaginary. "
                           "Illustrations (a) A cheats by pretending to be B."])
    assert m._drop_illustrations(paras) == [
        "Explanation.-The offence is committed whether real or imaginary."]


def test_inline_marginal_subheading_is_removed():
    """'if a capital offence; if a capital offence.--shall, if...' (s201, s212)."""
    out = m._drop_subheadings(["gives any information, if a capital offence; if a capital "
                               "offence.--shall, if the offence is punishable with death"])
    assert out == ["gives any information, shall, if the offence is punishable with death"]
    out = m._drop_subheadings(["respecting such design, if offence be committed-if offence be not "
                               "committed. if offence be committed-if offence be not "
                               "committed.--shall, if that offence be committed"])
    assert out == ["respecting such design, shall, if that offence be committed"]


def test_bare_subheading_and_its_glued_copy_become_one_limb():
    """s506: the threat-to-kill limb must stay part of the section's sentence."""
    out = m._drop_subheadings(["Whoever commits it shall be punished, or with both;",
                               "If threat be to cause death or grievous hurt, etc.",
                               "If threat be to cause death or grievous hurt, etc.--and if the "
                               "threat be to cause death, for seven years."])
    assert out == ["Whoever commits it shall be punished, or with both; and if the threat be "
                   "to cause death, for seven years."]


def test_markers_and_widely_spaced_omission_stars_are_removed():
    assert m._paragraphs(["2*[Secondly.--Imprisonment for life;]", "",
                          "3*            *               *            *",
                          "Fourthly.--Imprisonment"]) == [
        "Secondly.--Imprisonment for life;", "Fourthly.--Imprisonment"]
    assert m._paragraphs(["the appropriate Government 5[may commute"]) == [
        "the appropriate Government may commute"]


def test_footnote_after_inline_rule_is_dropped():
    assert m._paragraphs(["shall also be liable to fine. ------------------------ 1. Subs. "
                          "by Act 19 of 1872, s. 1, for the original paragraph."]) == [
        "shall also be liable to fine."]


def test_paragraph_never_opens_in_lower_case():
    assert m._paragraphs(["facilitate the commission", "", "of an offence punishable"]) == [
        "facilitate the commission of an offence punishable"]


def test_completion_rule_requires_a_prefix():
    cut = "Whoever commits the offence shall be punished for two years, or with both;"
    assert m.is_completion(cut, cut + " and if the threat be to cause death, seven years.")
    assert not m.is_completion(cut, cut)
    assert not m.is_completion("Whoever by electronic means commits it shall be punished.",
                               cut + " and if the threat be to cause death, seven years.")


def test_intrusion_by_gap_and_by_long_run():
    """s214's block ran into the middle of s216 (s215's head was never found)."""
    s216 = ("whenever a public servant in the exercise of the lawful powers of such public "
            "servant orders a certain person to be apprehended for an offence whoever knowing "
            "of such escape or order for apprehension harbours or conceals that person with "
            "the intention of preventing him from being apprehended shall be punished in the "
            "manner following that is to say")
    civic = {"214": ("Whoever gives any gratification;", ""), "215": ("Whoever takes...", ""),
             "216": (s216, "")}
    up = "Whoever gives any gratification;"
    assert m.intrusion("214", up, up + " shall be punished.", civic, "216").startswith(
        "block spans unparsed s215")
    assert m.intrusion("214", up, up + " shall be punished.", civic, "215") is None
    assert m.intrusion("214", up, up + " or " + s216, civic, "215").startswith("shares")

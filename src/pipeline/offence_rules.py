r"""Deterministic offence rules, read off the structure of the codes themselves.

Four rules, each switchable for ablation:

* Lesser-included offences (`lesser`). When an aggravated form of an offence is
  charged AND Node 2b supports it, the plain form is redundant beside it: IPC
  420 (cheating and dishonestly inducing delivery) is cheating plus more, so
  IPC 417 (punishment for cheating) adds nothing. The lesser section is not
  deleted; it is shown as "included in" the greater one. A greater offence the
  judge DOUBTED never absorbs anything -- if it falls, the lesser charge is
  what remains. Only pairs whose ingredients nest by the statute's own words
  are listed (380 is "theft in a dwelling house": theft plus a place).

* Injury grade (`injury`). The hurt offences are graded by two facts, the
  injury (hurt / grievous hurt, IPC 320 / BNS 116 list grievous hurt
  exhaustively) and the means (a dangerous weapon or means, IPC 324/326 / BNS
  118). Node 1 reports both in its fact profile; this rule maps them to the
  section, which Node 2 then verifies like any other proposal. Measured: the
  demo's skull fracture with an iron rod was charged as simple hurt by weapon
  (324), not grievous hurt (326) -- the grading was left to the model.

* Death (`injury`). Murder, culpable homicide, dowry death, death by
  negligence and abetment of suicide all need a death. When Node 1 reported
  the worst harm as something less, those sections get a rule doubt, as the
  headcount rule does for an unlawful assembly of three.

* Attempts (`attempt`). The converse: an attempt to murder (IPC 307 / BNS 109)
  is never doubted merely because no one died.
"""
from __future__ import annotations

import re

from . import ablation

# greater -> lesser sections it includes. A key may be a sub-section
# ("118(2)"); the lookup tries the sub-section first, then the section.
INCLUDED = {
    "ipc": {
        "418": {"417"}, "419": {"417"}, "420": {"417"},
        "324": {"323"}, "325": {"323"}, "326": {"323", "324", "325"},
        "380": {"379"}, "381": {"379"}, "382": {"379"},
        "392": {"379"}, "394": {"392", "379", "323"},
        "407": {"406"}, "408": {"406"}, "409": {"406"},
        "342": {"341"}, "448": {"447"},
        "467": {"465"}, "468": {"465"},
    },
    "bns": {
        "117": {"115"}, "118(1)": {"115"}, "118(2)": {"115", "117"},
        "304": {"303"}, "305": {"303"}, "306": {"303"}, "307": {"303"}, "309": {"303"},
        "127": {"126"},
    },
}


def included_in(era, verified, supported):
    """{(section, subsection): "IPC 420"} for each verified section included in a
    SUPPORTED greater one. `supported` is a set of (section, subsection) keys."""
    if ablation.off("lesser"):
        return {}
    table = INCLUDED.get(era, {})
    out = {}
    for g in verified:
        gk = (g["section"], g.get("subsection"))
        if gk not in supported:
            continue
        lesser = table.get(g.get("subsection") or "", table.get(g["section"], set()))
        for v in verified:
            k = (v["section"], v.get("subsection"))
            if k != gk and v["section"] in lesser and k not in out:
                out[k] = f"{era.upper()} {g.get('subsection') or g['section']}"
    return out


# --- injury grade --------------------------------------------------------------

INJURY_LEVELS = ["none", "hurt", "grievous hurt", "death"]

# (injury, dangerous weapon or means) -> the section that punishes it.
INJURY_SECTIONS = {
    "ipc": {("hurt", False): "IPC 323", ("hurt", True): "IPC 324",
            ("grievous hurt", False): "IPC 325", ("grievous hurt", True): "IPC 326"},
    "bns": {("hurt", False): "BNS 115(2)", ("hurt", True): "BNS 118(1)",
            ("grievous hurt", False): "BNS 117(2)", ("grievous hurt", True): "BNS 118(2)"},
}

# IPC 320 Eighthly says twenty days; BNS 116(h) says fifteen.
_SEVERE_PAIN_DAYS = {"ipc": 20, "bns": 15}

INJURY_FIELDS = ("injury", "dangerous_weapon", "harm_intended")
INJURY_SCHEMA = {
    "injury": {"type": "string", "enum": INJURY_LEVELS},
    "dangerous_weapon": {"type": "boolean"},
    "harm_intended": {"type": "boolean"},
}


def injury_prompt(era):
    return (
        "- injury: the most serious bodily harm the facts say the accused caused to anyone: \"none\"; "
        "\"hurt\" (bodily pain, disease or infirmity); \"grievous hurt\", which is ONLY: emasculation, "
        "permanent loss of sight of an eye or of hearing of an ear, loss or permanent impairment of a "
        "limb or joint, permanent disfiguration of the head or face, fracture or dislocation of a bone "
        "or tooth, or hurt that endangers life or causes "
        f"{_SEVERE_PAIN_DAYS[era]} days of severe bodily pain or inability to follow ordinary pursuits; "
        "or \"death\".\n"
        "- dangerous_weapon: true if that harm was caused with an instrument for shooting, stabbing or "
        "cutting, or any instrument likely to cause death when used as a weapon (a knife, axe or iron "
        "rod), or by fire, poison, or a corrosive or explosive substance.\n"
        "- harm_intended: true if the accused caused that harm on purpose; false for an accident or "
        "negligence, or when no harm was caused.")


def injury_rule(era, profile):
    """The hurt section the reported injury and means call for, as a proposal, or None."""
    if ablation.off("injury") or not profile or profile.get("harm_intended") is not True:
        return None
    level = profile.get("injury")
    raw = INJURY_SECTIONS.get(era, {}).get((level, bool(profile.get("dangerous_weapon"))))
    if raw is None:
        return None
    means = "with a dangerous weapon or means" if profile.get("dangerous_weapon") else "without a weapon"
    return {"raw": raw, "reason": f"rule: {level} caused intentionally, {means}", "round": 0,
            "source": "rule"}


# Pairs whose texts differ ONLY in the harm: the greater one reads the lesser's
# words with "grievous hurt" for "hurt" (IPC 324/326 share the dangerous-weapon
# clause word for word; 323/325 share "voluntarily causes"; BNS 115/117 too).
GRIEVOUS_OF = {"ipc": {"326": "324", "325": "323"}, "bns": {"117": "115"}}


def grievous_consistency(era, verified, records, profile):
    """{(section, subsection): reason} for each doubted grievous-hurt section whose
    simple-hurt twin the judge SUPPORTED, when Node 1 reported grievous hurt.

    Measured on the group-assault demo, 2026-10-06: the judge supported IPC 324
    (hurt by an iron rod) and doubted 326 on whether the same iron rod was
    "likely to cause death" -- the identical clause it had just accepted. The
    one ingredient 326 adds is grievous hurt, and a skull fracture is grievous
    hurt by IPC 320's own list. The doubt contradicts the judge's own verdict."""
    if ablation.off("injury") or (profile or {}).get("injury") != "grievous hurt":
        return {}
    pairs = GRIEVOUS_OF.get(era, {})
    ok = {r["section"] for r in records if r["supported"]}
    out = {}
    for v, r in zip(verified, records):
        twin = pairs.get(v["section"])
        if twin and not r["supported"] and twin in ok:
            out[(v["section"], v.get("subsection"))] = (
                f"rule: the judge accepted every other ingredient for {era.upper()} {twin}, whose text is "
                f"the same but for grievous hurt, and the facts report grievous hurt")
    return out


# --- attempts --------------------------------------------------------------------

# An attempt is the act done with the intent; the result is what did NOT happen.
ATTEMPTS = {"ipc": {"307", "308", "511"}, "bns": {"62", "109", "110"}}
_ONLY_DEATH = re.compile(
    r"(?:(?:the|an?|no|actual|resulting|causing|caused|of|victim'?s?|complainant'?s?|person'?s?)\s+)*"
    r"(?:death|died|killing|killed)"
    r"(?:\s+of\s+(?:the\s+)?(?:victim|complainant|person|injured))?(?:\s+(?:was\s+)?(?:caused|occurred))?\W*")


def attempt_without_result(era, section, missing):
    """A reason string when the judge doubts an ATTEMPT only because no one died.

    Measured on the knife demo, 2026-10-15: the judge doubted BNS 109 (attempt
    to murder) with the missing ingredient "death", in both of two live runs.
    BNS 109 / IPC 307 punish the act done with intent to kill "if by that act
    death be caused" as murder -- an attempt is, by its own words, the case
    where death is NOT caused. Only a doubt that names nothing but the death is
    overruled; any other missing ingredient (intent, the act) still stands."""
    if ablation.off("attempt") or section not in ATTEMPTS.get(era, set()):
        return None
    if not missing or not _ONLY_DEATH.fullmatch(missing.strip().lower()):
        return None
    return (f"rule: {era.upper()} {section} is an attempt, which by its own words needs no death; "
            f"the judge's only objection was \"{missing.strip()}\"")


NEEDS_DEATH = {
    "ipc": {"299", "300", "302", "304", "304A", "304B", "306"},
    "bns": {"100", "101", "103", "105", "106", "80", "108"},
}


def death_rule(era, section, profile):
    """A reason string if the section needs a death and Node 1 reported none."""
    if ablation.off("injury") or section not in NEEDS_DEATH.get(era, set()):
        return None
    level = (profile or {}).get("injury")
    if level in ("none", "hurt", "grievous hurt"):
        return f"this offence requires a death; the facts report {level if level != 'none' else 'no harm'}, not death"
    return None

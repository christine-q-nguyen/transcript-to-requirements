"""DFV (desirability / feasibility / viability) and RICE scoring with written rationale.

Scores are deliberately simple and transparent: every component is 1-5 with a one-line reason,
and the label (build / test / defer / stop) follows explicit rules a reviewer can argue with.
"""
from __future__ import annotations

import re
from statistics import mean

from .schema import IntakeRecord, Score


def _conf(rec: IntakeRecord, name: str) -> float:
    f = rec.fields.get(name)
    return f.confidence if f and f.value else 0.0


def _num_in(rec: IntakeRecord, name: str) -> float | None:
    f = rec.fields.get(name)
    if not f or f.value is None:
        return None
    if isinstance(f.value, (int, float)):
        return float(f.value)
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(f.value))
    return float(m.group(0).replace(",", "")) if m else None


def score_dfv(rec: IntakeRecord) -> Score:
    users = _num_in(rec, "user_count") or 0
    d = 1.0
    d_reason = "no users, volume, or pain evidenced"
    if _conf(rec, "pain_points") >= 0.5:
        d, d_reason = 3.0, "pain points stated"
    if users >= 10 or _conf(rec, "volume_or_frequency") >= 0.7:
        d, d_reason = 4.0, f"{int(users) or 'recurring'} users/volume evidenced with pain"
    if users >= 50 and _conf(rec, "cycle_time_today") >= 0.7:
        d, d_reason = 5.0, f"{int(users)} users and quantified cycle time"

    f = 2.0
    f_reason = "data and systems unclear"
    if _conf(rec, "data_sources") >= 0.5 and _conf(rec, "systems_in_use") >= 0.5:
        f, f_reason = 3.0, "data sources and systems named"
    if _conf(rec, "data_shape") >= 0.5:
        f, f_reason = 4.0, "data shape described"
    if _conf(rec, "constraints") >= 0.6 or _conf(rec, "security_or_data_use") >= 0.6:
        f, f_reason = max(2.0, f - 1.0), f_reason + "; constraints or data-use limits raise integration risk"

    v = 2.0
    v_reason = "no sponsor or success criteria"
    if _conf(rec, "success_criteria") >= 0.5:
        v, v_reason = 3.0, "success criteria stated"
    if rec.fields.get("sponsor") and rec.fields["sponsor"].value:
        v, v_reason = 4.0, f"sponsor identified ({rec.fields['sponsor'].value}); " + v_reason
    if _conf(rec, "timeline") >= 0.5 and v >= 4.0:
        v, v_reason = 5.0, v_reason + "; timeline given"

    if d >= 3.5 and f >= 3.5 and v >= 4.0:
        label = "build"
    elif d >= 3.0 and f >= 3.0:
        label = "test"
    elif d >= 3.0:
        label = "defer"
    else:
        label = "stop"
    return Score("DFV", {"desirability": d, "feasibility": f, "viability": v}, round((d + f + v) / 3, 2),
                 {"desirability": d_reason, "feasibility": f_reason, "viability": v_reason}, label)


def score_rice(rec: IntakeRecord, effort_person_months: float | None = None) -> Score:
    users = _num_in(rec, "user_count") or 5
    freq_text = str(rec.get("volume_or_frequency") or "").lower()
    freq = 20 if "day" in freq_text else 4 if "week" in freq_text else 1
    reach = users * freq  # user-events per month
    cycle = _num_in(rec, "cycle_time_today")
    impact = 0.5
    if cycle:
        impact = 3.0 if cycle >= 8 else 2.0 if cycle >= 2 else 1.0
    confidence = round(mean([f.confidence for f in rec.fields.values()]) if rec.fields else 0.3, 2)
    effort = effort_person_months or (2.0 if _conf(rec, "data_shape") >= 0.5 else 3.0)
    if _conf(rec, "constraints") >= 0.6:
        effort += 1.0
    total = round(reach * impact * confidence / effort, 1)
    return Score("RICE", {"reach": reach, "impact": impact, "confidence": confidence, "effort": effort}, total,
                 {"reach": f"{int(users)} users x {freq} events/month", "impact": f"cycle time today ~{cycle or 'unknown'} units",
                  "confidence": "mean field confidence", "effort": "person-months, +1 if constraints"},
                 "high" if total >= 100 else "medium" if total >= 30 else "low")

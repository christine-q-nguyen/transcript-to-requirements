"""Draft Jira-ready stories from an intake record.

One epic per intake; one story per engineering track that the evidence supports:
discovery, data, model, integration, governance, enablement. Every story carries the evidence
quotes that justify it, so a reviewer at Gate 3 can trace each line back to the transcript.
"""
from __future__ import annotations

from .schema import IntakeRecord, Score, Story, Field


def _ev(rec: IntakeRecord, *names: str):
    out = []
    for n in names:
        f = rec.fields.get(n)
        if f:
            out.extend(f.evidence[:2])
    return out


def _txt(rec: IntakeRecord, name: str, default: str = "not stated") -> str:
    v = rec.get(name)
    if v is None or v == "" or v == []:
        return default
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if isinstance(v, dict):
        return "; ".join(f"{k}: {val}" for k, val in v.items() if val) or ", ".join(v.keys())
    return str(v)


def draft_stories(rec: IntakeRecord, dfv: Score, rice: Score, project_key: str = "INTAKE") -> list[Story]:
    title = _txt(rec, "title", "Untitled intake")
    labels = [f"dfv-{dfv.label}", f"rice-{rice.label}", "t2r"]
    epic = Story(
        key=None, issue_type="Epic", summary=title[:120],
        description=(
            f"*Problem.* {_txt(rec, 'problem_statement')}\n\n"
            f"*Users.* {_txt(rec, 'users')} ({_txt(rec, 'user_count', '?')} people); {_txt(rec, 'volume_or_frequency')}.\n\n"
            f"*Today.* {_txt(rec, 'current_workflow')} Cycle time: {_txt(rec, 'cycle_time_today')}.\n\n"
            f"*Success.* {_txt(rec, 'success_criteria')}\n\n"
            f"*DFV* D{dfv.components['desirability']:.0f} F{dfv.components['feasibility']:.0f} V{dfv.components['viability']:.0f} -> {dfv.label}. "
            f"*RICE* {rice.total} ({rice.label}).\n\n"
            f"*Latent needs.* " + (" ".join(f"- {n}" for n in rec.latent_needs) or "none inferred") + "\n\n"
            f"*Open questions / gaps.* {', '.join(rec.gaps) or 'none'}"
        ),
        labels=labels, track="discovery", acceptance_criteria=["Intake approved at Gate 2", "Stories approved at Gate 3"],
        evidence=_ev(rec, "problem_statement", "success_criteria"),
    )
    stories: list[Story] = [epic]

    def add(track: str, summary: str, desc: str, ac: list[str], *ev_fields: str):
        stories.append(Story(None, "Story", summary[:120], desc, labels + [f"track-{track}"], track, ac, _ev(rec, *ev_fields), parent="EPIC"))

    if rec.gaps:
        add("discovery", f"Close intake gaps: {', '.join(rec.gaps[:4])}",
            "Second discovery call or async follow-up to fill the fields below the confidence threshold.\n\nGaps: " + ", ".join(rec.gaps),
            ["Each gap has a value with evidence or is explicitly marked unknown", "Confidence >= 0.6 on all decision-relevant fields"],
            "open_questions")
    if rec.fields.get("data_sources") or rec.fields.get("data_shape"):
        add("data", f"Define canonical input schema for {title[:60]}",
            f"Sources: {_txt(rec, 'data_sources')}. Shape: {_txt(rec, 'data_shape')}. Systems: {_txt(rec, 'systems_in_use')}.\n\n"
            "Publish the schema as JSON Schema with fixtures covering the variance observed in the transcript.",
            ["Schema handles the column/header variance described", "Fixtures for at least two real file shapes (anonymized)", "Validation errors are actionable"],
            "data_sources", "data_shape")
    if rec.fields.get("pain_points") or rec.fields.get("cycle_time_today"):
        add("model", f"Prototype the core automation for {title[:60]}",
            f"Automate the step described as: {_txt(rec, 'pain_points')}\n\nBaseline cycle time: {_txt(rec, 'cycle_time_today')}. "
            "Start with the cheapest approach that could work (rules or a small model); escalate to an LLM only on low confidence.",
            ["Per-item confidence score exposed", "Low-confidence items route to a human queue", "Measured against the baseline cycle time on a held-out sample"],
            "pain_points", "cycle_time_today")
    if rec.fields.get("systems_in_use"):
        add("integration", f"Integrate with {_txt(rec, 'systems_in_use')[:60]}",
            "Read/write to the systems named in the transcript through the firm's standard gateway; no direct credentials in the prototype.",
            ["Least-privilege service account", "Audit log of writes", "Works inside the users' current tool"],
            "systems_in_use")
    if rec.fields.get("constraints") or rec.fields.get("security_or_data_use"):
        add("governance", "Data-use and security review before build",
            f"Constraints: {_txt(rec, 'constraints')}\n\nData use: {_txt(rec, 'security_or_data_use')}\n\nConfirm permissions, retention, and who can see outputs before any production data is used.",
            ["Written data-use decision recorded", "Risk owner named", "Human review gate defined for external-facing outputs"],
            "constraints", "security_or_data_use")
    if rec.fields.get("adoption_risk") or rec.fields.get("why_it_failed"):
        add("enablement", "Adoption plan: co-build with the pilot team",
            f"Why the last attempt failed: {_txt(rec, 'why_it_failed')}\n\nAdoption risk: {_txt(rec, 'adoption_risk')}\n\n"
            "Pick the team that is pulling, co-build the first version with them, capture before/after, let them be the reference.",
            ["Pilot cohort named", "Before/after metric agreed", "Office hours scheduled for the first 4 weeks"],
            "adoption_risk", "why_it_failed")
    return stories

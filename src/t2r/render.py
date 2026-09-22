"""Markdown rendering for the intake summary and the story set."""
from __future__ import annotations

from .schema import IntakeRecord, Score, Story, Transcript, INTAKE_FIELDS


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if isinstance(v, dict):
        return "; ".join(f"{k}: {val}" for k, val in v.items() if val) or ", ".join(v.keys())
    return str(v)


def render_intake(tr: Transcript, rec: IntakeRecord, scores: list[Score]) -> str:
    out = [f"# Intake summary — {_fmt(rec.get('title'))}", "", f"Source: `{tr.source}` ({tr.fmt}, {len(tr.turns)} turns)", ""]
    out.append("## Who was in the room")
    for s, r in rec.speaker_roles.items():
        out.append(f"- {s} — {r}")
    out += ["", "## Fields", "", "| Field | Value | Confidence | Basis | Evidence |", "|---|---|---|---|---|"]
    for name in INTAKE_FIELDS:
        f = rec.fields.get(name)
        if not f:
            out.append(f"| {name} | — | 0.00 | missing | |")
            continue
        ev = "; ".join(f"[{e.timestamp}] “{e.quote[:80]}…”" if len(e.quote) > 80 else f"[{e.timestamp}] “{e.quote}”" for e in f.evidence[:2])
        out.append(f"| {name} | {_fmt(f.value)[:160]} | {f.confidence:.2f} | {f.basis} | {ev} |")
    out += ["", "## Latent needs (implied, not stated)"]
    out += [f"- {n}" for n in rec.latent_needs] or ["- none inferred"]
    out += ["", "## Gaps to close on the next call"]
    out += [f"- {g}" for g in rec.gaps] or ["- none"]
    out += ["", "## Scores"]
    for s in scores:
        comps = ", ".join(f"{k} {v:g}" for k, v in s.components.items())
        out.append(f"- **{s.name}** {s.total} → **{s.label}** ({comps})")
        for k, r in s.rationale.items():
            out.append(f"  - {k}: {r}")
    return "\n".join(out)


def render_stories(stories: list[Story]) -> str:
    out = ["# Jira-ready stories", ""]
    for s in stories:
        out.append(f"## [{s.issue_type}] {s.summary}")
        out.append(f"track: `{s.track}` · labels: {', '.join(s.labels)}" + (f" · parent: {s.parent}" if s.parent else ""))
        out.append("")
        out.append(s.description)
        out.append("")
        out.append("Acceptance criteria:")
        out += [f"- {a}" for a in s.acceptance_criteria]
        if s.evidence:
            out.append("")
            out.append("Evidence:")
            out += [f"- [{e.timestamp}] “{e.quote}”" for e in s.evidence[:3]]
        out.append("")
    return "\n".join(out)

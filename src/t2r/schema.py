"""Data model. Everything the pipeline produces is a plain dataclass that serializes to JSON."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


ROLES = ("requester", "sponsor", "user", "engineer", "facilitator", "other")


@dataclass
class Turn:
    index: int
    start: str          # "HH:MM:SS.mmm"
    end: str
    speaker: str
    text: str
    role: str = "other"  # one of ROLES, filled by classify.py

    @property
    def start_seconds(self) -> float:
        h, m, s = self.start.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)


@dataclass
class Transcript:
    source: str
    fmt: str            # vtt | zoom | teams | txt
    turns: list[Turn]

    def speakers(self) -> list[str]:
        seen: list[str] = []
        for t in self.turns:
            if t.speaker not in seen:
                seen.append(t.speaker)
        return seen


@dataclass
class Evidence:
    turn_index: int
    timestamp: str
    quote: str


@dataclass
class Field:
    """A single extracted field with its evidence and confidence.

    confidence in [0, 1]; basis is 'data-backed' (a number/artifact was cited),
    'anecdotal' (asserted in conversation), or 'inferred' (not stated; derived from context).
    """
    name: str
    value: object
    confidence: float
    basis: str = "anecdotal"
    evidence: list[Evidence] = field(default_factory=list)


# The 22 intake fields. Order matters for the summary layout.
INTAKE_FIELDS = [
    "title", "requesting_team", "problem_statement", "current_workflow", "pain_points",
    "users", "user_count", "volume_or_frequency", "cycle_time_today", "data_sources",
    "data_shape", "systems_in_use", "what_was_tried", "why_it_failed", "constraints",
    "success_criteria", "adoption_risk", "security_or_data_use", "sponsor", "timeline",
    "open_questions", "glossary",
]


@dataclass
class IntakeRecord:
    fields: dict[str, Field]
    speaker_roles: dict[str, str]
    latent_needs: list[str] = field(default_factory=list)   # LENS-style: needs not stated but implied
    gaps: list[str] = field(default_factory=list)            # fields with low confidence -> follow-up checklist

    def get(self, name: str):
        f = self.fields.get(name)
        return f.value if f else None


@dataclass
class Score:
    name: str            # DFV | RICE
    components: dict[str, float]
    total: float
    rationale: dict[str, str]
    label: str           # e.g. "test" | "build" | "defer" | "stop"


@dataclass
class Story:
    key: Optional[str]
    issue_type: str      # Epic | Story | Task
    summary: str
    description: str
    labels: list[str]
    track: str           # discovery | data | model | integration | governance | enablement
    acceptance_criteria: list[str]
    evidence: list[Evidence] = field(default_factory=list)
    parent: Optional[str] = None


@dataclass
class GateDecision:
    gate: str
    approved: bool
    reviewer: str
    note: str = ""


@dataclass
class RunResult:
    transcript: Transcript
    intake: IntakeRecord
    scores: list[Score]
    stories: list[Story]
    gates: list[GateDecision]

    def to_dict(self) -> dict:
        return asdict(self)

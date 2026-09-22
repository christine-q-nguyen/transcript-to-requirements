"""Three human approval gates, and a reviewer budget.

Gate 1  Attendee roles      — a person confirms who was in the room and what role each played.
Gate 2  Intake review       — a person reviews the summary; only fields below the confidence threshold are
                              surfaced for attention (the escalation rate is a design parameter, not "everything").
Gate 3  Story approval      — a person approves the Jira-ready stories; nothing is written before this.

`approve_all=True` runs non-interactively (CI, evals, demos) and records that the gates were auto-approved.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from .schema import GateDecision, IntakeRecord, Story, Transcript


@dataclass
class ReviewerBudget:
    """How much human attention a run may spend. Fields below `threshold` are escalated, up to `max_items`."""
    threshold: float = 0.6
    max_items: int = 8

    def escalate(self, rec: IntakeRecord) -> list[str]:
        low = sorted(((f.confidence, name) for name, f in rec.fields.items() if f.confidence < self.threshold))
        return [name for _, name in low[: self.max_items]]


def _ask(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower()


def gate_roles(tr: Transcript, roles: dict[str, str], conf: dict[str, float], reviewer: str, approve_all: bool) -> GateDecision:
    print("\n== Gate 1 · Attendee roles ==")
    for s in tr.speakers():
        print(f"  {s:<24} {roles[s]:<12} confidence {conf[s]:.2f}")
    if approve_all:
        return GateDecision("roles", True, reviewer, "auto-approved (--approve-all)")
    ans = _ask("Approve roles? [y]es / [e]dit / [n]o: ")
    if ans.startswith("e"):
        for s in tr.speakers():
            new = _ask(f"  role for {s} [{roles[s]}]: ")
            if new:
                roles[s] = new
        for t in tr.turns:
            t.role = roles.get(t.speaker, "other")
        return GateDecision("roles", True, reviewer, "edited by reviewer")
    return GateDecision("roles", ans.startswith("y"), reviewer, "")


def gate_intake(rec: IntakeRecord, summary_md: str, budget: ReviewerBudget, reviewer: str, approve_all: bool) -> GateDecision:
    print("\n== Gate 2 · Intake review ==")
    print(summary_md)
    esc = budget.escalate(rec)
    print(f"\nEscalated for your attention ({len(esc)} of {len(rec.fields)} fields below {budget.threshold:.2f}): {', '.join(esc) or 'none'}")
    if rec.gaps:
        print(f"Follow-up checklist (missing or weak): {', '.join(rec.gaps)}")
    if approve_all:
        return GateDecision("intake", True, reviewer, f"auto-approved; escalated={esc}")
    ans = _ask("Approve intake summary and proceed to stories? [y/n]: ")
    return GateDecision("intake", ans.startswith("y"), reviewer, f"escalated={esc}")


def gate_stories(stories: list[Story], stories_md: str, reviewer: str, approve_all: bool) -> GateDecision:
    print("\n== Gate 3 · Story approval ==")
    print(stories_md)
    if approve_all:
        return GateDecision("stories", True, reviewer, f"auto-approved {len(stories)} stories")
    ans = _ask(f"Approve {len(stories)} stories for export? Nothing is written until you say yes. [y/n]: ")
    return GateDecision("stories", ans.startswith("y"), reviewer, "")

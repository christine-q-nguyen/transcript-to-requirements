"""End-to-end pipeline: ingest -> classify -> [Gate 1] -> extract -> score -> [Gate 2] -> draft -> [Gate 3] -> export."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .classify import classify_speakers, role_confidence
from .export import get_adapter
from .extract import get_extractor
from .gates import ReviewerBudget, gate_intake, gate_roles, gate_stories
from .ingest import load_transcript
from .render import render_intake, render_stories
from .schema import RunResult
from .score import score_dfv, score_rice
from .stories import draft_stories


def run(path: str, out_dir: str = "out", provider: str | None = None, approve_all: bool = False,
        reviewer: str = "reviewer", project_key: str = "INTAKE", threshold: float = 0.6, export: bool = True) -> RunResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    tr = load_transcript(path)
    roles = classify_speakers(tr)
    conf = role_confidence(tr, roles)
    g1 = gate_roles(tr, roles, conf, reviewer, approve_all)
    if not g1.approved:
        raise SystemExit("Stopped at Gate 1.")

    rec = get_extractor(provider).extract(tr, roles)
    dfv, rice = score_dfv(rec), score_rice(rec)
    summary_md = render_intake(tr, rec, [dfv, rice])
    (out / "intake-summary.md").write_text(summary_md, encoding="utf-8")
    g2 = gate_intake(rec, summary_md, ReviewerBudget(threshold=threshold), reviewer, approve_all)
    if not g2.approved:
        raise SystemExit("Stopped at Gate 2.")

    stories = draft_stories(rec, dfv, rice, project_key)
    stories_md = render_stories(stories)
    (out / "jira-draft.md").write_text(stories_md, encoding="utf-8")
    g3 = gate_stories(stories, stories_md, reviewer, approve_all)
    result = RunResult(tr, rec, [dfv, rice], stories, [g1, g2, g3])
    if g3.approved and export:
        keys = get_adapter(out / "jira", project_key).create(stories)
        print(f"\nExported {len(keys)} issues -> {keys[0]} … {keys[-1]}")
    (out / "run.json").write_text(json.dumps(asdict(result), indent=2, default=str), encoding="utf-8")
    print(f"\nArtifacts written to {out.resolve()}")
    return result

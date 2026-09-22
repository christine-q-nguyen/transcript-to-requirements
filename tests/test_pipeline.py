"""Smoke and behaviour tests. Run: pytest -q (standard library + pytest only)."""
from pathlib import Path

import pytest

from t2r.classify import classify_speakers
from t2r.eval.harness import faithfulness_coverage, field_correct, kappa, risk_coverage
from t2r.extract import HeuristicExtractor
from t2r.gates import ReviewerBudget
from t2r.ingest import load_transcript, detect_format
from t2r.score import score_dfv, score_rice
from t2r.stories import draft_stories
from t2r.export import JiraMockAdapter, to_jira_payload

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
FILES = sorted(DATA.glob("*.*"))


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_ingest_all_formats(path):
    tr = load_transcript(path)
    assert tr.fmt in {"vtt", "zoom", "teams", "txt"}
    assert len(tr.turns) >= 10
    assert all(t.speaker and t.text for t in tr.turns)
    assert tr.turns[0].start_seconds <= tr.turns[-1].start_seconds


def test_format_detection():
    assert detect_format("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi", ".vtt") == "vtt"
    assert detect_format("00:00:04 Dana: hi\n00:00:09 Sam: there\n00:00:12 Dana: ok", ".txt") == "zoom"
    assert detect_format("[0:05] Dana: hi\n[0:09] Sam: there\n[0:12] Dana: ok", ".txt") == "teams"
    assert detect_format("Dana: hi\nSam: there", ".txt") == "txt"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_roles_have_one_facilitator_and_a_sponsor(path):
    tr = load_transcript(path)
    roles = classify_speakers(tr)
    assert list(roles.values()).count("facilitator") == 1
    assert "sponsor" in roles.values()


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_extraction_is_traceable(path):
    tr = load_transcript(path)
    rec = HeuristicExtractor().extract(tr, classify_speakers(tr))
    assert rec.get("problem_statement")
    assert rec.get("user_count") is not None
    # every evidence quote must be a substring of the transcript turn it points to (faithfulness by construction)
    for f in rec.fields.values():
        for e in f.evidence:
            turn = tr.turns[e.turn_index]
            assert e.quote[:40].lower() in turn.text.lower()
        assert 0.0 <= f.confidence <= 1.0


def test_scores_and_stories_and_export(tmp_path):
    tr = load_transcript(FILES[0])
    rec = HeuristicExtractor().extract(tr, classify_speakers(tr))
    dfv, rice = score_dfv(rec), score_rice(rec)
    assert dfv.label in {"build", "test", "defer", "stop"}
    assert rice.total > 0
    stories = draft_stories(rec, dfv, rice)
    assert stories[0].issue_type == "Epic"
    assert any(s.track == "governance" for s in stories)  # constraints were stated in every synthetic call
    payload = to_jira_payload(stories[1], "INTAKE", "INTAKE-1")
    assert payload["fields"]["parent"] == {"key": "INTAKE-1"}
    keys = JiraMockAdapter(tmp_path, "INTAKE").create(stories)
    assert keys[0] == "INTAKE-1" and (tmp_path / "INTAKE-1.json").exists()


def test_reviewer_budget_escalates_low_confidence_only():
    tr = load_transcript(FILES[0])
    rec = HeuristicExtractor().extract(tr, classify_speakers(tr))
    esc = ReviewerBudget(threshold=0.6, max_items=3).escalate(rec)
    assert len(esc) <= 3
    assert all(rec.fields[n].confidence < 0.6 for n in esc)


def test_eval_metrics_behave():
    assert field_correct(40, 40) and field_correct("about 40 people", 40) and not field_correct("12", 40)
    assert field_correct(["SharePoint", "PDF"], ["sharepoint", "pdf", "snowflake"])
    assert kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert kappa([True, True, True, True], [True, True, True, False]) == 0.0  # no discrimination
    rc = risk_coverage([(0.9, True), (0.5, False), (0.7, True)])
    assert rc[0]["coverage"] == 1.0 and rc[-1]["n_auto"] == 1
    tr = load_transcript(FILES[0])
    faith, cov = faithfulness_coverage(tr, [tr.turns[1].text[:60], "completely unrelated statement about penguins"], [1])
    assert faith == 0.5 and cov == 1.0

# transcript-to-requirements (t2r)

[![tests](https://github.com/christine-q-nguyen/transcript-to-requirements/actions/workflows/tests.yml/badge.svg)](https://github.com/christine-q-nguyen/transcript-to-requirements/actions/workflows/tests.yml) ![license: MIT](https://img.shields.io/badge/license-MIT-blue) ![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

Turn a discovery-call transcript into a structured intake record, DFV/RICE scores, and Jira-ready stories — with **evidence on every field**, **per-field confidence**, **three human approval gates**, and an **evaluation harness** that publishes the risk–coverage curve instead of an accuracy headline.

Standard-library Python at the core (runs offline). LLM providers and an MCP server are optional extras. Synthetic data only; MIT licensed.

```
transcript ──► ingest ──► classify ──► [Gate 1] ──► extract ──► score ──► [Gate 2] ──► stories ──► [Gate 3] ──► export
   VTT/Zoom/Teams   turns      roles      roles ok?    22 fields   DFV/RICE   summary ok?   epic+tracks  approve?    Jira
```

## Why this exists
Requirements from discovery calls take weeks because someone has to re-listen, re-type, and re-argue. The pattern here is the one I ran inside a large firm's AI enablement team: encode the discovery method itself, keep the human decision inside the workflow (at the kickoff and every handoff), and write the definition of "good" down before anyone argues about a demo. This is a from-scratch public version; it contains no proprietary code, prompts, data, or system names.

The story behind it is a [case study on my site](https://christinenguyen.me/work/case-artifact.html). Its sister project, [portfolio-from-evidence](https://github.com/christine-q-nguyen/portfolio-from-evidence), applies the same evidence-first idea to a résumé.

## Quick start
```bash
git clone https://github.com/christine-q-nguyen/transcript-to-requirements && cd transcript-to-requirements
pip install -e ".[dev]"                 # stdlib core + pytest

# run the pipeline on a synthetic call, non-interactively (the three gates auto-approve)
t2r run data/synthetic/harborline_claims_triage.vtt --approve-all --out out

# run it interactively and actually sit at the gates
t2r run data/synthetic/meridian_invoice_reconciliation.txt --reviewer "your name"

# evaluate against the labeled set
t2r eval

# start the MCP server (read-only tools for agents)
pip install -e ".[mcp]" && t2r mcp
```
Outputs land in `out/`: `intake-summary.md`, `jira-draft.md`, `run.json`, and one Jira payload per story in `out/jira/`. Set `T2R_JIRA_URL`, `T2R_JIRA_EMAIL`, `T2R_JIRA_TOKEN` to export to a real Jira Cloud project (only after Gate 3).

## What it extracts
22 fields: title, requesting team, problem statement, current workflow, pain points, users, user count, volume/frequency, cycle time today, data sources, data shape, systems in use, what was tried, why it failed, constraints, success criteria, adoption risk, security/data use, sponsor, timeline, open questions, glossary. Each with a value, a **confidence** (0–1), a **basis** (data-backed · anecdotal · inferred), and **timestamped evidence quotes**. Plus **latent needs** — the requirement nobody said out loud (a canonical schema, an explainability view, a permissions check, an adoption plan) — and a **gap checklist** for the next call.

## The three gates
| Gate | Question a person answers | What is escalated |
|---|---|---|
| 1 · Roles | Who was in the room and what role did each play? | Every speaker, with heuristic confidence. Edit inline. |
| 2 · Intake | Is the summary right enough to draft against? | Only fields below the confidence threshold (`--threshold`, default 0.6), up to a reviewer budget. |
| 3 · Stories | May the system write these stories? | The full story set with evidence. Nothing is exported before yes. |

The escalation rate is a design parameter. Human attention is the scarce resource; the eval tells you where to set the threshold.

## Eval results (heuristic baseline, 3 synthetic transcripts)
| Metric | Value |
|---|---|
| Field accuracy | 79% |
| Speaker-role accuracy | 100% |
| Faithfulness (statements supported by the transcript) | 86% |
| Coverage (requirement-bearing turns reflected) | 96% |
| DFV label match (build / test / defer / stop) | 100% |
| Judge agreement / κ vs human rulings | 0.96 / **0.0** |

| Auto-accept threshold | Coverage | Risk |
|---|---|---|
| 0.5 | 100% | 21% |
| 0.6 | 71% | 19% |
| **0.7** | **41%** | **15%** |
| 0.8 | 30% | 20% |
| 0.9 | 15% | 30% |

CI re-runs the eval on every push and fails if these numbers drift from [`eval_results/results.json`](eval_results/results.json). Three honest readings. The curve is **not monotone** — the heuristic over-trusts sentences that contain a number, so risk rises again at 0.9; publish the curve and pick 0.7 for this baseline. **κ = 0 at 96% agreement** means the offline rubric judge never says no; validate the judge before trusting the rubric. Most field misses are **paraphrase misses** (the extractor quotes, the gold label summarizes) — faithfulness stays high because it never invents. Full table and per-transcript breakdown: [`eval_results/RESULTS.md`](eval_results/RESULTS.md). Method: [`docs/EVALS.md`](docs/EVALS.md).

## Providers
| Provider | Set | Notes |
|---|---|---|
| `heuristic` (default) | nothing | Deterministic, offline, the floor. |
| `anthropic` | `ANTHROPIC_API_KEY`, optional `T2R_MODEL` | `pip install -e ".[anthropic]"` |
| `openai` | `OPENAI_API_KEY`, optional `T2R_MODEL` | `pip install -e ".[openai]"` |

The LLM provider asks for the same JSON schema and then re-attaches every quote to a transcript turn; quotes that do not trace back cap that field's confidence at 0.4 so it is escalated at Gate 2.

## MCP server
`t2r mcp` exposes `ingest_transcript`, `extract_intake`, and `draft_jira_stories` to an MCP client (Claude Desktop, Cursor, etc.). Tools are read-only, file paths are allow-listed under `T2R_ROOT`, and no Jira credentials are reachable from the server. See [`docs/SECURITY.md`](docs/SECURITY.md).

## Patterns this borrows, with citations
Requirements from conversations — RECOVER (arXiv:2411.19552), LENS (arXiv:2606.25867), Inter2US faithfulness/coverage (arXiv:2510.08622). Oversight as a resource-allocation problem — *Oversight Has a Capacity* (arXiv:2606.08919), decoupled HITL (arXiv:2604.23049). Confidence thresholds — selective classification (arXiv:1705.08500), cascade routing (arXiv:2410.10347). Judge validation — *Judging LLM-as-a-Judge* (arXiv:2306.05685). Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Layout
```
src/t2r/            ingest · classify · extract · score · gates · stories · render · export · pipeline · cli · mcp_server
src/t2r/eval/       harness (metrics, risk–coverage, rubric judge, κ)
data/synthetic/     three fictional discovery calls: WebVTT, Zoom text, Teams text
data/labels/        gold fields, speaker roles, requirement-bearing turns, DFV label, human rubric rulings
eval_results/       RESULTS.md, results.json
docs/               ARCHITECTURE.md · EVALS.md · SECURITY.md
tests/              pytest
```

## Roadmap
- LLM judge for R6/R7 with a validation table against human rulings
- Per-field calibration (isotonic) so the confidence curve is monotone
- Second-call diffing: what changed between intake v1 and v2
- Confluence/Notion export adapters

MIT © 2026 Christine Nguyen

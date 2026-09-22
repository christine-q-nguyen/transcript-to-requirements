# Evaluation

`t2r eval` runs the pipeline over the labeled synthetic set and writes `eval_results/RESULTS.md` and `results.json`.

## Metrics
| Metric | Definition | Why it is here |
|---|---|---|
| Field accuracy | Per field: numbers must match exactly; lists match at set-F1 ≥ 0.5; text matches at token-F1 ≥ 0.5 against the gold label. Averaged over 22 fields × transcripts. | The obvious one. Paraphrase misses count as wrong on purpose. |
| Speaker-role accuracy | Heuristic role per speaker vs gold. | Gate 1 exists because this is fallible. |
| Faithfulness | Share of generated statements (field values + story summaries) supported by some transcript turn at ≥ 35% token overlap. | Inter2US (arXiv:2510.08622) "requirements faithfulness". The extractor should never invent. |
| Coverage | Share of gold requirement-bearing turns matched by at least one generated statement. | Inter2US "interview coverage". Did we miss what people said? |
| DFV label match | Predicted build/test/defer/stop vs the human label. | The decision, not the fields, is what leaders consume. |
| Judge agreement / κ | Rubric judge (8 binary criteria on the rendered summary) vs human rulings in the label files; Cohen's κ. | LLM-as-judge literature (arXiv:2306.05685): agreement alone hides a judge that always says yes. |
| Risk–coverage | Sweep confidence thresholds; coverage = share of fields auto-accepted, risk = error rate among them. | Selective classification (arXiv:1705.08500); the threshold is a workflow decision, so publish the curve. |

## Labeling
Each `data/labels/<name>.json` holds: `fields` (gold values), `speaker_roles`, `requirement_turns` (turn indices that carry requirements), `dfv_label`, and `human_rulings` (the eight rubric criteria as a person judged them). Add a transcript by dropping a file in `data/synthetic/` and a label with the same stem in `data/labels/`.

## Rubric (judge)
R1 problem present · R2 users quantified · R3 cycle time present · R4 evidence attached to the problem · R5 gaps listed · R6 no invented numbers · R7 a latent need is present · R8 a DFV label is present. Binary pass/fail, checked by code. With an LLM provider configured, R6 and R7 should be judged by a model against the transcript; the offline judge is deliberately conservative and, as the current results show, undiscriminating (κ = 0) — which is the lesson.

## Adding an LLM row
```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY
pip install 'transcript-to-requirements[anthropic]'
t2r eval --provider anthropic --out eval_results/anthropic
```
Report both rows side by side; the delta between heuristic and LLM is the value of the model, and the heuristic row is your floor when the API is unavailable.

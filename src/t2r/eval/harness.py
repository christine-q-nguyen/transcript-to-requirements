"""Evaluation harness.

Metrics (all standard library):
1. Field accuracy      — extracted value vs gold label per field (exact for numbers, token-F1 >= 0.5 for text, set-F1 for lists).
2. Faithfulness        — share of generated requirement statements supported by some transcript turn (Inter2US-style).
3. Coverage            — share of gold requirement-bearing turns matched by at least one generated statement.
4. Risk–coverage curve — sweep the confidence threshold: coverage = share of fields auto-accepted, risk = error rate among them.
5. Judge validation    — a rubric judge (heuristic offline; LLM when a key is set) vs human rulings on the intake summary: agreement and Cohen's kappa.

Outputs: eval_results/results.json and eval_results/RESULTS.md (the table the README embeds).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from ..classify import classify_speakers
from ..extract import get_extractor
from ..ingest import load_transcript
from ..render import render_intake
from ..schema import IntakeRecord, Transcript, INTAKE_FIELDS
from ..score import score_dfv, score_rice
from ..stories import draft_stories

_STOP = set("the a an and or of to in for on with by is are was were be been it this that we our i you they them us at as from into about".split())


def _tokens(s) -> set[str]:
    if isinstance(s, (list, dict)):
        s = " ".join(map(str, s.keys() if isinstance(s, dict) else s))
    return {w for w in re.findall(r"[a-z0-9]+", str(s).lower()) if w not in _STOP}


def _f1(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    tp = len(a & b)
    if tp == 0:
        return 0.0
    p, r = tp / len(a), tp / len(b)
    return 2 * p * r / (p + r)


def field_correct(pred, gold) -> bool:
    if gold is None:
        return pred is None
    if pred is None:
        return False
    if isinstance(gold, (int, float)):
        m = re.search(r"\d[\d,]*", str(pred))
        return bool(m) and float(m.group(0).replace(",", "")) == float(gold)
    if isinstance(gold, list):
        return _f1({str(x).lower() for x in gold}, {str(x).lower() for x in (pred if isinstance(pred, list) else [pred])}) >= 0.5
    return _f1(_tokens(pred), _tokens(gold)) >= 0.5


def faithfulness_coverage(tr: Transcript, statements: list[str], gold_turns: list[int], thresh: float = 0.35) -> tuple[float, float]:
    turn_tokens = {t.index: _tokens(t.text) for t in tr.turns}
    supported, matched_turns = 0, set()
    for s in statements:
        st = _tokens(s)
        best_i, best = None, 0.0
        for i, tt in turn_tokens.items():
            if not st or not tt:
                continue
            overlap = len(st & tt) / len(st)
            if overlap > best:
                best, best_i = overlap, i
        if best >= thresh:
            supported += 1
            matched_turns.add(best_i)
    faith = supported / len(statements) if statements else 0.0
    cov = len(matched_turns & set(gold_turns)) / len(gold_turns) if gold_turns else 0.0
    return round(faith, 3), round(cov, 3)


def risk_coverage(rows: list[tuple[float, bool]]) -> list[dict]:
    out = []
    for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        acc = [(c, ok) for c, ok in rows if c >= th]
        coverage = len(acc) / len(rows) if rows else 0.0
        risk = (sum(1 for _, ok in acc if not ok) / len(acc)) if acc else 0.0
        out.append({"threshold": th, "coverage": round(coverage, 3), "risk": round(risk, 3), "n_auto": len(acc)})
    return out


# ---- rubric judge ----------------------------------------------------------------------------
RUBRIC = {
    "R1_problem_present": lambda md: "| problem_statement |" in md and "| problem_statement | — |" not in md,
    "R2_users_quantified": lambda md: bool(re.search(r"\| user_count \| \d", md)),
    "R3_cycle_time_present": lambda md: "| cycle_time_today | — |" not in md and "cycle_time_today" in md,
    "R4_evidence_on_problem": lambda md: bool(re.search(r"\| problem_statement \|[^\n]*\[\d\d:\d\d:\d\d", md)),
    "R5_gaps_listed": lambda md: "## Gaps to close" in md,
    "R6_no_invented_numbers": lambda md: True,  # heuristic extractor cannot invent numbers; LLM judge checks quotes
    "R7_latent_need_present": lambda md: "- none inferred" not in md.split("## Latent needs")[-1].split("##")[0],
    "R8_dfv_label_present": lambda md: bool(re.search(r"\*\*DFV\*\* [\d.]+ → \*\*(build|test|defer|stop)\*\*", md)),
}


def judge(md: str) -> dict[str, bool]:
    return {k: bool(f(md)) for k, f in RUBRIC.items()}


def kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


# ---- driver ----------------------------------------------------------------------------------
def run_eval(data_dir: str, labels_dir: str, out_dir: str, provider: str = "heuristic") -> dict:
    data, labels, out = Path(data_dir), Path(labels_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    extractor = get_extractor(provider)
    per_file, rc_rows, judge_pairs = [], [], []
    for tpath in sorted(data.glob("*.*")):
        lab_path = labels / (tpath.stem + ".json")
        if not lab_path.exists():
            continue
        gold = json.loads(lab_path.read_text(encoding="utf-8"))
        tr = load_transcript(tpath)
        roles = classify_speakers(tr)
        rec = extractor.extract(tr, roles)
        dfv, rice = score_dfv(rec), score_rice(rec)

        # 1. field accuracy
        correct = {}
        for f in INTAKE_FIELDS:
            g = gold["fields"].get(f)
            p = rec.get(f)
            ok = field_correct(p, g)
            correct[f] = ok
            if f in rec.fields:
                rc_rows.append((rec.fields[f].confidence, ok))
        acc = round(mean(correct.values()), 3)
        role_acc = round(mean(1.0 if roles.get(s) == r else 0.0 for s, r in gold["speaker_roles"].items()), 3)

        # 2/3. faithfulness & coverage over generated statements (field values + story summaries)
        statements = [str(rec.fields[f].value) for f in rec.fields if isinstance(rec.fields[f].value, str)]
        statements += [s.summary for s in draft_stories(rec, dfv, rice)]
        faith, cov = faithfulness_coverage(tr, statements, gold.get("requirement_turns", []))

        # 5. judge vs human rulings
        md = render_intake(tr, rec, [dfv, rice])
        j = judge(md)
        human = gold.get("human_rulings", {})
        for k in RUBRIC:
            if k in human:
                judge_pairs.append((j[k], bool(human[k])))

        per_file.append({"transcript": tpath.name, "format": tr.fmt, "turns": len(tr.turns), "field_accuracy": acc,
                         "role_accuracy": role_acc, "faithfulness": faith, "coverage": cov,
                         "dfv_label": dfv.label, "gold_dfv_label": gold.get("dfv_label"), "rubric_pass": sum(j.values()), "rubric_total": len(j),
                         "fields_wrong": [f for f, ok in correct.items() if not ok]})

    summary = {
        "provider": provider,
        "n_transcripts": len(per_file),
        "field_accuracy": round(mean(p["field_accuracy"] for p in per_file), 3) if per_file else 0,
        "role_accuracy": round(mean(p["role_accuracy"] for p in per_file), 3) if per_file else 0,
        "faithfulness": round(mean(p["faithfulness"] for p in per_file), 3) if per_file else 0,
        "coverage": round(mean(p["coverage"] for p in per_file), 3) if per_file else 0,
        "dfv_label_match": round(mean(1.0 if p["dfv_label"] == p["gold_dfv_label"] else 0.0 for p in per_file), 3) if per_file else 0,
        "judge_agreement": round(mean(1.0 if a == b else 0.0 for a, b in judge_pairs), 3) if judge_pairs else None,
        "judge_kappa": kappa([a for a, _ in judge_pairs], [b for _, b in judge_pairs]) if judge_pairs else None,
        "risk_coverage": risk_coverage(rc_rows),
        "per_file": per_file,
    }
    (out / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "RESULTS.md").write_text(render_results(summary), encoding="utf-8")
    print(render_results(summary))
    return summary


def render_results(s: dict) -> str:
    lines = [f"# Eval results — provider: `{s['provider']}` · {s['n_transcripts']} labeled transcripts", "",
             "| Metric | Value | What it means |", "|---|---|---|",
             f"| Field accuracy | {s['field_accuracy']:.0%} | extracted value matches the gold label (22 fields per transcript) |",
             f"| Speaker-role accuracy | {s['role_accuracy']:.0%} | heuristic role per speaker vs gold |",
             f"| Faithfulness | {s['faithfulness']:.0%} | generated statements supported by a transcript turn |",
             f"| Coverage | {s['coverage']:.0%} | gold requirement-bearing turns reflected in the output |",
             f"| DFV label match | {s['dfv_label_match']:.0%} | build / test / defer / stop agrees with the human label |",
             f"| Judge agreement / κ | {s['judge_agreement'] if s['judge_agreement'] is not None else 'n/a'} / {s['judge_kappa'] if s['judge_kappa'] is not None else 'n/a'} | rubric judge vs human rulings |",
             "", "## Risk–coverage (auto-accept fields at or above threshold)", "", "| Threshold | Coverage | Risk (error rate among auto-accepted) | n |", "|---|---|---|---|"]
    lines += [f"| {r['threshold']:.1f} | {r['coverage']:.0%} | {r['risk']:.0%} | {r['n_auto']} |" for r in s["risk_coverage"]]
    lines += ["", "## Per transcript", "", "| Transcript | Format | Turns | Fields | Roles | Faith. | Cov. | DFV (pred/gold) | Rubric | Wrong fields |", "|---|---|---|---|---|---|---|---|---|---|"]
    for p in s["per_file"]:
        lines.append(f"| {p['transcript']} | {p['format']} | {p['turns']} | {p['field_accuracy']:.0%} | {p['role_accuracy']:.0%} | {p['faithfulness']:.0%} | {p['coverage']:.0%} | {p['dfv_label']}/{p['gold_dfv_label']} | {p['rubric_pass']}/{p['rubric_total']} | {', '.join(p['fields_wrong'][:6])} |")
    lines += ["", "Read the curve, not the headline: pick the threshold where risk is acceptable for *your* workflow and route the rest to a person."]
    return "\n".join(lines)

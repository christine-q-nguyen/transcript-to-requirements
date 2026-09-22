"""Field extraction.

Two providers share one contract (`Extractor.extract(transcript, roles) -> IntakeRecord`):

* HeuristicExtractor — standard-library, deterministic, runs offline. It is the baseline the eval
  harness always reports, and the fallback when no API key is configured.
* LLMExtractor — Anthropic or OpenAI via environment variables. Asks for the same JSON schema,
  then re-attaches evidence by matching quoted text back to transcript turns so every field is traceable.

Every field carries a confidence in [0,1] and a basis: data-backed (a number or artifact was cited),
anecdotal (asserted), or inferred (derived, not stated).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from .schema import Evidence, Field, IntakeRecord, Transcript, Turn, INTAKE_FIELDS

_NUM = re.compile(r"\b\d[\d,\.]*\s*(?:%|k|K|hours?|hrs?|days?|weeks?|months?|minutes?|mins?|people|analysts|users|colleagues|editors|rows|files|invoices|claims|surveys|tickets|per\b|a\b)", re.I)

# Sentence-level cues per field. Each hit becomes evidence; the field value is the joined sentences.
_CUES: dict[str, list[str]] = {
    "requesting_team": [r"\b(?:i'?m|we'?re|i am|we are) (?:on|from|with|in) the ([\w &/-]+?) (?:team|group|practice|function)\b", r"\bthe ([\w &/-]+?) team (?:is|are) asking\b"],
    "problem_statement": [r"\bthe (?:problem|pain|issue|challenge) (?:is|here is|we have is)\b", r"\bwe struggle\b", r"\bit takes (?:us|the team)\b", r"\bthe bottleneck\b"],
    "current_workflow": [r"\b(?:today|right now|currently|at the moment)[, ]+(?:we|i|the team|analysts)\b", r"\bthe way it works\b", r"\bstep one\b", r"\bfirst (?:we|i)\b", r"\bevery (?:morning|day|week)[, ]+i\b", r"\bi (?:export|download|open each|log in)\b"],
    "pain_points": [r"\b(?:manual(?:ly)?|copy[- ]?past\w+|re-?key\w*|error[- ]prone|frustrat\w+|painful|tedious|by hand)\b"],
    "users": [r"\b(?:our|the) (?:field |research |intake |claims )?(?:analysts|editors|underwriters|adjusters|reviewers|field staff|team members|associates|coordinators)\b", r"\b\d+ (?:analysts|adjusters|coordinators|editors|reviewers|people) on the team\b", r"\bthe (?:people|users) (?:who|doing) \b", r"\busers? (?:are|would be)\b"],
    "user_count": [r"\b(\d{1,4})\s+(?:people|analysts|users|colleagues|editors|adjusters|reviewers|staff)\b"],
    "volume_or_frequency": [r"\b\d[\d,]*\s*(?:rows|files|invoices|claims|surveys|tickets|documents|reports|requests|sites|waves|batches|partners|regions)\b", r"\b(?:every|per|a|each) (?:day|week|month|quarter|year)\b", r"\bannually\b"],
    "cycle_time_today": [r"\btakes? (?:us |me |them )?(?:about |around |roughly )?\d+(?:\.\d+)?\s*(?:hours?|hrs?|days?|weeks?|minutes?)\b", r"\b\d+(?:\.\d+)?\s*(?:hours?|days?|weeks?) (?:per|for each|a)\b"],
    "data_sources": [r"\b(?:spreadsheets?|excel|csv|sharepoint|snowflake|salesforce|pdfs?|emails?|database|data warehouse|api|sql|s3|box|onedrive|jira|servicenow)\b"],
    "data_shape": [r"\b(?:columns?|rows?|fields?|schema|headers?|format(?:s)? (?:vary|varies|change|differ)|unstructured|structured|free text|tables?)\b"],
    "systems_in_use": [r"\b(?:excel|sharepoint|snowflake|salesforce|servicenow|jira|confluence|tableau|power ?bi|outlook|teams|slack|sap|workday|databricks)\b"],
    "what_was_tried": [r"\bwe (?:tried|piloted|bought|built|used|experimented with)\b", r"\b(?:last year|previously|before),? (?:we|they)\b"],
    "why_it_failed": [r"\b(?:didn'?t|did not|doesn'?t|does not) (?:work|scale|stick|help)\b", r"\bfailed because\b", r"\bthe problem (?:with that )?was\b", r"\bpeople stopped using\b"],
    "constraints": [r"\b(?:can'?t|cannot|must not|not allowed|aren'?t allowed|compliance|regulat\w+|legal|pii|hipaa|gdpr|retention|on-?prem|no external)\b"],
    "success_criteria": [r"\bsuccess (?:looks like|would be|means)\b", r"\bif we could\b", r"\bgood (?:would|looks) (?:be|like)\b", r"\bwe'?d be happy if\b", r"\bthe goal is\b"],
    "adoption_risk": [r"\b(?:worried|pushback|push back|won'?t use|trust|skeptical|resist\w*|change management|training)\b"],
    "security_or_data_use": [r"\b(?:client data|customer data|pii|confidential|permission|data rights|access(?: control)?|who can see|encrypt\w*|audit)\b"],
    "timeline": [r"\bby (?:the )?end of (?:q[1-4]|the (?:quarter|year|month))\b", r"\bby (?:next|this) (?:month|quarter|year|week)\b", r"\bby q[1-4]\b", r"\bin (?:the next )?\d+ (?:weeks?|months?)\b", r"\bdeadline\b", r"\bnext quarter\b", r"\bfiscal year[- ]?end\b", r"\bby (?:january|february|march|april|may|june|july|august|september|october|november|december)\b", r"\b(?:spring|summer|fall|winter) wave\b"],
    "open_questions": [r"\bwe don'?t know\b", r"\bnot sure\b", r"\bneed to (?:check|confirm|find out)\b", r"\bopen question\b", r"\bto be confirmed\b"],
}
_ACRONYM = re.compile(r"\b([A-Z]{2,6})\b(?:\s*\(([^)]{3,60})\))?")

_LATENT_RULES = [
    (lambda f: "spreadsheet" in _lower(f, "data_sources") and _has(f, "pain_points"),
     "A canonical input schema and ingestion step — the stated ask is a tool; the latent need is standardized inputs so rules can be reused across files."),
    (lambda f: "trust" in _lower(f, "adoption_risk") or "check" in _lower(f, "current_workflow"),
     "An explainability and review view so users can see why an output was produced and correct it without re-doing the work."),
    (lambda f: _has(f, "security_or_data_use") or _has(f, "constraints"),
     "A data-use and permissions check before build — the conversation implies data that may need legal or client approval."),
    (lambda f: _has(f, "why_it_failed"),
     "An adoption plan that addresses why the last attempt failed; a better tool alone will not change behaviour."),
    (lambda f: "vary" in _lower(f, "data_shape") or "differ" in _lower(f, "data_shape"),
     "Tolerance for varying columns and headers — mapping to canonical fields at ingestion rather than per-file rules."),
]


def _lower(fields: dict[str, Field], name: str) -> str:
    f = fields.get(name)
    return str(f.value).lower() if f and f.value else ""


def _has(fields: dict[str, Field], name: str) -> bool:
    f = fields.get(name)
    return bool(f and f.value and f.confidence >= 0.5)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


class HeuristicExtractor:
    name = "heuristic"

    def extract(self, tr: Transcript, roles: dict[str, str]) -> IntakeRecord:
        fields: dict[str, Field] = {}
        for fname, pats in _CUES.items():
            hits: list[tuple[Turn, str, re.Match]] = []
            for t in tr.turns:
                if t.role == "facilitator" and fname not in ("open_questions",):
                    continue  # facilitator questions are prompts, not evidence
                for s in _sentences(t.text):
                    for p in pats:
                        m = re.search(p, s, re.I)
                        if m:
                            hits.append((t, s, m))
                            break
            if not hits:
                continue
            value, basis, conf = self._value(fname, hits)
            ev = [Evidence(t.index, t.start, s[:220]) for t, s, _ in hits[:4]]
            fields[fname] = Field(fname, value, conf, basis, ev)

        # sponsor: prefer the speaker classified as sponsor
        sponsors = [s for s, r in roles.items() if r == "sponsor"]
        if sponsors:
            fields["sponsor"] = Field("sponsor", sponsors[0], 0.7, "inferred", [])
        # glossary: acronyms with expansions when present
        gloss: dict[str, str] = {}
        for t in tr.turns:
            for m in _ACRONYM.finditer(t.text):
                acr, exp = m.group(1), m.group(2)
                if acr in ("AI", "OK", "US", "UK", "PM", "PDF", "CSV", "API", "SQL") and not exp:
                    continue
                if exp or acr not in gloss:
                    gloss[acr] = exp or gloss.get(acr, "")
        if gloss:
            fields["glossary"] = Field("glossary", gloss, 0.6, "inferred", [])
        # title: first problem sentence, trimmed
        prob = fields.get("problem_statement")
        if prob:
            first = str(prob.value).split(". ")[0]
            title = re.sub(r"^(?:so |well |the (?:problem|pain|issue|challenge) (?:is|here is|we have is)[, ]*)", "", first, flags=re.I)
            title = re.sub(r"^that\s+", "", title, flags=re.I).strip()
            title = (title[:1].upper() + title[1:])[:80].rstrip(" ,.")
            fields["title"] = Field("title", (title or "Untitled intake"), 0.5, "inferred", prob.evidence[:1])
        else:
            fields["title"] = Field("title", "Untitled intake", 0.2, "inferred", [])

        rec = IntakeRecord(fields=fields, speaker_roles=roles)
        rec.latent_needs = [text for rule, text in _LATENT_RULES if rule(fields)]
        rec.gaps = [f for f in INTAKE_FIELDS if f not in fields or fields[f].confidence < 0.5]
        return rec

    @staticmethod
    def _value(fname: str, hits: list[tuple[Turn, str, re.Match]]):
        if fname == "user_count":
            nums = [int(m.group(1)) for _, _, m in hits if m.groups() and m.group(1)]
            return (max(nums) if nums else None), "data-backed", min(0.95, 0.75 + 0.05 * len(nums))
        if fname == "requesting_team":
            teams = [m.group(1).strip() for _, _, m in hits if m.groups() and m.group(1)]
            return (teams[0] if teams else None), "anecdotal", 0.7 if teams else 0.3
        if fname in ("data_sources", "systems_in_use"):
            vals = sorted({m.group(0).title() for _, _, m in hits})
            return vals, "anecdotal", min(0.9, 0.55 + 0.1 * len(vals))
        sents = []
        for _, s, _ in hits:
            if s not in sents:
                sents.append(s)
        text = " ".join(sents[:1] if fname == "users" else sents[:3])
        data_backed = bool(_NUM.search(text))
        conf = 0.8 if data_backed else 0.55
        conf = min(0.95, conf + (0.1 if len(hits) >= 2 else 0.0))
        return text, ("data-backed" if data_backed else "anecdotal"), round(conf, 2)


_PROMPT = """You are extracting a structured intake record from a discovery-call transcript.
Return ONLY a JSON object with these keys: {keys}.
For every key return an object: {{"value": <string|number|list|object|null>, "confidence": <0..1>,
"basis": "data-backed"|"anecdotal"|"inferred", "quotes": [<exact short quotes from the transcript that support the value>]}}.
Also return "latent_needs": [<needs implied but not stated, each one sentence>].
Rules: use only the transcript; never invent numbers; quotes must be verbatim substrings of the transcript.

TRANSCRIPT (index | timestamp | speaker[role]: text)
{transcript}
"""


@dataclass
class LLMExtractor:
    provider: str = "anthropic"
    model: str | None = None
    name: str = "llm"

    def extract(self, tr: Transcript, roles: dict[str, str]) -> IntakeRecord:
        lines = [f"{t.index} | {t.start} | {t.speaker}[{t.role}]: {t.text}" for t in tr.turns]
        prompt = _PROMPT.format(keys=", ".join(INTAKE_FIELDS), transcript="\n".join(lines))
        raw = self._complete(prompt)
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        fields: dict[str, Field] = {}
        for k in INTAKE_FIELDS:
            item = data.get(k)
            if not item or item.get("value") in (None, "", []):
                continue
            ev = []
            for q in item.get("quotes", [])[:4]:
                t = _find_turn(tr, q)
                if t:
                    ev.append(Evidence(t.index, t.start, q[:220]))
            conf = float(item.get("confidence", 0.5))
            if item.get("quotes") and not ev:
                conf = min(conf, 0.4)  # quotes that do not trace back are a red flag
            fields[k] = Field(k, item["value"], round(conf, 2), item.get("basis", "anecdotal"), ev)
        rec = IntakeRecord(fields=fields, speaker_roles=roles, latent_needs=list(data.get("latent_needs", []))[:6])
        rec.gaps = [f for f in INTAKE_FIELDS if f not in fields or fields[f].confidence < 0.5]
        return rec

    def _complete(self, prompt: str) -> str:
        if self.provider == "anthropic":
            import anthropic  # optional extra
            client = anthropic.Anthropic()
            msg = client.messages.create(model=self.model or os.getenv("T2R_MODEL", "claude-sonnet-4-5"), max_tokens=4000,
                                         messages=[{"role": "user", "content": prompt}])
            return "".join(getattr(b, "text", "") for b in msg.content)
        if self.provider == "openai":
            from openai import OpenAI  # optional extra
            client = OpenAI()
            r = client.chat.completions.create(model=self.model or os.getenv("T2R_MODEL", "gpt-4.1"),
                                               messages=[{"role": "user", "content": prompt}], temperature=0)
            return r.choices[0].message.content or "{}"
        raise ValueError(f"unknown provider {self.provider}")


def _find_turn(tr: Transcript, quote: str) -> Turn | None:
    q = re.sub(r"\s+", " ", quote.strip().lower())
    if len(q) < 8:
        return None
    for t in tr.turns:
        if q in re.sub(r"\s+", " ", t.text.lower()):
            return t
    # fuzzy: longest common word run >= 6 words
    words = q.split()
    for t in tr.turns:
        tl = t.text.lower()
        for i in range(0, max(1, len(words) - 5)):
            if " ".join(words[i:i + 6]) in tl:
                return t
    return None


def get_extractor(provider: str | None = None):
    provider = (provider or os.getenv("T2R_PROVIDER") or "heuristic").lower()
    if provider == "heuristic":
        return HeuristicExtractor()
    if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set; use --provider heuristic or set the key.")
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set; use --provider heuristic or set the key.")
    return LLMExtractor(provider=provider)

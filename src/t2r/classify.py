"""Speaker role classification (heuristic). Gate 1 asks a human to confirm or correct the result."""
from __future__ import annotations

import re
from collections import Counter

from .schema import Transcript, ROLES

_CUES = {
    "requester": [r"\bwe need\b", r"\bwe('re| are) looking for\b", r"\bcan you (help|build)\b", r"\bour team\b", r"\bwe would like\b", r"\bwe asked\b", r"\b(?:i'?m|we'?re|i am|we are) (?:on|from|with|in) the [\w &/-]+? team\b", r"\bthe (?:problem|issue|challenge) is\b", r"\bwe (?:process|reconcile|handle|run|get) (?:around |about |roughly )?\d\b", r"\bsuccess looks like\b", r"\bif we could\b", r"\bgood would be\b", r"\bthe goal is\b", r"\bwe (?:tried|bought|built)\b"],
    "sponsor":   [r"\bbudget\b", r"\bfund(ing)?\b", r"\bpriority for (the|my) (practice|org|group)\b", r"\bi('ll| will) sponsor\b", r"\bleadership\b", r"\bsign off\b"],
    "user":      [r"\bevery (day|week|morning)\b", r"\bi (spend|open|copy|paste|export|download|fix|recode)\b", r"\bwhen i (do|run|process)\b", r"\bmy spreadsheet\b", r"\bit takes me\b", r"\bi have to\b", r"\bi'?d use it\b", r"\bi think (?:people|the team) would\b", r"\bthe coordinators are\b"],
    "engineer":  [r"\bapi\b", r"\bschema\b", r"\bpipeline\b", r"\bdeploy\b", r"\bmodel\b", r"\bvector\b", r"\bauth\b", r"\btoken\b", r"\bendpoint\b", r"\blatency\b"],
    "facilitator": [r"\blet('s| us) (start|move|go)\b", r"\bnext question\b", r"\bto recap\b", r"\bthanks everyone\b", r"\bwhat (problem|have you tried)\b", r"\bwho (are|else)\b", r"\bhow big\b"],
}


def classify_speakers(tr: Transcript) -> dict[str, str]:
    """Return {speaker: role}. The first speaker asking structured discovery questions is the facilitator."""
    scores: dict[str, Counter] = {s: Counter() for s in tr.speakers()}
    for t in tr.turns:
        low = t.text.lower()
        for role, pats in _CUES.items():
            hits = sum(len(re.findall(p, low)) for p in pats)
            if hits:
                scores[t.speaker][role] += hits
    roles: dict[str, str] = {}
    for s, c in scores.items():
        if not c:
            roles[s] = "other"
            continue
        role, _ = c.most_common(1)[0]
        roles[s] = role
    # Exactly one facilitator: the speaker with the most facilitator cues.
    fac = max(scores.items(), key=lambda kv: kv[1]["facilitator"])
    if fac[1]["facilitator"] > 0:
        for s in roles:
            if roles[s] == "facilitator" and s != fac[0]:
                roles[s] = _second_best(scores[s])
        roles[fac[0]] = "facilitator"
    for t in tr.turns:
        t.role = roles.get(t.speaker, "other")
    return roles


def _second_best(c: Counter) -> str:
    for role, _ in c.most_common():
        if role != "facilitator":
            return role
    return "other"


def role_confidence(tr: Transcript, roles: dict[str, str]) -> dict[str, float]:
    """Share of a speaker's cue hits that belong to the chosen role; 0.5 floor when no cues fired."""
    conf: dict[str, float] = {}
    for s in tr.speakers():
        total = hits = 0
        for t in tr.turns:
            if t.speaker != s:
                continue
            low = t.text.lower()
            for role, pats in _CUES.items():
                n = sum(len(re.findall(p, low)) for p in pats)
                total += n
                if role == roles[s]:
                    hits += n
        conf[s] = round(hits / total, 2) if total else 0.5
    return conf


assert set(_CUES) <= set(ROLES)

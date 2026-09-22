"""Transcript ingestion. Supports WebVTT (Zoom/Teams export), Zoom .txt, Teams .txt, and plain 'Speaker: text' files."""
from __future__ import annotations

import re
from pathlib import Path

from .schema import Transcript, Turn

_TS = r"(\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)"
_VTT_CUE = re.compile(rf"^{_TS}\s*-->\s*{_TS}")
_ZOOM_LINE = re.compile(rf"^\[?{_TS}\]?\s+([^:]+):\s*(.*)$")          # 00:00:05 Speaker: text
_TEAMS_LINE = re.compile(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+([^:]{1,60}):\s*(.*)$")  # [0:05] Speaker: text
_PLAIN_LINE = re.compile(r"^([A-Z][\w .'-]{1,50}):\s+(.*)$")
_SPEAKER_IN_CUE = re.compile(r"^(?:<v\s+([^>]+)>)?\s*(?:([^:<>]{1,60}):\s*)?(.*)$")


def _norm_ts(ts: str) -> str:
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 2:
        parts = ["00"] + parts
    h, m, s = parts
    if "." not in s:
        s = f"{s}.000"
    return f"{int(h):02d}:{int(m):02d}:{s}"


def _add_seconds(ts: str, secs: float) -> str:
    h, m, s = ts.split(":")
    total = int(h) * 3600 + int(m) * 60 + float(s) + secs
    h2, rem = divmod(total, 3600)
    m2, s2 = divmod(rem, 60)
    return f"{int(h2):02d}:{int(m2):02d}:{s2:06.3f}"


def parse_vtt(text: str) -> list[Turn]:
    turns: list[Turn] = []
    lines = text.splitlines()
    i, idx = 0, 0
    while i < len(lines):
        m = _VTT_CUE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        start, end = _norm_ts(m.group(1)), _norm_ts(m.group(2))
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip():
            body.append(lines[i].strip())
            i += 1
        cue = " ".join(body)
        sm = _SPEAKER_IN_CUE.match(cue)
        speaker = (sm.group(1) or sm.group(2) or "Unknown").strip() if sm else "Unknown"
        content = (sm.group(3) if sm else cue).strip()
        content = re.sub(r"</?v[^>]*>", "", content).strip()
        if content:
            turns.append(Turn(idx, start, end, speaker, content))
            idx += 1
    return _merge_consecutive(turns)


def parse_lines(text: str, pattern: re.Pattern, has_ts: bool) -> list[Turn]:
    turns: list[Turn] = []
    idx = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = pattern.match(line)
        if not m:
            if turns:
                turns[-1].text += " " + line
            continue
        if has_ts:
            ts, speaker, content = m.group(1), m.group(2), m.group(3)
            start = _norm_ts(ts)
        else:
            speaker, content = m.group(1), m.group(2)
            start = _add_seconds("00:00:00.000", idx * 8.0)  # synthetic pacing for plain files
        turns.append(Turn(idx, start, _add_seconds(start, 6.0), speaker.strip(), content.strip()))
        idx += 1
    return _merge_consecutive(turns)


def _merge_consecutive(turns: list[Turn]) -> list[Turn]:
    """Merge back-to-back cues from the same speaker into one turn (VTT splits every few seconds)."""
    merged: list[Turn] = []
    for t in turns:
        if merged and merged[-1].speaker == t.speaker and (t.start_seconds - merged[-1].start_seconds) < 20:
            merged[-1].text += " " + t.text
            merged[-1].end = t.end
        else:
            merged.append(Turn(len(merged), t.start, t.end, t.speaker, t.text))
    return merged


def detect_format(text: str, suffix: str) -> str:
    if text.lstrip().startswith("WEBVTT") or suffix == ".vtt":
        return "vtt"
    sample = [l for l in text.splitlines() if l.strip()][:20]
    if sum(bool(_ZOOM_LINE.match(l)) for l in sample) >= max(2, len(sample) // 3):
        return "zoom"
    if sum(bool(_TEAMS_LINE.match(l)) for l in sample) >= max(2, len(sample) // 3):
        return "teams"
    return "txt"


def load_transcript(path: str | Path) -> Transcript:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    fmt = detect_format(text, p.suffix.lower())
    if fmt == "vtt":
        turns = parse_vtt(text)
    elif fmt == "zoom":
        turns = parse_lines(text, _ZOOM_LINE, has_ts=True)
    elif fmt == "teams":
        turns = parse_lines(text, _TEAMS_LINE, has_ts=True)
    else:
        turns = parse_lines(text, _PLAIN_LINE, has_ts=False)
    if not turns:
        raise ValueError(f"No turns parsed from {p} (detected format: {fmt})")
    return Transcript(source=str(p), fmt=fmt, turns=turns)

"""MCP server exposing the pipeline as tools, so an agent (Claude Desktop, Cursor, etc.) can call it.

Design notes (see docs/SECURITY.md):
* Tools never write to Jira. `draft_stories` returns payloads; the human-approved export stays a CLI step.
* Inputs are file paths under an allow-listed root (T2R_ROOT, default: cwd) to prevent path traversal.
* No credentials are read by the server; the REST adapter is not reachable from MCP tools.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path


def _safe_path(p: str) -> Path:
    root = Path(os.getenv("T2R_ROOT", os.getcwd())).resolve()
    path = (root / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"path {p} is outside the allowed root {root}")
    return path


def serve() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Install the MCP extra: pip install 'transcript-to-requirements[mcp]'") from exc

    from .classify import classify_speakers, role_confidence
    from .extract import get_extractor
    from .ingest import load_transcript
    from .render import render_intake, render_stories
    from .score import score_dfv, score_rice
    from .stories import draft_stories
    from .export import to_jira_payload

    mcp = FastMCP("transcript-to-requirements")

    @mcp.tool()
    def ingest_transcript(path: str) -> dict:
        """Parse a VTT / Zoom / Teams / plain transcript into speaker turns with timestamps and heuristic roles."""
        tr = load_transcript(_safe_path(path))
        roles = classify_speakers(tr)
        return {"format": tr.fmt, "turns": len(tr.turns), "speakers": roles, "role_confidence": role_confidence(tr, roles)}

    @mcp.tool()
    def extract_intake(path: str, provider: str = "heuristic", roles_override: dict | None = None) -> dict:
        """Extract the 22-field intake record with per-field confidence and evidence. Pass roles_override after a human confirms roles (Gate 1)."""
        tr = load_transcript(_safe_path(path))
        roles = classify_speakers(tr)
        if roles_override:
            roles.update(roles_override)
            for t in tr.turns:
                t.role = roles.get(t.speaker, "other")
        rec = get_extractor(provider).extract(tr, roles)
        dfv, rice = score_dfv(rec), score_rice(rec)
        return {"intake": asdict(rec), "dfv": asdict(dfv), "rice": asdict(rice), "summary_markdown": render_intake(tr, rec, [dfv, rice])}

    @mcp.tool()
    def draft_jira_stories(path: str, provider: str = "heuristic", project_key: str = "INTAKE") -> dict:
        """Draft Jira-ready stories (as payloads) for human review at Gate 3. This tool never writes to Jira."""
        tr = load_transcript(_safe_path(path))
        roles = classify_speakers(tr)
        rec = get_extractor(provider).extract(tr, roles)
        dfv, rice = score_dfv(rec), score_rice(rec)
        stories = draft_stories(rec, dfv, rice, project_key)
        return {"markdown": render_stories(stories), "payloads": [to_jira_payload(s, project_key) for s in stories]}

    mcp.run()


if __name__ == "__main__":
    serve()

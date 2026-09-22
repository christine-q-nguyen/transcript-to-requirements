"""Export adapters. The mock adapter writes Jira-shaped JSON to disk (default). The REST adapter posts to a real
Jira Cloud instance and is used only when explicitly configured — and only after Gate 3 approves."""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path

from .schema import Story


def to_jira_payload(story: Story, project_key: str, parent_key: str | None = None) -> dict:
    desc = story.description
    if story.acceptance_criteria:
        desc += "\n\nh3. Acceptance criteria\n" + "\n".join(f"* {a}" for a in story.acceptance_criteria)
    if story.evidence:
        desc += "\n\nh3. Evidence\n" + "\n".join(f"* [{e.timestamp}] {e.quote}" for e in story.evidence[:3])
    fields = {
        "project": {"key": project_key},
        "summary": story.summary,
        "description": desc,
        "issuetype": {"name": story.issue_type},
        "labels": story.labels,
    }
    if parent_key and story.issue_type != "Epic":
        fields["parent"] = {"key": parent_key}
    return {"fields": fields}


class JiraMockAdapter:
    """Writes one JSON payload per story and returns fake keys. Safe default."""

    def __init__(self, out_dir: str | Path, project_key: str = "INTAKE"):
        self.out = Path(out_dir)
        self.project_key = project_key

    def create(self, stories: list[Story]) -> list[str]:
        self.out.mkdir(parents=True, exist_ok=True)
        keys: list[str] = []
        epic_key = None
        for i, s in enumerate(stories, start=1):
            key = f"{self.project_key}-{i}"
            if s.issue_type == "Epic":
                epic_key = key
            payload = to_jira_payload(s, self.project_key, epic_key if s.issue_type != "Epic" else None)
            (self.out / f"{key}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            s.key = key
            keys.append(key)
        return keys


class JiraRestAdapter:
    """Minimal Jira Cloud REST v3 client using urllib. Requires T2R_JIRA_URL, T2R_JIRA_EMAIL, T2R_JIRA_TOKEN."""

    def __init__(self, project_key: str):
        self.base = os.environ["T2R_JIRA_URL"].rstrip("/")
        auth = f"{os.environ['T2R_JIRA_EMAIL']}:{os.environ['T2R_JIRA_TOKEN']}".encode()
        self.headers = {"Authorization": "Basic " + base64.b64encode(auth).decode(), "Content-Type": "application/json", "Accept": "application/json"}
        self.project_key = project_key

    def create(self, stories: list[Story]) -> list[str]:
        keys: list[str] = []
        epic_key = None
        for s in stories:
            payload = to_jira_payload(s, self.project_key, epic_key if s.issue_type != "Epic" else None)
            req = urllib.request.Request(f"{self.base}/rest/api/3/issue", data=json.dumps(payload).encode(), headers=self.headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (explicit, configured host)
                key = json.loads(resp.read())["key"]
            if s.issue_type == "Epic":
                epic_key = key
            s.key = key
            keys.append(key)
        return keys


def get_adapter(out_dir: str | Path, project_key: str):
    if os.getenv("T2R_JIRA_URL"):
        return JiraRestAdapter(project_key)
    return JiraMockAdapter(out_dir, project_key)

# Security and data-use notes

This tool processes meeting transcripts, which routinely contain names, internal system details, and sometimes regulated data. Treat it accordingly.

## Threat model (MCP server)
Informed by the MCP Safety Audit (arXiv:2504.03767) and enterprise MCP security guidance (arXiv:2504.08623).

| Risk | Mitigation in this repo |
|---|---|
| Path traversal through tool arguments | All file arguments resolve under `T2R_ROOT` (default: cwd) and are rejected otherwise. |
| Tool poisoning / an agent being talked into writing | MCP tools are read-only: they return payloads and markdown; there is no export tool. Writing to Jira is a CLI step after Gate 3. |
| Credential exposure | The MCP server reads no Jira credentials. The REST adapter is only constructed when `T2R_JIRA_URL` is set, and only from the CLI. |
| Prompt injection via transcript content (LLM provider) | Extraction prompt instructs quote-only sourcing; quotes that do not trace back to a turn cap the field's confidence at 0.4 and surface at Gate 2. |
| Data leaving the environment | The heuristic provider never calls a network. The LLM provider sends the transcript to the configured vendor — do not use it on transcripts you are not permitted to share externally. |

## Practices
- Run with `--provider heuristic` on anything sensitive until data-use is cleared.
- Keep `out/` out of version control (it is git-ignored); it contains transcript excerpts.
- Prefer scoped service accounts and an organizational gateway for any real Jira writes; never a shared token.
- Redact names before sharing `run.json` outside the team.

## Reporting
Open an issue for security concerns; do not include transcript content in the report.

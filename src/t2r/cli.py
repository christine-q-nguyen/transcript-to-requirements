"""Command line: `t2r run`, `t2r eval`, `t2r mcp`."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="t2r", description="Meeting transcript -> requirements -> Jira-ready stories, with human gates.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run the pipeline on one transcript")
    r.add_argument("transcript")
    r.add_argument("--out", default="out")
    r.add_argument("--provider", choices=["heuristic", "anthropic", "openai"], default=None, help="default: $T2R_PROVIDER or heuristic")
    r.add_argument("--approve-all", action="store_true", help="non-interactive; auto-approve the three gates")
    r.add_argument("--reviewer", default="reviewer")
    r.add_argument("--project", default="INTAKE", help="Jira project key")
    r.add_argument("--threshold", type=float, default=0.6, help="confidence below which fields are escalated at Gate 2")
    r.add_argument("--no-export", action="store_true")

    e = sub.add_parser("eval", help="Run the evaluation harness on the labeled synthetic set")
    e.add_argument("--data", default="data/synthetic")
    e.add_argument("--labels", default="data/labels")
    e.add_argument("--out", default="eval_results")
    e.add_argument("--provider", choices=["heuristic", "anthropic", "openai"], default="heuristic")

    sub.add_parser("mcp", help="Start the MCP server (requires the 'mcp' extra)")

    a = p.parse_args(argv)
    if a.cmd == "run":
        from .pipeline import run
        run(a.transcript, a.out, a.provider, a.approve_all, a.reviewer, a.project, a.threshold, export=not a.no_export)
        return 0
    if a.cmd == "eval":
        from .eval.harness import run_eval
        run_eval(a.data, a.labels, a.out, a.provider)
        return 0
    if a.cmd == "mcp":
        from .mcp_server import serve
        serve()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

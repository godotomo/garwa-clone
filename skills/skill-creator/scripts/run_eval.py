#!/usr/bin/env python3
"""Evaluate a skill description against a set of trigger eval queries.

Runs each query through the LLM CLI tool (default `garwa -p`, overridable via
the `LLM_CLI` environment variable) a configurable number of times to measure
how reliably the skill triggers, and reports per-query and aggregate trigger
rates.

Usage:
    python -m scripts.run_eval --eval-set <trigger-eval.json> \
        --skill-path <path-to-skill> --model <model-id> \
        [--runs-per-query 3] [--verbose]

The eval set is a JSON array:
    [{"query": "...", "should_trigger": true}, ...]
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def llm_cmd(prompt: str, model: str) -> list[str]:
    """Build the CLI command for a single LLM call, model-agnostic.

    Uses the `LLM_CLI` env var (a shell command string, e.g. `garwa -p` or
    `llm -p`) followed by the prompt and `--model <model>`.
    """
    cli = os.environ.get("LLM_CLI", "garwa -p")
    return [*shlex.split(cli), prompt, "--model", model]


def build_prompt(skill_path: Path, query: str) -> str:
    """Build the prompt that asks the LLM whether the skill should trigger."""
    skill_md = skill_path / "SKILL.md"
    frontmatter = ""
    if skill_md.exists():
        text = skill_md.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                frontmatter = text[3:end].strip()
    return (
        f"You have access to a skill with this frontmatter:\n\n"
        f"{frontmatter}\n\n"
        f"Available skills list includes this skill's name and description.\n\n"
        f"A user sends this query:\n\n{query}\n\n"
        f"Would you consult this skill for this query? Answer with exactly "
        f"'YES' or 'NO' and nothing else."
    )


def run_once(skill_path: Path, query: str, model: str) -> bool:
    prompt = build_prompt(skill_path, query)
    proc = subprocess.run(
        llm_cmd(prompt, model),
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (proc.stdout or "").strip().upper()
    return out.startswith("YES")


def evaluate(eval_set: list[dict], skill_path: Path, model: str, runs_per_query: int, verbose: bool) -> dict:
    results = []
    for item in eval_set:
        query = item["query"]
        should = bool(item.get("should_trigger", True))
        triggers = 0
        for i in range(runs_per_query):
            if run_once(skill_path, query, model):
                triggers += 1
            if verbose:
                print(f"  [{i + 1}/{runs_per_query}] {query[:60]!r} -> {triggers} triggers so far")
        results.append(
            {
                "query": query,
                "should_trigger": should,
                "trigger_rate": triggers / runs_per_query,
                "triggers": triggers,
                "runs": runs_per_query,
            }
        )

    # Trigger rate: fraction of should-trigger queries that actually triggered.
    should_queries = [r for r in results if r["should_trigger"]]
    trigger_rate = (
        sum(r["trigger_rate"] for r in should_queries) / len(should_queries)
        if should_queries
        else 0.0
    )
    # False positive rate: fraction of should-not-trigger queries that wrongly triggered.
    not_queries = [r for r in results if not r["should_trigger"]]
    false_positive_rate = (
        sum(r["trigger_rate"] for r in not_queries) / len(not_queries)
        if not_queries
        else 0.0
    )
    return {
        "trigger_rate": trigger_rate,
        "false_positive_rate": false_positive_rate,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a skill description against trigger queries")
    parser.add_argument("--eval-set", type=Path, required=True, help="Path to trigger-eval.json")
    parser.add_argument("--skill-path", type=Path, required=True, help="Path to the skill directory")
    parser.add_argument("--model", required=True, help="Model ID powering the current session")
    parser.add_argument("--runs-per-query", type=int, default=3, help="Runs per query (default 3)")
    parser.add_argument("--verbose", action="store_true", help="Print per-run progress")
    args = parser.parse_args(argv)

    if not args.eval_set.exists():
        print(f"error: eval set not found: {args.eval_set}", file=sys.stderr)
        return 1

    eval_set = json.loads(args.eval_set.read_text(encoding="utf-8"))
    result = evaluate(eval_set, args.skill_path, args.model, args.runs_per_query, args.verbose)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

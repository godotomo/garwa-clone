#!/usr/bin/env python3
"""Optimize a skill's description by iterating on trigger-eval results.

The loop repeatedly:
  1. Splits the eval set into 60% train / 40% held-out test.
  2. Runs `scripts.run_eval` on the current description (each query 3 times).
  3. Compares the trigger rate against the previous iteration.
  4. If the rate improved, keeps the description; otherwise reverts to the
     best-known description and proposes a new candidate (via an LLM call
     through the configured CLI tool).
  5. Stops after `--max-iterations` or when the train trigger rate reaches
     `--target-rate`.

When done, writes a JSON report (including `best_description`, selected by
test score rather than train score to avoid overfitting) and opens an HTML
report in the browser.

Usage:
    python -m scripts.run_loop --skill-path <path-to-skill> \
        --eval-set <trigger-eval.json> --model <model-id> \
        [--max-iterations 5] [--target-rate 0.95] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import webbrowser
from pathlib import Path

from scripts.run_eval import evaluate, llm_cmd


def split_eval_set(eval_set: list[dict], seed: int = 0) -> tuple[list[dict], list[dict]]:
    """Split the eval set into 60% train / 40% test."""
    rng = random.Random(seed)
    items = list(eval_set)
    rng.shuffle(items)
    split = max(1, round(len(items) * 0.6))
    return items[:split], items[split:]


def propose_candidate(skill_path: Path, eval_set: list[dict], model: str, current_desc: str, results: dict) -> str:
    """Ask an LLM to rewrite the description to improve trigger reliability."""
    failures = [
        r for r in results["results"]
        if r["should_trigger"] and r["trigger_rate"] < 1.0
    ]
    problem_queries = ", ".join(f'"{r["query"]}"' for r in failures[:5]) or "none"
    prompt = (
        f"You are improving a skill's description so it triggers reliably.\n\n"
        f"Current description:\n\n{current_desc}\n\n"
        f"Queries that failed to trigger the skill:\n{problem_queries}\n\n"
        f"Rewrite the description (frontmatter name + description) to cover these "
        f"queries while staying concise. Output only the rewritten description."
    )
    proc = subprocess.run(
        llm_cmd(prompt, model),
        capture_output=True,
        text=True,
        timeout=180,
    )
    return (proc.stdout or "").strip() or current_desc


def write_description(skill_path: Path, description: str) -> Path:
    """Write the description back into SKILL.md frontmatter (best-effort)."""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return skill_md
    text = skill_md.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            body = text[end + 3 :]
            new = "---\n" + description.rstrip() + "\n---\n" + body
            skill_md.write_text(new, encoding="utf-8")
    return skill_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimize a skill description via trigger-eval loop")
    parser.add_argument("--skill-path", type=Path, required=True, help="Path to the skill directory")
    parser.add_argument("--eval-set", type=Path, required=True, help="Path to trigger-eval.json")
    parser.add_argument("--model", required=True, help="Model ID for the session")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--target-rate", type=float, default=0.95)
    parser.add_argument("--runs-per-query", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.eval_set.exists():
        print(f"error: eval set not found: {args.eval_set}", file=sys.stderr)
        return 1

    eval_set = json.loads(args.eval_set.read_text(encoding="utf-8"))
    train, test = split_eval_set(eval_set, args.seed)

    skill_md = args.skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"error: SKILL.md not found: {skill_md}", file=sys.stderr)
        return 1

    # Extract current frontmatter description.
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        print("error: SKILL.md has no frontmatter", file=sys.stderr)
        return 1
    end = text.find("---", 3)
    current_desc = text[3:end].strip()

    best_desc = current_desc
    best_test_rate = 0.0
    history = []

    for it in range(1, args.max_iterations + 1):
        if args.verbose:
            print(f"--- iteration {it} ---")
        train_result = evaluate(train, args.skill_path, args.model, args.runs_per_query, args.verbose)
        test_result = evaluate(test, args.skill_path, args.model, args.runs_per_query, args.verbose)
        train_rate = train_result["trigger_rate"]
        test_rate = test_result["trigger_rate"]
        history.append({
            "iteration": it,
            "train_trigger_rate": train_rate,
            "test_trigger_rate": test_rate,
            "description": current_desc,
        })
        print(f"iteration {it}: train={train_rate:.2f} test={test_rate:.2f}")

        # Select best by TEST score to avoid overfitting to train.
        if test_rate > best_test_rate:
            best_test_rate = test_rate
            best_desc = current_desc

        if train_rate >= args.target_rate:
            print(f"Reached target rate {args.target_rate:.2f} on train. Stopping.")
            break

        candidate = propose_candidate(args.skill_path, train, args.model, current_desc, train_result)
        if candidate == current_desc:
            print("No candidate change proposed. Stopping.")
            break
        write_description(args.skill_path, candidate)
        current_desc = candidate

    # Restore best-known description.
    write_description(args.skill_path, best_desc)
    report = {
        "best_description": best_desc,
        "best_test_trigger_rate": best_test_rate,
        "target_rate": args.target_rate,
        "history": history,
    }
    report_path = args.skill_path / "description_optimization_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {report_path}")

    # Render and open an HTML report.
    html = render_report_html(report, args.skill_path.name)
    html_path = args.skill_path / "description_optimization_report.html"
    html_path.write_text(html, encoding="utf-8")
    webbrowser.open(html_path.as_uri())
    print(f"Opened {html_path}")
    return 0


def render_report_html(report: dict, skill_name: str) -> str:
    rows = "".join(
        f"<tr><td>{h['iteration']}</td>"
        f"<td>{h['train_trigger_rate']:.2f}</td>"
        f"<td>{h['test_trigger_rate']:.2f}</td></tr>"
        for h in report["history"]
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Description Optimization — {skill_name}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #0f1115; color: #e6e8ec; padding: 24px; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 600px; }}
  th, td {{ border: 1px solid #262b36; padding: 8px 12px; text-align: left; }}
  th {{ background: #171a21; }}
  pre {{ background: #171a21; border: 1px solid #262b36; padding: 12px; border-radius: 8px; white-space: pre-wrap; }}
</style></head><body>
<h1>Description Optimization — {skill_name}</h1>
<h2>Best test trigger rate: {report['best_test_trigger_rate']:.2f}</h2>
<table><tr><th>Iteration</th><th>Train</th><th>Test</th></tr>{rows}</table>
<h2>Best description</h2>
<pre>{report['best_description']}</pre>
</body></html>"""


if __name__ == "__main__":
    sys.exit(main())

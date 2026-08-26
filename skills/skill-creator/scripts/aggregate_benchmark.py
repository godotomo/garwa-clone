#!/usr/bin/env python3
"""Aggregate per-run grading.json + timing.json into a benchmark for one iteration.

Reads a workspace iteration directory structured like:

    <workspace>/iteration-<N>/
        <eval-name>/
            eval_metadata.json
            with_skill/
                outputs/...
                grading.json
                timing.json
            without_skill/   (or old_skill/)
                outputs/...
                grading.json
                timing.json

and writes `benchmark.json` and `benchmark.md` into the iteration directory.

Usage:
    python -m scripts.aggregate_benchmark <workspace>/iteration-<N> --skill-name <name>
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _std(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _round(v: float) -> float:
    return round(v, 4)


def aggregate(iteration_dir: Path, skill_name: str) -> dict:
    configs: list[dict] = []
    eval_names: list[str] = []

    # Collect per-eval, per-config grading data.
    evals_by_config: dict[str, list[dict]] = {}
    for eval_dir in sorted(p for p in iteration_dir.iterdir() if p.is_dir()):
        eval_name = eval_dir.name
        eval_names.append(eval_name)
        meta = _load_json(eval_dir / "eval_metadata.json")
        for config in ("with_skill", "without_skill", "old_skill"):
            run_dir = eval_dir / config
            if not (run_dir / "grading.json").exists():
                continue
            grading = _load_json(run_dir / "grading.json")
            timing = {}
            if (run_dir / "timing.json").exists():
                timing = _load_json(run_dir / "timing.json")
            expectations = grading.get("expectations", [])
            passed = sum(1 for e in expectations if e.get("passed"))
            total = len(expectations)
            evals_by_config.setdefault(config, []).append(
                {
                    "eval_name": eval_name,
                    "prompt": meta.get("prompt", ""),
                    "passed": passed,
                    "total": total,
                    "time_seconds": timing.get("total_duration_seconds", 0.0),
                    "tokens": timing.get("total_tokens", 0),
                }
            )

    # Order configs: with_skill first, then its baseline counterpart.
    config_order = [c for c in ("with_skill", "without_skill", "old_skill") if c in evals_by_config]
    for config in config_order:
        runs = evals_by_config[config]
        pass_rates = [r["passed"] / r["total"] if r["total"] else 0.0 for r in runs]
        times = [r["time_seconds"] for r in runs]
        tokens = [r["tokens"] for r in runs]
        configs.append(
            {
                "name": config,
                "pass_rate": _round(_mean(pass_rates)),
                "pass_rate_mean": _round(_mean(pass_rates)),
                "pass_rate_std": _round(_std(pass_rates)),
                "time_mean_seconds": _round(_mean(times)),
                "time_std_seconds": _round(_std(times)),
                "tokens_mean": round(_mean(tokens)),
                "tokens_std": round(_std(tokens)),
                "evals": [
                    {"eval_name": r["eval_name"], "passed": r["passed"], "total": r["total"]}
                    for r in runs
                ],
            }
        )

    # Deltas: each with-skill config vs its baseline.
    deltas: list[dict] = []
    for config in config_order:
        if config == "with_skill":
            for base in ("without_skill", "old_skill"):
                if base in evals_by_config:
                    ws = next(c for c in configs if c["name"] == "with_skill")
                    bl = next(c for c in configs if c["name"] == base)
                    deltas.append(
                        {
                            "config": "with_skill",
                            "vs": base,
                            "pass_rate_delta": _round(ws["pass_rate"] - bl["pass_rate"]),
                            "time_delta_seconds": _round(ws["time_mean_seconds"] - bl["time_mean_seconds"]),
                            "tokens_delta": ws["tokens_mean"] - bl["tokens_mean"],
                        }
                    )

    return {
        "skill_name": skill_name,
        "iteration": _iteration_number(iteration_dir),
        "configs": configs,
        "deltas": deltas,
        "analyst_notes": [],
    }


def _iteration_number(iteration_dir: Path) -> int:
    try:
        return int(iteration_dir.name.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return 0


def render_markdown(benchmark: dict) -> str:
    lines = [
        f"# Benchmark — {benchmark['skill_name']} (iteration {benchmark['iteration']})",
        "",
    ]
    for cfg in benchmark["configs"]:
        lines.append(f"## {cfg['name']}")
        lines.append("")
        lines.append(f"- Pass rate: {cfg['pass_rate']:.0%} (std {cfg['pass_rate_std']:.0%})")
        lines.append(f"- Time: {cfg['time_mean_seconds']:.1f}s (std {cfg['time_std_seconds']:.1f}s)")
        lines.append(f"- Tokens: {cfg['tokens_mean']:,} (std {cfg['tokens_std']:,})")
        lines.append("")
        lines.append("| Eval | Passed | Total |")
        lines.append("|------|--------|-------|")
        for ev in cfg["evals"]:
            lines.append(f"| {ev['eval_name']} | {ev['passed']} | {ev['total']} |")
        lines.append("")
    if benchmark["deltas"]:
        lines.append("## Deltas (with_skill vs baseline)")
        lines.append("")
        for d in benchmark["deltas"]:
            lines.append(
                f"- vs {d['vs']}: pass_rate {d['pass_rate_delta']:+.0%}, "
                f"time {d['time_delta_seconds']:+.1f}s, tokens {d['tokens_delta']:+,}"
            )
        lines.append("")
    if benchmark.get("analyst_notes"):
        lines.append("## Analyst notes")
        lines.append("")
        for note in benchmark["analyst_notes"]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate run results into a benchmark")
    parser.add_argument("iteration_dir", type=Path, help="Path to <workspace>/iteration-<N>")
    parser.add_argument("--skill-name", required=True, help="Name of the skill")
    args = parser.parse_args(argv)

    if not args.iteration_dir.is_dir():
        print(f"error: not a directory: {args.iteration_dir}", file=sys.stderr)
        return 1

    benchmark = aggregate(args.iteration_dir, args.skill_name)
    benchmark_path = args.iteration_dir / "benchmark.json"
    md_path = args.iteration_dir / "benchmark.md"
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(benchmark), encoding="utf-8")
    print(f"Wrote {benchmark_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

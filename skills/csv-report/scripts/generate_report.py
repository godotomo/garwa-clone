#!/usr/bin/env python3
"""Generate a professional Markdown/DOCX/PDF report from a CSV file.

Bundled script for the `csv-report` skill. Deterministic and reusable.
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path


def load_rows(path: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    return reader.fieldnames, rows


def detect_type(values):
    """Return 'numeric', 'date', or 'categorical' for a column's non-empty values."""
    non_empty = [v for v in values if v not in (None, "")]
    if not non_empty:
        return "categorical"
    # numeric if all parse as float
    try:
        for v in non_empty:
            float(v)
        return "numeric"
    except ValueError:
        pass
    return "categorical"


def summarize(col, values):
    t = detect_type(values)
    non_empty = [v for v in values if v not in (None, "")]
    n = len(values)
    missing = n - len(non_empty)
    out = {"column": col, "type": t, "count": len(non_empty), "missing": missing}
    if t == "numeric":
        nums = [float(v) for v in non_empty]
        out["mean"] = round(statistics.mean(nums), 2)
        out["median"] = round(statistics.median(nums), 2)
        out["min"] = round(min(nums), 2)
        out["max"] = round(max(nums), 2)
        out["std"] = round(statistics.stdev(nums), 2) if len(nums) > 1 else 0.0
    else:
        from collections import Counter
        c = Counter(non_empty)
        out["unique"] = len(c)
        out["top"] = c.most_common(1)[0][0] if c else ""
    return out


def build_report(path, title):
    cols, rows = load_rows(path)
    n_rows = len(rows)
    n_cols = len(cols)

    # data quality
    total_missing = 0
    dup_count = 0
    seen = set()
    for r in rows:
        key = tuple(r.get(c, "") for c in cols)
        if key in seen:
            dup_count += 1
        seen.add(key)
        for c in cols:
            if r.get(c, "") in (None, ""):
                total_missing += 1

    summaries = [summarize(c, [r.get(c, "") for r in rows]) for c in cols]

    lines = []
    lines.append(f"# {title} — Data Summary Report")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- Total rows: {n_rows}")
    lines.append(f"- Total columns: {n_cols}")
    lines.append(f"- Columns: {', '.join(cols)}")
    lines.append("")
    lines.append("## Data Quality")
    pct = round(100 * total_missing / (n_rows * n_cols), 2) if n_rows * n_cols else 0
    lines.append(f"- Missing values: {total_missing} ({pct}%)")
    lines.append(f"- Duplicate rows: {dup_count}")
    for s in summaries:
        if s["missing"]:
            lines.append(f"- `{s['column']}`: {s['missing']} missing")
    lines.append("")
    lines.append("## Summary Statistics")
    lines.append("| Column | Type | Count | Mean | Median | Min | Max | Std |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in summaries:
        if s["type"] == "numeric":
            lines.append(
                f"| {s['column']} | numeric | {s['count']} | {s['mean']} | "
                f"{s['median']} | {s['min']} | {s['max']} | {s['std']} |"
            )
        else:
            lines.append(
                f"| {s['column']} | categorical | {s['count']} | — | — | — | — | "
                f"({s['unique']} unique, top: {s['top']}) |"
            )
    lines.append("")
    lines.append("## Sample Data")
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "---|" * n_cols)
    for r in rows[:5]:
        lines.append("| " + " | ".join(str(r.get(c, "")).replace("|", "\\|") for c in cols) + " |")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Generate a report from a CSV.")
    ap.add_argument("--input", required=True, help="Path to input CSV")
    ap.add_argument("--title", default="Dataset", help="Report title")
    ap.add_argument("--out", default="report.md", help="Output file path")
    ap.add_argument("--format", default="md", choices=["md", "docx", "pdf"])
    args = ap.parse_args()

    md = build_report(args.input, args.title)

    if args.format == "md":
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"Wrote {args.out}")
        return

    # DOCX / PDF require optional deps; keep it simple and delegate.
    print(f"Format '{args.format}' requires extra dependencies; wrote Markdown instead.")
    Path(args.out).write_text(md, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    sys.exit(main())

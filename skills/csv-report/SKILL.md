---
name: csv-report
description: "Generate a professional, formatted report (Markdown, DOCX, or PDF) from a CSV file: automatic column detection, summary statistics, data quality checks, and clean tables. Use this skill whenever the user wants to turn a CSV/Excel export into a readable report, summarize a dataset, check data quality, or produce a formatted document from tabular data — even if they don't explicitly say 'report' (e.g. 'make me a summary of this sales file', 'turn this export into something presentable')."
---

# CSV Report Generator

Turn any CSV file into a clean, professional report with summary statistics,
data-quality checks, and formatted tables. This skill is deterministic and
reproducible: given the same CSV, it produces the same report structure.

## When to use

- User has a CSV/Excel export and wants a human-readable summary or report.
- User wants data-quality checks (missing values, duplicates, type issues).
- User wants a formatted document (Markdown/DOCX/PDF) from tabular data.

## Workflow

1. **Locate the CSV** — confirm the path. If the user gave a directory, pick the
   most recent `.csv` file.
2. **Inspect the schema** — read the header row and a few sample rows to detect
   column types (numeric, categorical, date, free-text).
3. **Compute summary statistics** — for each numeric column: count, mean,
   median, min, max, std. For categorical columns: unique count + top values.
4. **Run data-quality checks** — report missing values per column, duplicate
   rows, and any obviously malformed values (e.g. negative quantities, empty
   strings in required fields).
5. **Generate the report** — use the bundled script `scripts/generate_report.py`
   (see below) so the output is consistent. Do not hand-write the report logic.

## Report structure

ALWAYS use this exact template:

```
# <Dataset Title> — Data Summary Report

## Overview
- Total rows: N
- Total columns: M
- Columns: <list>

## Data Quality
- Missing values: <count> (<pct>%)
- Duplicate rows: <count>
- <per-column issues>

## Summary Statistics
<markdown table: column | type | count | mean | median | min | max | std>

## Sample Data
<first 5 rows as a table>
```

## Using the bundled script

The script `scripts/generate_report.py` handles parsing, statistics, quality
checks, and Markdown output. Run it with:

```bash
python3 scripts/generate_report.py --input <file.csv> --title "<Title>" --out <report.md>
```

It also supports `--format docx` and `--format pdf` if the `docx`/`pdf` skills'
dependencies are available. Prefer the script over manual computation — it is
tested and avoids mistakes in edge cases (empty files, single-column CSVs,
non-numeric data).

## Quality gates

Before declaring the report done, verify:

- [ ] Every numeric column has mean/median/min/max/std computed.
- [ ] Missing values and duplicates are explicitly reported (even if zero).
- [ ] The report follows the exact template above.
- [ ] The output file exists and is non-empty.

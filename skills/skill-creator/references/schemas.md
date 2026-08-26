# Schemas

This file documents the JSON structures used throughout the skill-creator workflow. Keep the field names exact — the viewer, grading scripts, and benchmark aggregator depend on them.

## evals.json

The test-case definition file, stored at `evals/evals.json` in the skill directory. Written in two phases: first with just prompts (before running), then assertions are added while the runs are in progress.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "name": "descriptive-name-here",
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": [],
      "assertions": [
        {
          "name": "output-is-xlsx",
          "description": "The output file is a valid .xlsx workbook",
          "type": "programmatic",
          "check": "python",
          "script": "assert Path('output').suffix == '.xlsx'"
        },
        {
          "name": "contains-profit-margin-column",
          "description": "A 'Profit Margin' column exists with percentage values",
          "type": "programmatic",
          "check": "python",
          "script": "df = read_workbook('output'); assert 'Profit Margin' in df.columns"
        }
      ]
    }
  ]
}
```

### Field reference

- `skill_name` (string): the skill's name, matching its directory and SKILL.md frontmatter.
- `evals` (array): one object per test case.
  - `id` (integer): zero-based or sequential index used as `eval-<id>`.
  - `name` (string): a short descriptive slug of what the test case checks (e.g. `profit-margin-column`). Used for the run directory and shown in the viewer. If omitted, defaults to `eval-<id>`.
  - `prompt` (string): the user's task prompt, verbatim.
  - `expected_output` (string, optional): a prose description of what a successful result looks like.
  - `files` (array): input file paths relative to the skill directory that should be copied into the run's input area. Empty if none.
  - `assertions` (array): quantitative checks. Each assertion:
    - `name` (string): short, descriptive, reads clearly in the benchmark viewer.
    - `description` (string, optional): one-line explanation of what it verifies.
    - `type` (string): `programmatic` or `manual`.
    - `check` (string): for `programmatic`, the tool used (`python`, `bash`, etc.).
    - `script` (string): for `programmatic`, the code to run. It receives the run's `outputs/` directory as context.
    - For `manual` assertions, only `name` and `description` are needed — a human (or grader subagent) judges them.

## eval_metadata.json

Written per test case into each run's eval directory (e.g. `<workspace>/iteration-1/<eval-name>/eval_metadata.json`). Captures the intent of the eval and the assertions to check. Assertions may be empty initially and filled in while runs are in progress.

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

## timing.json

Written per run into the run directory (e.g. `<workspace>/iteration-1/<eval-name>/with_skill/timing.json`) immediately when the subagent task completes. This data only arrives through the task notification, so capture it right away.

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

## grading.json

Written per run into the run directory after the grader evaluates each assertion against the outputs. **The `expectations` array must use the exact field names `text`, `passed`, and `evidence`** — the viewer depends on these. Do not use `name`/`met`/`details` or other variants.

```json
{
  "run_id": "eval-0-with_skill",
  "eval_name": "descriptive-name-here",
  "expectations": [
    {
      "text": "output-is-xlsx",
      "passed": true,
      "evidence": "output.xlsx exists and opens as a valid workbook"
    },
    {
      "text": "contains-profit-margin-column",
      "passed": false,
      "evidence": "'Profit Margin' column missing; only Revenue and Cost present"
    }
  ]
}
```

### Field reference

- `run_id` (string): `<eval-name>-<config>` where config is `with_skill`, `without_skill`, or `old_skill`.
- `eval_name` (string): matches the eval's descriptive name.
- `expectations` (array): one object per assertion.
  - `text` (string): the assertion name (or its description).
  - `passed` (boolean): whether the assertion passed.
  - `evidence` (string): a short, concrete justification — what was checked and what was found.

## benchmark.json

Produced by `scripts.aggregate_benchmark` (or generated manually — if so, follow this schema exactly). Aggregates pass rates, timing, and token usage across all runs in an iteration, with mean ± stddev and the delta between each with-skill config and its baseline.

```json
{
  "skill_name": "example-skill",
  "iteration": 1,
  "configs": [
    {
      "name": "with_skill",
      "pass_rate": 0.83,
      "pass_rate_mean": 0.83,
      "pass_rate_std": 0.12,
      "time_mean_seconds": 41.2,
      "time_std_seconds": 5.1,
      "tokens_mean": 74000,
      "tokens_std": 9200,
      "evals": [
        {
          "eval_name": "profit-margin-column",
          "passed": 2,
          "total": 3
        }
      ]
    },
    {
      "name": "without_skill",
      "pass_rate": 0.5,
      "pass_rate_mean": 0.5,
      "pass_rate_std": 0.15,
      "time_mean_seconds": 33.0,
      "time_std_seconds": 4.2,
      "tokens_mean": 61000,
      "tokens_std": 8100,
      "evals": [
        {
          "eval_name": "profit-margin-column",
          "passed": 1,
          "total": 3
        }
      ]
    }
  ],
  "deltas": [
    {
      "config": "with_skill",
      "vs": "without_skill",
      "pass_rate_delta": 0.33,
      "time_delta_seconds": 8.2,
      "tokens_delta": 13000
    }
  ],
  "analyst_notes": [
    "assertion 'output-is-xlsx' passes for both configs — non-discriminating",
    "eval 'profit-margin-column' has high variance; may be flaky"
  ]
}
```

When building the configs array, put each with-skill version before its baseline counterpart (e.g. `with_skill` then `without_skill`, or `with_skill` then `old_skill`).

## feedback.json

Produced by the eval viewer when the user clicks "Submit All Reviews". In headless/Cowork environments it downloads as a file; copy it into the workspace so the next iteration can pick it up.

```json
{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "the chart is missing axis labels", "timestamp": "2025-01-01T12:00:00Z"},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "2025-01-01T12:01:00Z"}
  ],
  "status": "complete"
}
```

Empty `feedback` means the user thought it was fine. Focus improvements on runs with specific complaints.

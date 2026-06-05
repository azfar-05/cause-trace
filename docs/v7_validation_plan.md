# CauseTrace V7: CI Acquisition Layer Validation Plan

## Purpose

Validate the operational behavior of the V7 CI acquisition layer against real
GitHub Actions executions.  The acquisition layer consists of two functions:

- `resolve_good_commit` — queries the GitHub Actions API for the last green
  build SHA on the current branch
- `extract_trace_from_log` — selects the first usable stack trace from CI
  test-runner output

This plan exercises both functions through deliberate, controlled failures in a
known environment.  Attribution quality is a secondary concern; acquisition
correctness is the primary target.

---

## 1. Repository

**Use the `cause-trace` repository itself.**

No separate repository is needed.  The `cause-trace` repo already has:
- `.github/workflows/causetrace.yml` (created in V7)
- `src/` with known file paths and function names
- `tests/` with a pytest suite
- A clean, linear git history

A new `validation/` package is added to the repo as the breakable target.
This keeps the existing `src/` signal pipeline untouched and gives the
investigation a controlled module with predictable file/function/line
coordinates.

### Validation package structure

```
validation/
    __init__.py       (empty)
    target.py         (two functions: process() and compute())
tests/
    test_target.py    (four tests against validation/target.py)
```

**`validation/target.py` — initial green state:**

```python
def process(data: dict, key: str) -> str:
    value = data[key]
    return f"result: {value}"


def compute(x: int, multiplier: int = 2) -> int:
    return x * multiplier
```

**`tests/test_target.py`:**

```python
from validation.target import compute, process


def test_process_basic():
    assert process({"a": 1}, "a") == "result: 1"


def test_process_missing_key():
    assert process({"a": 1}, "b") == "result: None"


def test_compute_basic():
    assert compute(5) == 10


def test_compute_with_multiplier():
    assert compute(3, multiplier=4) == 12
```

Note: `test_process_missing_key` is intentionally wrong (it will always fail).
Fix it before starting validation: `assert process({"a": 1, "b": None}, "b") == "result: None"`.

**Establish the green baseline before running any scenario:**

Commit the validation package, confirm all tests pass in CI, and record the
green run SHA.  This becomes the expected `good_commit` for S1–S4.

---

## 2. Failure Scenarios

Five scenarios, each a deliberate breaking commit pushed to `main`.
After each scenario, push a fix commit to restore the green baseline before
running the next scenario.

---

### S1 — Single targeted failure (baseline validation)

**Purpose:** Confirm the full acquisition-to-investigation pipeline works
end-to-end with the cleanest possible input.

**Commit change:**

```python
# validation/target.py
def compute(x: int, multiplier: int = 2) -> int:
    raise RuntimeError("compute is broken")  # S1 deliberate regression
```

**Expected CI log trace:**

```
tests/test_target.py::test_compute_basic FAILED
tests/test_target.py::test_compute_with_multiplier FAILED

FAILURES
_______ test_compute_basic _______
...
tests/test_target.py:N: in test_compute_basic
    assert compute(5) == 10
validation/target.py:N: in compute
    raise RuntimeError("compute is broken")
RuntimeError: compute is broken
```

**Expected acquisition output:**

| Field | Expected value |
|---|---|
| `bad_commit` | SHA of this commit |
| `good_commit` | SHA of the green baseline commit |
| Window size | 1 |
| Trace extracted | Contains `validation/target.py` and `tests/test_target.py` |
| Top-ranked commit | This commit |
| Dominant signals | `function` (compute), `line`, `file` |

**What this validates:**
- `resolve_good_commit` resolves the correct prior green SHA
- `extract_trace_from_log` finds the pytest failure block
- `compute` function name fires the function signal
- Line proximity fires because the raise is near the line range

---

### S2 — Two failing tests, two traces in one log

**Purpose:** Validate that `extract_trace_from_log` returns the FIRST repo
trace when the log contains multiple failure blocks, rather than concatenating
or returning the wrong one.

**Commit change:**

```python
# validation/target.py
def process(data: dict, key: str) -> str:
    raise ValueError("process is broken")   # S2 deliberate regression

def compute(x: int, multiplier: int = 2) -> int:
    raise RuntimeError("compute is broken") # S2 deliberate regression
```

**Expected CI log:** Two separate failure blocks in the pytest output —
`test_process_basic` first (alphabetical), then `test_compute_basic`.

**Expected acquisition output:**

| Field | Expected value |
|---|---|
| Window size | 1 |
| Trace extracted | Contains the FIRST failure block only (process or compute, depending on pytest order) |
| Trace does NOT contain | Both failure blocks concatenated |
| Top-ranked commit | This commit |

**What this validates:**
- `extract_trace_from_log` selects one trace, not all
- The selected trace is the first one in the log
- Investigation proceeds against the selected trace (not a merge of all failures)

**Note:** Record which test's trace was selected.  If `test_compute_basic` runs
before `test_process_basic` in pytest output, compute's trace is selected.
Verify by checking the `Files` and `Functions` lines in the CauseTrace header.

---

### S3 — Non-repo trace preceding repo trace

**Purpose:** Validate that `extract_trace_from_log` prefers a trace containing
repository file paths over an earlier trace containing only library paths.

**Setup:** Add a new test file `tests/test_noise.py` that produces a
stdlib-only traceback.  The noise test must be ordered BEFORE the target test
in pytest's collection sequence (use name prefix `test_aaa_` or `test_0_` if
needed to guarantee ordering).

**`tests/test_noise.py` (added in this commit):**

```python
import json

def test_json_noise():
    # Deliberately fails inside stdlib json — trace has no repo file paths.
    json.loads("}{invalid-json}")
```

**Commit change (in same commit):**

```python
# validation/target.py
def compute(x: int, multiplier: int = 2) -> int:
    raise RuntimeError("compute broken by S3")
```

**Expected CI log (partial, with --tb=long):**

```
_______ test_json_noise _______
Traceback (most recent call last):
  File "tests/test_noise.py", line 4, in test_json_noise
    json.loads("}{invalid-json}")
  File "/usr/lib/python3.11/json/__init__.py", line 346, in loads
    ...
json.decoder.JSONDecodeError: ...

_______ test_compute_basic _______
...
tests/test_target.py:N: in test_compute_basic
    assert compute(5) == 10
validation/target.py:N: in compute
    raise RuntimeError("compute broken by S3")
RuntimeError: ...
```

**Expected acquisition output:**

| Field | Expected value |
|---|---|
| Trace extracted | Contains `validation/target.py` (not `json/__init__.py`) |
| Top-ranked commit | This commit |

**What this validates:**
- `extract_trace_from_log` prefers the trace with repo-matching paths
- The json stdlib trace is not selected even though it appears first

**Important:** This scenario requires `pytest --tb=long` in the workflow step
to produce Traceback-format output.  Update the workflow step for this run:
```
pytest tests/ -v --tb=long 2>&1 | tee test-output.txt
```

Without `--tb=long`, pytest's short format produces `E json.decoder.JSONDecodeError` inline,
not as a Traceback block.  Record whether `resolve_good_commit` and trace
selection both work with the `--tb=long` flag.

---

### S4 — Shallow trace (assertion failure only)

**Purpose:** Document CauseTrace's behavior when the extracted trace contains
only the test file, with no source file frames.  No line proximity or function
signal can fire; ranking falls to file-only and recency.

**Commit change:**

```python
# validation/target.py
def compute(x: int, multiplier: int = 2) -> int:
    return x * multiplier * 0   # BUG: always returns 0
```

**Expected CI log (pytest short format):**

```
_______ test_compute_basic _______

    def test_compute_basic():
>       assert compute(5) == 10
E       AssertionError: assert 0 == 10
E        +  where 0 = compute(5)

tests/test_target.py:N: AssertionError
```

The trace has only `tests/test_target.py`.  `validation/target.py` does not
appear because no exception is raised inside it — the assertion fails in the
test file.

**Expected acquisition output:**

| Field | Expected value |
|---|---|
| Trace extracted | `tests/test_target.py` only |
| Files parsed | `tests/test_target.py` |
| Functions parsed | `test_compute_basic` |
| Line proximity | 0 (no src/ file in trace) |
| Function signal | 0 (test function not in modified functions) |
| File overlap | 0 (test file is not touched by the commit) |
| Ranking basis | Recency only |

**What this validates:**
- CauseTrace does not crash on a shallow trace
- The acquisition layer still produces a complete output
- Signal degradation is visible in the output (all signals = 0, recency only)
- The scenario is recorded as a known failure mode under shallow-trace conditions

**Pass/fail note:** A ranking result of "recency only" for this scenario is
EXPECTED and correct.  It is not an acquisition failure.

---

### S5 — Commit window size > 1

**Purpose:** Validate that `resolve_good_commit` constructs the correct window
when multiple commits exist between the last green build and the failing build.

**Setup:** Push three commits in a single `git push`:

```
Commit A: Add a comment to validation/target.py (noise — no test impact)
Commit B: Break compute() with a raise (causal)
Commit C: Add a docstring to process() (noise — no test impact)
```

The push triggers one CI run.  `bad_commit = HEAD = Commit C`.
`good_commit = last green SHA = before Commit A`.
Window contains A, B, and C.

**Commit B change (causal):**

```python
def compute(x: int, multiplier: int = 2) -> int:
    raise RuntimeError("broken in S5 commit B")
```

**Expected acquisition output:**

| Field | Expected value |
|---|---|
| Window size | 3 |
| Commits in window | A (noise), B (causal), C (noise) |
| Top-ranked commit | Commit B |
| Commit A score | Low (no file/function/line overlap with trace) |
| Commit C score | Low (same reason) |

**What this validates:**
- `resolve_good_commit` correctly returns the SHA before Commit A
- `bad_commit` is Commit C (HEAD), not Commit B
- CauseTrace correctly identifies Commit B from a 3-commit window
- Noise commits do not displace the causal commit

---

## 3. Data Collection Checklist

For each scenario run, download `causetrace-results.txt` from the GitHub
Actions artifacts and fill in:

```
Scenario:          S__
Run URL:           https://github.com/azfar-05/cause-trace/actions/runs/___
bad_commit:        ____________  (from run, GITHUB_SHA env var)
good_commit:       ____________  (from CauseTrace header output)
Window size:       ____________  (from "N commit(s) in range" in header)
Trace source:      ____________  (files listed under "PARSED FROM TRACE")
Functions parsed:  ____________  (functions listed under "PARSED FROM TRACE")
Top-ranked commit: ____________  (first ranked commit SHA)
Top-ranked score:  ____________  (score from output)
Acquisition error: YES / NO      (ci_runner.py aborted?)
Error message:     ____________  (if YES: message from stderr)
Causal commit correct: YES / NO  (top-ranked = expected causal?)
```

Additionally record for each run:
- Full `causetrace-results.txt` (archived, not summarized)
- Whether `resolve_good_commit` produced any visible error in the workflow log
- Whether the `test-output.txt` artifact was uploaded (confirms capture step worked)

---

## 4. Success Criteria

Success criteria are separated by layer.  Acquisition layer criteria must all
pass before attribution quality is evaluated.

### CI Integration (pass/fail)

| Criterion | Pass | Fail |
|---|---|---|
| ci_runner.py executes | Runs without abort | Exits with error message |
| `causetrace-results.txt` uploaded | Artifact present in run | Artifact missing |
| Workflow completes | Steps run to completion | Workflow errors out |

### good_commit Resolution (pass/fail)

| Criterion | Pass | Fail |
|---|---|---|
| SHA returned | Non-empty SHA string | `resolve_good_commit` returned None |
| SHA is ancestor | `git merge-base --is-ancestor good bad` succeeds | investigate() ancestor check fails |
| SHA precedes bad_commit | good_commit in commit history before bad_commit | same SHA as bad_commit |

### Trace Extraction (pass/fail)

| Criterion | Pass | Fail |
|---|---|---|
| Trace returned | Non-empty string | `extract_trace_from_log` returned None → ci_runner aborts |
| Contains file paths | At least 1 file parsed from trace | "Files: (none extracted)" in output |
| Correct trace selected (S3) | Trace contains `validation/target.py` | Trace contains only stdlib paths |
| Single trace returned (S2) | One trace block, not concatenated | Multiple `Traceback` headers in extracted trace |

### Commit Window (pass/fail)

| Criterion | Pass | Fail |
|---|---|---|
| Correct window size (S1) | 1 | Any other value |
| Correct window size (S5) | 3 | Any other value |
| Causal commit in window | Expected causal SHA appears in ranked output | Causal SHA absent from all ranked candidates |

### End-to-End Attribution (informational — not blocking)

| Criterion | Result |
|---|---|
| S1: causal at rank #1 | Expected |
| S2: causal at rank #1 | Expected (two functions broken, one trace selected) |
| S3: causal at rank #1 | Expected |
| S4: any rank (shallow) | Acceptable — record actual rank, not pass/fail |
| S5: causal at rank #1 | Expected |

S4 attribution quality is **informational only**.  A wrong ranking for S4 is
not a validation failure — it documents a known architectural limitation
(shallow traces, see V5 Gap 3).

---

## 5. Failure Triage Priority

If the acquisition layer fails, investigate in this order.  Do not investigate
attribution quality until acquisition is confirmed working.

**Priority 1 — `resolve_good_commit` returns None**

Possible causes:
- `GITHUB_TOKEN` permissions insufficient for the Actions API
  - Check: `curl -H "Authorization: Bearer $GITHUB_TOKEN" "https://api.github.com/repos/azfar-05/cause-trace/actions/runs?status=success&per_page=1"` in the workflow step
- No prior successful run on this branch (first run problem)
  - Confirm: check workflow run history manually before running scenarios
- `GITHUB_WORKFLOW` env var not set or resolving to wrong workflow name
  - Debug: log `os.environ.get("GITHUB_WORKFLOW")` in ci_runner.py temporarily

**Priority 2 — `extract_trace_from_log` returns None**

Possible causes:
- pytest output format not recognized (no Traceback header, no `___` separator)
  - Debug: inspect `test-output.txt` artifact directly; check which patterns are present
- pytest running in a mode that suppresses traceback output (e.g., `--tb=no`)
  - Fix: ensure `--tb=short` or `--tb=long` is in the pytest command

**Priority 3 — ci_runner.py aborts on `good_commit == bad_commit`**

Possible cause:
- The workflow runs twice (push + pull_request trigger) and the second run
  queries the first run's passing SHA which happens to be the same commit
  - Fix: use only one trigger (`push` or `pull_request`, not both)

**Priority 4 — Shallow clone error**

Symptom: `git.exc.GitCommandError` or empty commit range
Cause: `fetch-depth: 0` missing or overridden by another workflow step
Fix: Confirm `fetch-depth: 0` is present in the `actions/checkout@v4` step

---

## 6. Execution Order

Run scenarios in this order.  Each scenario requires a green baseline before
execution.

```
Step 0:  Add validation/ package.  Confirm all tests pass.  Record green SHA.
         This is the good_commit baseline for S1–S4.

Step 1:  Run S1 (single targeted failure).
         If FAIL on acquisition: stop, diagnose Priority 1–2 issues.
         If PASS: restore green baseline, continue.

Step 2:  Run S4 (shallow trace).
         S4 is the simplest commit change (return wrong value, no raise).
         Running it second confirms trace extraction works for the
         pytest short format before introducing more complex log structures.
         Record attribution result (informational).
         Restore green baseline.

Step 3:  Run S2 (two failing tests).
         Confirms trace selection returns ONE trace when log has multiple.
         Restore green baseline.

Step 4:  Run S3 (non-repo trace first).
         Requires adding tests/test_noise.py and re-running with --tb=long.
         If trace selection picks the wrong trace: record failure, continue.
         Restore green baseline (remove test_noise.py).

Step 5:  Run S5 (window > 1).
         Requires pushing 3 commits in one git push.
         Confirm window size = 3 in the CauseTrace header.
         Confirm causal commit (B) ranks above noise commits (A, C).
```

**After all scenarios:**

Compile results for all 5 data collection checklists.  Evaluate against the
acquisition-layer success criteria.  Record any criterion that failed and the
observed behavior.

Attribution quality results (rank correctness) are secondary — record them but
evaluate them separately from acquisition correctness.

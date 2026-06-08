# CauseTrace: Live-Failure Observation Strategy

---

## Purpose

CauseTrace has a working CI/CD acquisition layer. The `ci_adapter.py` module resolves `good_commit` via the GitHub Actions API and extracts the stack trace from CI log output. Historical CI failures are an unreliable evaluation source — they reintroduce archaeology problems (absent boundaries, reconstructed traces, causal uncertainty) that the acquisition layer was designed to eliminate.

This document defines how CauseTrace observes and evaluates real failures in its natural operating environment. It is not an architecture document — no signals change here. The objective is to treat live CI failures as the primary evaluation source and accumulate enough observations to assess production reliability and identify which failure classes arise in practice.

---

## 1. Deployment Target

**CauseTrace's own repository and one active personal project.**

### Why two targets

A single target is insufficient. CauseTrace's own repository generates organic failures infrequently — the project is stable enough that regressions are rare. A single personal project generates higher failure volume but risks narrow signal coverage.

Two targets provide:
- **cause-trace repo**: Controlled, already instrumented, known file/function topology. Organic failures are rare but acquisition is clean.
- **One active personal project**: Higher volume, realistic development patterns, unknown topology. Generates the diversity needed to observe gap classes naturally.

### Constraints on the personal project

The target must:
- Be a Python project using pytest (current CauseTrace parser is Python-first)
- Be actively developed (at least a few commits per week)
- Have a GitHub Actions CI pipeline (or be willing to add one)
- Have a known-green baseline from which CauseTrace can resolve `good_commit`

The target must **not**:
- Be a project with predominantly configuration-only changes
- Have CI runs primarily triggered by documentation or tooling changes
- Contain a codebase where the majority of failures are dependency or environment issues

### Deployment steps

No new infrastructure. Two steps:

1. Copy `ci_runner.py`, `.github/workflows/causetrace.yml`, and `src/ci_adapter.py` into the personal project repository. Adjust `REPO_OWNER`, `REPO_NAME`, and `BRANCH` environment variables.
2. Confirm `resolve_good_commit` returns a non-None SHA on the first manual trigger.

Do not automate collection. Do not build a database. Record observations manually using the schema in Section 3.

---

## 2. Observation Window

**Collect 10 failures before drawing conclusions.**

### Justification

Five failures is insufficient — all could fall into the same gap class and produce a misleading picture. Twenty failures delays the feedback loop and provides diminishing returns if the first ten already reveal the dominant gap classes.

Ten failures strikes the right balance:
- Enough diversity to identify which documented gaps manifest naturally in practice
- Small enough to accumulate within 4–6 weeks of active development on a typical project
- Sufficient to assess acquisition layer reliability

**The count resets on acquisition errors.** A failure where `ci_runner.py` aborts without producing a ranking (because `resolve_good_commit` returned None or `extract_trace_from_log` returned None) is an acquisition failure, not an observation. Record it separately. The 10-failure count counts only runs where the full pipeline completed.

---

## 3. Data Collection Schema

For each observed failure, record the following fields. Store one record per failure in `data/live_observations.json` as a JSON array.

```json
{
  "id": "obs-001",
  "date": "YYYY-MM-DD",
  "repo": "cause-trace | <project-name>",

  "acquisition": {
    "status": "success | error",
    "error_reason": null,
    "good_commit": "<sha>",
    "bad_commit": "<sha>",
    "window_size": 1,
    "good_commit_source": "api | fallback | manual"
  },

  "trace": {
    "depth": 3,
    "contains_source_files": true,
    "files_parsed": ["src/scorer.py", "tests/test_scorer.py"],
    "functions_parsed": ["rank_commits", "test_rank_commits"],
    "has_line_numbers": true
  },

  "signals": {
    "file_overlap_fired": true,
    "function_signal_fired": true,
    "line_proximity_fired": true,
    "caller_callee_fired": false
  },

  "ranking": {
    "top_commit": "<sha>",
    "top_score": 34.2,
    "candidates_total": 3
  },

  "outcome": {
    "fix_commit": "<sha | null>",
    "fix_commit_rank": 1,
    "search_space_reduced": true,
    "causal_in_window": true,
    "notes": ""
  },

  "classification": {
    "failure_category": "code_regression",
    "gap_class": "3",
    "in_scope": true
  }
}
```

### Field definitions

**acquisition.status**: Whether `ci_runner.py` completed without aborting. `"error"` if `resolve_good_commit` returned None, `extract_trace_from_log` returned None, or an exception escaped the runner.

**acquisition.good_commit_source**: `"api"` if resolved via GitHub Actions API, `"fallback"` if resolved via local git heuristic, `"manual"` if overridden.

**trace.depth**: Number of frames in the extracted trace. A depth of 1 is a shallow trace (Gap 3 in `docs/benchmark_gaps.md`). Count only frames with file + line number.

**trace.contains_source_files**: False if the trace contains only test files (e.g. `tests/test_foo.py`) and no source files (e.g. `src/foo.py`). Shallow-trace condition where file overlap cannot fire against source files.

**signals.X_fired**: True if the signal contributed a non-zero score to the top-ranked commit. Do not record whether it fired for any commit — record whether it contributed to the top result.

**outcome.fix_commit**: The SHA of the commit that actually fixed the failure, if discovered. Set to null if the fix has not been applied yet or cannot be determined. Fill in after the fix lands.

**outcome.fix_commit_rank**: Where the fix commit ranked in CauseTrace's output. 1 means top-ranked. null if fix_commit is null or the fix commit was not in the window.

**outcome.search_space_reduced**: True if the fix commit ranked in the top 3 OR if the window was narrowed from N candidates to ≤3 by the ranking.

**classification.failure_category**: See Section 5. Use the most specific applicable category.

**classification.gap_class**: Which of the 10 documented gaps (see `docs/benchmark_gaps.md`) this failure most closely exercises. Use "none" if no gap class applies (clean, narrow-window case). Use a comma-separated list if multiple apply.

**classification.in_scope**: False if the failure is out of CauseTrace's operating scope (see Section 5).

---

## 4. Evaluation Methodology

Do not apply benchmark-style accuracy metrics to individual observations. A single wrong answer does not indicate a scoring defect; it may indicate an out-of-scope failure type, an acquisition boundary error, or expected behavior under signal-sparse conditions.

Evaluate across the full 10-failure corpus when collection is complete.

### Acquisition reliability

Criterion: `acquisition.status == "success"` in ≥8/10 observations.

If fewer than 8 succeed, the acquisition layer is not reliable enough for production use. Diagnose the dominant error reason (API auth, no prior green build, trace extraction failure) and treat it as a blocking finding.

### Search space reduction

Criterion: `outcome.search_space_reduced == true` in ≥6/10 in-scope observations.

This is the core operating claim. CauseTrace should reduce the search space to ≤3 candidates in at least 60% of in-scope cases. A lower rate indicates scoring behavior is not translating to the live environment.

Do not evaluate search space reduction for out-of-scope failures.

### Signal availability

For each observation, record which signals fired. After 10 observations, compute:
- What fraction had `trace.depth == 1` (shallow)?
- What fraction had `trace.contains_source_files == false`?
- What fraction had all three structural signals fire (file + function + line)?
- What fraction fired only file overlap (recency-dominated)?

This distribution tells you the signal density of real CI failures, not the density of curated benchmarks.

### Gap class coverage

After 10 observations, list which gap classes appeared. An unobserved gap class may mean:
- The gap is rare in this deployment environment (acceptable — revisit after more failures)
- The deployment target is too clean to exercise it (reconsider target selection)

An observed gap class where CauseTrace gave a wrong answer is a **learning event** — record the exact configuration and treat it as a candidate benchmark.

### Wrong answer analysis

For each observation where `fix_commit_rank > 1` (the fix commit did not rank first), document:
1. Which gap class was involved
2. Which signals fired for the top-ranked (wrong) commit
3. Which signals were absent for the fix commit
4. Whether the wrong answer was predictable from the documented gap analysis

A wrong answer predicted by the gap analysis (e.g. shallow trace + recency wins) is expected and confirms the gap is real in practice. A wrong answer not predicted by any documented gap is a new finding.

---

## 5. Failure Taxonomy

### In scope

**code_regression**: A change to source code introduced by a commit breaks behavior that was passing before. The trace points at source files, and the causal commit is in the window. This is CauseTrace's primary operating case.

**test_assertion_regression**: A change causes a test assertion to fail. The trace may be shallow (test file only, no source frames) — this maps to Gap 3. Still in scope; the causal commit is identifiable even if signals are sparse.

**dependency_version_regression**: The commit that updates a dependency version is in the window. The actual bug is in upstream code, but the commit introducing the version bump is a valid causal candidate. Partially in scope: CauseTrace can rank the bump commit, but line-level signals will not fire against upstream code.

### Out of scope

**configuration_issue**: The failure is caused by a change to CI YAML, `.env`, or build configuration, not to Python source. No stack trace points at source files. CauseTrace cannot operate without a source-referenced trace.

**ci_infrastructure_issue**: The failure is caused by a CI service outage, flaky network, resource limit, or test runner instability unrelated to any commit. There is no causal commit. Record these as out-of-scope and exclude from the 10-failure count.

**environment_drift**: The failure is caused by a Python version upgrade, OS library change, or container image change that was not captured in a commit. No commit in the window is causal. Out of scope.

### Boundary cases

A failure is **ambiguous** if you cannot determine whether it is code_regression or environment_drift within 15 minutes of investigation. Record it as `"failure_category": "ambiguous"` and mark `"in_scope": false`. Do not spend engineering time diagnosing out-of-scope or ambiguous failures for CauseTrace's benefit.

---

## 6. Success Criteria

Observation collection is complete when all three of the following are met:

### Criterion 1: Acquisition reliability

`acquisition.status == "success"` in ≥8/10 observations.

Failure on this criterion means the acquisition layer has a deployment gap that must be addressed before evaluation can proceed.

### Criterion 2: In-scope search space reduction

Among observations where `in_scope == true`, `search_space_reduced == true` in ≥6 of them.

This validates that CauseTrace's core operating claim holds in a live environment, not just on curated benchmarks.

### Criterion 3: Gap class documentation

At least one gap class from the documented gap analysis (`docs/benchmark_gaps.md`) was observed in the live failure set. The gap class is documented with a specific observed failure, its acquisition parameters, and its ranking outcome.

This criterion does not require a wrong answer — a correct ranking that matches a gap class configuration (e.g. a shallow trace that ranked correctly via recency) still validates the class as observable in practice.

---

When 10 qualifying observations are recorded in `data/live_observations.json` and Criteria 1–3 are evaluated, the dominant gap class distribution determines the next engineering objective. Do not determine the next direction on fewer than 10 observations.

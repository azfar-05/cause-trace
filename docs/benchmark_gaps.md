# CauseTrace — Benchmark Gap Analysis

**Date:** 2026-05-30
**Corpus:** 12 cases (post-removal of flask-app-line-984)
**Accuracy:** 12/12 top-1 (100%)

This document identifies classes of failures that the current corpus does NOT validate.
100% accuracy on 12 curated, narrow-window cases is not evidence of general correctness.
The gaps below describe where the scorer's behavior is unknown or likely to degrade.

---

## Gap 1 — Large Commit Windows with Hot-File Saturation

**Risk: High**

**Scenario:**
A regression window contains 30–100 commits. Multiple commits touch a high-churn file (e.g. `app.py`, `models.py`, `utils.py`) near the failure line. File overlap and line proximity fire at the same score for several commits. No commit in the window modifies the function named in the trace.

**Why it matters:**
This is a realistic and common investigation scenario — weekly sprints, release branches, hotfix windows after a long freeze. The only corpus case that exercised this pattern (flask-app-line-984) was removed as invalid. There is currently no valid case covering large-window behavior.

**Signals stressed:**
- Line proximity becomes a tie-creator rather than a discriminator when many commits touch the same file in the same region.
- Function signal is absent (the failure function is not in `modified_functions`), removing the primary discriminator.
- Recency becomes the de facto tiebreaker and may not correlate with causality.
- Narrower behavior at `min_candidates=15` with a large Tier 1 set is unvalidated.

**Known corpus blind spot:** The failure mode is entirely unrepresented. The scorer's behavior in this regime is unknown.

---

## Gap 2 — Adversarial Refactor Competing Against a Targeted Fix

**Risk: High**

**Scenario:**
A commit window contains (a) a large scope-expanding refactor (annotation pass, style sweep, API surface expansion) that incidentally overlaps many functions in the trace, and (b) a small targeted behavioral fix that is the actual cause. The refactor is not the culprit.

**Why it matters:**
Function score is computed as the sum of best-match scores over all failure functions, using a Cartesian product of (failure_functions × modified_functions). A commit that modifies 40 functions scores proportionally higher than one that modifies 2, even if the 2-function commit is more causally precise. The size penalty (`-sqrt(files) × 1.2`) grows too slowly to counteract this at scale.

Case 6 (requests-prepare-body-isinstance) demonstrates the inverse — the refactor IS the correct commit and wins with fn=42. But no case tests whether a refactor can incorrectly displace a targeted fix.

**Signals stressed:**
- Function score inflation via breadth accumulation.
- Size penalty effectiveness (currently unvalidated as a discriminator).
- Line proximity as the potential tiebreaker if both commits touch the same file.

**Known corpus blind spot:** Every case with a large-commit winner (Case 6) is correct by coincidence of ground truth. No case has an adversarial large commit as a wrong candidate.

---

## Gap 3 — Shallow Stack Traces (Single Frame)

**Risk: Medium**

**Scenario:**
The failure trace contains a single frame: one file, one function, one line. No call chain. This happens frequently in assertion errors, top-level script crashes, and certain test framework failures.

**Why it matters:**
All 12 current cases have multi-frame traces (2–4 frames, multiple files or functions). A single-frame trace provides minimal evidence: one file overlap candidate, one function, one line. Signal density collapses. In a window with multiple commits touching that file, the scorer is left with recency alone to discriminate.

**Signals stressed:**
- File overlap fires for all commits touching the single file equally.
- Function signal fires only if the one function is in `modified_functions` and not in the IGNORE list.
- Line proximity fires for at most one matching file.
- Recency is the dominant discriminator when all three structural signals saturate identically.

**Known corpus blind spot:** No single-frame trace in the corpus. Shallow-trace behavior is entirely unvalidated.

---

## Gap 4 — Causal Commit With No File Overlap in Trace

**Risk: Medium**

**Scenario:**
The failure surfaces in file A (present in the trace), but the root cause is in file B (not named in the trace). The causal commit modifies only file B. This happens when: an internal helper is broken, a dataclass/schema is changed, or a base class method is modified and a subclass in a different file raises.

**Why it matters:**
The narrower (Tier 1) filters commits that touch ≥1 trace file. A commit touching only file B would be excluded unless the recency fallback preserves it. With `min_candidates=15`, in a window of 30+ commits the causal commit may or may not survive depending on its recency rank among non-overlapping commits.

The structural call pair logic (`find_structural_call_pairs`) is bounded to the changed file and does not traverse imports or module boundaries. Cross-module causal attribution has no signal pathway.

**Signals stressed:**
- Narrower Tier 2 fallback behavior (untested at realistic window sizes).
- Partial match signal as a weak proxy for cross-module naming conventions.
- Absence of file, line, and function signals for the causal commit; recency-only attribution.

**Known corpus blind spot:** No case exercises this pattern. All cases have the causal commit touching at least one file named in the trace.

---

## Gap 5 — Signal Sparsity: File-Only Win Under Competition

**Risk: Medium**

**Scenario:**
The causal commit is identified only by file overlap (no function or line match). In a window with 5+ commits touching the same file, the scorer must rank the correct commit above competitors on file=7, recency only. The correct commit may not be the most recent.

**Why it matters:**
Case 8 (pytest-approx-timedelta-float-rel) demonstrates file-only attribution (score 9.51, file=7, no function/line). It passes because the window contains only 4 commits and the correct commit has strong recency. This is a clean window that masks the fragility. A window with 10 commits all touching `python_api.py` would be indistinguishable under this signal profile.

**Signals stressed:**
- File overlap as the sole discriminating signal is insufficient under competition.
- Recency bias is unchecked — any recent commit touching the right file would outscore the correct commit if the correct commit is older.

**Known corpus blind spot:** Case 8 passes for the right reason in a clean window. The same failure mode under competitive conditions is unvalidated.

---

## Gap 6 — Competing Commits With Identical Signal Profiles

**Risk: Medium**

**Scenario:**
Two or more commits in the window touch the same file, modify the same function, and fall within ±5 lines of the failure line. All three structural signals fire identically. Ground truth is the older commit, but recency ranks the newer one first.

**Why it matters:**
Case 9 (werkzeug-headers-str-internal-list) has two annotation commits touching the same file — a near-twin scenario. Line proximity differentiates them (only the causal commit touches line 543). But the case depends on line proximity breaking the tie. If both commits touched the same line region, the scorer would be unable to distinguish them.

**Signals stressed:**
- Tie-breaking when file=7, fn=8, line=10 are identical for two commits.
- Sort stability: the matcher sorts by `(score, timestamp)` descending, so the more recent commit wins all ties. This is undocumented behavior and may be wrong.

**Known corpus blind spot:** No case has full signal-profile collision between a causal and a competing commit. Tie-breaking behavior is untested.

---

## Gap 7 — Deep Call Chain Propagation (>1 Hop)

**Risk: Medium**

**Scenario:**
The failure is triggered 3+ hops away from the modified function. The trace shows the intermediate callers (B, C, D) but not the causal function (A). The commit modifies A. No direct name match exists between modified functions and trace functions.

**Why it matters:**
`find_structural_call_pairs` identifies caller-callee pairs within a single file and at one hop. It does not follow chains. A regression where `A` is broken and the trace shows `D → C → B` (A not visible) would produce zero caller-callee signal.

Cases 2, 3, 11, 12 all demonstrate single-hop caller-callee attribution correctly. Multi-hop propagation is structurally impossible under the current implementation.

**Signals stressed:**
- Caller-callee signal is bounded at one hop. Two-hop propagation produces zero signal.
- File overlap may fire if the causal file also contains one of the trace functions, but this is coincidental.

**Known corpus blind spot:** All caller-callee cases are one-hop. Multi-hop propagation is unrepresented and would silently fail.

---

## Gap 8 — Rename or Move as the Causal Change

**Risk: Low–Medium**

**Scenario:**
The causal commit renames a function (e.g. `dispatch_request` → `handle_request`) or moves a file. The old name appears in existing code that calls it; the trace references the old name. The commit's `modified_functions` contains the new name only.

**Why it matters:**
`extract_modified_functions_from_patch` scans for `def function_name(` in the diff. A rename produces a `def new_name(` on `+` lines and `def old_name(` on `-` lines. The `-` line is not captured (only `+` lines are attributed to `current_function`). The old name is never added to `modified_functions`. The function signal cannot fire.

**Signals stressed:**
- Function signal: would fire on the new name, which may not appear in the trace.
- Line proximity: may fire if the def line is near the failure line.
- Partial match: may fire if old and new names share a 12-character prefix.

**Known corpus blind spot:** No rename case in the corpus. Silent failure mode for this common refactor pattern.

---

## Gap 9 — Weak or Absent Line Numbers in Trace

**Risk: Low–Medium**

**Scenario:**
The stack trace provides file names but no line numbers. This occurs with minified JS, some C extensions, certain Python tracebacks that suppress line info, or manually constructed traces.

**Why it matters:**
Line proximity contributes +10 per matched file — the largest single signal weight in the system. Without line numbers, every case reduces to file + function + recency. The scorer has no tested baseline for this degraded mode under competitive conditions.

**Signals stressed:**
- Line proximity: silently returns 0 for all commits. No indication in output that it is unavailable.
- Score distribution compresses; margins between candidates narrow.
- Recency weight (up to 5.0) becomes more dominant relative to remaining structural signals.

**Known corpus blind spot:** All 12 cases have line numbers. Lineless trace behavior is unvalidated.

---

## Gap 10 — Multi-Commit Causality (Compound Regression)

**Risk: Low**

**Scenario:**
The regression requires two commits together to manifest. Commit A changes a data structure; Commit B changes the consumer. Either alone is benign; both together break behavior. There is no single causal commit.

**Why it matters:**
CauseTrace is designed to identify a single causal commit. The ranking model has no representation for compound causality. In a corpus that only contains single-commit regressions, this failure mode is invisible.

**Signals stressed:**
- All signals are designed for single-commit attribution. No signal captures joint causality.
- The top-1 result will be the commit that individually scores highest, which may be either A or B or neither.

**Known corpus blind spot:** No compound regression in the corpus. The system's behavior in this regime is unknown by design.

---

## Summary Table

| Gap | Risk | Primary Signal at Risk | Corpus Cases |
|-----|------|----------------------|--------------|
| 1. Large windows / hot-file saturation | **High** | Line, function, recency | 0 |
| 2. Adversarial refactor vs. targeted fix | **High** | Function (inflation), size penalty | 0 |
| 3. Shallow trace (single frame) | Medium | File, recency | 0 |
| 4. Causal commit outside trace files | Medium | Narrower Tier 2, partial match | 0 |
| 5. File-only win under competition | Medium | File, recency | 1 (clean window only) |
| 6. Identical signal profiles / tie-breaking | Medium | Sort stability, recency | 0 |
| 7. Deep call chain (>1 hop) | Medium | Caller-callee | 0 |
| 8. Rename/move as causal change | Low–Med | Function extraction | 0 |
| 9. No line numbers in trace | Low–Med | Line proximity | 0 |
| 10. Compound regression (2+ commits) | Low | All (by design) | 0 |

The corpus exercises the scorer well within the class of clean, narrow-window, three-signal convergence cases.
Outside that class, behavior is largely unknown.

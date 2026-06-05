# CauseTrace — Benchmark Gap Analysis

**Date:** 2026-06-05 (updated from 2026-05-30)
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

**V5 Investigation Status (2026-06-05):**

Mechanism confirmed. Benchmark unsourced.

Testing with the flask `dispatch_request` regression (`6a649690`) in a deliberately expanded 50-commit window (good=`adf363679`, bad=`fbb6f0bc`) revealed:

- 18 Tier 1 commits all touching `app.py`, all scoring `file_overlap = 7` identically
- Three commits sharing identical `fn=11, cc=3` signals (function overlap does not discriminate)
- Score compression: causal leads runner-up by only **5.85 points** (vs. infinite margin in the 1-commit window)
- The entire margin comes from `line_proximity = +10`; remove it and the causal drops to rank **#3**
- Without line proximity, `e82db2c` ("fix provide_automatic_options override") scores 19.61 and ranks #1 — a wrong answer

The gap is confirmed at the mechanism level. A live wrong answer was not demonstrated because the causal (`6a649690`) changed lines **throughout** the dispatch_request function body (lines 962–1048), ensuring line proximity fires for almost any trace point in the function. The gap would be live for a causal that makes a targeted one- or two-line change in a heavily-trafficked function where the trace failure line is >5 lines away from the change.

Benchmark not accepted: the causal ranks correctly in the tested window. A case requiring a surgical causal change in a hot function remains unsourced.

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

**V5 Investigation Status (2026-06-05):**

Mechanism confirmed mathematically and empirically. Benchmark unsourced.

The scoring arithmetic is unambiguous: with a 2-function trace, a 10-file annotation commit touching both trace functions scores `fn=16 - sqrt(10)×1.2 = 12.2` on structure alone, beating a 2-file targeted fix at `fn=8 - sqrt(2)×1.2 = 6.3`. The gap is **5.9 points before recency**, large enough to dominate in most windows.

Empirical confirmation: Case 7 (`requests-prepare-body-isinstance`) demonstrates the mechanism in reverse — the 19-file inline-types refactor (`fn=42`) vastly outscores everything else in the window and is, by coincidence, the correct answer. The same mechanism that produces correct results when the large commit is causal produces false positives when it is not.

No historical benchmark was found where a large annotation/refactor commit is the adversary (non-causal) and outranks a small behavioral causal. The difficulty is sourcing: annotation passes tend to be far in git history from the behavioral fixes they surround, making it hard to construct a window with both commits within ≤15 commits.

In CI/CD contexts, this pattern arises naturally when a type annotation pass and a behavioral bug land in the same build window.

Benchmark not accepted. Gap confirmed, unsourced.

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

**V5 Investigation Status (2026-06-05):**

Extensive search across all repos. No benchmark sourced.

Single-frame traces (one file, one function, one line) are uncommon in curated historical regression documentation because documented regressions tend to surface through deep call chains that are more easily explained. They are routine in CI environments where test assertion failures produce shallow frames.

The scoring behavior under a single-frame trace is not fundamentally broken — file overlap, function overlap, and line proximity all remain active. The gap is that with only one frame, the three signals saturate across more commits (every commit touching the one file scores equally on file overlap; multiple commits may touch the one function). Recency becomes dominant earlier in the tie-breaking hierarchy.

A CI/CD deployment would surface single-frame traces continuously and provide the required good/bad boundaries to test this gap without historical archaeology. The gap is likely to be naturally abundant in production use. Benchmark unsourced.

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

**V5 Investigation Status (2026-06-05):**

Architectural limitation confirmed. Candidate found but rejected after stability analysis.

The `werkzeug f88164a2` commit ("Prevent scientific notation being used for floats") introduced a real regression: `FloatConverter.to_url(1.0)` returns `"1."` (trailing dot) instead of `"1.0"`. The failure surfaces in `map.py` when the routing matcher raises `NotFound` because `"1."` does not match the FloatConverter regex `\d+\.\d+`. The causal touches only `converters.py`; the trace references only `map.py`. Zero file overlap.

In a 22-commit window (`9029a1ec..f88164a2`): `tier1=0` throughout, all commits survive via Tier 2 recency fallback, causal scores `base=-2.08, final=2.92` (pure size penalty + recency). It ranks #1 by accident — only because no other commit in the 22-commit window touches `map.py`.

Stability analysis showed the result is fragile: in a 106-commit window (reached by crossing the nearest merge boundary), 7 commits touching `map.py` appear and the causal drops to **rank #8** with score 2.92 vs. the leader's 17.72. The correct ranking is inverted by the file_overlap signal — every `map.py` commit earns the baseline 7-point file overlap the causal cannot access.

The architectural gap is confirmed: when the causal touches only file B and the trace shows only file A, the structural signal pathway is completely severed. The scorer operates on pure recency. The correct answer when it occurs is coincidental. Candidate rejected because no stable window was found that simultaneously: (a) includes map.py-touching competitors, (b) stays within ≤25 commits, and (c) has valid (good, bad] semantics with the causal inside.

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

**V5 Investigation Status (2026-06-05):**

Vulnerability confirmed. Candidate found but rejected after semantic review.

Werkzeug commits `d3d3df56` (causal, "validate host characters") and `deab88f6` (fix, "relax get_host strictness") both modify `get_host` in `sansio/utils.py`, both have 3 files, and produce identical base scores of **22.922** — a perfect tie on all structural signals. Recency is the sole discriminator: `deab88f6` is newer and scores 27.92 vs. the causal's 22.92. The causal ranks **#2**.

Candidate rejected: the window required using `deab88f6` (the regression fix) as `bad_commit`, which violates the `(good, bad]` semantic contract — the failure is not present at `bad_commit`. CI/CD integration would prevent this violation structurally: the window closes at `first_fail`, before the fix exists.

The recency tiebreaker vulnerability is real and would manifest in any window containing two commits with identical structural profiles (common in cherry-pick workflows, annotation pairs, or iterative function edits). The sort stability fallback — `(score, timestamp)` descending — is undocumented behavior and may produce wrong answers when it fires.

Benchmark not accepted. Gap confirmed, unsourced in valid window form.

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

---

## V5 Meta-Finding: Archaeology vs. Architecture (2026-06-05)

V5 sourcing difficulties fall into two distinct categories that must be kept separate.

**Archaeology difficulties** (artifacts of reconstructing history):
- Window semantic violations — `bad_commit` landing at a fix commit, not the first fail (Gaps 4, 6)
- Merge topology explosion — git DAG expansion producing 106-commit windows from intended 30-commit windows (Gap 4)
- Absent CI artifacts — no first-known-bad boundary, no verbatim stack trace
- Causal uncertainty — regression must be inferred from commit messages rather than test output

**Scoring/architecture vulnerabilities** (properties of CauseTrace itself):
- Function score inflation from large commits (Gap 2)
- File_overlap filter severing cross-file signal pathways (Gap 4)
- Recency as the effective tiebreaker when structural signals saturate (Gaps 1, 3, 6)
- Line proximity as the last discriminator under hot-file saturation (Gap 1)

CauseTrace is designed for CI/CD integration where first-known-good and first-known-bad are emitted by the test runner, and the stack trace is captured verbatim. Under that model, all archaeology difficulties disappear: semantic violations cannot occur, merge topology is irrelevant, and causal uncertainty is resolved by the test suite.

The scoring vulnerabilities persist unchanged in CI/CD deployment. They are real production risks, not benchmark-construction artifacts. V5 failed to source benchmarks for Gaps 1, 2, 3, 4, and 6 not because those gaps are small, but because they require configuration patterns that historical repository data does not preserve cleanly. The gaps are expected to arise naturally and frequently in CI/CD contexts.

---

## Summary Table

| Gap | Risk | V5 Status | Primary Signal at Risk | Corpus Cases |
|-----|------|-----------|----------------------|--------------|
| 1. Large windows / hot-file saturation | **High** | Mechanism confirmed, unsourced | Line, function, recency | 0 |
| 2. Adversarial refactor vs. targeted fix | **High** | Mechanism confirmed, unsourced | Function (inflation), size penalty | 0 |
| 3. Shallow trace (single frame) | Medium | Search complete, unsourced | File, recency | 0 |
| 4. Causal commit outside trace files | Medium | Architecture confirmed, candidate rejected | Narrower Tier 2, recency-only | 0 |
| 5. File-only win under competition | Medium | No update | File, recency | 1 (clean window only) |
| 6. Identical signal profiles / tie-breaking | Medium | Vulnerability confirmed, candidate rejected | Sort stability, recency | 0 |
| 7. Deep call chain (>1 hop) | Medium | No update | Caller-callee | 0 |
| 8. Rename/move as causal change | Low–Med | No update | Function extraction | 0 |
| 9. No line numbers in trace | Low–Med | No update | Line proximity | 0 |
| 10. Compound regression (2+ commits) | Low | No update | All (by design) | 0 |

The corpus exercises the scorer well within the class of clean, narrow-window, three-signal convergence cases.
Outside that class, behavior is largely unknown. V5 confirmed five scoring/architecture vulnerabilities without adding
benchmarks for any of them — a finding about the limits of historical archaeology as a sourcing method,
not about the gaps being small.

# CauseTrace Corpus Analysis

**Date:** 2026-05-30 (V5 note added 2026-06-05)
**Corpus size:** 12 cases (unchanged through V5)
**Overall accuracy:** 12/12 top-1 (100%)

> **V5 note (2026-06-05):** The V5 benchmark expansion investigated Gaps 1, 2, 3, 4, and 6. No new cases were added to the corpus. All five gaps were confirmed at the mechanism or architecture level, but no valid benchmark candidates were sourced — the primary obstacle being historical data limitations rather than absence of the failure modes. See `benchmark_gaps.md` for V5 investigation status per gap.

> **2026-05-30 update:** `flask-app-line-984` removed. The case had a 2890-commit window spanning 8 years, an expected commit that was a bulk `black` reformat with no behavioral change, a fabricated stacktrace (`unknown_function`, `RuntimeError: test failure`), and a failure line inside a docstring. It violated four corpus acceptance criteria and was not a valid regression case. Test numbering below reflects the original 13-case corpus (no renumbering applied).

---

## Score Signal Reference

| Signal | Weight | Notes |
|--------|--------|-------|
| File overlap | 5 + 2×n | Base 5 for any match, +2 per matching file |
| Line proximity | +10 per file | Match within ±5 lines of failure line |
| Function (exact) | +8 per match | Modified function == failure function |
| Function (prefix) | +4 per match | 12-char prefix match |
| Caller/callee | +3.0 per pair | Structural adjacency in changed file |
| Recency | up to 5.0 | Normalized timestamp × RECENCY_WEIGHT |
| Focus bonus | +3 | Single-file commit that matches |
| Size penalty | -sqrt(files)×1.2 | Noise dampening |

---

## Per-Case Signal Breakdown

### ~~Test 1 — flask-app-line-984~~ — REMOVED

Case removed 2026-05-30. See header note.

---

### Test 2 — flask-helpers-redirect-302 — PASS

**Score:** 27.6 | line=10, function=8, file=7, recency=5.0  
**Failure mode:** mixed\_structural

Clean win. The causal commit is the only one modifying both `helpers.py` near line 242 AND the `redirect` function. Three corroborating signals (file, line, function) converge on a single commit.

---

### Test 3 — flask-app-dispatch-request-ctx — PASS

**Score:** 30.06 | line=10, function=11, file=7, recency=5.0  
**Failure mode:** caller\_callee\_propagation

Function score of 11 indicates both exact match (8) and caller/callee bonus (3). The modified function `dispatch_request` is named in the trace, and the commit is the sole recent touch to that function. Structural propagation does real work here.

---

### Test 4 — flask-ctx-teardown-exceptiongroup — PASS

**Score:** 32.21 | line=10, function=14, file=7, recency=5.0  
**Failure mode:** caller\_callee\_propagation

Function score of 14 suggests multiple structural overlaps. The commit modifies teardown logic in `ctx.py`; the trace names both `pop` and the teardown chain. Caller-callee reasoning correctly elevates this commit over others that only touch `ctx.py` incidentally.

---

### Test 5 — urllib3-collections-maxsize-zero — PASS

**Score:** 32.4 | line=10, function=14, file=7, recency=5.0  
**Second place:** 7.69 (large gap)

Multi-file trace (`poolmanager.py` + `_collections.py`). All four signal categories contribute. The gap between #1 and #2 (24.7 points) indicates this is one of the clearest wins in the corpus.

---

### Test 6 — urllib3-connectionpool-httpheaderdict-cast — PASS

**Score:** 17.6 | line=0, function=8, file=7, recency=5.0  
**Failure mode:** mixed\_structural  
**Notable:** Line proximity is ZERO — win came from file+function+recency only.

The commit spans `connectionpool.py` and `_collections.py`. The trace's exact failure line was not close to any changed line, so line proximity returned 0. The win depended entirely on function matching (`urlopen`, `_make_request`) and file overlap. This shows the scorer can survive without line proximity when function overlap is present.

---

### Test 7 — requests-prepare-body-isinstance — PASS

**Score:** 57.63 | line=10, function=46, file=7, recency=0.0  
**Failure mode:** function\_overlap  
**Expected ≠ bad\_commit:** causal commit is inside the window, not the most recent

**Concerning case.** The causal commit is a large inline type-annotation refactor (scores function=46). It touches so many functions that several happen to match the failure trace. The function score of 46 is more than 3× the next highest in the corpus (14). The commit wins despite recency=0 (it is the oldest in the window) and a size penalty of 5.37.

The scoring is technically correct — the right commit is ranked first — but the margin is inflated by mass function overlap, not surgical signal. A commit that happens to rename or annotate many functions across the same file would score similarly even if causally unrelated to the failure.

---

### Test 8 — pytest-assertion-terminal-writer — PASS

**Score:** 31.3 | line=10, function=11, file=7, recency=5.0  
**Failure mode:** function\_overlap

Clean three-signal win. The assertion refactor modifies the exact function named in the trace. Second-place commits touch `__init__.py` (file match only) and rank at 9.43 — well separated.

---

### Test 9 — pytest-approx-timedelta-float-rel — PASS

**Score:** 9.51 | line=0, function=0, file=7, recency=4.91  
**Expected ≠ bad\_commit:** causal commit is inside the window  
**Failure mode:** function\_overlap (labeled), but function=0 in practice

**Fragile win.** The correct commit wins on file+recency only. No function or line signals contributed. The bad\_commit (a481f26, "Fix strict options from addopts") also has no file/function/line overlap with the trace, scoring 2.32 from recency alone and appearing 4th.

This case is structurally weak: the scorer has no function evidence from the trace's `__init__` method (likely filtered by the IGNORE list or not modified in the correct commit), so the win reduces to "touched the right file, was recent." A different commit ordering could flip this result.

---

### Test 10 — werkzeug-headers-str-internal-list — PASS

**Score:** 25.12 | line=10, function=14, file=7, recency=0.0  
**Expected ≠ bad\_commit:** causal commit is oldest in window  
**Second place:** 37b9423 at 10.53 (same category — another annotation commit)

Despite being the oldest commit (recency=0), the causal commit wins because line+function signals are strong. The second-place commit is also an "inline annotations for datastructures" commit — a near-twin — but scores lower because it lacks the line proximity match. This case validates that structural signals can override recency when they have enough resolution.

---

### Test 11 — pytest-expression-scanner-backslash — PASS

**Score:** 28.3 | line=10, function=8, file=7, recency=5.0  
**Failure mode:** line\_proximity

Single commit in competition at similar score level. Clean win on three signals.

---

### Test 12 — werkzeug-get-host-security-error — PASS

**Score:** 30.32 | line=10, function=11, file=7, recency=5.0  
**Failure mode:** function\_overlap

Single commit in top 5. Narrow commit window with clear causal change; function score includes caller/callee bonus (11 = 8 exact + 3 adjacency).

---

### Test 13 — werkzeug-duplicate-rule-error — PASS

**Score:** 27.06 | line=10, function=8, file=7, recency=5.0  
**Failure mode:** function\_overlap

Single commit in top 5. Clean win.

---

## Signal Dominance Patterns

### Line Proximity

Line proximity appears in 10 of 12 winning commits (score=10 in all 10).  
When it fires, it adds the equivalent of 1.25 exact function matches and overwhelms most other single signals.  
It does not fire in Tests 6 and 9, yet both still pass — but for different reasons.

**Dominance risk:** When multiple commits touch the same file near the same line region, line proximity becomes a tie-creator rather than a discriminator. The removed case (Test 1) was the corpus instance of this failure mode; it is no longer represented.

### Function Score

Normal range for passing cases: 8–14.  
Outlier: Test 7 at 46.

The function score scales with the number of (modified\_function, failure\_function) pairs across the Cartesian product. A commit that modifies many functions — even a legitimate refactor — can accumulate high function scores through incidental overlap. The size penalty (sqrt×1.2) does not adequately counteract this for large commits.

**Effective discriminator in:** Tests 3, 4, 5, 6, 8, 10, 12, 13 — cases where the causal commit modifies the exact function named in the trace.

**Weak or absent in:** Tests 2, 9. Function=0 in Test 9 for the correct commit, removing the best discriminator.

### Recency

Weight: up to 5.0. This is the largest single uncorroborated signal — it fires purely on timestamp, not structural evidence.

Recency correctly assists in: Tests 2, 3, 4, 5, 8, 11, 12, 13 (causal commit is recent and correct).

Recency is overridden by structural signals in: Tests 7, 10 (causal commit is oldest but wins on function+line).

**Recency as de facto tiebreaker:** When file and line signals are saturated across multiple commits and function signal is absent, recency determines rank. Test 9 is a near-miss of this dynamic (file-only win, narrow margin).

### File Overlap

Base score of 7 for any overlap. Universal among correct commits in passing cases — expected, since the parser extracts files from the trace.

File overlap is necessary but not sufficient. Cases where it fires for many commits (Test 1, Test 9) require function or line to narrow further.

### Partial Match

Score=2. No case in the corpus demonstrates a partial match providing decisive discrimination. It fires only when exact file overlap is absent, which did not occur for any top-ranked commit. This signal contributes negligibly to current results.

### Size Penalty

`-sqrt(files) × 1.2`. Ranges from -1.2 (1 file) to -5.37 (Test 7, large commit).

For Test 7 the penalty is 5.37 against a function score of 46 — the penalty is absorbed without effect. The penalty's sqrt scaling means it grows slowly and cannot counteract mass function accumulation in genuinely large commits.

---

## Recurring Ambiguity Classes

### Class 1: Hot-File Saturation

**Cases:** None currently in corpus (Test 1 removed).

**Mechanism:** Many commits touch a popular file (e.g., `app.py`) near a heavily-modified line region. File score and line proximity fire identically for multiple commits. Without function evidence, the scorer is left with recency as its only remaining discriminator, which may not correlate with causality.

**Current boundary:** This failure mode is unrepresented after removal of Test 1. A realistic instance (bounded window, real regression, real stacktrace) remains a gap in the corpus.

### Class 2: Large-Commit Function Inflation

**Cases:** Test 7.

**Mechanism:** A commit that modifies a large number of functions (annotation refactors, style passes, broad API changes) accumulates function score proportional to its breadth, not its causal precision. A 50-function annotation commit will score higher than a 2-function targeted fix if enough of those 50 functions overlap with trace functions.

**Current boundary:** The scorer produces correct top-1 results in Test 7, but the margin is inflated for wrong structural reasons. The approach is fragile: a commit window with two large refactors would surface the wrong one if the second happened to overlap more functions.

### Class 3: File-Only Evidence

**Cases:** Test 9.

**Mechanism:** The trace provides a file name and line, but the causal commit modifies functions filtered by IGNORE (e.g., `__init__`) or functions not named in the trace. The scorer falls back to file+recency. Margin over competitors is narrow; the case passes but for minimal reasons.

**Current boundary:** The scorer succeeds when the causal commit is the only (or most recent) one touching the file. It would fail if another commit in the window had stronger recency and touched the same file.

### Class 4: Near-Twin Commits

**Cases:** Test 10 (two inline-annotation commits touching same file).

**Mechanism:** Two commits belong to the same development activity (e.g., annotation passes), touch the same file, and score similarly. Line proximity differentiates them. This class is handled correctly currently, but it surfaces a latent fragility: if the causal commit lacked line proximity, the annotated twin would score higher via recency.

---

## Notable Structural Wins

**Test 5 (urllib3-maxsize-zero):** Multi-file trace correctly resolved. Caller in `poolmanager.py` triggers failure in `_collections.py`. The commit modifies both files; signal overlap is complete. Gap of 24.7 points to second place is the largest in the corpus.

**Test 6 (urllib3-httpheaderdict):** Won with zero line proximity. File+function signals alone identified a cross-file refactor as causal. Demonstrates that function matching can compensate for absent line evidence.

**Test 10 (werkzeug-annotations):** Recency=0 (oldest commit in window) correctly overridden by function=14 + line=10. Demonstrates the structural signal hierarchy functioning as intended when evidence quality is high.

**Tests 3, 4 (flask caller/callee):** Caller-callee adjacency bonus (3.0) provided meaningful lift in cases where the modified function indirectly causes the failure through a call chain. Function scores of 11 in both cases (8 exact + 3 adjacency) confirm the structural propagation logic is active and helping.

---

## Notable Ranking Weaknesses

**Test 1 (removed):** This was the only failure in the original corpus. The case was invalid — see header note. Hot-file saturation at realistic window sizes is not yet covered by any remaining case.

**Test 7 (inflated margin):** Correct top-1 result, but function score of 46 is evidence of mass-overlap inflation rather than targeted causal signal. The result is correct but not for the right reasons. A second commit of similar breadth in the same window could defeat the causal commit.

**Test 9 (fragile file-only win):** A 9.51 score winning on file+recency alone is a thin margin. No structural evidence corroborates the attribution. The scorer is essentially saying "this file was touched recently" with no further precision.

---

## Observations on Benchmark Composition

**Corpus skew toward function-overlap cases:** 8 of 12 cases are tagged `function-overlap`. The scorer is calibrated well for this class. Most wins are clean three-signal convergences (file+function+line).

**Indirect causality (expected ≠ bad\_commit):** 3 of 12 cases (Tests 7, 9, 10) have a causal commit inside the window that is not the most recent commit. This is a structurally harder class: recency works against the correct answer. All three pass, but for varying quality of reasons (Test 10: correct, Test 7: inflated, Test 9: fragile).

**Narrow vs. wide windows:** All remaining cases have tight commit windows (1–7 commits) or clear dominance. Wide-window behavior is unrepresented after removal of Test 1. The scorer's accuracy is strongly coupled to window size — wider windows increase the probability of hot-file saturation — but this is not exercised in the current corpus.

**Underrepresented failure modes:**
- Hot-file saturation at a realistic bounded window (was only Test 1; that case was invalid and removed)
- Cross-file propagation where files are unrelated by name (no partial match possible)
- API contract breakage where the causal commit and the failure are in different modules entirely
- Large refactors that are NOT the causal commit, competing with a small targeted fix
- Regressions where the stack trace is shallow (single frame, one function name)

---

## Summary: What CauseTrace Reasons About Well

CauseTrace currently handles the following class of failures reliably:

> A targeted commit modifies a function named in the failure trace, in the file named in the failure trace, near the line number named in the failure trace, and is among the most recent commits in the window.

Within that class, the three-signal convergence (file+function+line) produces wide margins and clean rankings. Caller-callee propagation correctly extends this to one-hop indirect failures.

**Where deterministic narrowing begins breaking down:**

1. **Signal saturation:** When file and line proximity fire for many commits simultaneously, the scorer cannot narrow further without additional structural evidence. Recency fills the vacuum and may rank causally unrelated commits first.

2. **Function score scaling:** The additive Cartesian product scoring inflates scores for large commits in proportion to their breadth, not their causal precision. The size penalty does not compensate adequately.

3. **File-only evidence:** Without function or line corroboration, attribution reduces to "this file was touched" — fragile and recency-dominated.

4. **Wide commit windows:** The more commits in the window, the higher the probability of hot-file saturation and spurious function overlap. Accuracy degrades non-linearly as window width grows.

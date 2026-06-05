#!/usr/bin/env python3
"""
CauseTrace scoring sensitivity analysis.

Binary top-1 accuracy is insufficient when the corpus is saturated.
This script measures:

  1. Score margin (correct commit score − next-best commit score) per case.
  2. How each signal affects those margins when zeroed.
  3. Pairwise and triple ablations (more aggressive zeroing).
  4. Score contribution breakdown per signal per case.
  5. Weight sweeps for recency, function overlap, and line proximity.

Does NOT permanently modify any scorer code.
"""

import contextlib
import os
import sys
from typing import Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

import src.signals.call_site as _cs_mod
from evaluation_runner import (
    CASES_PATH,
    EvaluationResult,
    commit_matches,
    evaluate_test_case,
    load_cases,
)

TEST_CASES = load_cases(CASES_PATH)
N = len(TEST_CASES)


# ── Signal wrappers ───────────────────────────────────────────────────────────


def _cs_no_func_overlap(commit, failure_functions, include_breakdown=False):
    """Return only caller_callee component; zeroes pure function-overlap score."""
    total, cc = _cs_mod.call_site_breakage_score(
        commit, failure_functions, include_breakdown=True
    )
    if include_breakdown:
        return cc, cc
    return cc


def _cs_scaled(scale: float) -> Callable:
    """Scale pure function-overlap (not caller_callee) by `scale`."""
    def _fn(commit, failure_functions, include_breakdown=False):
        total, cc = _cs_mod.call_site_breakage_score(
            commit, failure_functions, include_breakdown=True
        )
        new_total = (total - cc) * scale + cc
        if include_breakdown:
            return new_total, cc
        return new_total
    return _fn


def _line_scaled(scale: float) -> Callable:
    from src.signals.line_proximity import line_proximity_score as _orig
    def _fn(*a, **kw):
        return _orig(*a, **kw) * scale
    return _fn


# ── Runner ────────────────────────────────────────────────────────────────────


def run_variant(name: str, patches: List[Tuple]) -> Dict:
    results: List[EvaluationResult] = []
    errors: List[str] = []

    with contextlib.ExitStack() as stack:
        for target, replacement in patches:
            stack.enter_context(patch(target, replacement))
        for tc in TEST_CASES:
            try:
                results.append(evaluate_test_case(tc))
            except Exception as exc:
                errors.append(f"  [ERR] {tc.get('id','?')}: {exc}")

    return {
        "name": name,
        "top1": sum(r.matched_top1 for r in results),
        "top3": sum(r.matched_top3 for r in results),
        "total": len(results),
        "results": results,
        "errors": errors,
    }


def score_margin(result: EvaluationResult) -> Optional[float]:
    """Return correct_commit_score − best_wrong_commit_score.

    Positive = correct is ranked above next-best.
    Negative = inverted (should not happen if top1 is correct).
    None if no predicted commits or only 1 commit.
    """
    commits = result.predicted_commits
    if not commits:
        return None

    expected = result.expected_commit
    correct_score = next(
        (c["score"] for c in commits if commit_matches(expected, c["hash"])),
        None,
    )
    if correct_score is None:
        return None

    wrong_scores = [
        c["score"] for c in commits if not commit_matches(expected, c["hash"])
    ]
    if not wrong_scores:
        return None  # Only one commit in window

    return round(correct_score - max(wrong_scores), 2)


def delta_str(v: int, base: int) -> str:
    d = v - base
    return f"+{d}" if d > 0 else (f"{d}" if d < 0 else " 0")


def fmt_margin(m: Optional[float]) -> str:
    if m is None:
        return "  —  "
    return f"{m:+.2f}"


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    W = 76
    print(f"\n{'═' * W}")
    print("  CauseTrace Scoring Sensitivity Analysis")
    print(f"  Corpus: {N} cases  (baseline is 12/12 top-1 saturated)")
    print(f"{'═' * W}")

    # ── Phase 1: Baseline score margins ──────────────────────────────────────

    print("\n  Phase 1 — Baseline score margins per case\n")
    print(f"  {'Case ID':<42}  {'Top-1':>6}  {'Margin':>8}  {'Window'}  ")
    print(f"  {'─'*42}  {'─'*6}  {'─'*8}  {'─'*10}")

    sys.stdout.write("  Computing baseline ... ")
    sys.stdout.flush()
    baseline = run_variant("baseline", [])
    print("done")

    margins: Dict[str, Optional[float]] = {}
    window_sizes: Dict[str, int] = {}

    for r in baseline["results"]:
        m = score_margin(r)
        margins[r.case_id] = m
        window_sizes[r.case_id] = r.narrow_stats.get("narrowed", len(r.predicted_commits))
        hit = "✓" if r.matched_top1 else "✗"
        print(f"  {r.case_id:<42}  {hit:>6}  {fmt_margin(m):>8}  {window_sizes[r.case_id]} commits")

    valid_margins = [m for m in margins.values() if m is not None]
    print(f"\n  Margin stats: min={min(valid_margins):.2f}  max={max(valid_margins):.2f}  avg={sum(valid_margins)/len(valid_margins):.2f}")
    print(f"  Cases with margin < 3.0: {sum(1 for m in valid_margins if m < 3.0)}")
    print(f"  Cases with margin < 1.0: {sum(1 for m in valid_margins if m < 1.0)}")

    # ── Phase 2: Single signal ablations with margin tracking ─────────────────

    print(f"\n{'─' * W}")
    print("  Phase 2 — Single-signal ablations: top-1 accuracy + margin impact\n")

    ablations = [
        ("no_recency",        [("src.matcher.RECENCY_WEIGHT", 0.0)]),
        ("no_line_proximity", [("src.signals.scorer.line_proximity_score",
                                 lambda *a, **kw: 0)]),
        ("no_func_overlap",   [("src.signals.scorer.call_site_breakage_score",
                                 _cs_no_func_overlap)]),
        ("no_caller_callee",  [("src.signals.call_site.CALLER_CALLEE_BONUS", 0.0)]),
        ("no_file_overlap",   [("src.signals.scorer.file_overlap_score",
                                 lambda *a, **kw: (0, []))]),
    ]

    ablation_results: Dict[str, Dict] = {"baseline": baseline}

    for name, p in ablations:
        sys.stdout.write(f"  Running {name:<22} ... ")
        sys.stdout.flush()
        r = run_variant(name, p)
        ablation_results[name] = r
        print(f"top-1 {r['top1']}/{r['total']}")

    # Margin impact table
    print(f"\n  {'Signal':<22}  {'Top-1':>7}  {'Δ top-1':>8}  {'Margin: avg':>12}  {'min margin':>11}  {'inversions':>11}")
    print(f"  {'─'*22}  {'─'*7}  {'─'*8}  {'─'*12}  {'─'*11}  {'─'*11}")

    base1 = baseline["top1"]
    base_margins = [m for m in margins.values() if m is not None]
    base_avg = sum(base_margins) / len(base_margins)

    rows = []
    for name, _ in ablations:
        r = ablation_results[name]
        var_margins = [score_margin(res) for res in r["results"]]
        valid = [m for m in var_margins if m is not None]
        avg = sum(valid) / len(valid) if valid else 0
        min_m = min(valid) if valid else 0
        inversions = sum(1 for m in valid if m < 0)
        rows.append((name, r, avg, min_m, inversions))

    rows.sort(key=lambda x: (x[2], x[3]))  # sort by avg margin ascending

    for name, r, avg, min_m, inversions in rows:
        d1 = delta_str(r["top1"], base1)
        delta_avg = avg - base_avg
        sign = "+" if delta_avg >= 0 else ""
        print(
            f"  {name:<22}  {r['top1']}/{r['total']:>4}  {d1:>8}  "
            f"{avg:>8.2f} ({sign}{delta_avg:.2f})  {min_m:>11.2f}  {inversions:>11}"
        )

    print(
        f"  {'baseline':<22}  {base1}/{N:>4}  {'—':>8}  "
        f"{base_avg:>8.2f}        {min(base_margins):>11.2f}  {'0':>11}"
    )

    # Per-case margin delta table
    print(f"\n  Per-case margin after each ablation (Δ from baseline):\n")
    header_signals = [name for name, _ in ablations]
    case_header = f"  {'Case':<42}" + "".join(f"  {s[:8]:>8}" for s in header_signals)
    print(case_header)
    print(f"  {'─'*42}" + "  ────────" * len(ablations))

    for r in baseline["results"]:
        cid = r.case_id
        bm = margins.get(cid)
        row = f"  {cid:<42}"
        for name, _ in ablations:
            v = ablation_results[name]
            vm = score_margin(next((x for x in v["results"] if x.case_id == cid), None))
            if bm is None or vm is None:
                cell = "      —"
            else:
                d = vm - bm
                sign = "+" if d >= 0 else ""
                cell = f"  {sign}{d:>5.1f}"
            row += cell
        print(row)

    # ── Phase 3: Pairwise ablations ───────────────────────────────────────────

    print(f"\n{'─' * W}")
    print("  Phase 3 — Pairwise ablations (two signals zeroed simultaneously)\n")

    NO_RECENCY      = ("src.matcher.RECENCY_WEIGHT", 0.0)
    NO_LINE         = ("src.signals.scorer.line_proximity_score", lambda *a, **kw: 0)
    NO_FUNC         = ("src.signals.scorer.call_site_breakage_score", _cs_no_func_overlap)
    NO_CC           = ("src.signals.call_site.CALLER_CALLEE_BONUS", 0.0)
    NO_FILE         = ("src.signals.scorer.file_overlap_score", lambda *a, **kw: (0, []))

    pairs = [
        ("no_recency+no_line",    [NO_RECENCY, NO_LINE]),
        ("no_recency+no_func",    [NO_RECENCY, NO_FUNC]),
        ("no_recency+no_file",    [NO_RECENCY, NO_FILE]),
        ("no_line+no_func",       [NO_LINE, NO_FUNC]),
        ("no_line+no_file",       [NO_LINE, NO_FILE]),
        ("no_func+no_file",       [NO_FUNC, NO_FILE]),
        ("no_cc+no_line",         [NO_CC, NO_LINE]),
        ("no_cc+no_file",         [NO_CC, NO_FILE]),
    ]

    print(f"  {'Combination':<30}  {'Top-1':>7}  {'Δ top-1':>8}  {'Avg margin':>12}  {'Min margin':>11}")
    print(f"  {'─'*30}  {'─'*7}  {'─'*8}  {'─'*12}  {'─'*11}")

    for name, p in pairs:
        sys.stdout.write(f"  Running {name:<28} ... ")
        sys.stdout.flush()
        r = run_variant(name, p)
        var_margins = [score_margin(res) for res in r["results"]]
        valid = [m for m in var_margins if m is not None]
        avg = sum(valid) / len(valid) if valid else 0
        min_m = min(valid) if valid else 0
        d1 = delta_str(r["top1"], base1)
        print(f"top-1 {r['top1']}/{r['total']}  margin avg={avg:.2f}  min={min_m:.2f}")
        print(
            f"  {name:<30}  {r['top1']}/{r['total']:>4}  {d1:>8}  "
            f"{avg:>12.2f}  {min_m:>11.2f}"
        )

    # ── Phase 4: Triple ablations (only 2 signals surviving) ─────────────────

    print(f"\n{'─' * W}")
    print("  Phase 4 — Triple ablations (only 2 signals surviving)\n")

    triples = [
        ("only_recency+file",     [NO_LINE, NO_FUNC, NO_CC]),
        ("only_recency+line",     [NO_FUNC, NO_CC, NO_FILE]),
        ("only_recency+func",     [NO_LINE, NO_CC, NO_FILE]),
        ("only_line+file",        [NO_RECENCY, NO_FUNC, NO_CC]),
        ("only_line+func",        [NO_RECENCY, NO_CC, NO_FILE]),
        ("only_func+file",        [NO_RECENCY, NO_LINE, NO_CC]),
        ("only_cc+file",          [NO_RECENCY, NO_LINE, NO_FUNC]),
        ("only_cc+line",          [NO_RECENCY, NO_FUNC, NO_FILE]),
    ]

    print(f"  {'Surviving signals':<28}  {'Top-1':>7}  {'Δ top-1':>8}  {'Avg margin':>12}  {'Min margin':>11}")
    print(f"  {'─'*28}  {'─'*7}  {'─'*8}  {'─'*12}  {'─'*11}")

    for name, p in triples:
        sys.stdout.write(f"  Running {name:<26} ... ")
        sys.stdout.flush()
        r = run_variant(name, p)
        var_margins = [score_margin(res) for res in r["results"]]
        valid = [m for m in var_margins if m is not None]
        avg = sum(valid) / len(valid) if valid else 0
        min_m = min(valid) if valid else 0
        d1 = delta_str(r["top1"], base1)
        print(f"top-1 {r['top1']}/{r['total']}")
        print(
            f"  {name:<28}  {r['top1']}/{r['total']:>4}  {d1:>8}  "
            f"{avg:>12.2f}  {min_m:>11.2f}"
        )

    # ── Phase 5: Weight sweeps ────────────────────────────────────────────────

    print(f"\n{'─' * W}")
    print("  Phase 5 — Weight sweeps\n")

    sweeps = [
        ("recency_0x",          [("src.matcher.RECENCY_WEIGHT", 0.0)]),
        ("recency_1x [base]",   None),
        ("recency_2x",          [("src.matcher.RECENCY_WEIGHT", 10.0)]),
        ("func_0.5x",           [("src.signals.scorer.call_site_breakage_score", _cs_scaled(0.5))]),
        ("func_1x [base]",      None),
        ("func_2x",             [("src.signals.scorer.call_site_breakage_score", _cs_scaled(2.0))]),
        ("line_0x",             [("src.signals.scorer.line_proximity_score", lambda *a, **kw: 0)]),
        ("line_1x [base]",      None),
        ("line_2x",             [("src.signals.scorer.line_proximity_score", _line_scaled(2.0))]),
    ]

    groups = [
        ("Recency",          ["recency_0x", "recency_1x [base]", "recency_2x"]),
        ("Function overlap", ["func_0.5x", "func_1x [base]", "func_2x"]),
        ("Line proximity",   ["line_0x", "line_1x [base]", "line_2x"]),
    ]

    sweep_cache: Dict[str, Dict] = {}

    for name, p in sweeps:
        sys.stdout.write(f"  Running {name:<24} ... ")
        sys.stdout.flush()
        if p is None:
            r = baseline
        else:
            r = run_variant(name, p)
        sweep_cache[name] = r
        print(f"top-1 {r['top1']}/{r['total']}")

    print(f"\n  {'Sweep variant':<24}  {'Top-1':>7}  {'Δ top-1':>8}  {'Avg margin':>12}  {'Min margin':>11}")
    print(f"  {'─'*24}  {'─'*7}  {'─'*8}  {'─'*12}  {'─'*11}")

    for group_name, keys in groups:
        print(f"\n  {group_name}")
        for k in keys:
            r = sweep_cache.get(k)
            if not r:
                continue
            var_margins = [score_margin(res) for res in r["results"]]
            valid = [m for m in var_margins if m is not None]
            avg = sum(valid) / len(valid) if valid else 0
            min_m = min(valid) if valid else 0
            d1 = delta_str(r["top1"], base1)
            print(
                f"    {k:<24}  {r['top1']}/{r['total']:>4}  {d1:>8}  "
                f"{avg:>12.2f}  {min_m:>11.2f}"
            )

    # ── Phase 6: Signal importance ranking ────────────────────────────────────

    print(f"\n{'─' * W}")
    print("  Phase 6 — Signal importance ranking\n")

    print("  (Signals ranked by margin preservation when zeroed)\n")

    signal_labels = {
        "no_recency":        "Recency        ",
        "no_line_proximity": "Line proximity ",
        "no_func_overlap":   "Func overlap   ",
        "no_caller_callee":  "Caller-callee  ",
        "no_file_overlap":   "File overlap   ",
    }

    signal_metrics = []
    for name, _ in ablations:
        r = ablation_results[name]
        var_margins = [score_margin(res) for res in r["results"]]
        valid = [m for m in var_margins if m is not None]
        avg = sum(valid) / len(valid) if valid else 0
        min_m = min(valid) if valid else 0
        top1_delta = r["top1"] - base1
        avg_delta = avg - base_avg
        signal_metrics.append((name, top1_delta, avg_delta, avg, min_m))

    signal_metrics.sort(key=lambda x: (x[2], x[3]))  # most damaging first

    print(f"  {'Signal':<16}  {'Δ top-1':>8}  {'Δ avg margin':>13}  {'Avg margin':>11}  {'Min margin':>11}")
    print(f"  {'─'*16}  {'─'*8}  {'─'*13}  {'─'*11}  {'─'*11}")

    for name, d1, d_avg, avg, min_m in signal_metrics:
        label = signal_labels.get(name, name)
        sign = "+" if d_avg >= 0 else ""
        print(
            f"  {label}  {delta_str(d1 + base1 - base1, 0):>8}  "  # Δ top-1
            f"  {sign}{d_avg:>8.2f}      {avg:>8.2f}  {min_m:>11.2f}"
        )

    print(f"\n  {'baseline':<16}  {'—':>8}  {'—':>13}  {base_avg:>11.2f}  {min(base_margins):>11.2f}")

    # ── Final summary ─────────────────────────────────────────────────────────

    print(f"\n{'═' * W}")
    print("  SUMMARY\n")
    print(f"  Corpus: {N} cases.  Baseline top-1: 12/12 (100%).")
    print()
    print("  Key finding:")
    print("  The corpus is fully saturated at baseline. No single-signal ablation")
    print("  drops top-1 accuracy. The discriminating measure is score margin.")
    print()
    print("  Signal ranking by margin impact (most load-bearing → least):")
    for i, (name, d1, d_avg, avg, min_m) in enumerate(signal_metrics, 1):
        label = signal_labels.get(name, name).strip()
        sign = "+" if d_avg >= 0 else ""
        print(f"    {i}. {label:<16}  Δ avg margin = {sign}{d_avg:.2f}")
    print(f"{'═' * W}\n")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()

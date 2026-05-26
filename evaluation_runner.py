import json
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from src.git_utils import get_commit_changes
from src.matcher import RECENCY_WEIGHT, rank_commits
from src.parser import (
    extract_file_line_pairs,
    extract_files_from_stacktrace,
    extract_functions_from_stacktrace,
)
from src.signals.scorer import score_commit


REPOS_ROOT = os.environ.get("CAUSETRACE_REPOS_ROOT", os.path.expanduser("~"))
CASES_PATH = "data/cases.json"


def load_cases(path: str) -> List[Dict]:
    with open(path) as f:
        cases = json.load(f)
    result = []
    for case in cases:
        repo_path = os.path.join(REPOS_ROOT, case["repo"])
        result.append({**case, "repo_path": repo_path})
    return result


TEST_CASES = load_cases(CASES_PATH)

@dataclass
class EvaluationResult:
    case_id: str
    failure_mode: str
    repo_path: str
    expected_commit: str
    predicted_commits: List[Dict]
    matched_top1: bool
    matched_top3: bool
    matched_top5: bool


def commit_matches(expected_commit: str, predicted_commit: str) -> bool:
    expected = expected_commit.strip().lower()
    predicted = predicted_commit.strip().lower()
    return expected.startswith(predicted) or predicted.startswith(expected)


def validate_test_case(test_case: Dict[str, str]) -> None:
    required_fields = [
        "repo_path",
        "stacktrace",
        "good_commit",
        "bad_commit",
        "expected_commit",
    ]

    missing = [field for field in required_fields if not test_case.get(field)]
    if missing:
        missing_fields = ", ".join(missing)
        raise ValueError(f"Missing required test case fields: {missing_fields}")


def parse_stacktrace(stacktrace: str) -> Dict[str, Sequence]:
    return {
        "files": extract_files_from_stacktrace(stacktrace),
        "file_line_pairs": extract_file_line_pairs(stacktrace),
        "functions": extract_functions_from_stacktrace(stacktrace),
    }


def top_k_match(expected_commit: str, ranked_commits: Sequence[Dict], k: int) -> bool:
    return any(
        commit_matches(expected_commit, commit["hash"])
        for commit in ranked_commits[:k]
    )


def recency_breakdown(commits: Sequence[Dict]) -> Dict[str, float]:
    if not commits:
        return {}

    timestamps = [commit.get("timestamp", 0) for commit in commits]
    min_ts = min(timestamps)
    max_ts = max(timestamps)

    def normalize(ts: int) -> float:
        if max_ts == min_ts:
            return 1.0
        return (ts - min_ts) / (max_ts - min_ts)

    return {
        commit["hash"]: round(normalize(commit.get("timestamp", 0)) * RECENCY_WEIGHT, 2)
        for commit in commits
    }


def attach_score_breakdowns(
    ranked_commits: Sequence[Dict],
    stacktrace_files: Sequence[str],
    stacktrace_file_lines: Sequence,
    failure_functions: Sequence[str],
) -> List[Dict]:
    breakdown_commits: List[Dict] = []

    for commit in ranked_commits:
        _, breakdown = score_commit(
            commit,
            stacktrace_files,
            stacktrace_file_lines,
            failure_functions,
            include_breakdown=True,
        )
        breakdown_commits.append({**commit, "breakdown": breakdown})

    recency_scores = recency_breakdown(ranked_commits)

    for commit in breakdown_commits:
        commit["breakdown"]["recency"] = recency_scores.get(commit["hash"], 0.0)
        commit["breakdown"]["final"] = commit["score"]

    return breakdown_commits


def evaluate_test_case(test_case: Dict[str, str]) -> EvaluationResult:
    validate_test_case(test_case)

    parsed = parse_stacktrace(test_case["stacktrace"])
    commits = get_commit_changes(
        test_case["repo_path"],
        test_case["good_commit"],
        test_case["bad_commit"],
    )
    ranked = rank_commits(
        commits,
        parsed["files"],
        parsed["file_line_pairs"],
        parsed["functions"],
    )

    with_breakdowns = attach_score_breakdowns(
        ranked,
        parsed["files"],
        parsed["file_line_pairs"],
        parsed["functions"],
    )
    top_five = with_breakdowns[:5]

    return EvaluationResult(
        case_id=test_case.get("id", "unknown"),
        failure_mode=test_case.get("failure_mode", "unknown"),
        repo_path=test_case["repo_path"],
        expected_commit=test_case["expected_commit"],
        predicted_commits=top_five,
        matched_top1=top_k_match(test_case["expected_commit"], ranked, 1),
        matched_top3=top_k_match(test_case["expected_commit"], ranked, 3),
        matched_top5=top_k_match(test_case["expected_commit"], ranked, 5),
    )


def percentage(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return (count / total) * 100


W = 64  # output width


def _signal_summary(breakdown: Dict) -> str:
    parts = []
    if breakdown.get("line", 0):
        parts.append(f"line={breakdown['line']:.0f}")
    if breakdown.get("function", 0):
        parts.append(f"fn={breakdown['function']:.0f}")
    if breakdown.get("caller_callee", 0):
        parts.append(f"cc={breakdown['caller_callee']:.0f}")
    if breakdown.get("file", 0):
        parts.append(f"file={breakdown['file']:.0f}")
    if not parts:
        parts.append("recency-only")
    return "  ".join(parts)


def _result_label(result: "EvaluationResult") -> str:
    if result.matched_top1:
        return "PASS  (top-1)"
    if result.matched_top3:
        return "PASS  (top-3)"
    if result.matched_top5:
        return "PASS  (top-5)"
    return "FAIL"


def print_test_result(index: int, total: int, result: "EvaluationResult") -> None:
    expected_short = result.expected_commit[:7]
    label = _result_label(result)
    mode = result.failure_mode

    print(f"\n{'─' * W}")
    print(f"  Case {index}/{total}  ·  {result.case_id}  [{mode}]")
    print(f"{'─' * W}")
    print(f"  Expected   {expected_short}     Result  {label}")
    print()

    if not result.predicted_commits:
        print("  (no commits scored)")
    else:
        # Header row
        print(f"  {'Rank':<6}{'Hash':<10}{'Score':>7}  {'Signals'}")
        print(f"  {'─'*4}  {'─'*7}  {'─'*5}  {'─'*30}")
        for rank, commit in enumerate(result.predicted_commits, start=1):
            bd = commit["breakdown"]
            is_match = commit_matches(result.expected_commit, commit["hash"])
            marker = "✓" if is_match else " "
            msg = commit["message"].splitlines()[0][:32]
            signals = _signal_summary(bd)
            score_str = f"{commit['score']:>6.2f}"
            print(f"  #{rank}{marker}  {commit['hash']:<8}  {score_str}  {signals}")
            print(f"         {msg}")
        print()

    # Warning: higher line-score commit ranked lower than top-1
    if result.predicted_commits:
        top = result.predicted_commits[0]
        top_line = top["breakdown"]["line"]
        for c in result.predicted_commits[1:]:
            if c["breakdown"]["line"] > top_line:
                print(f"  [NOTE] #{result.predicted_commits.index(c)+1} has higher line score"
                      f" than #1 ({c['breakdown']['line']} vs {top_line})")


def print_summary(results: Iterable["EvaluationResult"]) -> None:
    results = list(results)
    total = len(results)
    top1_hits = sum(r.matched_top1 for r in results)
    top3_hits = sum(r.matched_top3 for r in results)
    top5_hits = sum(r.matched_top5 for r in results)

    print(f"\n{'═' * W}")
    print("  EVALUATION SUMMARY")
    print(f"{'═' * W}")
    print(f"  Cases     {total}")
    print(f"  Top-1     {top1_hits}/{total}  ({percentage(top1_hits, total):.1f}%)")
    print(f"  Top-3     {top3_hits}/{total}  ({percentage(top3_hits, total):.1f}%)")
    print(f"  Top-5     {top5_hits}/{total}  ({percentage(top5_hits, total):.1f}%)")

    # Per-failure-mode breakdown
    from collections import defaultdict
    by_mode: Dict[str, List[bool]] = defaultdict(list)
    for r in results:
        by_mode[r.failure_mode].append(r.matched_top1)

    print()
    print("  By failure mode (top-1):")
    for mode, hits in sorted(by_mode.items()):
        n = len(hits)
        h = sum(hits)
        bar = "✓" * h + "✗" * (n - h)
        print(f"    {mode:<30}  {h}/{n}  {bar}")

    # List failures
    failures = [r for r in results if not r.matched_top1]
    if failures:
        print()
        print("  Failed cases:")
        for r in failures:
            print(f"    {r.case_id}  [{r.failure_mode}]")

    print(f"{'═' * W}\n")


def main() -> None:
    if not TEST_CASES:
        print("No valid test cases found.")
        return

    total = len(TEST_CASES)
    results: List[EvaluationResult] = []

    for index, test_case in enumerate(TEST_CASES, start=1):
        try:
            result = evaluate_test_case(test_case)
            results.append(result)
            print_test_result(index, total, result)
        except Exception as exc:
            print(f"\n  Case {index}  error: {exc}")
            print(f"  Expected: {test_case.get('expected_commit', 'unknown')}")
            print(f"  {'─' * W}")

    print_summary(results)


if __name__ == "__main__":
    main()

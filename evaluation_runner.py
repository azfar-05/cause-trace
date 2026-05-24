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


def print_test_result(index: int, result: EvaluationResult) -> None:
    print(f"Test {index}")
    print(f"Repo: {result.repo_path}")
    print(f"Expected commit: {result.expected_commit}")
    print("Top 5 predicted commits:")

    if not result.predicted_commits:
        print("  None")
    else:
        for rank, commit in enumerate(result.predicted_commits, start=1):
            breakdown = commit["breakdown"]
            print(
                f"  {rank}. {commit['hash']} | score={commit['score']} | "
                f"{commit['message']}"
            )
            print(f"     Commit: {commit['hash']}")
            print(f"       final: {breakdown['final']}")
            print(f"       line: {breakdown['line']}")
            print(f"       function: {breakdown['function']}")
            print(f"       file: {breakdown['file']}")
            print(f"       recency: {breakdown['recency']}")
            print(f"       size_penalty: {breakdown['size_penalty']}")

    print_line_score_warnings(result.predicted_commits)
    print(f"Matched top1: {'yes' if result.matched_top1 else 'no'}")
    print(f"Matched top3: {'yes' if result.matched_top3 else 'no'}")
    print(f"Matched top5: {'yes' if result.matched_top5 else 'no'}")
    print("-" * 60)


def print_line_score_warnings(predicted_commits: Sequence[Dict]) -> None:
    if not predicted_commits:
        return

    top_commit = predicted_commits[0]
    top_line_score = top_commit["breakdown"]["line"]

    for commit in predicted_commits[1:]:
        candidate_line_score = commit["breakdown"]["line"]
        if candidate_line_score > top_line_score:
            print("[WARNING] Higher line-score commit ranked lower:")
            print(f"  Top1: {top_commit['hash']} (line={top_line_score})")
            print(
                f"  Candidate: {commit['hash']} "
                f"(line={candidate_line_score})"
            )


def print_summary(results: Iterable[EvaluationResult]) -> None:
    results = list(results)
    total = len(results)
    top1_hits = sum(result.matched_top1 for result in results)
    top3_hits = sum(result.matched_top3 for result in results)
    top5_hits = sum(result.matched_top5 for result in results)

    print("Overall Accuracy")
    print(f"Total tests: {total}")
    print(f"Top1: {top1_hits}/{total} ({percentage(top1_hits, total):.1f}%)")
    print(f"Top3: {top3_hits}/{total} ({percentage(top3_hits, total):.1f}%)")
    print(f"Top5: {top5_hits}/{total} ({percentage(top5_hits, total):.1f}%)")


def main() -> None:
    if not TEST_CASES:
        print("No valid test cases generated.")
        return

    results: List[EvaluationResult] = []

    for index, test_case in enumerate(TEST_CASES, start=1):
        try:
            result = evaluate_test_case(test_case)
            results.append(result)
            print_test_result(index, result)
        except Exception as exc:
            print(f"Test {index}")
            print(f"Expected commit: {test_case.get('expected_commit', 'unknown')}")
            print(f"Error: {exc}")
            print("-" * 60)

    print_summary(results)


if __name__ == "__main__":
    main()

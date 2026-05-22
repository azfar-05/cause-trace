import random
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from src.git_utils import get_commit_changes
from src.matcher import RECENCY_WEIGHT, rank_commits
from src.parser import (
    extract_file_line_pairs,
    extract_files_from_stacktrace,
    extract_functions_from_stacktrace,
)
from src.signals.line_proximity import line_proximity_score
from src.signals.scorer import score_commit


REPO_PATH = "/Users/azfar/flask"

COMMITS = [
    "c34d6e81",
    "fbb6f0bc",
    "12e95c93",
    "e82db2ca",
    "25642fd1",
]


def extract_py_file_lines(diff: str) -> Dict[str, List[int]]:
    current_file = None
    py_file_lines: Dict[str, List[int]] = {}

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            candidate_file = line.replace("+++ b/", "")
            if (
                candidate_file.endswith(".py")
                and not candidate_file.startswith("tests/")
                and not candidate_file.startswith("test_")
                and not candidate_file.startswith("tests.")
            ):
                current_file = candidate_file
                py_file_lines.setdefault(current_file, [])
            else:
                current_file = None
        elif line.startswith("@@") and current_file:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if not match:
                continue

            start = int(match.group(1))
            count = int(match.group(2) or 1)
            py_file_lines[current_file].extend(range(start, start + count))

    return py_file_lines


def generate_test_cases() -> List[Dict]:
    test_cases: List[Dict] = []

    for commit in COMMITS:
        try:
            good = subprocess.check_output(
                ["git", "-C", REPO_PATH, "rev-parse", f"{commit}~1"],
                text=True,
            ).strip()
            bad = subprocess.check_output(
                ["git", "-C", REPO_PATH, "rev-parse", commit],
                text=True,
            ).strip()
            diff = subprocess.check_output(
                ["git", "-C", REPO_PATH, "show", commit, "--unified=0"],
                text=True,
            )
        except subprocess.CalledProcessError:
            continue

        current_file = None
        py_file_hunk_counts: Dict[str, int] = {}
        py_file_lines: Dict[str, List[int]] = {}

        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                candidate_file = line.replace("+++ b/", "")
                if (
                    candidate_file.endswith(".py")
                    and not candidate_file.startswith("tests/")
                    and not candidate_file.startswith("test_")
                    and not candidate_file.startswith("tests.")
                ):
                    current_file = candidate_file
                    py_file_hunk_counts.setdefault(current_file, 0)
                    py_file_lines.setdefault(current_file, [])
                else:
                    current_file = None
            elif line.startswith("@@") and current_file:
                match = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if not match:
                    continue

                start = int(match.group(1))
                count = int(match.group(2) or 1)
                py_file_hunk_counts[current_file] += 1
                py_file_lines[current_file].extend(range(start, start + count))

        if not py_file_hunk_counts:
            continue

        file = max(py_file_hunk_counts, key=py_file_hunk_counts.get)
        if py_file_hunk_counts[file] == 0:
            continue

        candidate_lines = py_file_lines.get(file, [])
        if not candidate_lines:
            continue

        try:
            commits = get_commit_changes(REPO_PATH, good, bad)
        except Exception:
            continue

        if not commits:
            continue

        commit_data = commits[0]
        shuffled_lines = candidate_lines[:]
        random.shuffle(shuffled_lines)

        line = random.choice(candidate_lines)

        stacktrace = (
            f'File "{file}", line {line}, in unknown_function\n'
            "    RuntimeError: test failure"
        )

        test_cases.append({
            "repo_path": REPO_PATH,
            "stacktrace": stacktrace,
            "good_commit": good,
            "bad_commit": bad,
            "expected_commit": bad,
        })

    sorted_commits = sorted(
        COMMITS,
        key=lambda commit: int(
            subprocess.check_output(
                ["git", "-C", REPO_PATH, "show", "-s", "--format=%ct", commit],
                text=True,
            ).strip()
        ),
        reverse=True,
    )
    added_overlap_case = False

    for i in range(len(sorted_commits) - 1):
        earlier_commit = sorted_commits[i]
        later_commit = sorted_commits[i + 1]

        try:
            good = subprocess.check_output(
                ["git", "-C", REPO_PATH, "rev-parse", f"{earlier_commit}~1"],
                text=True,
            ).strip()
            bad = subprocess.check_output(
                ["git", "-C", REPO_PATH, "rev-parse", later_commit],
                text=True,
            ).strip()
            earlier_diff = subprocess.check_output(
                ["git", "-C", REPO_PATH, "show", earlier_commit, "--unified=0"],
                text=True,
            )
            later_diff = subprocess.check_output(
                ["git", "-C", REPO_PATH, "show", later_commit, "--unified=0"],
                text=True,
            )
        except subprocess.CalledProcessError:
            continue

        earlier_lines = extract_py_file_lines(earlier_diff)
        later_lines = extract_py_file_lines(later_diff)
        earlier_map = {f.split("/")[-1]: f for f in earlier_lines}
        later_map = {f.split("/")[-1]: f for f in later_lines}
        common_basenames = set(earlier_map) & set(later_map)

        for base in common_basenames:
            file1 = earlier_map[base]
            file2 = later_map[base]
            overlap_lines = sorted(
                set(earlier_lines[file1]) & set(later_lines[file2])
            )
            if not overlap_lines:
                continue

            overlap_line = random.choice(overlap_lines)
            stacktrace = (
                f'File "{file2}", line {overlap_line}, in unknown_function\n'
                "    RuntimeError: test failure"
            )

            test_cases.append({
                "repo_path": REPO_PATH,
                "stacktrace": stacktrace,
                "good_commit": good,
                "bad_commit": bad,
                "expected_commit": bad,
            })
            added_overlap_case = True
            break

        if added_overlap_case:
            break

    if not added_overlap_case:
        commit2 = sorted_commits[0]
        commit1 = subprocess.check_output(
            ["git", "-C", REPO_PATH, "rev-parse", f"{commit2}~1"],
            text=True,
        ).strip()

        try:
            good = subprocess.check_output(
                ["git", "-C", REPO_PATH, "rev-parse", f"{commit1}~1"],
                text=True,
            ).strip()
            bad = subprocess.check_output(
                ["git", "-C", REPO_PATH, "rev-parse", commit2],
                text=True,
            ).strip()
            diff = subprocess.check_output(
                ["git", "-C", REPO_PATH, "show", commit2, "--unified=0"],
                text=True,
            )
        except subprocess.CalledProcessError:
            return test_cases

        py_lines = extract_py_file_lines(diff)

        if not py_lines:
            for line in diff.splitlines():
                if line.startswith("+++ b/"):
                    file = line.replace("+++ b/", "")
                    stacktrace = (
                        f'File "{file}", line 1, in unknown_function\n'
                        "    RuntimeError: test failure"
                    )

                    test_cases.append({
                        "repo_path": REPO_PATH,
                        "stacktrace": stacktrace,
                        "good_commit": good,
                        "bad_commit": bad,
                        "expected_commit": bad,
                    })
                    return test_cases

        for file, lines in py_lines.items():
            if not lines:
                continue

            line = random.choice(lines)

            stacktrace = (
                f'File "{file}", line {line}, in unknown_function\n'
                "    RuntimeError: test failure"
            )

            test_cases.append({
                "repo_path": REPO_PATH,
                "stacktrace": stacktrace,
                "good_commit": good,
                "bad_commit": bad,
                "expected_commit": bad,
            })
            break
    
    return test_cases


TEST_CASES = [
    {
    "repo_path": "/Users/azfar/flask",
    "stacktrace": 'File "src/flask/app.py", line 984, in unknown_function\n    RuntimeError: test failure',
    "good_commit": "e71a5ff8de93801c30ed6daecac4b8502aa86813",
    "bad_commit": "025589ee766249652e2e097da05808fe64911ddc",
    "expected_commit": "025589ee766249652e2e097da05808fe64911ddc",
}
] + generate_test_cases()

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

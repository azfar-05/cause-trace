import argparse
import subprocess

from src.git_utils import get_commit_changes
from src.matcher import rank_commits
from src.explainer import explain_failure
from src.parser import (
    extract_files_from_stacktrace,
    extract_file_line_pairs,
    extract_functions_from_stacktrace,
)


def is_valid_range(repo_path: str, good: str, bad: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", good, bad],
        cwd=repo_path,
    )
    return result.returncode == 0


def run(stacktrace: str, repo_path: str = ".", start_commit: str = None, end_commit: str = None):
    """
    Execute the CauseTrace pipeline:
    - Parse stack trace
    - Extract commits
    - Rank commits
    - Generate explanation
    """

    if not stacktrace.strip():
        return {
            "files": [],
            "top_commits": [],
            "explanation": "No stack trace provided.",
        }

    # Extract failure signals
    files = extract_files_from_stacktrace(stacktrace)
    file_line_pairs = extract_file_line_pairs(stacktrace)
    failure_functions = extract_functions_from_stacktrace(stacktrace)

    # Validate inputs
    if not start_commit or not end_commit:
        return {
            "files": files,
            "top_commits": [],
            "explanation": "Both start and end commits must be provided.",
        }

    if not is_valid_range(repo_path, start_commit, end_commit):
        return {
            "files": files,
            "top_commits": [],
            "explanation": "Invalid commit range.",
        }

    # Extract commits
    commits = get_commit_changes(repo_path, start_commit, end_commit)

    # Rank commits
    ranked = rank_commits(
        commits,
        files,
        file_line_pairs,
        failure_functions,
    )

    # Generate explanation from top candidates
    explanation = explain_failure(stacktrace, ranked[:2])

    return {
        "files": files,
        "top_commits": ranked[:3],
        "explanation": explanation,
    }


def main():
    parser = argparse.ArgumentParser(description="CauseTrace - Failure Analysis Tool")

    parser.add_argument("--file", type=str, help="Path to stack trace file")
    parser.add_argument("--good", type=str, required=True)
    parser.add_argument("--bad", type=str, required=True)

    args = parser.parse_args()

    # Read stack trace
    if args.file:
        with open(args.file, "r") as f:
            stacktrace = f.read()
    else:
        print("Paste stack trace (Ctrl+D to finish):")
        lines = []
        while True:
            try:
                lines.append(input())
            except EOFError:
                break
        stacktrace = "\n".join(lines)

    result = run(
        stacktrace,
        start_commit=args.good,
        end_commit=args.bad,
    )

    if not result["top_commits"]:
        print("\nNo results.\n")
        return

    print("\nTop suspect commits:\n")

    for i, c in enumerate(result["top_commits"], 1):
        matched = [f for f in c["files"] if f in result["files"]]

        print(f"{i}. Commit: {c['hash']}")
        print(f"   Message: {c['message']}")
        print(f"   Files: {', '.join(c['files'])}")
        print(f"   Matched Files: {', '.join(matched) if matched else 'None'}")
        print(f"   Total Files Changed: {len(c['files'])}")
        print(f"   Score: {c['score']}\n")

    print("Likely cause:\n")
    print(result["explanation"])


if __name__ == "__main__":
    main()
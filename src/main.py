import argparse
import subprocess

from src.git_utils import get_commit_changes
from src.matcher import rank_commits
from src.explainer import explain_failure
from src.parser import extract_files_from_stacktrace, extract_file_line_pairs


def is_valid_range(repo_path: str, good: str, bad: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", good, bad],
        cwd=repo_path
    )
    return result.returncode == 0


def run(stacktrace: str, repo_path: str = ".", start_commit: str = None, end_commit: str = None):
    if not stacktrace.strip():
        return {
            "files": [],
            "top_commits": [],
            "explanation": "No stack trace provided."
        }

    # Extract signals
    files = extract_files_from_stacktrace(stacktrace)
    file_line_pairs = extract_file_line_pairs(stacktrace)

    # Validate inputs
    if not start_commit or not end_commit:
        print("❌ Both --good and --bad commits must be provided")
        return {
            "files": files,
            "top_commits": [],
            "explanation": "Missing commit inputs."
        }

    if not is_valid_range(repo_path, start_commit, end_commit):
        print(f"❌ Invalid range: {start_commit} is not an ancestor of {end_commit}")
        return {
            "files": files,
            "top_commits": [],
            "explanation": "Invalid commit range."
        }

    # Get commits
    commits = get_commit_changes(repo_path, start_commit, end_commit)

    # Rank with file + line info
    ranked = rank_commits(commits, files, file_line_pairs)

    explanation = explain_failure(stacktrace, ranked[:2])

    return {
        "files": files,
        "top_commits": ranked[:3],
        "explanation": explanation
    }


def main():
    parser = argparse.ArgumentParser(description="CauseTrace - Failure Analysis Tool")

    parser.add_argument("--file", type=str, help="Path to stack trace file")
    parser.add_argument("--good", type=str, required=True)
    parser.add_argument("--bad", type=str, required=True)

    args = parser.parse_args()

    if args.file:
        with open(args.file, "r") as f:
            stacktrace = f.read()
    else:
        print("Paste stack trace (press Ctrl+D when done):")
        lines = []
        while True:
            try:
                line = input()
                lines.append(line)
            except EOFError:
                break
        stacktrace = "\n".join(lines)

    result = run(
        stacktrace,
        start_commit=args.good,
        end_commit=args.bad
    )

    if not result["top_commits"]:
        print("\n⚠️ No stack trace provided. Nothing to analyze.\n")
    else:
        print("\n🔍 Top Suspect Commits:\n")

        for i, c in enumerate(result["top_commits"], 1):
            print(f"{i}. Commit: {c['hash']}")
            print(f"   Message: {c['message']}")
            matched = [f for f in c['files'] if f in result["files"]]
            print(f"   Files: {', '.join(c['files'])}")
            print(f"   Matched Files: {', '.join(matched) if matched else 'None'}")
            print(f"   Total Files Changed: {len(c['files'])}")
            print(f"   Score: {c['score']}\n")

        print("🧠 Likely Cause:\n")
        print(result["explanation"])


if __name__ == "__main__":
    main()
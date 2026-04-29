from src.parser import extract_files_from_stacktrace
from src.git_utils import get_commit_changes
from src.matcher import rank_commits
from src.explainer import explain_failure


def run(stacktrace: str, repo_path: str = ".", commit_range: str = "HEAD~2"):
    files = extract_files_from_stacktrace(stacktrace)

    commits = get_commit_changes(repo_path, commit_range, "HEAD")

    ranked = rank_commits(commits, files)

    explanation = explain_failure(stacktrace, ranked[:2])

    return {
        "files": files,
        "top_commits": ranked[:3],
        "explanation": explanation
    }


if __name__ == "__main__":
    print("Paste stack trace (press Ctrl+D when done):")
    lines = []
    while True:
        try:
            line = input()
            lines.append(line)
        except EOFError:
            break

    stacktrace = "\n".join(lines)

    result = run(stacktrace)

    print("\n--- Top Commits ---")
    for c in result["top_commits"]:
        print(c)

    print("\n--- Explanation ---")
    print(result["explanation"])
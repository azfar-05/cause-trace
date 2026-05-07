from src.parser import (
    extract_files_from_stacktrace,
    extract_file_line_pairs,
    extract_functions_from_stacktrace
)
from src.git_utils import get_commit_changes
from src.matcher import rank_commits
from src.explainer import explain_failure

repo_path = "/Users/azfar/flask"

stacktrace = "ctx.py:160 in copy_current_request_context"


# Parse
files = extract_files_from_stacktrace(stacktrace)
lines = extract_file_line_pairs(stacktrace)
functions = extract_functions_from_stacktrace(stacktrace)

print("=== Parsed Failure ===")
print("Files:", files)
print("Lines:", lines)
print("Functions:", functions)
print("=" * 50)

# Correct window
commits = get_commit_changes(repo_path, "a29f88c~5", "a29f88c")
# Rank
ranked = rank_commits(commits, files, lines, functions)

print("\n=== Top Ranked Commits ===\n")

for c in ranked[:3]:
    print("Hash:", c["hash"])
    print("Score:", c["score"])
    print("Files:", c["files"])
    print("-" * 40)

print("\n=== LLM Explanation ===\n")

explanation = explain_failure(stacktrace, ranked[:3])
print(explanation)
for c in commits:
    if c["modified_functions"]:
        print(c["hash"], c["modified_functions"])
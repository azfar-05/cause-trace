from git import Repo, GitCommandError, NULL_TREE
from typing import List, Dict
import subprocess
import re


def get_commits_in_range(repo_path: str, start_commit: str, end_commit: str):
    """
    Return commits in the range (start_commit, end_commit].
    """
    repo = Repo(repo_path)

    try:
        return list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    except GitCommandError:
        raise Exception(f"Invalid commit range: {start_commit}..{end_commit}")


def get_changed_lines(repo_path: str, commit_hash: str):
    """
    Extract changed line numbers per file using `git show --unified=0`.
    Returns:
        { filename: [line_numbers] }
    """
    changed = {}

    try:
        result = subprocess.run(
            ["git", "show", commit_hash, "--unified=0"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return changed

    current_file = None

    for line in result.stdout.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line.replace("+++ b/", "").split("/")[-1]

        elif line.startswith("@@") and current_file:
            parts = line.split(" ")
            for p in parts:
                if p.startswith("+"):
                    try:
                        start_line = int(p.split(",")[0][1:])
                        changed.setdefault(current_file, []).append(start_line)
                    except Exception:
                        pass
                    break

    return changed


def find_enclosing_functions(repo_path: str, commit_hash: str, filepath: str, line_numbers: List[int]) -> List[str]:
    """
    Find enclosing Python function names for a set of changed line numbers.

    Reads the file content at the given commit and scans backward from each
    line number to find the nearest enclosing def. Handles both module-level
    functions and class methods.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{commit_hash}:{filepath}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    file_lines = result.stdout.splitlines()
    functions = set()

    for line_num in line_numbers:
        for i in range(min(line_num - 1, len(file_lines) - 1), -1, -1):
            m = re.match(r"\s*def\s+(\w+)\s*\(", file_lines[i])
            if m:
                functions.add(m.group(1))
                break

    return list(functions)


def get_commit_changes(repo_path: str, start_commit: str, end_commit: str) -> List[Dict]:
    """
    Extract structured commit data for scoring.
    Includes:
    - files touched
    - changed lines
    - modified functions (heuristic)
    """
    repo = Repo(repo_path)

    try:
        commits = list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    except GitCommandError:
        raise Exception(f"Invalid commit range: {start_commit}..{end_commit}")

    if not commits:
        return []

    result = []

    for commit in commits:
        files = set()
        modified_functions = set()
        full_path_map: Dict[str, str] = {}  # basename -> full repo path for Python files

        # Extract diffs with patch
        if not commit.parents:
            diffs = commit.diff(NULL_TREE, create_patch=True)
        else:
            diffs = commit.diff(commit.parents[0], create_patch=True)

        for diff in diffs:
            if diff.a_path:
                files.add(diff.a_path.split("/")[-1])
            if diff.b_path:
                basename = diff.b_path.split("/")[-1]
                files.add(basename)
                if diff.b_path.endswith(".py"):
                    full_path_map[basename] = diff.b_path

            if diff.diff:
                patch_text = diff.diff.decode("utf-8", errors="ignore")
                modified_functions.update(
                    extract_modified_functions_from_patch(patch_text)
                )

        changed_lines = get_changed_lines(repo_path, commit.hexsha)

        for basename, lines in changed_lines.items():
            full_path = full_path_map.get(basename)
            if not full_path or not lines:
                continue
            modified_functions.update(
                find_enclosing_functions(repo_path, commit.hexsha, full_path, lines)
            )

        result.append({
            "hash": commit.hexsha[:7],
            "message": commit.message.strip(),
            "files": list(files),
            "timestamp": commit.committed_date,
            "changed_lines": changed_lines,
            "modified_functions": list(modified_functions),
        })

    return result


def extract_modified_functions_from_patch(patch_text: str):
    """
    Heuristically detect functions whose bodies were modified.

    Strategy:
    - Track current function context from definitions
    - Assign added lines ('+') to the most recent function
    - Supports Python and common JavaScript patterns
    """
    functions = set()
    current_function = None

    for line in patch_text.split("\n"):
        # Python: def func(
        py_match = re.search(r"def\s+(\w+)\s*\(", line)
        if py_match:
            current_function = py_match.group(1)
            continue

        # JS: function func(
        js_match = re.search(r"function\s+(\w+)\s*\(", line)
        if js_match:
            current_function = js_match.group(1)
            continue

        # JS arrow: const fn = (...) =>
        arrow_match = re.search(r"(\w+)\s*=\s*\(?.*\)?\s*=>", line)
        if arrow_match:
            current_function = arrow_match.group(1)
            continue

        # Assign added lines to current function
        if line.startswith("+") and current_function:
            functions.add(current_function)

    return list(functions)
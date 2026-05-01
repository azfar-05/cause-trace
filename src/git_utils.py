from git import Repo, GitCommandError
from typing import List, Dict
from git import NULL_TREE
import subprocess
import re 


def get_commits_in_range(repo_path: str, start_commit: str, end_commit: str):
    repo = Repo(repo_path)

    try:
        commits = list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    except GitCommandError:
        raise Exception(f"Invalid commit range: {start_commit}..{end_commit}")

    return commits


def get_changed_lines(repo_path: str, commit_hash: str):
    changed = {}

    try:
        result = subprocess.run(
            ["git", "show", commit_hash, "--unified=0"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
    except:
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
                    except:
                        pass
                    break

    return changed


def get_commit_changes(repo_path: str, start_commit: str, end_commit: str) -> List[Dict]:
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

        # 🔧 IMPORTANT: enable patch extraction
        if not commit.parents:
            diffs = commit.diff(NULL_TREE, create_patch=True)
        else:
            diffs = commit.diff(commit.parents[0], create_patch=True)

        for diff in diffs:
            # file tracking
            if diff.a_path:
                files.add(diff.a_path.split("/")[-1])
            if diff.b_path:
                files.add(diff.b_path.split("/")[-1])

            # ✅ extract functions from patch
            if diff.diff:
                patch_text = diff.diff.decode("utf-8", errors="ignore")
                funcs = extract_modified_functions_from_patch(patch_text)
                modified_functions.update(funcs)

        # line-level changes
        changed_lines = get_changed_lines(repo_path, commit.hexsha)

        result.append({
            "hash": commit.hexsha[:7],
            "message": commit.message.strip(),
            "files": list(files),
            "timestamp": commit.committed_date,
            "changed_lines": changed_lines,
            "modified_functions": list(modified_functions)
        })

    return result


def extract_modified_functions_from_patch(patch_text: str):
    functions = set()

    lines = patch_text.split("\n")

    for line in lines:
        if not line.startswith("+"):
            continue

        py_match = re.search(r"def\s+(\w+)\s*\(", line)
        js_match = re.search(r"function\s+(\w+)\s*\(", line)
        arrow_match = re.search(r"(\w+)\s*=\s*\(?.*\)?\s*=>", line)

        match = py_match or js_match or arrow_match

        if match:
            functions.add(match.group(1))

    return list(functions)
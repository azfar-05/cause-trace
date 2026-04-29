from git import Repo, GitCommandError
from typing import List, Dict
from git import NULL_TREE
import subprocess


def get_commits_in_range(repo_path: str, start_commit: str, end_commit: str):
    """
    Get list of commits between start_commit and end_commit (exclusive of start, inclusive of end)
    """
    repo = Repo(repo_path)

    try:
        commits = list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    except GitCommandError:
        raise Exception(f"Invalid commit range: {start_commit}..{end_commit}")

    return commits


def get_changed_lines(repo_path: str, commit_hash: str):
    """
    Extract changed line numbers per file using `git show`
    """
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

        # File-level changes (still using GitPython here, fine)
        if not commit.parents:
            diffs = commit.diff(NULL_TREE)
        else:
            diffs = commit.diff(commit.parents[0])

        for diff in diffs:
            if diff.a_path:
                files.add(diff.a_path.split("/")[-1])
            if diff.b_path:
                files.add(diff.b_path.split("/")[-1])

        # Line-level changes (robust via git CLI)
        changed_lines = get_changed_lines(repo_path, commit.hexsha)

        result.append({
            "hash": commit.hexsha[:7],
            "message": commit.message.strip(),
            "files": list(files),
            "timestamp": commit.committed_date,
            "changed_lines": changed_lines
        })

    return result
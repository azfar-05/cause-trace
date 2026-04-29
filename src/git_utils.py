from git import Repo, GitCommandError
from typing import List, Dict
from git import NULL_TREE


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

        # If no parent (initial commit), diff against empty tree
        if not commit.parents:
            diffs = commit.diff(NULL_TREE)
        else:
            diffs = commit.diff(commit.parents[0])

        for diff in diffs:
            if diff.a_path:
                files.add(diff.a_path.split("/")[-1])
            if diff.b_path:
                files.add(diff.b_path.split("/")[-1])

        result.append({
            "hash": commit.hexsha[:7],
            "message": commit.message.strip(),
            "files": list(files),
            "timestamp": commit.committed_date
        })

    return result
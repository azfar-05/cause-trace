from git import Repo
from typing import List, Dict


def get_commits_in_range(repo_path: str, start_commit: str, end_commit: str):
    """
    Get list of commits between start_commit and end_commit
    """
    repo = Repo(repo_path)
    commits = list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    return commits


def get_commit_changes(repo_path: str, start_commit: str, end_commit: str) -> List[Dict]:
    repo = Repo(repo_path)

    try:
        commits = repo.iter_commits(f"{start_commit}..{end_commit}")
    except GitCommandError:
        print("Invalid commit range. Falling back to recent commits.")
        commits = repo.iter_commits(end_commit, max_count=5)

    result = []

    for commit in commits:
        files = []

        for parent in commit.parents:
            diffs = commit.diff(parent)
            for diff in diffs:
                if diff.a_path:
                    files.append(diff.a_path.split("/")[-1])
                if diff.b_path:
                    files.append(diff.b_path.split("/")[-1])

        result.append({
            "hash": commit.hexsha[:7],
            "message": commit.message.strip(),
            "files": list(set(files)),
            "timestamp": commit.committed_date
        })

    return result
from typing import List, Dict
from datetime import datetime


from datetime import datetime

def score_commit(commit: Dict, stacktrace_files: List[str], commit_obj=None) -> int:
    score = 0

    matching_files = [f for f in commit["files"] if f in stacktrace_files]

    if matching_files:
        score += 5

        # Penalize large commits
        score -= len(commit["files"])

        # Bonus for focused change
        if len(commit["files"]) == 1:
            score += 3

    #Recency
    commit_time = datetime.fromtimestamp(commit["timestamp"])
    age_seconds = (datetime.now() - commit_time).total_seconds()

    score += max(0, int(10 - age_seconds / 3600))

    return score


def rank_commits(commits: List[Dict], stacktrace_files: List[str]) -> List[Dict]:
    """
    Rank commits based on relevance to stack trace
    """
    scored = []

    for commit in commits:
        score = score_commit(commit, stacktrace_files)

        scored.append({
            **commit,
            "score": score
        })

    # Sort by score (descending)
    scored.sort(key=lambda x: x["score"], reverse=True)

    return scored
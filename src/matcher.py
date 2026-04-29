from typing import List, Dict
from datetime import datetime


def is_partial_match(file1: str, file2: str) -> bool:
    return file1 in file2 or file2 in file1


def score_commit(commit: Dict, stacktrace_files: List[str]) -> float:
    score = 0.0

    matching_files = []
    partial_matches = []

    # 🔍 Match detection
    for f in commit["files"]:
        if f in stacktrace_files:
            matching_files.append(f)
        else:
            for sf in stacktrace_files:
                if is_partial_match(f, sf):
                    partial_matches.append(f)
                    break

    # ✅ Direct matches (strong signal)
    if matching_files:
        score += 5
        score += len(matching_files) * 2

    # ⚖️ Partial matches (weaker signal)
    if partial_matches:
        score += 2

    # 📉 Penalize noisy commits (but softer)
    score -= len(commit["files"]) * 0.5

    # 🎯 Focused change bonus
    if len(commit["files"]) == 1 and matching_files:
        score += 3

    # ⏱ Recency bonus
    commit_time = datetime.fromtimestamp(commit["timestamp"])
    age_seconds = (datetime.now() - commit_time).total_seconds()

    recency_score = max(0, 10 - (age_seconds / 3600))  # decays hourly
    score += recency_score

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
            "score": round(score, 2)  # cleaner output
        })

    # 🔥 Sort: score first, then recency
    scored.sort(
        key=lambda x: (x["score"], x["timestamp"]),
        reverse=True
    )

    return scored
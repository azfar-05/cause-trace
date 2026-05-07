from typing import List, Dict, Tuple
from src.signals.scorer import score_commit


RECENCY_WEIGHT = 5.0


def rank_commits(
    commits: List[Dict],
    stacktrace_files: List[str],
    stacktrace_file_lines: List[Tuple[str, int]],
    failure_functions: List[str]
) -> List[Dict]:
    """
    Rank commits using deterministic scoring and recency.

    Responsibilities:
    - Invoke scoring logic (signals/scorer.py)
    - Apply normalized recency boost
    - Sort commits by final score

    No signal logic is implemented here.
    """

    if not commits:
        return []

    timestamps = [c.get("timestamp", 0) for c in commits]
    min_ts = min(timestamps)
    max_ts = max(timestamps)

    def normalize(ts: int) -> float:
        if max_ts == min_ts:
            return 1.0
        return (ts - min_ts) / (max_ts - min_ts)

    scored = []

    for commit in commits:
        base_score = score_commit(
            commit,
            stacktrace_files,
            stacktrace_file_lines,
            failure_functions
        )

        ts = commit.get("timestamp", 0)
        recency = normalize(ts)

        final_score = base_score + recency * RECENCY_WEIGHT

        scored.append({
            **commit,
            "score": round(final_score, 2)
        })

    scored.sort(
        key=lambda x: (x["score"], x.get("timestamp", 0)),
        reverse=True
    )

    return scored
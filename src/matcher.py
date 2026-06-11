from typing import Dict, List, Sequence, Tuple
from src.signals.scorer import score_commit


RECENCY_WEIGHT = 5.0


def recency_scores(commits: Sequence[Dict]) -> Dict[str, float]:
    """
    Return normalized recency scores for display/breakdown purposes.

    Maps each commit hash to a rounded float in [0.0, RECENCY_WEIGHT].
    Single-commit windows (or all-same-timestamp) return RECENCY_WEIGHT for all.

    This is the canonical normalization formula. rank_commits uses an
    unrounded variant internally for score accumulation.
    """
    if not commits:
        return {}
    timestamps = [c.get("timestamp", 0) for c in commits]
    lo, hi = min(timestamps), max(timestamps)

    def _norm(ts: int) -> float:
        return 1.0 if lo == hi else (ts - lo) / (hi - lo)

    return {
        c["hash"]: round(_norm(c.get("timestamp", 0)) * RECENCY_WEIGHT, 2)
        for c in commits
    }


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
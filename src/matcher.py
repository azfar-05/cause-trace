from typing import List, Dict, Tuple
from src.signals.line_proximity import line_proximity_score
from src.signals.file_overlap import file_overlap_score
from src.signals.partial_match import partial_match_score
from src.signals.scorer import score_commit


def is_partial_match(file1: str, file2: str) -> bool:
    return file1 in file2 or file2 in file1


def rank_commits(
    commits: List[Dict],
    stacktrace_files: List[str],
    stacktrace_file_lines: List[Tuple[str, int]],
    failure_functions: List[str]
) -> List[Dict]:
    """
    Rank commits based on relevance to stack trace + recency + line proximity
    """
    if not commits:
        return []

    # ⏱ Normalize timestamps
    timestamps = [c["timestamp"] for c in commits]
    min_ts = min(timestamps)
    max_ts = max(timestamps)

    def normalize(ts):
        if max_ts == min_ts:
            return 1.0
        return (ts - min_ts) / (max_ts - min_ts)

    scored = []

    for commit in commits:
        base_score = score_commit(commit, stacktrace_files, stacktrace_file_lines, failure_functions)
        recency = normalize(commit["timestamp"])

        score = base_score + recency * 5

        scored.append({
            **commit,
            "score": round(score, 2)
        })

    # 🔥 Sort by score, then recency
    scored.sort(
        key=lambda x: (x["score"], x["timestamp"]),
        reverse=True
    )

    return scored
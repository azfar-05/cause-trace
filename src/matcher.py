from typing import List, Dict, Tuple


def is_partial_match(file1: str, file2: str) -> bool:
    return file1 in file2 or file2 in file1


def score_commit(
    commit: Dict,
    stacktrace_files: List[str],
    stacktrace_file_lines: List[Tuple[str, int]]
) -> float:
    score = 0.0

    matching_files = []
    partial_matches = []

    # 🔍 File-level matching
    for f in commit["files"]:
        if f in stacktrace_files:
            matching_files.append(f)
        else:
            for sf in stacktrace_files:
                if is_partial_match(f, sf):
                    partial_matches.append(f)
                    break

    # ✅ Direct matches
    if matching_files:
        score += 5
        score += len(matching_files) * 2

    # ⚖️ Partial matches
    if partial_matches:
        score += 2

    # 📉 Noise penalty
    score -= len(commit["files"]) * 1.2

    # 🎯 Focused change bonus
    if len(commit["files"]) == 1 and matching_files:
        score += 3

    # 🧠 Line-level proximity (dedup per file)
    line_match_score = 0
    seen_files = set()

    for file, line in stacktrace_file_lines:
        if file in commit.get("changed_lines", {}) and file not in seen_files:
            changed_lines = commit["changed_lines"][file]

            for cl in changed_lines:
                if abs(cl - line) <= 5:
                    line_match_score += 10
                    seen_files.add(file)
                    break

    score += line_match_score

    return score


def rank_commits(
    commits: List[Dict],
    stacktrace_files: List[str],
    stacktrace_file_lines: List[Tuple[str, int]]
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
        base_score = score_commit(commit, stacktrace_files, stacktrace_file_lines)
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
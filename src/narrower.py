"""
Deterministic commit-range narrowing stage.

Sits between git_utils.get_commit_changes() and matcher.rank_commits().
Reduces large candidate sets to causally relevant commits before full scoring.

Algorithm:
  Tier 1 — file overlap: keep commits that touch ≥1 file from the stack trace.
            A commit with no file overlap with the trace is very unlikely to be
            the cause.
  Tier 2 — recency fallback: if fewer than min_candidates pass Tier 1, supplement
            with the most recent unincluded commits. Preserves culprits in
            trace-weak cases (stack trace has no file evidence, or tiny windows).

Guard: if the stack trace provides no file names, skip narrowing entirely and
return all commits unchanged (prevents silent false negatives).
"""

from typing import Dict, List, Tuple


def narrow_candidates(
    commits: List[Dict],
    stacktrace_files: List[str],
    min_candidates: int = 20,
) -> Tuple[List[Dict], Dict]:
    """
    Narrow a commit list to causally relevant candidates before scoring.

    Args:
        commits:          Full commit list from get_commit_changes() (newest-first).
        stacktrace_files: File paths extracted from the failure stack trace.
        min_candidates:   Minimum number of commits to retain. Prevents discarding
                          the culprit when the trace has weak file evidence.

    Returns:
        (narrowed_commits, stats) where stats contains:
          total         — original commit count
          narrowed      — retained commit count
          tier1         — commits passing the file-overlap filter
          reduction_pct — percentage of commits removed (0–100)
    """
    total = len(commits)

    # Guard: no trace files or no commits → return unchanged
    if not commits or not stacktrace_files:
        return commits, {
            "total": total,
            "narrowed": total,
            "tier1": total,
            "reduction_pct": 0,
        }

    trace_basenames = {f.split("/")[-1] for f in stacktrace_files}

    # Tier 1: file overlap
    tier1 = [
        c for c in commits
        if set(c.get("files", [])) & trace_basenames
    ]

    # Tier 2: recency fallback to reach min_candidates
    # commits are newest-first (git default), so fallback pulls from the front
    if len(tier1) < min_candidates:
        seen = {c["hash"] for c in tier1}
        fallback = [c for c in commits if c["hash"] not in seen]
        extra_needed = max(0, min_candidates - len(tier1))
        result = tier1 + fallback[:extra_needed]
    else:
        result = tier1

    narrowed = len(result)
    stats = {
        "total": total,
        "narrowed": narrowed,
        "tier1": len(tier1),
        "reduction_pct": round(100.0 * (1 - narrowed / total), 1) if total > 0 else 0,
    }
    return result, stats

from src.signals.line_proximity import line_proximity_score
from src.signals.file_overlap import file_overlap_score
from src.signals.partial_match import partial_match_score
from src.signals.call_site import call_site_breakage_score


def score_commit(commit, stacktrace_files, stacktrace_file_lines, failure_functions):
    """
    Compute a deterministic relevance score for a commit based on failure context.

    Signals:
    - File overlap (strong)
    - Partial filename match (weak)
    - Function-level overlap / call-site breakage (structural signal)
    - Line proximity (strongest)
    - Commit size penalty (noise reduction)
    - Focus bonus (single-file targeted change)

    The scoring is additive, with penalties applied directly.
    """

    score = 0.0

    # File-level signals
    file_score, matching_files = file_overlap_score(commit, stacktrace_files)
    score += file_score

    partial_score, _ = partial_match_score(
        commit,
        stacktrace_files,
        matching_files
    )
    score += partial_score

    # Structural signal (function-level)
    score += call_site_breakage_score(commit, failure_functions)

    # Noise penalty (larger commits are less precise)
    score -= len(commit["files"]) * 1.2

    # Focus bonus (single-file precise change)
    if len(commit["files"]) == 1 and matching_files:
        score += 3

    # Line-level signal (highest precision)
    score += line_proximity_score(commit, stacktrace_file_lines)

    return score
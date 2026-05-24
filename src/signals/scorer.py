import math

from src.signals.line_proximity import line_proximity_score
from src.signals.file_overlap import file_overlap_score
from src.signals.partial_match import partial_match_score
from src.signals.call_site import call_site_breakage_score


def score_commit(
    commit,
    stacktrace_files,
    stacktrace_file_lines,
    failure_functions,
    include_breakdown=False,
):
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

    # Structural signal (function-level + caller/callee adjacency)
    function_score, caller_callee_score = call_site_breakage_score(
        commit, failure_functions, include_breakdown=True
    )
    score += function_score

    # Noise penalty (larger commits are less precise; sqrt dampens growth for large commits)
    size_penalty = math.sqrt(len(commit["files"])) * 1.2
    score -= size_penalty

    # Focus bonus (single-file precise change)
    focus_bonus = 0
    if len(commit["files"]) == 1 and matching_files:
        focus_bonus = 3
        score += focus_bonus

    # Line-level signal (highest precision)
    line_score = line_proximity_score(
        commit,
        stacktrace_file_lines,
        matching_files,
    )
    score += line_score

    if not include_breakdown:
        return score

    breakdown = {
        "line": line_score,
        "function": function_score,
        "caller_callee": caller_callee_score,
        "file": file_score,
        "partial_file": partial_score,
        "focus_bonus": focus_bonus,
        "size_penalty": size_penalty,
        "base_score": score,
    }
    return score, breakdown

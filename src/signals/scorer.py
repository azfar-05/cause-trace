from src.signals.line_proximity import line_proximity_score
from src.signals.file_overlap import file_overlap_score
from src.signals.partial_match import partial_match_score
from src.signals.call_site import call_site_breakage_score

def score_commit(commit, stacktrace_files, stacktrace_file_lines, failure_functions):
    score = 0.0

    # 1. File overlap (strong)
    file_score, matching_files = file_overlap_score(commit, stacktrace_files)
    score += file_score

    # 2. Partial match (weaker)
    partial_score, _ = partial_match_score(
        commit,
        stacktrace_files,
        matching_files
    )
    score += partial_score


    # 3. Call site breakage
    score += call_site_breakage_score(commit, failure_functions)

    # 4. Noise penalty
    score -= len(commit["files"]) * 1.2

    # 5. Focus bonus
    if len(commit["files"]) == 1 and matching_files:
        score += 3

    # 6. Line proximity (strongest)
    score += line_proximity_score(commit, stacktrace_file_lines)

    return score
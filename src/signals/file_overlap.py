def file_overlap_score(commit, stacktrace_files):
    """
    Compute a score based on direct file overlap between the commit
    and the stack trace.

    Returns:
    - score (int)
    - matching_files (list[str])
    """

    commit_files = commit.get("files", [])
    matching_files = [f for f in commit_files if f in stacktrace_files]

    if not matching_files:
        return 0, []

    # Base score for any overlap, plus incremental per file
    score = 5 + len(matching_files) * 2

    return score, matching_files
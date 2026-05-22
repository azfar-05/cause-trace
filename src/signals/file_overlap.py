def file_overlap_score(commit, stacktrace_files):
    """
    Compute a score based on direct file overlap between the commit
    and the stack trace.

    Returns:
    - score (int)
    - matching_files (list[str])
    """

    commit_files = commit.get("files", [])
    matching_files = []

    for stacktrace_file in stacktrace_files:
        exact_matches = [f for f in commit_files if f == stacktrace_file]
        if exact_matches:
            matching_files.extend(
                f for f in exact_matches if f not in matching_files
            )
            continue

        stacktrace_basename = stacktrace_file.split("/")[-1]
        basename_matches = [
            f for f in commit_files
            if f.split("/")[-1] == stacktrace_basename
        ]
        matching_files.extend(
            f for f in basename_matches if f not in matching_files
        )

    if not matching_files:
        return 0, []

    # Base score for any overlap, plus incremental per file
    score = 5 + len(matching_files) * 2

    return score, matching_files

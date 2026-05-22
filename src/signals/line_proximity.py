def line_proximity_score(commit, stacktrace_file_lines, matching_files):
    """
    Compute a score based on proximity between changed lines in a commit
    and line numbers present in the stack trace.

    A match is counted if a changed line is within ±5 lines of the failure line.
    Each file contributes at most once to avoid overcounting.

    Returns:
    - score (int)
    """

    changed_lines_map = commit.get("changed_lines", {})
    if not changed_lines_map or not stacktrace_file_lines or not matching_files:
        return 0

    score = 0
    seen_files = set()

    for stacktrace_file, line in stacktrace_file_lines:
        stacktrace_basename = stacktrace_file.split("/")[-1]
        matched_file = next(
            (
                commit_file for commit_file in matching_files
                if commit_file == stacktrace_file
                or commit_file.split("/")[-1] == stacktrace_basename
            ),
            None,
        )

        if not matched_file or matched_file in seen_files:
            continue

        changed_lines = changed_lines_map.get(matched_file)
        if not changed_lines:
            continue

        for cl in changed_lines:
            if abs(cl - line) <= 5:
                score += 10
                seen_files.add(matched_file)
                break

    return score

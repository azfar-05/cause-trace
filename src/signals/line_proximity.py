def line_proximity_score(commit, stacktrace_file_lines):
    """
    Compute a score based on proximity between changed lines in a commit
    and line numbers present in the stack trace.

    A match is counted if a changed line is within ±5 lines of the failure line.
    Each file contributes at most once to avoid overcounting.

    Returns:
    - score (int)
    """

    changed_lines_map = commit.get("changed_lines", {})
    if not changed_lines_map or not stacktrace_file_lines:
        return 0

    score = 0
    seen_files = set()

    for file, line in stacktrace_file_lines:
        if file in seen_files:
            continue

        changed_lines = changed_lines_map.get(file)
        if not changed_lines:
            continue

        for cl in changed_lines:
            if abs(cl - line) <= 5:
                score += 10
                seen_files.add(file)
                break

    return score
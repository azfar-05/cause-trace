def is_partial_match(file1: str, file2: str) -> bool:
    """
    Determine if two file names partially match.
    """
    return file1 in file2 or file2 in file1


def partial_match_score(commit, stacktrace_files, exclude_files):
    """
    Compute a weak score based on partial filename matches.

    Excludes files that already have direct matches.

    Returns:
    - score (int)
    - partial_matches (list[str])
    """

    commit_files = commit.get("files", [])
    partial_matches = []

    for f in commit_files:
        if f in exclude_files:
            continue

        for sf in stacktrace_files:
            if is_partial_match(f, sf):
                partial_matches.append(f)
                break

    if not partial_matches:
        return 0, []

    # Weak signal: any partial match
    return 2, partial_matches
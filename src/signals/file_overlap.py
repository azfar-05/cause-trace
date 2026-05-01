def file_overlap_score(commit, stacktrace_files):
    matching_files = []

    for f in commit["files"]:
        if f in stacktrace_files:
            matching_files.append(f)

    score = 0

    if matching_files:
        score += 5
        score += len(matching_files) * 2

    return score, matching_files
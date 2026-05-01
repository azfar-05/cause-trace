def is_partial_match(file1: str, file2: str) -> bool:
    return file1 in file2 or file2 in file1


def partial_match_score(commit, stacktrace_files, exclude_files):
    partial_matches = []

    for f in commit["files"]:
        if f in exclude_files:
            continue

        for sf in stacktrace_files:
            if is_partial_match(f, sf):
                partial_matches.append(f)
                break

    score = 0
    if partial_matches:
        score += 2

    return score, partial_matches
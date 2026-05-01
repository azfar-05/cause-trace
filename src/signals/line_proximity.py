def line_proximity_score(commit, stacktrace_file_lines):
    score = 0
    seen_files = set()

    for file, line in stacktrace_file_lines:
        if file in commit.get("changed_lines", {}) and file not in seen_files:
            changed_lines = commit["changed_lines"][file]

            for cl in changed_lines:
                if abs(cl - line) <= 5:
                    score += 10
                    seen_files.add(file)
                    break

    return score
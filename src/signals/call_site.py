def call_site_breakage_score(commit, failure_functions):
    """
    Compute a structural signal based on overlap between modified functions
    and functions present in the failure stack trace.

    Includes:
    - Exact function match (strong signal)
    - Prefix-based similarity (weaker, captures related functions)

    Ignores generic function names to reduce noise.
    """

    if not failure_functions:
        return 0.0

    IGNORE = {"get", "set", "index", "run", "__init__", "__getitem__"}

    modified = {
        f for f in commit.get("modified_functions", [])
        if f not in IGNORE
    }

    failure_funcs = {
        f for f in failure_functions
        if f not in IGNORE
    }

    if not modified or not failure_funcs:
        return 0.0

    score = 0.0

    for cf in modified:
        for ff in failure_funcs:
            # Exact match (strong)
            if cf == ff:
                score += 8

            # Prefix similarity (captures related lifecycle functions)
            else:
                min_len = min(len(cf), len(ff), 12)
                if cf[:min_len] == ff[:min_len]:
                    score += 4

    return score
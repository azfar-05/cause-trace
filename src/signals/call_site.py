CALLER_CALLEE_BONUS = 3.0


def call_site_breakage_score(commit, failure_functions, include_breakdown=False):
    """
    Compute a structural signal based on overlap between modified functions
    and functions present in the failure stack trace.

    Includes:
    - Exact function match (strong signal)
    - Prefix-based similarity (weaker, captures related functions)
    - Caller/callee adjacency: stack-trace function calls a modified function
      within the same changed file (weaker than exact, stronger than partial match)

    Ignores generic function names to reduce noise.
    """

    if not failure_functions:
        if include_breakdown:
            return 0.0, 0.0
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
        if include_breakdown:
            return 0.0, 0.0
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

    # Structural caller/callee adjacency: (failure_fn, modified_fn) pair
    # exists in the changed file — stack-trace function calls modified function
    caller_callee_score = 0.0
    structural_pairs = commit.get("structural_call_pairs", set())
    if structural_pairs:
        for ff in failure_funcs:
            for mf in modified:
                if (ff, mf) in structural_pairs:
                    caller_callee_score += CALLER_CALLEE_BONUS

    score += caller_callee_score

    if include_breakdown:
        return score, caller_callee_score
    return score
def call_site_breakage_score(commit, failure_functions):
    """
    Detect if commit modified functions that are used in the failure stack trace.
    """

    if not failure_functions:
        return 0

    modified = set(commit.get("modified_functions", []))
    failure_funcs = set(failure_functions)

    overlap = modified.intersection(failure_funcs)

    if overlap:
        return 7  # moderate-strong signal

    return 0
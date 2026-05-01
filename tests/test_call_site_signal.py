from src.matcher import rank_commits


def test_call_site_breakage_prioritized():
    commits = [
        {
            "hash": "1",
            "files": ["utils.py"],  #  does not match failure file
            "message": "",
            "timestamp": 1000,
            "changed_lines": {},
            "modified_functions": ["validate_token"],  #  key
        },
        {
            "hash": "2",
            "files": ["auth.py"],  # direct file match
            "message": "",
            "timestamp": 900,
            "changed_lines": {},
            "modified_functions": [],  # no structural signal
        },
    ]

    stacktrace_files = ["auth.py"]
    stacktrace_file_lines = []
    failure_functions = ["validate_token"]

    ranked = rank_commits(
        commits,
        stacktrace_files,
        stacktrace_file_lines,
        failure_functions
    )

    # This is the key expectation
    assert ranked[0]["hash"] == "1"
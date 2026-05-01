from src.matcher import rank_commits


def test_rank_commits_basic():
    commits = [
        {"hash": "1", "files": ["main.py"], "message": "", "timestamp": 1000},
        {"hash": "2", "files": ["utils.py"], "message": "", "timestamp": 1000},
    ]

    stacktrace_files = ["main.py"]
    stacktrace_file_lines = []
    failure_functions = []  # ✅ move inside function

    ranked = rank_commits(
        commits,
        stacktrace_files,
        stacktrace_file_lines,
        failure_functions
    )

    assert ranked[0]["hash"] == "1"
    assert ranked[0]["score"] > ranked[1]["score"]
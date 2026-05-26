from src.signals.line_proximity import line_proximity_score


def test_line_proximity_hit():
    commit = {
        "changed_lines": {
            "auth.py": [10, 20, 30]
        }
    }
    stacktrace = [("auth.py", 22)]  # close to line 20
    score = line_proximity_score(commit, stacktrace, matching_files=["auth.py"])
    assert score == 10


def test_line_proximity_no_hit():
    commit = {
        "changed_lines": {
            "auth.py": [100, 200]
        }
    }
    stacktrace = [("auth.py", 10)]
    score = line_proximity_score(commit, stacktrace, matching_files=["auth.py"])
    assert score == 0


def test_line_proximity_dedup_per_file():
    commit = {
        "changed_lines": {
            "auth.py": [20, 21, 22]
        }
    }
    stacktrace = [
        ("auth.py", 20),
        ("auth.py", 21),
        ("auth.py", 22),
    ]
    score = line_proximity_score(commit, stacktrace, matching_files=["auth.py"])
    assert score == 10  # NOT 30
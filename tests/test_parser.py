from src.parser import extract_files_from_stacktrace
failure_functions = []

def test_extract_files_basic():
    stacktrace = """
    Error at auth.js:45
    at login (auth.js:45)
    at main (index.js:10)
    """

    files = extract_files_from_stacktrace(stacktrace)

    assert "auth.js" in files
    assert "index.js" in files


def test_extract_files_empty():
    stacktrace = "No file info here"

    files = extract_files_from_stacktrace(stacktrace)

    assert files == []
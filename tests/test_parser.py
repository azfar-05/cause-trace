from src.parser import extract_files_from_stacktrace


def test_extract_files():
    stacktrace = """
    Error at auth.js:45
    at login (auth.js:45)
    at main (index.js:10)
    """

    files = extract_files_from_stacktrace(stacktrace)

    assert "auth.js" in files
    assert "index.js" in files
    print(files)


if __name__ == "__main__":
    test_extract_files()
import re
from typing import List, Tuple


def extract_files_from_stacktrace(stacktrace: str) -> List[str]:
    """
    Extract file names from stack trace lines.

    Supports patterns like:
    - file.py:123
    - path/to/file.py:123
    """

    pattern = r'([\w\/\.-]+\.\w+):\d+'
    matches = re.findall(pattern, stacktrace)

    files = {match.split("/")[-1] for match in matches}
    return list(files)


def extract_functions_from_stacktrace(stacktrace: str) -> List[str]:
    """
    Extract function names from stack traces.

    Supports:
    - JavaScript: at function_name (file.js:line)
    - Python: in function_name
    """

    # JS style: at func_name (...)
    js_pattern = r'at\s+([A-Za-z_][A-Za-z0-9_]*)\s*\('

    # Python style: in func_name
    py_pattern = r'in\s+([A-Za-z_][A-Za-z0-9_]*)'

    matches = re.findall(js_pattern, stacktrace)
    matches += re.findall(py_pattern, stacktrace)

    return list(set(matches))


def extract_file_line_pairs(stacktrace: str) -> List[Tuple[str, int]]:
    """
    Extract (file, line) pairs from stack trace.

    Returns:
        List of (filename, line_number)
    """

    pattern = r'([\w\/\.-]+\.\w+):(\d+)'
    matches = re.findall(pattern, stacktrace)

    pairs = {
        (file.split("/")[-1], int(line))
        for file, line in matches
    }

    return list(pairs)


if __name__ == "__main__":
    sample_trace = """
    Traceback (most recent call last):
      File "app.py", line 20, in login
      File "utils.py", line 45, in validate_token
    """

    print("Files:", extract_files_from_stacktrace(sample_trace))
    print("Functions:", extract_functions_from_stacktrace(sample_trace))
    print("File-Line Pairs:", extract_file_line_pairs(sample_trace))
import re
from typing import List, Tuple


def extract_files_from_stacktrace(stacktrace: str) -> List[str]:
    colon_pattern = r'([\w\/\.-]+\.\w+):\d+'
    python_pattern = r'File\s+"([^"]+\.\w+)",\s+line\s+\d+'
    matches = re.findall(colon_pattern, stacktrace)
    matches += re.findall(python_pattern, stacktrace)
    files = list(set(matches))
    return files


def extract_functions_from_stacktrace(stacktrace: str) -> List[str]:
    """
    Extract function names from both JS and Python stack traces.

    Supports:
    - JS: at function_name (file.js:line)
    - Python: in function_name
    """

    # JS style
    js_pattern = r'at\s+([A-Za-z_][A-Za-z0-9_]*)\s*\('

    # Python style: only match "in <name>" at end of a traceback File line
    py_pattern = r'File\s+"[^"]+",\s+line\s+\d+,\s+in\s+([A-Za-z_][A-Za-z0-9_]*)'

    matches = re.findall(js_pattern, stacktrace)
    matches += re.findall(py_pattern, stacktrace)

    return list(set(matches))


def extract_file_line_pairs(stacktrace: str) -> List[Tuple[str, int]]:
    colon_pattern = r'([\w\/\.-]+\.\w+):(\d+)'
    python_pattern = r'File\s+"([^"]+\.\w+)",\s+line\s+(\d+)'
    matches = re.findall(colon_pattern, stacktrace)
    matches += re.findall(python_pattern, stacktrace)
    pairs = set((file, int(line)) for file, line in matches)
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

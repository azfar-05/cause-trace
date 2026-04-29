import re
from typing import List, Tuple


def extract_files_from_stacktrace(stacktrace: str) -> List[str]:
    """
    Extract unique file names from a stack trace.

    Args:
        stacktrace (str): Raw stack trace text

    Returns:
        List[str]: List of unique file names
    """
    pattern = r'([\w\/\.-]+\.\w+):\d+'
    matches = re.findall(pattern, stacktrace)

    # Normalize + deduplicate
    files = list(set([match.split("/")[-1] for match in matches]))

    return files


def extract_file_line_pairs(stacktrace: str) -> List[Tuple[str, int]]:
    """
    Extract (file, line number) pairs from stack trace.

    Args:
        stacktrace (str): Raw stack trace text

    Returns:
        List[Tuple[str, int]]: List of (file, line) tuples
    """
    pattern = r'([\w\/\.-]+\.\w+):(\d+)'
    matches = re.findall(pattern, stacktrace)

    result = [(file.split("/")[-1], int(line)) for file, line in matches]

    return result


if __name__ == "__main__":
    sample_trace = """
    Error: NullPointerException at auth.js:45
        at login (auth.js:45)
        at main (index.js:10)
    """

    print("Files:", extract_files_from_stacktrace(sample_trace))
    print("File-Line Pairs:", extract_file_line_pairs(sample_trace))
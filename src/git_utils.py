from git import Repo, GitCommandError, NULL_TREE
from typing import Dict, List, Optional, Set, Tuple
import subprocess
import re
import time

# Accumulated per-run timing. Reset by evaluation_runner before each case.
timing: Dict[str, float] = {
    "iter_commits": 0.0,
    "diff_extract": 0.0,
    "changed_lines": 0.0,
    "fetch_file": 0.0,
    "fn_extract": 0.0,
    "structural_pairs": 0.0,
}


def reset_timing() -> None:
    for k in timing:
        timing[k] = 0.0


def get_commits_in_range(repo_path: str, start_commit: str, end_commit: str):
    """
    Return commits in the range (start_commit, end_commit].
    """
    repo = Repo(repo_path)

    try:
        return list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    except GitCommandError:
        raise Exception(f"Invalid commit range: {start_commit}..{end_commit}")


def get_changed_lines(repo_path: str, commit_hash: str):
    """
    Extract changed line numbers per file using `git show --unified=0`.
    Returns:
        { filename: [line_numbers] }
    """
    changed = {}

    try:
        result = subprocess.run(
            ["git", "show", commit_hash, "--unified=0"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return changed

    current_file = None

    for line in result.stdout.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line.replace("+++ b/", "").split("/")[-1]

        elif line.startswith("@@") and current_file:
            parts = line.split(" ")
            for p in parts:
                if p.startswith("+"):
                    try:
                        start_line = int(p.split(",")[0][1:])
                        changed.setdefault(current_file, []).append(start_line)
                    except Exception:
                        pass
                    break

    return changed


def _fetch_file_at_commit(
    repo_path: str, commit_hash: str, filepath: str
) -> Optional[List[str]]:
    try:
        result = subprocess.run(
            ["git", "show", f"{commit_hash}:{filepath}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def _enclosing_functions_from_lines(
    file_lines: List[str], line_numbers: List[int]
) -> List[str]:
    functions = set()
    for line_num in line_numbers:
        for i in range(min(line_num - 1, len(file_lines) - 1), -1, -1):
            m = re.match(r"\s*def\s+(\w+)\s*\(", file_lines[i])
            if m:
                functions.add(m.group(1))
                break
    return list(functions)


def find_enclosing_functions(
    repo_path: str, commit_hash: str, filepath: str, line_numbers: List[int]
) -> List[str]:
    """
    Find enclosing Python function names for a set of changed line numbers.

    Reads the file content at the given commit and scans backward from each
    line number to find the nearest enclosing def. Handles both module-level
    functions and class methods.
    """
    file_lines = _fetch_file_at_commit(repo_path, commit_hash, filepath)
    if file_lines is None:
        return []
    return _enclosing_functions_from_lines(file_lines, line_numbers)


def find_structural_call_pairs(
    file_lines: List[str],
    modified_fn_names: Set[str],
) -> Set[Tuple[str, str]]:
    """
    Scan a file for functions that call any modified function.

    Returns pairs of (caller_function, called_modified_function).
    Bounded to the file — does not resolve imports or traverse call graphs.
    Self-calls (caller == callee) are excluded.
    """
    pairs: Set[Tuple[str, str]] = set()
    current_fn: Optional[str] = None

    for line in file_lines:
        stripped = line.lstrip()
        m = re.match(r"def\s+(\w+)\s*\(", stripped)
        if m:
            current_fn = m.group(1)
            continue

        if current_fn:
            for target in modified_fn_names:
                if current_fn != target and re.search(
                    rf"\b{re.escape(target)}\s*\(", line
                ):
                    pairs.add((current_fn, target))

    return pairs


def get_commit_metadata(repo_path: str, start_commit: str, end_commit: str) -> List[Dict]:
    """
    Lightweight first pass: collect only filenames, full-path map, and timestamps.

    Uses create_patch=False so no patch content is loaded — O(commits) cheap git
    metadata reads only.  Each returned dict contains two private fields consumed
    by enrich_commits():
        _hexsha        — full 40-char hash needed for subprocess calls
        _full_path_map — basename → repo-relative path for Python files

    Call narrow_candidates() on the result, then pass the narrowed list to
    enrich_commits() so expensive extraction runs only on surviving candidates.
    """
    repo = Repo(repo_path)

    _t = time.perf_counter()
    try:
        commits = list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    except GitCommandError:
        raise Exception(f"Invalid commit range: {start_commit}..{end_commit}")
    timing["iter_commits"] += time.perf_counter() - _t

    if not commits:
        return []

    result = []
    for commit in commits:
        files: set = set()
        full_path_map: Dict[str, str] = {}

        _t = time.perf_counter()
        if not commit.parents:
            diffs = commit.diff(NULL_TREE, create_patch=False)
        else:
            diffs = commit.diff(commit.parents[0], create_patch=False)

        for diff in diffs:
            if diff.a_path:
                files.add(diff.a_path.split("/")[-1])
            if diff.b_path:
                basename = diff.b_path.split("/")[-1]
                files.add(basename)
                if diff.b_path.endswith(".py"):
                    full_path_map[basename] = diff.b_path
        timing["diff_extract"] += time.perf_counter() - _t

        result.append({
            "hash":                 commit.hexsha[:7],
            "message":              commit.message.strip(),
            "files":                list(files),
            "timestamp":            commit.committed_date,
            # Populated by enrich_commits():
            "changed_lines":        {},
            "modified_functions":   [],
            "structural_call_pairs": set(),
            # Private — consumed and removed by enrich_commits():
            "_hexsha":        commit.hexsha,
            "_full_path_map": full_path_map,
        })

    return result


def enrich_commits(repo_path: str, commits: List[Dict]) -> List[Dict]:
    """
    Full second pass: extract changed lines, modified functions, and structural
    call pairs.  Runs only on the commits passed in — call after narrow_candidates()
    so expensive work is bounded to the surviving candidate set.

    Consumes and removes the _hexsha and _full_path_map private fields added by
    get_commit_metadata().
    """
    if not commits:
        return commits

    repo = Repo(repo_path)

    for commit in commits:
        hexsha        = commit.pop("_hexsha")
        full_path_map = commit.pop("_full_path_map")

        # Load patch for this commit to extract modified function names
        _t = time.perf_counter()
        repo_commit = repo.commit(hexsha)
        if not repo_commit.parents:
            diffs = repo_commit.diff(NULL_TREE, create_patch=True)
        else:
            diffs = repo_commit.diff(repo_commit.parents[0], create_patch=True)

        modified_functions: Set[str] = set()
        for diff in diffs:
            if diff.diff:
                patch_text = diff.diff.decode("utf-8", errors="ignore")
                modified_functions.update(extract_modified_functions_from_patch(patch_text))
        timing["diff_extract"] += time.perf_counter() - _t

        _t = time.perf_counter()
        changed_lines = get_changed_lines(repo_path, hexsha)
        timing["changed_lines"] += time.perf_counter() - _t

        file_cache: Dict[str, List[str]] = {}
        for basename, lines in changed_lines.items():
            full_path = full_path_map.get(basename)
            if not full_path or not lines:
                continue

            _t = time.perf_counter()
            file_lines = _fetch_file_at_commit(repo_path, hexsha, full_path)
            timing["fetch_file"] += time.perf_counter() - _t

            if file_lines is None:
                continue
            file_cache[basename] = file_lines

            _t = time.perf_counter()
            modified_functions.update(_enclosing_functions_from_lines(file_lines, lines))
            timing["fn_extract"] += time.perf_counter() - _t

        structural_call_pairs: Set[Tuple[str, str]] = set()
        _t = time.perf_counter()
        for file_lines in file_cache.values():
            structural_call_pairs.update(
                find_structural_call_pairs(file_lines, modified_functions)
            )
        timing["structural_pairs"] += time.perf_counter() - _t

        commit["changed_lines"]        = changed_lines
        commit["modified_functions"]   = list(modified_functions)
        commit["structural_call_pairs"] = structural_call_pairs

    return commits


def get_commit_changes(repo_path: str, start_commit: str, end_commit: str) -> List[Dict]:
    """
    Extract structured commit data for scoring.
    Includes:
    - files touched
    - changed lines
    - modified functions (heuristic)
    """
    repo = Repo(repo_path)

    _t = time.perf_counter()
    try:
        commits = list(repo.iter_commits(f"{start_commit}..{end_commit}"))
    except GitCommandError:
        raise Exception(f"Invalid commit range: {start_commit}..{end_commit}")
    timing["iter_commits"] += time.perf_counter() - _t

    if not commits:
        return []

    result = []

    for commit in commits:
        files = set()
        modified_functions = set()
        full_path_map: Dict[str, str] = {}  # basename -> full repo path for Python files

        # Extract diffs with patch
        _t = time.perf_counter()
        if not commit.parents:
            diffs = commit.diff(NULL_TREE, create_patch=True)
        else:
            diffs = commit.diff(commit.parents[0], create_patch=True)

        for diff in diffs:
            if diff.a_path:
                files.add(diff.a_path.split("/")[-1])
            if diff.b_path:
                basename = diff.b_path.split("/")[-1]
                files.add(basename)
                if diff.b_path.endswith(".py"):
                    full_path_map[basename] = diff.b_path

            if diff.diff:
                patch_text = diff.diff.decode("utf-8", errors="ignore")
                modified_functions.update(
                    extract_modified_functions_from_patch(patch_text)
                )
        timing["diff_extract"] += time.perf_counter() - _t

        _t = time.perf_counter()
        changed_lines = get_changed_lines(repo_path, commit.hexsha)
        timing["changed_lines"] += time.perf_counter() - _t

        # First pass: fetch file content once per Python file, resolve enclosing functions
        file_cache: Dict[str, List[str]] = {}
        for basename, lines in changed_lines.items():
            full_path = full_path_map.get(basename)
            if not full_path or not lines:
                continue

            _t = time.perf_counter()
            file_lines = _fetch_file_at_commit(repo_path, commit.hexsha, full_path)
            timing["fetch_file"] += time.perf_counter() - _t

            if file_lines is None:
                continue
            file_cache[basename] = file_lines

            _t = time.perf_counter()
            modified_functions.update(_enclosing_functions_from_lines(file_lines, lines))
            timing["fn_extract"] += time.perf_counter() - _t

        # Second pass: find structural call pairs with complete modified_functions
        structural_call_pairs: Set[Tuple[str, str]] = set()
        _t = time.perf_counter()
        for file_lines in file_cache.values():
            structural_call_pairs.update(
                find_structural_call_pairs(file_lines, modified_functions)
            )
        timing["structural_pairs"] += time.perf_counter() - _t

        result.append({
            "hash": commit.hexsha[:7],
            "message": commit.message.strip(),
            "files": list(files),
            "timestamp": commit.committed_date,
            "changed_lines": changed_lines,
            "modified_functions": list(modified_functions),
            "structural_call_pairs": structural_call_pairs,
        })

    return result


def extract_modified_functions_from_patch(patch_text: str):
    """
    Heuristically detect functions whose bodies were modified.

    Strategy:
    - Track current function context from definitions
    - Assign added lines ('+') to the most recent function
    - Supports Python and common JavaScript patterns
    """
    functions = set()
    current_function = None

    for line in patch_text.split("\n"):
        # Python: def func(
        py_match = re.search(r"def\s+(\w+)\s*\(", line)
        if py_match:
            current_function = py_match.group(1)
            continue

        # JS: function func(
        js_match = re.search(r"function\s+(\w+)\s*\(", line)
        if js_match:
            current_function = js_match.group(1)
            continue

        # JS arrow: const fn = (...) =>
        arrow_match = re.search(r"(\w+)\s*=\s*\(?.*\)?\s*=>", line)
        if arrow_match:
            current_function = arrow_match.group(1)
            continue

        # Assign added lines to current function
        if line.startswith("+") and current_function:
            functions.add(current_function)

    return list(functions)
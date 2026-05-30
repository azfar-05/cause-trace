"""
Shared deterministic investigation pipeline.

Encapsulates the five stages common to both the CLI (main.py) and the
benchmark runner (evaluation_runner.py):

    parse → get_commit_metadata → narrow_candidates → enrich_commits → rank_commits

Narrowing runs on lightweight commit metadata (filenames + timestamps only).
Full extraction — changed lines, modified functions, structural call pairs —
runs only on the narrowed candidate set, not the entire commit window.

Both callers use run_pipeline() and handle their own output, timing,
and AI explanation logic around it.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.git_utils import enrich_commits, get_commit_metadata
from src.matcher import rank_commits
from src.narrower import narrow_candidates
from src.parser import (
    extract_file_line_pairs,
    extract_files_from_stacktrace,
    extract_functions_from_stacktrace,
)


@dataclass
class PipelineResult:
    files: List[str]
    file_line_pairs: List[Tuple[str, int]]
    functions: List[str]
    ranked: List[Dict]
    narrow_stats: Dict


def run_pipeline(
    repo_path: str,
    good_commit: str,
    bad_commit: str,
    stacktrace: str,
) -> PipelineResult:
    """
    Execute the shared deterministic pipeline and return structured results.

    Does not validate commit ancestry, produce output, apply instrumentation,
    or invoke the AI explanation layer — those are caller responsibilities.
    """
    files = extract_files_from_stacktrace(stacktrace)
    file_line_pairs = extract_file_line_pairs(stacktrace)
    functions = extract_functions_from_stacktrace(stacktrace)

    metadata = get_commit_metadata(repo_path, good_commit, bad_commit)
    narrowed, narrow_stats = narrow_candidates(metadata, files)
    enriched = enrich_commits(repo_path, narrowed)
    ranked = rank_commits(enriched, files, file_line_pairs, functions)

    return PipelineResult(
        files=files,
        file_line_pairs=file_line_pairs,
        functions=functions,
        ranked=ranked,
        narrow_stats=narrow_stats,
    )

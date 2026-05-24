"""
CauseTrace — CLI investigation entry point.

Usage:
    python main.py --repo flask --good <commit> --bad <commit> --trace stacktrace.txt
    python main.py --repo urllib3 --good <commit> --bad <commit>   # reads trace from stdin
"""

import argparse
import os
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

from src.git_utils import get_commit_changes
from src.matcher import RECENCY_WEIGHT, rank_commits
from src.parser import (
    extract_file_line_pairs,
    extract_files_from_stacktrace,
    extract_functions_from_stacktrace,
)
from src.signals.scorer import score_commit


REPOS_ROOT = os.environ.get("CAUSETRACE_REPOS_ROOT", os.path.expanduser("~"))

W = 68  # output width


# ── terminal helpers ──────────────────────────────────────────────────────────

def rule(char: str = "─") -> None:
    print(char * W)


def section(title: str) -> None:
    print()
    rule()
    print(f"  {title}")
    rule()


def blank() -> None:
    print()


# ── deterministic explanation ─────────────────────────────────────────────────

def _find_closest_line(
    commit: Dict,
    matched_files: List[str],
    stacktrace_file_lines: List[Tuple[str, int]],
) -> Optional[Tuple[str, int, int, int]]:
    """Return (filename, changed_line, failure_line, delta) for the closest match."""
    changed = commit.get("changed_lines", {})
    matched_basenames = {f.split("/")[-1] for f in matched_files}

    best: Optional[Tuple[int, str, int, int, int]] = None  # (delta, file, cl, fl, _)
    for sf, fl in stacktrace_file_lines:
        bn = sf.split("/")[-1]
        if bn not in matched_basenames:
            continue
        for cl in changed.get(bn, []):
            delta = abs(cl - fl)
            if delta <= 5:
                if best is None or delta < best[0]:
                    best = (delta, bn, cl, fl, 0)

    if best:
        delta, bn, cl, fl, _ = best
        return bn, cl, fl, delta
    return None


def generate_why(
    breakdown: Dict,
    matched_files: List[str],
    failure_functions: List[str],
    stacktrace_file_lines: List[Tuple[str, int]],
    commit: Dict,
) -> str:
    parts: List[str] = []

    line_score = breakdown.get("line", 0)
    fn_score = breakdown.get("function", 0)
    cc_score = breakdown.get("caller_callee", 0)
    file_score = breakdown.get("file", 0)

    # Line proximity — strongest, mention explicitly
    if line_score > 0:
        hit = _find_closest_line(commit, matched_files, stacktrace_file_lines)
        if hit:
            fname, cl, fl, delta = hit
            if delta == 0:
                parts.append(
                    f"{fname} was modified at line {cl}, exactly the failure line."
                )
            else:
                parts.append(
                    f"{fname} was modified at line {cl}, within {delta} line(s) of the failure at {fl}."
                )

    # Function overlap
    if fn_score > 0 and failure_functions:
        modified = set(commit.get("modified_functions", []))
        exact = [f for f in failure_functions if f in modified]
        if exact:
            fns = ", ".join(f"{f}()" for f in exact[:2])
            parts.append(f"{fns} was modified and appears in the failure trace.")

    # Caller-callee structural relationship
    if cc_score > 0:
        parts.append(
            "A caller of the modified function was also changed"
            " (structural caller-callee link)."
        )

    # File-only match (no line/function hit)
    if not parts and file_score > 0 and matched_files:
        names = ", ".join(f.split("/")[-1] for f in matched_files[:2])
        parts.append(
            f"{names} appears in the failure trace but no line or function overlap was found."
            " Low-precision match."
        )

    # Nothing matched — recency-only ranking
    if not parts:
        parts.append(
            "No direct file, line, or function overlap found. Ranked by recency."
        )

    return "  ".join(parts)


# ── score with full breakdown ─────────────────────────────────────────────────

def _recency_scores(commits: Sequence[Dict]) -> Dict[str, float]:
    if not commits:
        return {}
    timestamps = [c.get("timestamp", 0) for c in commits]
    lo, hi = min(timestamps), max(timestamps)
    def norm(ts: int) -> float:
        return 1.0 if lo == hi else (ts - lo) / (hi - lo)
    return {c["hash"]: round(norm(c.get("timestamp", 0)) * RECENCY_WEIGHT, 2) for c in commits}


def _ranked_with_breakdown(
    commits: List[Dict],
    files: List[str],
    file_line_pairs: List[Tuple[str, int]],
    functions: List[str],
) -> List[Dict]:
    recency = _recency_scores(commits)
    out = []
    for c in commits:
        _, bd = score_commit(c, files, file_line_pairs, functions, include_breakdown=True)
        bd["recency"] = recency.get(c["hash"], 0.0)
        bd["final"] = c["score"]  # already on the ranked commit from rank_commits
        out.append({**c, "breakdown": bd})
    return out


# ── output formatting ─────────────────────────────────────────────────────────

def _signal_row(label: str, detail: str, value: float, fired: bool) -> None:
    if value == 0.0:
        val_str = "   —"
    elif value > 0:
        val_str = f"+{value:.1f}"
    else:
        val_str = f"{value:.1f}"
    prefix = "  ✓" if fired else "   "
    left = f"{prefix}  {label:<13}  {detail}"
    right = val_str.rjust(W - len(left) - 2)
    # clamp if too long
    if len(left) + len(right) + 2 > W:
        left = left[:W - len(right) - 3] + "…"
    print(f"{left}  {right}")


def print_commit_block(
    rank: int,
    commit: Dict,
    matched_files: List[str],
    failure_functions: List[str],
    stacktrace_file_lines: List[Tuple[str, int]],
) -> None:
    bd = commit["breakdown"]
    hash_short = commit["hash"][:7]
    msg = commit["message"].splitlines()[0][:46]
    score_str = f"score {commit['score']:.2f}"

    # Commit header line
    left = f"  #{rank}  {hash_short}  {msg}"
    right = score_str.rjust(W - len(left))
    if len(left) + len(right) > W:
        left = left[:W - len(right) - 1] + "…"
    blank()
    print(f"{left}{right}")

    # Signals
    blank()
    print("      Signals")

    file_score = bd.get("file", 0)
    _signal_row(
        "file",
        f"{', '.join(f.split('/')[-1] for f in matched_files[:2]) or '—'} in trace",
        file_score,
        fired=file_score > 0,
    )

    line_score = bd.get("line", 0)
    hit = _find_closest_line(commit, matched_files, stacktrace_file_lines)
    if hit:
        _, cl, fl, delta = hit
        line_detail = f"Δ={delta}  ·  changed {cl}, failure {fl}"
    else:
        line_detail = "no match"
    _signal_row("line", line_detail, line_score, fired=line_score > 0)

    fn_score = bd.get("function", 0)
    modified = set(commit.get("modified_functions", []))
    matched_fns = [f for f in failure_functions if f in modified][:2]
    fn_detail = f"{', '.join(matched_fns)}()" if matched_fns else "no match"
    _signal_row("function", fn_detail, fn_score, fired=fn_score > 0)

    cc_score = bd.get("caller_callee", 0)
    _signal_row("caller-callee", "structural link" if cc_score > 0 else "none", cc_score, fired=cc_score > 0)

    recency = bd.get("recency", 0)
    _signal_row("recency", f"{recency:.2f} of {RECENCY_WEIGHT:.1f}", recency, fired=False)

    penalty = bd.get("size_penalty", 0)
    n_files = len(commit.get("files", []))
    _signal_row("size", f"{n_files} file(s) changed", -penalty, fired=False)

    # Why
    why = generate_why(bd, matched_files, failure_functions, stacktrace_file_lines, commit)
    blank()
    print("      Why")
    # wrap at ~58 chars
    words = why.split()
    line_buf: List[str] = []
    indent = "        "
    for word in words:
        candidate = " ".join(line_buf + [word])
        if len(candidate) > 56:
            print(f"{indent}{' '.join(line_buf)}")
            line_buf = [word]
        else:
            line_buf.append(word)
    if line_buf:
        print(f"{indent}{' '.join(line_buf)}")

    blank()


# ── main investigation flow ───────────────────────────────────────────────────

def is_ancestor(repo_path: str, good: str, bad: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", good, bad],
        cwd=repo_path,
        capture_output=True,
    )
    return result.returncode == 0


def short(h: str) -> str:
    return h[:12] if len(h) > 12 else h


def investigate(
    repo_name: str,
    repo_path: str,
    good_commit: str,
    bad_commit: str,
    stacktrace: str,
    top_n: int = 5,
) -> int:
    """Run the investigation and print results. Returns 0 on success."""

    # ── Parse stacktrace ──────────────────────────────────────────────────────
    files = extract_files_from_stacktrace(stacktrace)
    file_line_pairs = extract_file_line_pairs(stacktrace)
    functions = extract_functions_from_stacktrace(stacktrace)

    # ── Validate range ────────────────────────────────────────────────────────
    if not is_ancestor(repo_path, good_commit, bad_commit):
        print(f"error: {short(good_commit)} is not an ancestor of {short(bad_commit)}", file=sys.stderr)
        return 1

    # ── Pull commits ──────────────────────────────────────────────────────────
    commits = get_commit_changes(repo_path, good_commit, bad_commit)
    if not commits:
        print("No commits found in the specified range.", file=sys.stderr)
        return 1

    ranked = rank_commits(commits, files, file_line_pairs, functions)
    ranked_bd = _ranked_with_breakdown(ranked, files, file_line_pairs, functions)

    # ── Header ────────────────────────────────────────────────────────────────
    blank()
    rule("═")
    print(f"  CauseTrace  ·  Failure Investigation")
    rule("═")
    blank()
    print(f"  Repo      {repo_name}  ·  {repo_path}")
    print(f"  Window    {short(good_commit)}..{short(bad_commit)}  ({len(commits)} commit(s) analyzed)")

    # Failure context from parsed trace
    trace_files_short = [f.split("/")[-1] for f in files]
    trace_line_refs = [f"{f.split('/')[-1]}:{l}" for f, l in file_line_pairs]
    trace_fns = [f for f in functions if f not in {"in", "File", "line"}]

    if trace_files_short:
        print(f"  Files     {', '.join(trace_files_short[:4])}")
    if trace_fns:
        print(f"  Functions {', '.join(trace_fns[:4])}")
    if trace_line_refs:
        print(f"  Lines     {', '.join(trace_line_refs[:4])}")

    # ── Ranked commits ────────────────────────────────────────────────────────
    section("CULPRIT CANDIDATES")

    shown = 0
    for i, commit in enumerate(ranked_bd[:top_n], 1):
        if i > 1:
            rule("·")
        matched = []
        for sf in files:
            bn = sf.split("/")[-1]
            if any(f.split("/")[-1] == bn for f in commit.get("files", [])):
                matched.append(sf)

        print_commit_block(i, commit, matched, functions, file_line_pairs)
        shown += 1

    if shown == 0:
        blank()
        print("  No commits scored positively against the failure trace.")
        blank()

    # ── Parsed trace summary ──────────────────────────────────────────────────
    section("PARSED FROM TRACE")
    blank()
    if files:
        print(f"  Files      {', '.join(files)}")
    else:
        print("  Files      (none extracted)")
    if trace_fns:
        print(f"  Functions  {', '.join(trace_fns)}")
    else:
        print("  Functions  (none extracted)")
    if file_line_pairs:
        refs = [f"{f}:{l}" for f, l in file_line_pairs]
        print(f"  Line refs  {', '.join(refs)}")
    else:
        print("  Line refs  (none extracted)")
    blank()
    rule("═")
    blank()

    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="CauseTrace — deterministic failure triage",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("--repo", required=True, help="Repo name (resolved under CAUSETRACE_REPOS_ROOT)")
    ap.add_argument("--good", required=True, help="Last known-good commit")
    ap.add_argument("--bad",  required=True, help="First known-bad commit (culprit window end)")
    ap.add_argument("--trace", help="Path to stack trace file (reads stdin if omitted)")
    ap.add_argument("--top", type=int, default=5, help="Number of candidates to show (default: 5)")
    args = ap.parse_args()

    # Resolve repo path
    repo_path = os.path.join(REPOS_ROOT, args.repo)
    if not os.path.isdir(repo_path):
        print(f"error: repo not found at {repo_path}", file=sys.stderr)
        print(f"       set CAUSETRACE_REPOS_ROOT or clone {args.repo} under ~/", file=sys.stderr)
        sys.exit(1)

    # Read stacktrace
    if args.trace:
        with open(args.trace) as f:
            stacktrace = f.read()
    else:
        print("Paste stack trace (Ctrl+D when done):", file=sys.stderr)
        stacktrace = sys.stdin.read()

    sys.exit(investigate(args.repo, repo_path, args.good, args.bad, stacktrace, top_n=args.top))


if __name__ == "__main__":
    main()

"""
CauseTrace — CLI investigation entry point.

Usage:
    python main.py --repo flask --good <commit> --bad <commit> --trace stacktrace.txt
    python main.py --repo urllib3 --good <commit> --bad <commit>   # reads trace from stdin
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from src.git_utils import fetch_diff_excerpt
from src.investigation import PipelineResult, run_pipeline
from src.matcher import RECENCY_WEIGHT, recency_scores
from src.parser import build_stacktrace_summary
from src.signals.scorer import compute_confidence, score_commit

# LLM explanation — optional, only imported when --explain is passed
try:
    from src.explainer import Explanation, explain_top_commit
    _EXPLAIN_AVAILABLE = True
except ImportError:
    _EXPLAIN_AVAILABLE = False


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
    return recency_scores(commits)


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


def _print_wrapped(label: Optional[str], text: str) -> None:
    """Print a labelled paragraph wrapped at ~56 chars."""
    indent = "        "
    if label:
        print(f"        {label}:")
    words = text.split()
    line_buf: List[str] = []
    for word in words:
        candidate = " ".join(line_buf + [word])
        if len(candidate) > 56:
            print(f"{indent}{' '.join(line_buf)}")
            line_buf = [word]
        else:
            line_buf.append(word)
    if line_buf:
        print(f"{indent}{' '.join(line_buf)}")


def print_commit_block(
    rank: int,
    commit: Dict,
    matched_files: List[str],
    failure_functions: List[str],
    stacktrace_file_lines: List[Tuple[str, int]],
    explanation=None,
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
    blank()
    if explanation is not None:
        # AI-assisted explanation — two grounded fields + deterministic confidence
        print(f"      Why  [AI · confidence: {explanation.confidence}]")
        _print_wrapped("What changed", explanation.what_changed)
        _print_wrapped("Why related", explanation.why_related)
    else:
        # Deterministic fallback
        why = generate_why(bd, matched_files, failure_functions, stacktrace_file_lines, commit)
        print("      Why")
        _print_wrapped(None, why)

    blank()


# ── observation record ───────────────────────────────────────────────────────

def _write_observation_record(
    record_path: str,
    repo_name: str,
    good_commit: str,
    bad_commit: str,
    total_commits: int,
    files: List[str],
    file_line_pairs: List[Tuple[str, int]],
    trace_fns: List[str],
    narrow_stats: Dict,
    ranked_bd: List[Dict],
) -> None:
    top = ranked_bd[0] if ranked_bd else None
    bd = top.get("breakdown", {}) if top else {}

    source_files = [
        f for f in files
        if not (
            os.path.basename(f).startswith("test_")
            or "/tests/" in f
            or f.startswith("tests/")
        )
    ]

    record = {
        "id": f"obs-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "repo": repo_name,
        "acquisition": {
            "status": "success",
            "error_reason": None,
            "good_commit": good_commit,
            "bad_commit": bad_commit,
            "window_size": total_commits,
            "good_commit_source": "api",
        },
        "trace": {
            "depth": len(file_line_pairs),
            "contains_source_files": bool(source_files),
            "files_parsed": files,
            "functions_parsed": trace_fns,
            "has_line_numbers": bool(file_line_pairs),
        },
        "signals": {
            "file_overlap_fired": bd.get("file", 0) > 0,
            "function_signal_fired": bd.get("function", 0) > 0,
            "line_proximity_fired": bd.get("line", 0) > 0,
            "caller_callee_fired": bd.get("caller_callee", 0) > 0,
        },
        "ranking": {
            "top_commit": top["hash"] if top else None,
            "top_score": round(top["score"], 2) if top else None,
            "candidates_total": narrow_stats.get("narrowed", 0),
        },
        "outcome": {
            "fix_commit": None,
            "fix_commit_rank": None,
            "search_space_reduced": None,
            "causal_in_window": None,
            "notes": "",
        },
        "classification": {
            "failure_category": None,
            "gap_class": None,
            "in_scope": None,
        },
    }

    with open(record_path, "w") as fh:
        json.dump(record, fh, indent=2)


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
    use_explain: bool = False,
    record_path: Optional[str] = None,
) -> int:
    """Run the investigation and print results. Returns 0 on success."""

    # ── Validate range ────────────────────────────────────────────────────────
    if not is_ancestor(repo_path, good_commit, bad_commit):
        print(f"error: {short(good_commit)} is not an ancestor of {short(bad_commit)}", file=sys.stderr)
        return 1

    # ── Run pipeline ──────────────────────────────────────────────────────────
    pipe = run_pipeline(repo_path, good_commit, bad_commit, stacktrace)
    files, file_line_pairs, functions = pipe.files, pipe.file_line_pairs, pipe.functions
    narrow_stats = pipe.narrow_stats

    if pipe.narrow_stats["total"] == 0:
        print("No commits found in the specified range.", file=sys.stderr)
        return 1

    ranked_bd = _ranked_with_breakdown(pipe.ranked, files, file_line_pairs, functions)

    # ── Header ────────────────────────────────────────────────────────────────
    blank()
    rule("═")
    print(f"  CauseTrace  ·  Failure Investigation")
    rule("═")
    blank()
    print(f"  Repo      {repo_name}  ·  {repo_path}")
    total_commits = narrow_stats["total"]
    print(f"  Window    {short(good_commit)}..{short(bad_commit)}  ({total_commits} commit(s) in range)")
    if narrow_stats["reduction_pct"] > 0:
        print(
            f"  Narrowed  {narrow_stats['narrowed']} candidates"
            f"  ({narrow_stats['reduction_pct']}% filtered — file overlap + recency fallback)"
        )

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

    # Pre-compute AI explanation for top-1 commit only (if requested)
    top1_explanation = None
    if use_explain and ranked_bd:
        if not _EXPLAIN_AVAILABLE:
            print("  [explain] explainer not available in this build", file=sys.stderr)
        else:
            top = ranked_bd[0]
            matched_top = [sf for sf in files
                           if any(f.split("/")[-1] == sf.split("/")[-1]
                                  for f in top.get("files", []))]
            confidence = compute_confidence(top["breakdown"])
            diff_excerpt = fetch_diff_excerpt(repo_path, top["hash"], matched_top)
            stacktrace_summary = build_stacktrace_summary(files, file_line_pairs, functions)
            top1_explanation = explain_top_commit(
                commit=top,
                breakdown=top["breakdown"],
                stacktrace_summary=stacktrace_summary,
                diff_excerpt=diff_excerpt,
                confidence=confidence,
            )
            if top1_explanation is None:
                import os as _os
                if not _os.getenv("OPENROUTER_API_KEY"):
                    print("  [explain] OPENROUTER_API_KEY not set — falling back to generate_why()",
                          file=sys.stderr)
                else:
                    print("  [explain] AI explanation unavailable — falling back to generate_why()",
                          file=sys.stderr)

    shown = 0
    for i, commit in enumerate(ranked_bd[:top_n], 1):
        if i > 1:
            rule("·")
        matched = []
        for sf in files:
            bn = sf.split("/")[-1]
            if any(f.split("/")[-1] == bn for f in commit.get("files", [])):
                matched.append(sf)

        expl = top1_explanation if (i == 1) else None
        print_commit_block(i, commit, matched, functions, file_line_pairs, explanation=expl)
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

    if record_path:
        _write_observation_record(
            record_path=record_path,
            repo_name=repo_name,
            good_commit=good_commit,
            bad_commit=bad_commit,
            total_commits=total_commits,
            files=files,
            file_line_pairs=file_line_pairs,
            trace_fns=trace_fns,
            narrow_stats=narrow_stats,
            ranked_bd=ranked_bd,
        )

    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from src.cli_init import init_main
        init_main(sys.argv[2:])
        return

    ap = argparse.ArgumentParser(
        description="CauseTrace — deterministic failure triage",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("--repo", required=True, help="Repo name (resolved under CAUSETRACE_REPOS_ROOT)")
    ap.add_argument("--good", required=True, help="Last known-good commit")
    ap.add_argument("--bad",  required=True, help="First known-bad commit (culprit window end)")
    ap.add_argument("--trace", help="Path to stack trace file (reads stdin if omitted)")
    ap.add_argument("--top", type=int, default=5, help="Number of candidates to show (default: 5)")
    ap.add_argument(
        "--explain",
        action="store_true",
        default=False,
        help="Generate AI-assisted explanation for the top-ranked commit (requires OPENROUTER_API_KEY)",
    )
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

    sys.exit(investigate(
        args.repo, repo_path, args.good, args.bad, stacktrace,
        top_n=args.top, use_explain=args.explain,
    ))


if __name__ == "__main__":
    main()

"""
CauseTrace CI entrypoint.

Reads CI environment variables, resolves the commit window, extracts the
stack trace from CI test-runner output, and invokes the existing investigation
pipeline.  No attribution logic lives here — this file is a thin adapter.

Usage (typically invoked by a CI job step):
    python ci_runner.py --log test-output.txt [--top N] [--explain] [--output results.txt]
    cat test-output.txt | python ci_runner.py
"""

import argparse
import io
import os
import sys
from typing import Optional, Tuple

from src.ci_adapter import extract_trace_from_log, resolve_good_commit


# ── CI environment detection ───────────────────────────────────────────────────

def detect_ci_system() -> Optional[str]:
    """Return the active CI system name, or None if not in a recognized CI environment."""
    if os.environ.get("GITHUB_ACTIONS"):
        return "github"
    if os.environ.get("GITLAB_CI"):
        return "gitlab"
    if os.environ.get("JENKINS_URL"):
        return "jenkins"
    if os.environ.get("TF_BUILD"):  # Azure Pipelines
        return "azure"
    return None


def detect_bad_commit() -> Optional[str]:
    """Return the failing build's commit SHA from CI environment variables."""
    return (
        os.environ.get("GITHUB_SHA")
        or os.environ.get("CI_COMMIT_SHA")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("BUILD_SOURCEVERSION")
    )


def resolve_repo_path() -> str:
    """
    Return the repository path from CI workspace variables.
    Falls back to cwd for local testing when no CI variable is set.
    """
    return (
        os.environ.get("GITHUB_WORKSPACE")
        or os.environ.get("CI_PROJECT_DIR")
        or os.environ.get("WORKSPACE")
        or os.environ.get("BUILD_SOURCESDIRECTORY")
        or os.getcwd()
    )


def detect_branch() -> Optional[str]:
    """Return the current branch name from CI environment variables."""
    return (
        os.environ.get("GITHUB_REF_NAME")
        or os.environ.get("CI_COMMIT_REF_NAME")
        or os.environ.get("GIT_BRANCH")
        or os.environ.get("BUILD_SOURCEBRANCHNAME")
    )


def detect_repo_identity() -> Tuple[Optional[str], Optional[str]]:
    """Return (owner, repo_name) from CI environment variables."""
    # GitHub Actions: GITHUB_REPOSITORY = "owner/repo"
    gh_repo = os.environ.get("GITHUB_REPOSITORY")
    if gh_repo and "/" in gh_repo:
        owner, name = gh_repo.split("/", 1)
        return owner, name

    # GitLab CI: CI_PROJECT_PATH = "group/project"
    gl_path = os.environ.get("CI_PROJECT_PATH")
    if gl_path and "/" in gl_path:
        owner, name = gl_path.rsplit("/", 1)
        return owner, name

    # Jenkins
    jenkins_job = os.environ.get("JOB_NAME")
    if jenkins_job:
        return None, jenkins_job

    # Azure Pipelines
    azure_repo = os.environ.get("BUILD_REPOSITORY_NAME")
    if azure_repo:
        return None, azure_repo

    return None, None


# ── abort ──────────────────────────────────────────────────────────────────────

def abort(message: str) -> None:
    print(f"causetrace-ci: {message}", file=sys.stderr)
    sys.exit(1)


# ── tee writer for --output ────────────────────────────────────────────────────

class _TeeWriter:
    """Write to two streams simultaneously."""

    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary

    def write(self, data):
        self._primary.write(data)
        self._secondary.write(data)

    def flush(self):
        self._primary.flush()
        self._secondary.flush()

    def isatty(self):
        return getattr(self._primary, "isatty", lambda: False)()


# ── GitHub workflow filename extraction ───────────────────────────────────────

def _extract_github_workflow_filename() -> Optional[str]:
    """
    Return the workflow filename (e.g. 'causetrace.yml') from GITHUB_WORKFLOW_REF.

    GITHUB_WORKFLOW (the display name) is NOT a valid workflow identifier for the
    GitHub API — only the filename or integer ID are accepted.
    GITHUB_WORKFLOW_REF format: 'owner/repo/.github/workflows/name.yml@refs/...'
    """
    ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    marker = "/.github/workflows/"
    if marker in ref:
        return ref.split(marker)[-1].split("@")[0]
    return None


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="CauseTrace CI entrypoint — resolves CI context and runs investigation",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument(
        "--log",
        help="Path to CI test output log file (reads stdin if omitted)",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=5,
        help="Number of candidates to show (default: 5)",
    )
    ap.add_argument(
        "--explain",
        action="store_true",
        help="Generate AI explanation for the top-ranked commit (requires OPENROUTER_API_KEY)",
    )
    ap.add_argument(
        "--output",
        help="Write investigation results to this file in addition to stdout",
    )
    args = ap.parse_args()

    # ── Detect CI context ──────────────────────────────────────────────────────
    ci_system = detect_ci_system()
    bad_commit = detect_bad_commit()
    repo_path = resolve_repo_path()
    branch = detect_branch()
    repo_owner, repo_name = detect_repo_identity()

    # ── Read CI log ────────────────────────────────────────────────────────────
    if args.log:
        try:
            with open(args.log) as f:
                log_text = f.read()
        except OSError as exc:
            abort(f"cannot read log file {args.log!r}: {exc}")
    else:
        log_text = sys.stdin.read()

    # ── Resolve good_commit via CI API ─────────────────────────────────────────
    good_commit: Optional[str] = None
    if ci_system and repo_name and branch:
        workflow_id = _extract_github_workflow_filename() if ci_system == "github" else None
        good_commit = resolve_good_commit(
            ci_system=ci_system,
            repo_owner=repo_owner or "",
            repo_name=repo_name,
            branch=branch,
            workflow_id=workflow_id,
        )

    # ── Extract stack trace ────────────────────────────────────────────────────
    trace = extract_trace_from_log(log_text, repo_name or "")

    # ── Validate required inputs ───────────────────────────────────────────────
    if not bad_commit:
        abort(
            "could not determine bad_commit — set GITHUB_SHA, CI_COMMIT_SHA, "
            "GIT_COMMIT, or BUILD_SOURCEVERSION"
        )

    if not good_commit:
        abort(
            "could not resolve good_commit — no successful prior build found "
            "on this branch, or CI API is unavailable"
        )

    if not trace:
        abort(
            "no usable stack trace found in CI log — pass the test runner "
            "output via --log or stdin"
        )

    if good_commit == bad_commit:
        abort(
            f"good_commit and bad_commit are identical ({bad_commit[:12]}) "
            "— no commit window to investigate"
        )

    # ── Commit window validation ───────────────────────────────────────────────
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        abort(f"repo_path {repo_path!r} does not appear to be a git repository")

    import subprocess
    for commit, label in ((good_commit, "good_commit"), (bad_commit, "bad_commit")):
        result = subprocess.run(
            ["git", "cat-file", "-t", commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            abort(f"{label} {commit[:12]!r} does not exist in {repo_path!r}")

    # ── Run investigation ──────────────────────────────────────────────────────
    from main import investigate  # noqa: PLC0415

    display_name = repo_name or os.path.basename(repo_path)

    if args.output:
        buffer = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = _TeeWriter(original_stdout, buffer)
        try:
            rc = investigate(
                repo_name=display_name,
                repo_path=repo_path,
                good_commit=good_commit,
                bad_commit=bad_commit,
                stacktrace=trace,
                top_n=args.top,
                use_explain=args.explain,
            )
        finally:
            sys.stdout = original_stdout
        with open(args.output, "w") as f:
            f.write(buffer.getvalue())
    else:
        rc = investigate(
            repo_name=display_name,
            repo_path=repo_path,
            good_commit=good_commit,
            bad_commit=bad_commit,
            stacktrace=trace,
            top_n=args.top,
            use_explain=args.explain,
        )

    sys.exit(rc)


if __name__ == "__main__":
    main()

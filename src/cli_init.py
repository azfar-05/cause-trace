"""
causetrace init — inject CauseTrace analysis steps into GitHub Actions workflows.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
    _YAML_AVAILABLE = True

    class _CauseTraceDumper(yaml.Dumper):
        def ignore_aliases(self, data):
            return True

except ImportError:
    _YAML_AVAILABLE = False


_INJECTED_STEP_ID = "causetrace_test"
_CAUSETRACE_STEP_NAMES = frozenset({
    "Install CauseTrace",
    "Run CauseTrace investigation",
    "Upload CauseTrace results",
    "Surface test failure",
})

_TEST_RUN_PATTERNS = (
    "pytest",
    "python -m pytest",
    "tox",
    "nox",
    "npm test",
    "jest",
    "go test",
    "cargo test",
    "mvn test",
)

# Job names matching these patterns are skipped — they're linting/typing jobs,
# not test jobs, so CauseTrace analysis wouldn't be useful there.
_SKIP_JOB_NAME_PATTERNS = (
    "lint",
    "type",
    "typing",
    "mypy",
    "flake",
    "ruff",
    "format",
    "style",
    "check",
    "audit",
    "security",
    "docs",
)


# ── YAML output helpers ───────────────────────────────────────────────────────

class _LiteralStr(str):
    """Force PyYAML to emit this string with | block style."""


def _configure_dumper() -> None:
    def _literal_representer(dumper, data):
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")

    _CauseTraceDumper.add_representer(_LiteralStr, _literal_representer)


# ── step manipulation ─────────────────────────────────────────────────────────

def _is_test_step(step: Dict) -> bool:
    run = step.get("run", "")
    if not isinstance(run, str) or not run:
        return False
    run_lower = run.lower()
    return any(pat in run_lower for pat in _TEST_RUN_PATTERNS)


def _already_injected(steps: List[Dict]) -> bool:
    return any(
        step.get("id") == _INJECTED_STEP_ID
        or step.get("name") in _CAUSETRACE_STEP_NAMES
        for step in steps
    )


def _wrap_run_cmd(original: str) -> _LiteralStr:
    """Append tee redirect to the last line of original run command."""
    cmd = original.strip()
    if "| tee test-output.txt" in cmd:
        return _LiteralStr(original)  # already piped

    lines = cmd.splitlines()
    # Strip trailing backslash continuations so the redirect lands on the
    # actual last command, not a line-continuation character.
    last = lines[-1].rstrip()
    if last.endswith("\\"):
        last = last[:-1].rstrip()
    lines[-1] = f"{last} 2>&1 | tee test-output.txt"

    if "pipefail" not in cmd:
        lines = ["set -o pipefail"] + lines

    return _LiteralStr("\n".join(lines) + "\n")


def _causetrace_steps() -> List[Dict]:
    return [
        {
            "name": "Install CauseTrace",
            "if": "steps.causetrace_test.outcome == 'failure'",
            "run": "pip install causetrace",
        },
        {
            "name": "Run CauseTrace investigation",
            "if": "steps.causetrace_test.outcome == 'failure'",
            "run": "causetrace-ci --log test-output.txt --output causetrace-results.txt",
            "env": {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"},
        },
        {
            "name": "Upload CauseTrace results",
            "if": "steps.causetrace_test.outcome == 'failure'",
            # Pin to a specific release; replace with a full commit SHA for
            # maximum supply-chain safety (see GitHub hardening guide).
            "uses": "actions/upload-artifact@v4.4.3",
            "with": {
                "name": "causetrace-results",
                "path": "causetrace-results.txt",
                "retention-days": 30,
            },
        },
        {
            "name": "Surface test failure",
            "if": "steps.causetrace_test.outcome == 'failure'",
            "run": "exit 1",
        },
    ]


def _reorder_step(step: Dict) -> Dict:
    """Return a copy of step with keys in a readable order for CI YAML."""
    priority = ["name", "id", "if", "shell", "run", "uses", "with", "env",
                "continue-on-error"]
    ordered: Dict = {}
    for key in priority:
        if key in step:
            ordered[key] = step[key]
    for key, value in step.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _inject_into_job(job: Dict) -> Optional[Tuple[int, str]]:
    """
    Modify job dict in-place. Returns (test_step_index, step_name) on success,
    None if nothing to inject.
    """
    steps = job.get("steps")
    if not isinstance(steps, list) or _already_injected(steps):
        return None

    idx = next((i for i, s in enumerate(steps) if _is_test_step(s)), None)
    if idx is None:
        return None

    step = steps[idx]
    step_name = step.get("name", f"step[{idx}]")

    # Rebuild the test step dict with keys in a clean order
    step["id"] = _INJECTED_STEP_ID
    step["continue-on-error"] = True
    step.setdefault("shell", "bash")
    step["run"] = _wrap_run_cmd(step["run"])
    steps[idx] = _reorder_step(step)

    # Ensure the job can read workflow-run history (needed by ci_adapter)
    perms = job.get("permissions")
    if perms is None:
        # Insert permissions before 'steps' for readability
        new_job: Dict = {}
        for k, v in list(job.items()):
            if k == "steps":
                new_job["permissions"] = {"actions": "read"}
            new_job[k] = v
        job.clear()
        job.update(new_job)
    elif isinstance(perms, dict) and perms.get("actions") != "read":
        perms["actions"] = "read"

    # Insert three CauseTrace steps immediately after the test step
    for offset, new_step in enumerate(_causetrace_steps(), start=1):
        steps.insert(idx + offset, new_step)

    return idx, step_name


# ── workflow file processing ──────────────────────────────────────────────────

def _find_workflow_files(root: Path) -> List[Path]:
    d = root / ".github" / "workflows"
    if not d.is_dir():
        return []
    return sorted(f for f in d.iterdir() if f.suffix in {".yml", ".yaml"} and f.is_file())


def _process_workflow(path: Path, apply: bool) -> List[str]:
    msgs: List[str] = []

    try:
        raw = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(raw)
    except (yaml.YAMLError, OSError) as exc:
        return [f"  SKIP  {path.name}: {exc}"]

    if not isinstance(doc, dict):
        return [f"  SKIP  {path.name}: not a valid workflow document"]

    jobs = doc.get("jobs") or {}
    if not jobs:
        return [f"  SKIP  {path.name}: no jobs defined"]

    injected: List[Tuple[str, int, str]] = []  # (job_name, idx, step_name)
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        if any(pat in job_name.lower() for pat in _SKIP_JOB_NAME_PATTERNS):
            continue
        result = _inject_into_job(job)
        if result is not None:
            idx, step_name = result
            injected.append((job_name, idx, step_name))

    if not injected:
        msgs.append(f"  SKIP  {path.name}: no injectable test steps found (or already injected)")
        return msgs

    for job_name, idx, step_name in injected:
        msgs.append(f"  FOUND {path.name}: job '{job_name}', step '{step_name}' (index {idx})")

    if not apply:
        msgs.append(f"  DRY   {path.name}: pass --apply to write changes")
        return msgs

    # Back up and write
    backup = path.with_suffix(path.suffix + ".orig")
    backup.write_text(raw, encoding="utf-8")

    output = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False,
                       width=4096, Dumper=_CauseTraceDumper)
    # PyYAML (YAML 1.1) parses `on:` as boolean True; restore the correct key.
    output = re.sub(r"(?m)^true:", "on:", output)
    path.write_text(output, encoding="utf-8")

    msgs.append(f"  WROTE {path.name}  (original saved as {backup.name})")
    return msgs


# ── entry point ───────────────────────────────────────────────────────────────

def init_main(argv: List[str]) -> None:
    if not _YAML_AVAILABLE:
        print("error: pyyaml is required for 'causetrace init'", file=sys.stderr)
        print("       pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    _configure_dumper()

    ap = argparse.ArgumentParser(
        prog="causetrace init",
        description=(
            "Detect GitHub Actions workflows and inject CauseTrace failure-analysis "
            "steps. Runs as a dry-run by default; pass --apply to write changes."
        ),
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write the modified workflow file(s) (default: dry-run)",
    )
    ap.add_argument(
        "--dir",
        default=".",
        metavar="PATH",
        help="Repository root to scan (default: current directory)",
    )
    ap.add_argument(
        "--workflow",
        metavar="FILE",
        help="Target a specific workflow file instead of auto-scanning",
    )
    args = ap.parse_args(argv)

    root = Path(args.dir).resolve()

    if args.workflow:
        wf_path = Path(args.workflow).resolve()
        if not (wf_path.suffix in {".yml", ".yaml"}
                and wf_path.parent.name == "workflows"
                and wf_path.parent.parent.name == ".github"):
            print("error: --workflow must point to a file inside a .github/workflows/ directory",
                  file=sys.stderr)
            sys.exit(1)
        files = [wf_path]
    else:
        files = _find_workflow_files(root)

    if not files:
        print(f"No GitHub Actions workflow files found under {root}/.github/workflows/")
        print("Set up a workflow first, then re-run 'causetrace init'.")
        sys.exit(1)

    mode = "APPLYING" if args.apply else "DRY RUN — pass --apply to write changes"
    print(f"causetrace init  [{mode}]")
    print(f"Scanning {len(files)} workflow file(s)\n")

    any_found = False
    for path in files:
        for msg in _process_workflow(path, apply=args.apply):
            print(msg)
            if msg.strip().startswith(("FOUND", "WROTE")):
                any_found = True

    print()
    if not any_found:
        print("No injectable test steps found.")
        return

    if args.apply:
        print("Done. CauseTrace will analyze failures on the next CI run.")
        print()
        print("Note: GITHUB_TOKEN is set automatically by GitHub Actions.")
        print("      No additional secrets are required.")
    else:
        print("Re-run with --apply to write these changes.")

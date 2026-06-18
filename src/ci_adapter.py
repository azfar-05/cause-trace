"""
CI/CD adapter layer for CauseTrace.

Provides two functions used by ci_runner.py to supply CauseTrace's
existing inputs from CI environment context:

    resolve_good_commit  — query the CI build-history API for the most
                           recent successful build on the current branch
    extract_trace_from_log — extract the first usable stack trace from
                              CI test-runner output
"""

import os
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse, quote as _urlquote

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore


# ── good-commit resolution ─────────────────────────────────────────────────────

def resolve_good_commit(
    ci_system: str,
    repo_owner: str,
    repo_name: str,
    branch: str,
    workflow_id: Optional[str] = None,
) -> Optional[str]:
    """
    Return the HEAD SHA of the most recent successful build on branch.

    Supports ci_system values: "github", "gitlab", "jenkins", "azure".
    Returns None if no successful build exists, authentication is missing,
    or any network or API error occurs.  No exceptions escape this function.
    """
    try:
        if ci_system == "github":
            return _resolve_github(repo_owner, repo_name, branch, workflow_id)
        if ci_system == "gitlab":
            return _resolve_gitlab(branch)
        if ci_system == "jenkins":
            return _resolve_jenkins(repo_name, branch)
        if ci_system == "azure":
            return _resolve_azure(branch, workflow_id)
        return None
    except Exception:
        return None


def _resolve_github(
    owner: str,
    repo: str,
    branch: str,
    workflow_id: Optional[str],
) -> Optional[str]:
    if _requests is None or not owner or not repo:
        return None
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if workflow_id:
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
    else:
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"

    resp = _requests.get(
        url,
        headers=headers,
        params={"branch": branch, "status": "success", "per_page": 1},
        timeout=10,
    )
    if resp.status_code != 200:
        return None

    runs = resp.json().get("workflow_runs", [])
    if not runs:
        return None
    return runs[0].get("head_sha")


def _resolve_gitlab(branch: str) -> Optional[str]:
    if _requests is None:
        return None
    token = os.environ.get("CI_JOB_TOKEN") or os.environ.get("GITLAB_TOKEN")
    project_id = os.environ.get("CI_PROJECT_ID")
    if not token or not project_id:
        return None

    server = os.environ.get("CI_SERVER_URL", "https://gitlab.com").rstrip("/")
    if urlparse(server).scheme not in ("http", "https"):
        return None
    resp = _requests.get(
        f"{server}/api/v4/projects/{project_id}/pipelines",
        headers={"PRIVATE-TOKEN": token},
        params={"ref": branch, "status": "success", "per_page": 1,
                "order_by": "updated_at", "sort": "desc"},
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    pipelines = resp.json()
    if not pipelines:
        return None
    return pipelines[0].get("sha")


def _resolve_jenkins(job_name: str, branch: str) -> Optional[str]:
    if _requests is None or not job_name:
        return None
    jenkins_url = os.environ.get("JENKINS_URL")
    if not jenkins_url:
        return None

    if urlparse(jenkins_url).scheme not in ("http", "https"):
        return None
    user = os.environ.get("JENKINS_USER")
    api_token = os.environ.get("JENKINS_API_TOKEN")
    auth = (user, api_token) if (user and api_token) else None
    base = jenkins_url.rstrip("/")

    # Multibranch pipeline path first, then simple job path
    job_encoded = _urlquote(job_name, safe="")
    sanitized = _urlquote(branch, safe="") if branch else ""
    urls = []
    if sanitized:
        urls.append(f"{base}/job/{job_encoded}/job/{sanitized}/lastSuccessfulBuild/api/json")
    urls.append(f"{base}/job/{job_encoded}/lastSuccessfulBuild/api/json")

    for url in urls:
        try:
            resp = _requests.get(url, auth=auth, timeout=10)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        for action in resp.json().get("actions", []):
            sha = action.get("lastBuiltRevision", {}).get("SHA1")
            if sha:
                return sha
            for br_data in action.get("buildsByBranchName", {}).values():
                sha = br_data.get("revision", {}).get("SHA1")
                if sha:
                    return sha

    return None


def _resolve_azure(branch: str, definition_id: Optional[str]) -> Optional[str]:
    if _requests is None:
        return None
    token = os.environ.get("SYSTEM_ACCESSTOKEN")
    collection_uri = os.environ.get("SYSTEM_TEAMFOUNDATIONCOLLECTIONURI")
    team_project = os.environ.get("SYSTEM_TEAMPROJECT")
    if not token or not collection_uri or not team_project:
        return None

    if not definition_id:
        definition_id = os.environ.get("SYSTEM_DEFINITIONID")
    if not definition_id:
        return None

    import base64
    credentials = base64.b64encode(f":{token}".encode()).decode()
    resp = _requests.get(
        f"{collection_uri.rstrip('/')}/{team_project}/_apis/build/builds",
        headers={"Authorization": f"Basic {credentials}"},
        params={
            "definitions": definition_id,
            "resultFilter": "succeeded",
            "branchName": f"refs/heads/{branch}",
            "$top": 1,
            "api-version": "7.1",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    builds = resp.json().get("value", [])
    if not builds:
        return None
    return builds[0].get("sourceVersion")


# ── stack trace extraction ─────────────────────────────────────────────────────

def extract_trace_from_log(
    log_text: str,
    repo_name: str,
) -> Optional[str]:
    """
    Extract the first well-formed stack trace from CI log output.

    Recognises Python tracebacks, pytest failure blocks, and JavaScript error
    stacks.  Prefers the first candidate whose file paths contain repo_name.
    Falls back to the first candidate overall.  Returns None if no trace found.
    """
    if not log_text:
        return None

    # GitHub Actions prepends an ISO timestamp to every log line.  Strip it so
    # that pattern matchers see clean lines (e.g. "_____ test ____" not
    # "2026-06-03T16:41:49.931Z _____ test ____").  No-op for non-timestamped logs.
    log_text = re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ", "", log_text, flags=re.MULTILINE)

    # Collect (position, text) for every candidate trace, then apply preference.
    candidates: List[Tuple[int, str]] = []
    candidates.extend(_find_python_tracebacks(log_text))
    candidates.extend(_find_pytest_failures(log_text))
    candidates.extend(_find_js_stacks(log_text))

    if not candidates:
        return None

    # Sort by order of appearance in log
    candidates.sort(key=lambda x: x[0])

    if repo_name:
        rl = repo_name.lower()
        for _, text in candidates:
            if rl in text.lower():
                return text

    return candidates[0][1]


def _line_positions(log_text: str) -> Tuple[List[str], List[int]]:
    """Return (lines, start-positions) for the log text."""
    lines = log_text.splitlines(keepends=True)
    positions: List[int] = []
    pos = 0
    for line in lines:
        positions.append(pos)
        pos += len(line)
    return lines, positions


def _find_python_tracebacks(log_text: str) -> List[Tuple[int, str]]:
    lines, positions = _line_positions(log_text)
    results: List[Tuple[int, str]] = []
    i = 0
    while i < len(lines):
        if "Traceback (most recent call last):" in lines[i]:
            start_pos = positions[i]
            start_i = i
            i += 1
            while i < len(lines):
                stripped = lines[i].rstrip("\n\r")
                # Exception type line: non-blank, not indented, not the header
                if stripped and not stripped[0].isspace() and i > start_i + 1:
                    i += 1  # include the exception line
                    break
                i += 1
            end_pos = positions[i] if i < len(lines) else len(log_text)
            results.append((start_pos, log_text[start_pos:end_pos].rstrip()))
        else:
            i += 1
    return results


def _find_pytest_failures(log_text: str) -> List[Tuple[int, str]]:
    lines, positions = _line_positions(log_text)
    results: List[Tuple[int, str]] = []
    i = 0
    # Match pytest separator: "___ test_name ___" or "FAILURES" section dividers
    _sep = re.compile(r"^_{5,}\s+\S.*\s+_{5,}\s*$")
    _end = re.compile(r"^[=_]{5,}")
    while i < len(lines):
        if _sep.match(lines[i].rstrip()):
            start_pos = positions[i]
            i += 1
            while i < len(lines):
                if _end.match(lines[i].rstrip()) and len(lines[i].rstrip()) > 20:
                    break
                i += 1
            end_pos = positions[i] if i < len(lines) else len(log_text)
            text = log_text[start_pos:end_pos].rstrip()
            # Keep only if there are file:line references
            if re.search(r"[\w/\.-]+\.py:\d+", text):
                results.append((start_pos, text))
        else:
            i += 1
    return results


def _find_js_stacks(log_text: str) -> List[Tuple[int, str]]:
    lines, positions = _line_positions(log_text)
    results: List[Tuple[int, str]] = []
    i = 0
    _err_header = re.compile(r"^[A-Za-z][A-Za-z0-9]*Error:")
    while i < len(lines):
        line = lines[i]
        if _err_header.match(line) and (not line[0].isspace()):
            start_pos = positions[i]
            i += 1
            at_count = 0
            while i < len(lines) and (
                lines[i].startswith("    at ") or lines[i].startswith("\tat ")
            ):
                at_count += 1
                i += 1
            if at_count > 0:
                end_pos = positions[i] if i < len(lines) else len(log_text)
                results.append((start_pos, log_text[start_pos:end_pos].rstrip()))
        else:
            i += 1
    return results

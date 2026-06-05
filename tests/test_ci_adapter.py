from unittest.mock import MagicMock, patch

import pytest

from src.ci_adapter import extract_trace_from_log, resolve_good_commit


# ── resolve_good_commit — GitHub ───────────────────────────────────────────────

def test_resolve_github_returns_sha(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"workflow_runs": [{"head_sha": "abc123def456"}]}

    with patch("src.ci_adapter._requests") as mock_req:
        mock_req.get.return_value = mock_resp
        sha = resolve_good_commit("github", "owner", "myrepo", "main")

    assert sha == "abc123def456"


def test_resolve_github_with_workflow_id(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"workflow_runs": [{"head_sha": "deadbeef"}]}

    with patch("src.ci_adapter._requests") as mock_req:
        mock_req.get.return_value = mock_resp
        sha = resolve_good_commit("github", "owner", "myrepo", "main", workflow_id="ci.yml")

    assert sha == "deadbeef"
    call_url = mock_req.get.call_args[0][0]
    assert "workflows/ci.yml/runs" in call_url


def test_resolve_github_empty_runs_returns_none(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"workflow_runs": []}

    with patch("src.ci_adapter._requests") as mock_req:
        mock_req.get.return_value = mock_resp
        sha = resolve_good_commit("github", "owner", "myrepo", "main")

    assert sha is None


def test_resolve_github_http_error_returns_none(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    with patch("src.ci_adapter._requests") as mock_req:
        mock_req.get.return_value = mock_resp
        sha = resolve_good_commit("github", "owner", "myrepo", "main")

    assert sha is None


def test_resolve_github_no_token_returns_none(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    sha = resolve_good_commit("github", "owner", "myrepo", "main")
    assert sha is None


def test_resolve_github_network_error_returns_none(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with patch("src.ci_adapter._requests") as mock_req:
        mock_req.get.side_effect = Exception("connection refused")
        sha = resolve_good_commit("github", "owner", "myrepo", "main")
    assert sha is None


# ── resolve_good_commit — GitLab ───────────────────────────────────────────────

def test_resolve_gitlab_returns_sha(monkeypatch):
    monkeypatch.setenv("CI_JOB_TOKEN", "fake-token")
    monkeypatch.setenv("CI_PROJECT_ID", "42")
    monkeypatch.setenv("CI_SERVER_URL", "https://gitlab.example.com")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"sha": "cafebabe"}]

    with patch("src.ci_adapter._requests") as mock_req:
        mock_req.get.return_value = mock_resp
        sha = resolve_good_commit("gitlab", "group", "myrepo", "main")

    assert sha == "cafebabe"


def test_resolve_gitlab_no_project_id_returns_none(monkeypatch):
    monkeypatch.setenv("CI_JOB_TOKEN", "fake-token")
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    sha = resolve_good_commit("gitlab", "group", "repo", "main")
    assert sha is None


def test_resolve_gitlab_no_token_returns_none(monkeypatch):
    monkeypatch.delenv("CI_JOB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("CI_PROJECT_ID", "42")
    sha = resolve_good_commit("gitlab", "group", "repo", "main")
    assert sha is None


# ── resolve_good_commit — edge cases ──────────────────────────────────────────

def test_resolve_unknown_ci_system_returns_none():
    sha = resolve_good_commit("unknown", "owner", "repo", "main")
    assert sha is None


def test_resolve_exception_does_not_propagate(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with patch("src.ci_adapter._requests") as mock_req:
        mock_req.get.side_effect = RuntimeError("unexpected")
        sha = resolve_good_commit("github", "owner", "repo", "main")
    assert sha is None


# ── extract_trace_from_log — Python tracebacks ────────────────────────────────

REPO_PY_TRACE = """\
Traceback (most recent call last):
  File "myapp/auth.py", line 42, in authenticate
    return self._validate(token)
  File "myapp/utils.py", line 15, in _validate
    raise ValueError("bad token")
ValueError: bad token
"""

UNRELATED_PY_TRACE = """\
Traceback (most recent call last):
  File "/usr/lib/python3.9/site-packages/pytest/runner.py", line 55, in runtest
    item.runtest()
AttributeError: internal pytest error
"""


def test_extract_python_trace_basic():
    result = extract_trace_from_log(REPO_PY_TRACE, "myapp")
    assert result is not None
    assert "auth.py" in result
    assert "ValueError" in result


def test_extract_prefers_repo_trace_when_multiple_present():
    log = UNRELATED_PY_TRACE + "\n\n" + REPO_PY_TRACE
    result = extract_trace_from_log(log, "myapp")
    assert result is not None
    assert "myapp" in result


def test_extract_returns_first_when_no_repo_match():
    log = UNRELATED_PY_TRACE + "\n\n" + REPO_PY_TRACE
    result = extract_trace_from_log(log, "nonexistent-repo-xyz")
    assert result is not None
    assert "Traceback" in result


def test_extract_no_trace_returns_none():
    log = "Build started\nInstalling dependencies...\nAll tests passed.\n"
    result = extract_trace_from_log(log, "myapp")
    assert result is None


def test_extract_empty_log_returns_none():
    result = extract_trace_from_log("", "myapp")
    assert result is None


# ── extract_trace_from_log — mixed CI logs ────────────────────────────────────

def test_extract_selects_repo_trace_from_mixed_log():
    mixed = f"""
Running test suite...

{UNRELATED_PY_TRACE}

FAILED tests/test_auth.py::test_login

{REPO_PY_TRACE}

2 failed, 10 passed in 0.45s
"""
    result = extract_trace_from_log(mixed, "myapp")
    assert result is not None
    assert "myapp" in result


def test_extract_fallback_to_first_when_no_match():
    log = UNRELATED_PY_TRACE + "\n\n" + UNRELATED_PY_TRACE.replace("AttributeError", "TypeError")
    result = extract_trace_from_log(log, "myapp")
    assert result is not None
    # First trace should be returned
    assert "Traceback" in result


# ── extract_trace_from_log — JavaScript stacks ────────────────────────────────

JS_TRACE = """\
TypeError: Cannot read property 'name' of undefined
    at getUser (myapp/api.js:30:5)
    at router.get (myapp/routes.js:12:3)
"""


def test_extract_js_trace():
    result = extract_trace_from_log(JS_TRACE, "myapp")
    assert result is not None
    assert "TypeError" in result or "api.js" in result


def test_extract_js_prefers_repo_match():
    unrelated_js = """\
ReferenceError: window is not defined
    at setup (/usr/lib/node_modules/jest/setup.js:10:3)
    at Object.<anonymous> (/usr/lib/node_modules/jest/main.js:5:1)
"""
    log = unrelated_js + "\n\n" + JS_TRACE
    result = extract_trace_from_log(log, "myapp")
    assert result is not None
    assert "myapp" in result


# ── extract_trace_from_log — pytest failure blocks ────────────────────────────

PYTEST_FAILURE_BLOCK = """\
________________________ test_login ________________________

    def test_login():
>       result = login("user", "bad_pass")

myapp/tests/test_auth.py:42: in test_login
    result = login("user", "bad_pass")
myapp/auth.py:30: in login
    return authenticate(username, password)
E   ValueError: invalid credentials

========================= short test summary info =========================
FAILED myapp/tests/test_auth.py::test_login - ValueError: invalid credentials
"""


def test_extract_pytest_block():
    result = extract_trace_from_log(PYTEST_FAILURE_BLOCK, "myapp")
    assert result is not None
    # Should contain file references from the failure block
    assert "auth.py" in result or "test_auth.py" in result

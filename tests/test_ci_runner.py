import os
from unittest.mock import MagicMock, patch

import pytest

import ci_runner


# ── CI system detection ────────────────────────────────────────────────────────

def test_detect_github(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.delenv("JENKINS_URL", raising=False)
    monkeypatch.delenv("TF_BUILD", raising=False)
    assert ci_runner.detect_ci_system() == "github"


def test_detect_gitlab(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.delenv("JENKINS_URL", raising=False)
    monkeypatch.delenv("TF_BUILD", raising=False)
    assert ci_runner.detect_ci_system() == "gitlab"


def test_detect_jenkins(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.setenv("JENKINS_URL", "http://jenkins.example.com")
    monkeypatch.delenv("TF_BUILD", raising=False)
    assert ci_runner.detect_ci_system() == "jenkins"


def test_detect_azure(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.delenv("JENKINS_URL", raising=False)
    monkeypatch.setenv("TF_BUILD", "True")
    assert ci_runner.detect_ci_system() == "azure"


def test_detect_none_outside_ci(monkeypatch):
    for var in ("GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "TF_BUILD"):
        monkeypatch.delenv(var, raising=False)
    assert ci_runner.detect_ci_system() is None


# ── bad_commit detection ───────────────────────────────────────────────────────

def test_detect_bad_commit_github(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "github-sha-123")
    assert ci_runner.detect_bad_commit() == "github-sha-123"


def test_detect_bad_commit_gitlab(monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("CI_COMMIT_SHA", "gitlab-sha-456")
    assert ci_runner.detect_bad_commit() == "gitlab-sha-456"


def test_detect_bad_commit_prefers_github_over_gitlab(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "github-sha")
    monkeypatch.setenv("CI_COMMIT_SHA", "gitlab-sha")
    assert ci_runner.detect_bad_commit() == "github-sha"


def test_detect_bad_commit_returns_none_when_absent(monkeypatch):
    for var in ("GITHUB_SHA", "CI_COMMIT_SHA", "GIT_COMMIT", "BUILD_SOURCEVERSION"):
        monkeypatch.delenv(var, raising=False)
    assert ci_runner.detect_bad_commit() is None


# ── repo_path resolution ───────────────────────────────────────────────────────

def test_resolve_repo_path_github_workspace(monkeypatch):
    monkeypatch.setenv("GITHUB_WORKSPACE", "/home/runner/work/myrepo/myrepo")
    assert ci_runner.resolve_repo_path() == "/home/runner/work/myrepo/myrepo"


def test_resolve_repo_path_gitlab(monkeypatch):
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.setenv("CI_PROJECT_DIR", "/builds/group/myrepo")
    assert ci_runner.resolve_repo_path() == "/builds/group/myrepo"


def test_resolve_repo_path_falls_back_to_cwd(monkeypatch):
    for var in ("GITHUB_WORKSPACE", "CI_PROJECT_DIR", "WORKSPACE", "BUILD_SOURCESDIRECTORY"):
        monkeypatch.delenv(var, raising=False)
    assert ci_runner.resolve_repo_path() == os.getcwd()


# ── repo identity detection ────────────────────────────────────────────────────

def test_detect_repo_identity_github(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/myapp")
    owner, name = ci_runner.detect_repo_identity()
    assert owner == "acme"
    assert name == "myapp"


def test_detect_repo_identity_gitlab(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("CI_PROJECT_PATH", "mygroup/subgroup/myapp")
    owner, name = ci_runner.detect_repo_identity()
    assert name == "myapp"


def test_detect_repo_identity_jenkins(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("CI_PROJECT_PATH", raising=False)
    monkeypatch.setenv("JOB_NAME", "my-pipeline")
    owner, name = ci_runner.detect_repo_identity()
    assert name == "my-pipeline"


# ── commit-window validation ───────────────────────────────────────────────────

def test_abort_exits_with_code_1(capsys):
    with pytest.raises(SystemExit) as exc_info:
        ci_runner.abort("something went wrong")
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "something went wrong" in captured.err


def test_abort_without_bad_commit(monkeypatch, capsys):
    """main() aborts when bad_commit cannot be resolved."""
    for var in ("GITHUB_SHA", "CI_COMMIT_SHA", "GIT_COMMIT", "BUILD_SOURCEVERSION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_WORKSPACE", "/tmp")

    with patch("sys.argv", ["ci_runner.py"]):
        with patch("ci_runner.resolve_good_commit", return_value="abc123"):
            with patch("ci_runner.extract_trace_from_log", return_value="trace"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.read.return_value = ""
                    with pytest.raises(SystemExit) as exc_info:
                        ci_runner.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "bad_commit" in captured.err


def test_abort_without_good_commit(monkeypatch, capsys, tmp_path):
    """main() aborts when good_commit cannot be resolved from CI API."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "bad-sha-123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

    with patch("sys.argv", ["ci_runner.py"]):
        with patch("ci_runner.resolve_good_commit", return_value=None):
            with patch("ci_runner.extract_trace_from_log", return_value="trace"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.read.return_value = ""
                    with pytest.raises(SystemExit) as exc_info:
                        ci_runner.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "good_commit" in captured.err


def test_abort_without_trace(monkeypatch, capsys, tmp_path):
    """main() aborts when no trace can be extracted from the CI log."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "bad-sha-123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

    with patch("sys.argv", ["ci_runner.py"]):
        with patch("ci_runner.resolve_good_commit", return_value="good-sha-456"):
            with patch("ci_runner.extract_trace_from_log", return_value=None):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.read.return_value = ""
                    with pytest.raises(SystemExit) as exc_info:
                        ci_runner.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "trace" in captured.err


def test_abort_on_identical_commits(monkeypatch, capsys, tmp_path):
    """main() aborts when good_commit and bad_commit resolve to the same SHA."""
    same_sha = "aaabbbccc111222333"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", same_sha)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

    with patch("sys.argv", ["ci_runner.py"]):
        with patch("ci_runner.resolve_good_commit", return_value=same_sha):
            with patch("ci_runner.extract_trace_from_log", return_value="trace text"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.read.return_value = ""
                    with pytest.raises(SystemExit) as exc_info:
                        ci_runner.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "identical" in captured.err


# ── pipeline invocation ────────────────────────────────────────────────────────

def test_main_invokes_investigate(monkeypatch, tmp_path):
    """main() calls investigate() with the resolved inputs when all inputs are valid."""
    # Set up a minimal fake git repo
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "bad-sha-000")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/myrepo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

    mock_investigate = MagicMock(return_value=0)

    with patch("sys.argv", ["ci_runner.py"]):
        with patch("ci_runner.resolve_good_commit", return_value="good-sha-111"):
            with patch("ci_runner.extract_trace_from_log", return_value="Traceback..."):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.read.return_value = ""
                    with patch("subprocess.run") as mock_run:
                        # Both cat-file checks succeed
                        mock_run.return_value = MagicMock(returncode=0)
                        with patch("main.investigate", mock_investigate):
                            with pytest.raises(SystemExit) as exc_info:
                                ci_runner.main()

    assert exc_info.value.code == 0
    mock_investigate.assert_called_once()
    call_kwargs = mock_investigate.call_args[1]
    assert call_kwargs["good_commit"] == "good-sha-111"
    assert call_kwargs["bad_commit"] == "bad-sha-000"
    assert call_kwargs["repo_path"] == str(tmp_path)
    assert call_kwargs["stacktrace"] == "Traceback..."

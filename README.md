# CauseTrace

[![CI](https://github.com/azfar-05/cause-trace/actions/workflows/causetrace.yml/badge.svg)](https://github.com/azfar-05/cause-trace/actions/workflows/causetrace.yml)
[![PyPI](https://img.shields.io/pypi/v/causetrace-cli)](https://pypi.org/project/causetrace-cli/)
[![Python](https://img.shields.io/pypi/pyversions/causetrace-cli)](https://pypi.org/project/causetrace-cli/)

When a test starts failing and you have a range of commits to blame, CauseTrace tells you which one to look at first.

It reads the stack trace, scores every commit in the window against structural signals from the code, and returns a ranked list of suspects — with a plain explanation of why each one scored as it did. No language model makes the call. The ranking is deterministic.

---

## Install

```bash
pip install causetrace-cli
```

This gives you two commands: `causetrace` for manual investigation and `causetrace-ci` for automated CI triage.

---

## The problem it solves

You have a CI failure. It was passing at commit A and failing at commit B. Between them are N commits. Which one introduced the regression?

If N is small you bisect manually. If N is large, or you need to triage quickly across many failing builds, you need a faster first pass. CauseTrace provides that first pass — deterministically, in seconds.

---

## Two ways to use it

### 1. Manual investigation

Point it at a repo, give it a commit window and a stack trace:

```bash
export CAUSETRACE_REPOS_ROOT=~/projects

causetrace \
  --repo flask \
  --good e71a5ff8 \
  --bad  025589ee \
  --trace stacktrace.txt
```

Or pipe the trace from stdin:

```bash
cat stacktrace.txt | causetrace --repo urllib3 --good abc123 --bad def456
```

| Flag | Description |
|------|-------------|
| `--repo` | Repo name (resolved under `CAUSETRACE_REPOS_ROOT`) |
| `--good` | Last known-good commit |
| `--bad` | First known-bad commit |
| `--trace` | Path to stack trace file (stdin if omitted) |
| `--top` | How many candidates to show (default: 5) |

---

### 2. Automatic CI integration

Run `causetrace init` inside any repo that has a GitHub Actions workflow. It detects your test job and injects failure-analysis steps automatically:

```bash
cd your-repo
causetrace init          # dry run — shows what it would change
causetrace init --apply  # writes the changes
```

After the next CI failure, CauseTrace runs automatically and uploads a triage report as an artifact. No manual intervention needed.

Options:

| Flag | Description |
|------|-------------|
| `--apply` | Write changes (default is dry run) |
| `--dir PATH` | Repo root to scan (default: current directory) |
| `--workflow FILE` | Target a specific workflow file |

---

## What the output looks like

```
════════════════════════════════════════════════════════════════════
  CauseTrace  ·  Failure Investigation
════════════════════════════════════════════════════════════════════

  Repo      flask  ·  /Users/azfar/projects/flask
  Window    eb58d862..eca5fd1d  (4 commits analyzed)
  Files     helpers.py
  Functions redirect
  Lines     helpers.py:242

────────────────────────────────────────────────────────────────────
  CULPRIT CANDIDATES
────────────────────────────────────────────────────────────────────

  #1  eca5fd1  redirect defaults to 303                   score 27.60

      Signals
  ✓  file          helpers.py in trace                       +7.0
  ✓  line          Δ=0  ·  changed 242, failure 242          +10.0
  ✓  function      redirect()                                +8.0
     caller-callee none                                         —
     recency       5.00 of 5.0                               +5.0
     size          2 file(s) changed                          -2.4

      Why
        helpers.py was modified at line 242, exactly the failure
        line. redirect() was modified and appears in the failure
        trace.
```

---

## How scoring works

CauseTrace extracts three things from the stack trace — files, line numbers, and function names — then scores each commit in the window against them.

| Signal | What it checks |
|--------|----------------|
| **file** | Commit touches a file named in the trace |
| **line** | A changed line falls within ±5 lines of a failure line |
| **function** | A modified function matches one named in the trace |
| **caller-callee** | A function in the trace calls a function the commit modified |
| **recency** | How recent the commit is in the window (tiebreaker only) |
| **size penalty** | Large commits are scored down — they're less precise |
| **focus bonus** | Single-file commits that match the trace score slightly higher |

Line proximity and function overlap are the strongest signals. Recency is the weakest — it only breaks ties.

---

## Optional: AI explanation

Pass `--explain` to get a plain-English explanation of why the top commit is likely the culprit. Requires an `OPENROUTER_API_KEY`.

```bash
causetrace --repo flask --good abc --bad def --trace trace.txt --explain
```

The explanation is grounded in the diff and the signal breakdown. It cannot change the ranking — it runs after the deterministic pipeline has already finished.

---

## What it is not

- Not a chatbot or repo Q&A assistant
- Not an autonomous debugging agent
- Not a code-fixing system
- Not a whole-codebase semantic analyzer

CauseTrace does one thing: given a failure and a commit window, narrow the suspects. Human judgment takes it from there.

---

## Design principles

- **No AI at ranking time.** The scorer is deterministic. AI is only used post-narrowing for explanation.
- **No whole-repo traversal.** Analysis is bounded to files touched by commits in the window.
- **No recursive call graphs.** Caller/callee detection is direct, within a single file.
- **Evaluation-driven signals.** Every heuristic is validated against real regressions before inclusion.

---

## Development

```bash
git clone https://github.com/azfar-05/cause-trace.git
cd cause-trace
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"   # or: pip install -r requirements.txt && pip install -e .
```

Run the tests:

```bash
pytest
```

`CAUSETRACE_REPOS_ROOT` must point to a directory containing any repos used in manual testing. The test suite does not require it.

---

## License

MIT

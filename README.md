# CauseTrace

CauseTrace is a deterministic failure-triage engine. Given a stack trace and a bounded commit window, it ranks which commits most likely caused the regression — using structural signals from the code, not language model guesswork.

---

## What it does

When a test suite starts failing and you have a range of commits to investigate, CauseTrace narrows the search. It reads the stack trace, extracts structural signals (which files, functions, and lines are implicated), and scores each commit in the window against those signals. The result is a ranked candidate list with an explicit explanation of why each commit scored as it did.

The emphasis is on explainability. Every score is computed from deterministic signals. Nothing is inferred by a language model at ranking time.

---

## What it is not

- Not a chatbot or repo Q&A assistant
- Not an autonomous debugging agent
- Not a code-fixing system
- Not a speculative AI reasoning engine

CauseTrace does one thing: bounded causal narrowing. It reduces a commit window to a short ranked list of suspects. Human judgment takes it from there.

---

## The core problem

You have a CI failure. You know it was passing at commit A and failing at commit B. Between A and B there are N commits. Which one introduced the regression?

If N is small, you bisect manually. If N is large — or if you need to triage quickly across multiple failing builds — you need a faster first pass.

CauseTrace provides that first pass deterministically.

---

## Pipeline

```
stack trace
    │
    ▼
[parser]          extract files, line refs, function names
    │
    ▼
[git_utils]       pull commit metadata, changed lines, modified functions,
                  structural call pairs from the commit window
    │
    ▼
[scorer]          score each commit against the extracted failure context:
                  - file overlap
                  - line proximity (±5 lines)
                  - function-level overlap
                  - caller/callee structural adjacency
                  - commit size penalty
                  - focus bonus (single-file precise change)
    │
    ▼
[matcher]         apply recency normalization, produce final ranking
    │
    ▼
[main]            format and display ranked candidates with signal breakdown
```

---

## Signals

| Signal | Description |
|--------|-------------|
| **file** | Commit touches a file named in the stack trace |
| **line** | A changed line falls within ±5 lines of a failure line |
| **function** | A modified function matches a function named in the trace |
| **caller-callee** | A function in the trace calls a modified function in the same file |
| **recency** | Normalized position in the commit window (most recent = highest) |
| **size penalty** | Larger commits are penalized (less precise attribution) |
| **focus bonus** | Single-file commits that match the trace get a small boost |

Line proximity and function overlap are the strongest discriminators. Recency is the weakest — it acts as a tiebreaker, not a primary signal.

---

## Getting started

```bash
git clone <this repo>
cd cause-trace
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

CauseTrace resolves repos by name under a root directory. Set `CAUSETRACE_REPOS_ROOT` to the directory containing your cloned repos (defaults to `~/`):

```bash
export CAUSETRACE_REPOS_ROOT=~/projects
```

---

## Running an investigation

```bash
python main.py \
  --repo flask \
  --good e71a5ff8 \
  --bad 025589ee \
  --trace stacktrace.txt
```

Or pipe the trace from stdin:

```bash
cat stacktrace.txt | python main.py --repo urllib3 --good abc123 --bad def456
```

Arguments:

| Flag | Description |
|------|-------------|
| `--repo` | Repo name (resolved under `CAUSETRACE_REPOS_ROOT`) |
| `--good` | Last known-good commit (exclusive lower bound) |
| `--bad` | First known-bad commit (inclusive upper bound) |
| `--trace` | Path to stack trace file (reads stdin if omitted) |
| `--top` | Number of candidates to show (default: 5) |

---

## Example output

```
════════════════════════════════════════════════════════════════════
  CauseTrace  ·  Failure Investigation
════════════════════════════════════════════════════════════════════

  Repo      flask  ·  /Users/azfar/flask
  Window    eb58d862cc4a..eca5fd1dfdc6  (4 commit(s) analyzed)
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
        line.  redirect() was modified and appears in the failure
        trace.
```

---

## Running the benchmark

```bash
python evaluation_runner.py
```

This runs all 12 benchmark cases and prints a per-case breakdown followed by overall accuracy.

Each case specifies:
- A repository, good commit, bad commit, and expected causal commit
- A stack trace representing the observed failure
- A `failure_mode` label indicating what kind of evidence the case tests

Current results: **12/12 top-1 (100%)**

One previously included case (`flask-app-line-984`) was removed after validation confirmed it was not a legitimate regression case — the commit window was excessively large and causality could not be established. Cases are removed when investigation proves them invalid, not retained to preserve a denominator.

100% accuracy on 12 curated cases does not mean the problem is solved. `docs/benchmark_gaps.md` documents important failure classes that the current corpus does not cover.

---

## Benchmark philosophy

The benchmark is a validation artifact, not a marketing metric. Its purpose is to expose failure modes, validate heuristics, and prevent regression drift — not to produce a headline number.

Cases are drawn from real regressions in real open-source projects (flask, urllib3, requests, pytest, werkzeug). Each case:

- Has a real stack trace from a real failure
- Has a bounded commit window with meaningful ambiguity
- Has a verified causal commit as ground truth

Cases are curated, not generated. Synthetic or trivial cases are rejected. A case may be removed at any time if investigation proves it contains invalid causality, fabricated failure context, or is not a real regression. Corpus integrity takes precedence over accuracy metrics.

Benchmark data: `data/cases.json`  
Corpus analysis: `docs/corpus_analysis.md`  
Known gaps: `docs/benchmark_gaps.md`

---

## AI-assisted explanation

CauseTrace includes an optional AI explanation mode. After the deterministic ranking pipeline completes, you can request a natural-language explanation of the top-ranked result.

The deterministic attribution is always authoritative. The AI layer cannot influence scores or reorder candidates. It runs strictly after narrowing has already happened.

**Inputs provided to the explanation layer:**
- Parsed failure context (files, functions, lines from the trace)
- Top-ranked commit (hash, author, message)
- Deterministic signal breakdown (which signals fired, at what weight)
- A filtered diff excerpt (only the hunk most relevant to the failure)

**What the explanation covers:**
- What changed in the commit
- Why those changes relate to the observed failure
- The deterministic confidence level (derived from signal scores, not model judgment)

The explanation is grounded entirely in the retrieved evidence. The model does not have access to the broader repository and cannot speculate beyond what the signal breakdown and diff excerpt contain.

---

## Benchmark case structure

```json
{
  "id": "flask-helpers-redirect-302",
  "repo": "flask",
  "good_commit": "eb58d862...",
  "bad_commit":  "eca5fd1d...",
  "expected_commit": "eca5fd1d...",
  "stacktrace": "File \"src/flask/helpers.py\", line 242, in redirect\n    AssertionError: ...",
  "description": "redirect() default changed 302 → 303; any test asserting status_code == 302 breaks",
  "failure_mode": "mixed_structural",
  "tags": ["file-overlap", "line-proximity", "function-overlap"]
}
```

`failure_mode` values:

| Value | Meaning |
|-------|---------|
| `line_proximity` | Win depends on changed lines near failure line |
| `function_overlap` | Win depends on function-name match |
| `caller_callee_propagation` | Failure propagates through a call chain |
| `mixed_structural` | Multiple signal categories contribute |

---

## Project layout

```
cause-trace/
├── main.py                 CLI entry point (investigation workflow)
├── evaluation_runner.py    Benchmark runner
├── data/
│   └── cases.json          Benchmark corpus (12 cases)
├── docs/
│   ├── corpus_analysis.md  Signal dominance and failure-mode analysis
│   └── benchmark_gaps.md   Untested failure classes and known blind spots
├── src/
│   ├── parser.py           Stack trace parsing
│   ├── git_utils.py        Commit extraction and structural analysis
│   ├── matcher.py          Recency normalization and final ranking
│   ├── explainer.py        AI-assisted explanation (optional, post-narrowing)
│   └── signals/
│       ├── scorer.py       Score assembly
│       ├── file_overlap.py File-level signal
│       ├── line_proximity.py Line-level signal
│       ├── call_site.py    Function and caller/callee signal
│       └── partial_match.py Weak filename match signal
└── tests/
    ├── test_parser.py
    ├── test_matcher.py
    ├── test_line_proximity.py
    └── test_call_site_signal.py
```

---

## Tests

```bash
pytest
```

---

## Current status

CauseTrace V4 is complete. The following capabilities are implemented and validated:

- **Deterministic attribution engine** — structural signal scoring across file, line, function, and caller/callee dimensions
- **Recency normalization and commit-size penalty** — post-scoring adjustments applied consistently across the pipeline
- **Benchmark corpus** — 12 curated real-regression cases, 12/12 top-1 accuracy
- **Benchmark evaluation infrastructure** — per-case signal breakdown and accuracy reporting
- **Grounded AI explanation layer** — optional post-narrowing explanation grounded in retrieved diff evidence; does not affect ranking
- **Benchmark gap analysis** — documented failure classes not covered by the current corpus (`docs/benchmark_gaps.md`)

The deterministic ranking pipeline is the authoritative layer. The AI explanation layer is additive and bounded.

---

## Design constraints

- **No AI at ranking time.** The scorer is deterministic. AI assistance is bounded to explanation after narrowing has already happened.
- **No whole-repo traversal.** Structural reasoning is bounded to files touched by commits in the window.
- **No recursive call graphs.** Caller/callee adjacency is limited to direct call detection within a single file.
- **Evaluation-driven heuristics.** No signal is added without benchmark evidence that it improves ranking on real cases.

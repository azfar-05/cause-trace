# CauseTrace — Claude Project Context

## Project Identity

CauseTrace is a deterministic failure-triage and root-cause narrowing engine.

It is NOT:
- a chatbot
- a generic AI debugger
- an autonomous coding agent
- a code-fixing system
- a repo Q&A assistant

The core problem CauseTrace solves is:

> “Given a failure and a bounded change window, which code changes most likely caused the regression?”

The system is designed to replicate how experienced engineers narrow failure causes:
through constrained evidence-driven reasoning, not open-ended AI speculation.

---

# Core Philosophy

Failures are usually introduced by changes.

The primary objective is:
- deterministic causal narrowing
- explainable ranking
- bounded investigation
- structural failure attribution

AI must NEVER perform:
- attribution
- ranking
- causal scoring

AI may later assist with:
- explanation
- summarization
- semantic interpretation

ONLY AFTER deterministic narrowing has already reduced the search space.

---

# Architectural Principles

## Preserve Pipeline Architecture

Current architecture:

ci_adapter -> parser -> git_utils -> signals -> scorer -> matcher -> explainer

`ci_adapter` resolves `good_commit` and extracts the stack trace from CI logs.
It is the entry point in CI/CD mode; `main.py` remains the entry point for manual investigation.

Maintain strict separation of responsibilities.

Do NOT:
- leak repository traversal into scoring
- couple ranking with explanation
- collapse pipeline stages together

---

# Engineering Discipline

Prioritize:
- correctness
- explainability
- bounded scope
- measurable refinement
- deterministic behavior

Avoid:
- premature abstraction
- generalized frameworks
- overengineering
- “AI-first” design
- agentic workflows

Every heuristic should remain:
- explainable
- measurable
- locally testable

---

# Current Direction

CauseTrace currently focuses on:
- commit-level causality ranking
- structural propagation reasoning
- bounded failure-window analysis
- deterministic investigation workflows
- CI/CD-integrated live observation (collecting failures organically)

The CI acquisition layer is complete and validated. `ci_adapter.py` resolves `good_commit` via the GitHub Actions API and extracts the stack trace from CI log output. `docs/current_direction.md` defines the observation schema, failure taxonomy, and success criteria.

The system intentionally prioritizes:
- deterministic signals first
- semantic interpretation later

---

# Deterministic Signals

Signals should remain:
- grounded
- local
- explainable
- evaluation-driven

Implemented signal categories include:
- file overlap
- partial filename match
- line proximity
- function overlap
- caller/callee structural propagation
- recency normalization
- commit-size penalty
- focus bonus

Signal additions must be justified through:
- benchmark evidence
- repeated failure patterns
- measurable ranking improvement

Do NOT add speculative heuristics without evaluation support.

---

# Structural Reasoning Constraints

Structural reasoning must remain:
- deterministic
- bounded
- explainable

Prefer:
- local propagation
- caller/callee adjacency
- function-level attribution

Avoid:
- global dependency graphs
- generalized static analysis
- recursive propagation engines
- whole-repo semantic traversal

---

# Evaluation Philosophy

CauseTrace is evaluation-driven.

Benchmark quality matters more than benchmark quantity.

Prefer:
- real regressions
- real stack traces
- bounded commit windows
- curated causal cases

Avoid:
- synthetic benchmark generation
- fabricated traces
- noisy random commit sampling

Evaluation infrastructure exists to:
- validate heuristics
- identify failure modes
- expose ambiguity classes
- prevent regression drift

---

# Benchmark Acceptance Principles

Strong benchmark cases should:
- represent real regressions
- contain meaningful ambiguity
- exercise actual ranking behavior
- preserve deterministic ground truth

Reject cases where:
- commit windows are excessively large
- causality is unclear
- stack traces are weak/non-informative
- the benchmark becomes trivial or noisy

---

# AI Usage Constraints

Do NOT turn CauseTrace into:
- generic repo RAG
- “chat with your codebase”
- autonomous debugging agents
- speculative AI reasoning systems

Future AI usage should remain:
- grounded
- retrieval-constrained
- evidence-backed

The deterministic ranking layer is the core differentiator and must remain central.

---

# Scope Boundaries

Avoid introducing:
- dashboards
- SaaS infrastructure
- cloud orchestration
- distributed systems
- generalized observability platforms
- unrelated developer tooling

Current priority is:
- causality quality
- live observation (active collection)
- investigation clarity
- deterministic reasoning quality

---

# Development Workflow

Preferred workflow:

1. bounded objective
2. investigation first
3. minimal implementation
4. evaluation
5. commit
6. reset context

Favor:
- small disciplined sessions
- incremental measurable progress
- architecture preservation

Avoid:
- giant refactors
- speculative redesigns
- broad autonomous modifications


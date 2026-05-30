"""
CauseTrace — AI-assisted explanation layer.

Produces grounded narrative for the top-ranked commit using only:
  - deterministic signal breakdown
  - diff excerpt (filtered to matched files)
  - stacktrace summary (structured, not raw)

The LLM is responsible for exactly two fields:
  - what_changed: what the diff modified
  - why_related:  how that change connects to the failure

Confidence is computed deterministically before the LLM is called.
The LLM does not reason about confidence.

Provider: OpenRouter (model configurable via CAUSETRACE_EXPLAIN_MODEL).
No vendor-specific SDK — uses requests only.
"""

import os
import json
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv("OPENROUTER_API_KEY")
_DEFAULT_MODEL = "google/gemini-2.0-flash-001"
_MODEL = os.getenv("CAUSETRACE_EXPLAIN_MODEL", _DEFAULT_MODEL)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# ── output struct ─────────────────────────────────────────────────────────────

@dataclass
class Explanation:
    commit_hash: str
    what_changed: str   # LLM-generated, anchored to diff
    why_related: str    # LLM-generated, anchored to signals
    confidence: str     # "High" | "Medium" | "Low" — deterministic, not LLM


# ── deterministic confidence ──────────────────────────────────────────────────

def compute_confidence(breakdown: Dict) -> str:
    """
    Compute confidence tier from signal scores.
    This is deterministic — the LLM never touches this.

      High   : line proximity fired  OR  (function + file both fired)
      Medium : file or function fired (but not both with line)
      Low    : no file / function / line match (recency-only ranking)
    """
    line = breakdown.get("line", 0)
    fn   = breakdown.get("function", 0)
    file = breakdown.get("file", 0)

    if line > 0 or (fn > 0 and file > 0):
        return "High"
    if file > 0 or fn > 0:
        return "Medium"
    return "Low"


# ── system prompt (static — cached at the provider level) ────────────────────

_SYSTEM_PROMPT = """\
You are a software failure analysis assistant for CauseTrace.

Your only job is to explain WHY a specific commit is the likely cause of a failure.
You have already been given the commit ranked #1 by a deterministic scoring system.
You must NOT override this ranking, suggest a different culprit, or propose fixes.

STRICT GROUNDING RULES — you may only reference:
  1. The diff excerpt provided (functions, lines, code behaviour visible in the diff)
  2. The signal breakdown provided (only signals with non-zero values)
  3. The stacktrace summary provided (files, line refs, functions)

You must NOT:
  - Invent developer intent
  - Use external knowledge about the project or library
  - Suggest remediation or fixes
  - Speculate beyond what the diff and signals show
  - Reference anything not in the provided data

OUTPUT FORMAT — respond with valid JSON only, no markdown, no prose outside JSON:
{
  "what_changed": "<one or two sentences anchored to the diff: which function/line changed and what it did>",
  "why_related": "<one or two sentences anchored to signal names and values: how the change connects to the failure>"
}

If the diff excerpt is empty or unavailable, set what_changed to:
"Diff not available — file match only."

Cite signal keys by their exact names: line, function, caller_callee, file.
"""


# ── user prompt (dynamic per invocation) ─────────────────────────────────────

def _build_user_prompt(
    commit: Dict,
    breakdown: Dict,
    stacktrace_summary: Dict,
    diff_excerpt: str,
    confidence: str,
) -> str:
    # Format only non-zero signals so the LLM isn't confused by zeroes
    fired = {k: v for k, v in breakdown.items() if isinstance(v, (int, float)) and v != 0}
    fired_str = "\n".join(f"  {k}: {v}" for k, v in fired.items())

    files_str   = ", ".join(stacktrace_summary.get("files", []))
    fn_str      = ", ".join(stacktrace_summary.get("functions", []))
    line_refs   = ", ".join(
        f"{f}:{l}" for f, l in stacktrace_summary.get("file_line_pairs", [])
    )

    diff_block = diff_excerpt.strip() if diff_excerpt.strip() else "(not available)"

    return f"""\
COMMIT
  hash:      {commit['hash']}
  message:   {commit['message'].splitlines()[0]}
  files:     {', '.join(commit.get('files', []))}
  functions: {', '.join(commit.get('modified_functions', []))}

STACKTRACE SUMMARY
  files:     {files_str}
  functions: {fn_str}
  line refs: {line_refs}

DETERMINISTIC SIGNAL BREAKDOWN (non-zero only)
{fired_str or "  (none — recency-only ranking)"}

CONFIDENCE (pre-computed, do not change): {confidence}

DIFF EXCERPT (≤150 lines, filtered to matched files)
---
{diff_block}
---

Respond with JSON only.
"""


# ── diff and trace preparation (called by main.py before explain_top_commit) ──

def fetch_diff_excerpt(repo_path: str, commit_hash: str, matched_files: List[str]) -> str:
    """
    Return up to 150 lines of diff for matched_files in the given commit.
    Resolves basenames to full repo-relative paths via git show --name-only.
    Returns empty string on any failure; caller treats that as unavailable.
    """
    if not matched_files:
        return ""
    basenames = {f.split("/")[-1] for f in matched_files}
    try:
        names = subprocess.run(
            ["git", "show", "--name-only", "--format=", commit_hash],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if names.returncode != 0:
        return ""
    full_paths = [ln for ln in names.stdout.splitlines() if ln and ln.split("/")[-1] in basenames]
    if not full_paths:
        return ""
    try:
        result = subprocess.run(
            ["git", "show", commit_hash, "--"] + full_paths,
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return "\n".join(result.stdout.splitlines()[:150])


def build_stacktrace_summary(
    files: List[str],
    file_line_pairs: List[Tuple[str, int]],
    functions: List[str],
) -> Dict:
    """Package parsed trace data into the dict expected by explain_top_commit."""
    return {
        "files": files,
        "file_line_pairs": file_line_pairs,
        "functions": functions,
    }


# ── main entry point ──────────────────────────────────────────────────────────

def explain_top_commit(
    commit: Dict,
    breakdown: Dict,
    stacktrace_summary: Dict,
    diff_excerpt: str,
    confidence: str,
) -> Optional[Explanation]:
    """
    Generate a grounded AI explanation for the top-ranked commit.

    Returns an Explanation dataclass, or None if the API call fails or
    OPENROUTER_API_KEY is not set (caller should fall back to generate_why).
    """
    if not _API_KEY:
        return None

    user_prompt = _build_user_prompt(
        commit, breakdown, stacktrace_summary, diff_excerpt, confidence
    )

    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0,   # deterministic output
    }

    try:
        resp = requests.post(_OPENROUTER_URL, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        print(f"  [explain] request error: {exc}", file=__import__("sys").stderr)
        return None

    if resp.status_code != 200:
        print(f"  [explain] HTTP {resp.status_code}: {resp.text[:200]}", file=__import__("sys").stderr)
        return None

    try:
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if the model wraps JSON in them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        print(f"  [explain] parse error: {exc}", file=__import__("sys").stderr)
        return None

    what = parsed.get("what_changed", "").strip()
    why  = parsed.get("why_related",  "").strip()

    if not what or not why:
        return None

    return Explanation(
        commit_hash=commit["hash"],
        what_changed=what,
        why_related=why,
        confidence=confidence,
    )

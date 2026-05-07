import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")


def explain_failure(stacktrace: str, top_commits: list) -> str:
    """
    Generate a grounded explanation for the top-ranked commit.

    The LLM must explain the ranking using only deterministic signals.
    It must not override the ranking or introduce external reasoning.
    """

    url = "https://openrouter.ai/api/v1/chat/completions"

    commit_summaries = ""

    for c in top_commits:
        commit_summaries += f"""
Commit: {c['hash']}
Files: {c['files']}
Score: {c['score']}
Timestamp: {c['timestamp']}
Modified functions: {c.get('modified_functions', [])}
Changed lines: {c.get('changed_lines', {})}
Total files changed: {len(c['files'])}
"""

    prompt = f"""
You are analyzing a software failure using structured signals.

STRICT RULES:
- Only use the provided data
- Do NOT invent causes or assume intent
- Prefer concrete signals over speculation
- If evidence is weak, explicitly say so

Stack trace:
{stacktrace}

Top suspect commits (ranked):
{commit_summaries}

AVAILABLE SIGNALS:
- File overlap
- Line-level proximity (changed lines near failure line)
- Function-level overlap or similarity
- Commit size (number of files changed)
- Recency (relative ordering)

IMPORTANT:
- The FIRST commit is already selected as the most likely cause
- Do NOT override the ranking
- Line proximity is the strongest signal when present
- Function-level overlap indicates structural relationship
- Larger commits are less precise

Task:
1. Use the FIRST commit as the most likely cause
2. Explain WHY using:
   - file overlap (if present)
   - line proximity (if present)
   - function-level overlap or similarity (if present)
   - recency (if relevant)
3. Do NOT rely on commit message meaning

Output format:

Most Likely Commit: <hash>

Reason:
- <file overlap reasoning>
- <line proximity reasoning if applicable>
- <function-level reasoning if applicable>
- <supporting signal (recency or others)>

Confidence: High / Medium / Low
"""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "openrouter/auto",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code != 200:
        return f"Error: {response.text}"

    return response.json()["choices"][0]["message"]["content"]
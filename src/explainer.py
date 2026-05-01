import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")


def explain_failure(stacktrace: str, top_commits: list) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"

    commit_summaries = ""
    for c in top_commits:
        changed_lines_info = ""
        if c.get("changed_lines"):
            changed_lines_info = f"- Changed lines: {c['changed_lines']}\n"

        commit_summaries += f"""
Commit: {c['hash']}
Message: {c['message']}
Files: {c['files']}
Score: {c['score']}
Timestamp: {c['timestamp']}
Signals:
- File overlap: {set(c['files']).intersection(set(stacktrace.split()))}
- Total files changed: {len(c['files'])}
{changed_lines_info}
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

Top suspect commits:
{commit_summaries}

AVAILABLE SIGNALS (already computed):
- File overlap with stack trace
- Line-level proximity (changed lines near error location)
- Commit size (number of files changed)
- Recency (relative within window)

IMPORTANT:
- Line proximity is the strongest signal when present
- Larger commits are LESS precise (do not treat them as more likely)
- The ranking already combines all signals — do not contradict it without strong evidence

Task:
1. Identify the most likely commit
2. Explain WHY using ONLY:
   - file overlap
   - line proximity (if present)
   - recency (if relevant)
3. Do NOT use commit message meaning as primary evidence

Output format:

Most Likely Commit: <hash>

Reason:
- <file overlap reasoning>
- <line proximity reasoning if applicable>
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
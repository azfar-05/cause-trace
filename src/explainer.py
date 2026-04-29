import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")


def explain_failure(stacktrace: str, top_commits: list) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"

    commit_summaries = ""
    for c in top_commits:
        commit_summaries += f"""
Commit: {c['hash']}
Message: {c['message']}
Files: {c['files']}
Score: {c['score']}
Timestamp: {c['timestamp']}
Signals:
- File overlap: {set(c['files']).intersection(set(stacktrace.split()))}
- Num files changed: {len(c['files'])}
"""

    prompt = f"""
You are a senior software engineer debugging a failure.

STRICT RULES:
- Only use the information provided
- Do NOT assume missing details
- If evidence is weak, say so
- Prefer concrete reasoning over generic statements

Stack trace:
{stacktrace}

Top suspect commits:
{commit_summaries}

Task:
1. Identify the most likely commit responsible
2. Explain WHY using:
   - file overlap with stack trace
   - type of change
   - recency
3. Mention uncertainty if applicable

Output format:

Most Likely Commit: <hash>

Reason:
- <point 1>
- <point 2>
- <point 3 (optional)>

Confidence: High / Medium / Low
IMPORTANT:
The scoring already considers recency and file relevance.
Do NOT contradict the ranking unless there is strong evidence.
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
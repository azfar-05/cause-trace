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
"""

    prompt = f"""
You are a senior engineer debugging a failure.

Stack trace:
{stacktrace}

Top suspect commits:
{commit_summaries}

Explain which commit is most likely responsible and why.
Be concise.
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
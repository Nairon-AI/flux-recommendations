#!/usr/bin/env python3
"""
Process a tweet from Slack inbox, analyze with Claude, and create a GitHub issue.

Usage:
    TWEET_URL=... TWITTER_API_KEY=... ANTHROPIC_API_KEY=... python scripts/slack-inbox.py
"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.request

TWITTER_API_BASE = "https://api.twitterapi.io"
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"

ANALYSIS_PROMPT = """You are analyzing a tweet to determine if it should become a recommendation in Flux - an AI-augmented SDLC workflow system.

Flux helps developers optimize their workflows with:
- MCPs (Model Context Protocol servers)
- CLI tools
- Editor plugins
- Skills (reusable prompts/workflows)
- Workflow patterns (best practices)

Categories in Flux:
- mcps/ (search, productivity, dev-tools)
- cli-tools/ (terminal, linting, git)
- plugins/ (vscode, neovim)
- skills/ (claude code skills)
- applications/ (desktop apps)
- workflow-patterns/ (ai, git, testing patterns)

SDLC phases where recommendations can help:
- Planning & Architecture
- Implementation & Coding
- Testing & QA
- Code Review
- Deployment & CI/CD
- Debugging & Maintenance

---

Analyze this tweet and provide:

1. **Relevance Score** (1-5 stars): How relevant is this to AI-augmented development?

2. **What It Is**: Brief explanation of the tool/technique/pattern being discussed

3. **Category**: Which Flux category would this belong in? (be specific, e.g., `workflow-patterns/verification/`)

4. **SDLC Fit**: Which phases of the SDLC does this help with?

5. **Integration Ideas**: How could this be integrated into an AI-augmented workflow?

6. **Recommendation**: Should we create a Flux recommendation for this? Why or why not?

7. **Next Steps**: If yes, what specific actions should we take?

Be concise but insightful. Focus on practical value for developers using AI coding assistants.

---

Tweet:
{tweet_text}

Author: @{author} ({author_name})
Engagement: {likes} likes, {retweets} retweets
"""


def extract_tweet_id(url):
    for pattern in [r"twitter\.com/\w+/status/(\d+)", r"x\.com/\w+/status/(\d+)"]:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_tweet(tweet_id, api_key):
    url = f"{TWITTER_API_BASE}/twitter/tweets?tweet_ids={tweet_id}"
    req = urllib.request.Request(url)
    req.add_header("X-API-Key", api_key)
    req.add_header("User-Agent", "FluxInbox/1.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            tweets = data.get("tweets", [])
            return tweets[0] if tweets else None
    except Exception as e:
        print(f"Error fetching tweet: {e}")
        return None


def analyze_with_claude(prompt, api_key):
    """Call Claude API to analyze the tweet."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    data = json.dumps(
        {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    req = urllib.request.Request(ANTHROPIC_API_BASE, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            return result.get("content", [{}])[0].get("text", "Analysis failed")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"Claude API error: {e.code} - {error_body}")
        return f"Analysis failed: {e.code}"
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return f"Analysis failed: {e}"


def main():
    # Get inputs
    tweet_url = os.environ.get("TWEET_URL")
    twitter_api_key = os.environ.get("TWITTER_API_KEY")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not tweet_url:
        print("Error: TWEET_URL not set")
        exit(1)
    if not twitter_api_key:
        print("Error: TWITTER_API_KEY not set")
        exit(1)
    if not anthropic_api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        exit(1)

    # Fetch tweet
    tweet_id = extract_tweet_id(tweet_url)
    if not tweet_id:
        print(f"Could not extract tweet ID from {tweet_url}")
        exit(1)

    tweet = fetch_tweet(tweet_id, twitter_api_key)
    if not tweet:
        print("Could not fetch tweet")
        exit(1)

    # Extract data
    text = tweet.get("text", "N/A")
    author = tweet.get("author", {}).get("userName", "unknown")
    author_name = tweet.get("author", {}).get("name", "Unknown")
    likes = tweet.get("likeCount", 0)
    retweets = tweet.get("retweetCount", 0)

    # Analyze with Claude
    prompt = ANALYSIS_PROMPT.format(
        tweet_text=text,
        author=author,
        author_name=author_name,
        likes=likes,
        retweets=retweets,
    )

    print("Analyzing tweet with Claude...")
    analysis = analyze_with_claude(prompt, anthropic_api_key)

    # Create issue title (first ~50 chars of tweet)
    title_text = text.replace("\n", " ")[:50]
    title = f"Inbox: {title_text}..."

    # Format tweet text as blockquote
    quoted_text = "\n".join(f"> {line}" for line in text.split("\n"))

    # Create issue body
    body = f"""## Tweet

{quoted_text}

**Author:** [@{author}](https://x.com/{author}) ({author_name})
**Engagement:** {likes} likes, {retweets} retweets
**Link:** {tweet_url}

---

## AI Analysis

{analysis}

---

## Actions

- [ ] Review AI analysis
- [ ] Create recommendation if approved
- [ ] Close issue when done

---
*Analyzed by Claude · From Slack inbox*
"""

    # Write body to file
    with open("/tmp/issue.md", "w") as f:
        f.write(body)

    # Create issue using gh cli
    result = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--title",
            title,
            "--body-file",
            "/tmp/issue.md",
            "--label",
            "inbox",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error creating issue: {result.stderr}")
        exit(1)

    print(f"Created issue: {result.stdout.strip()}")


if __name__ == "__main__":
    main()

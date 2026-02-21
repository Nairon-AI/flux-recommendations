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

ANALYSIS_PROMPT = """Analyze this tweet for Flux (AI-augmented dev workflow system).

Return ONLY valid JSON with this exact structure:
{{
  "title": "5-8 word title",
  "tldr": "1 sentence summary",
  "verdict": "Yes" | "No" | "Maybe",
  "stars": 1-5,
  "stars_reason": "brief reason",
  "category": "category/path/",
  "sdlc_phases": ["phase1", "phase2"],
  "what": "2-3 sentences explaining the tool/technique",
  "integration": "1-2 sentences on how to integrate"
}}

Categories: mcps/, cli-tools/, plugins/, skills/, applications/, workflow-patterns/
SDLC phases: Planning, Implementation, Testing, Code Review, CI/CD, Debugging

Tweet by @{author} ({author_name}) · {likes} likes, {retweets} RTs:
{tweet_text}
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


def fetch_thread_context(tweet, api_key):
    """Fetch parent tweet if this is a reply."""
    parent_id = tweet.get("inReplyToId") or tweet.get("in_reply_to_status_id")
    if not parent_id:
        return None

    parent = fetch_tweet(parent_id, api_key)
    return parent


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

    # Check if reply and fetch parent for context
    parent = fetch_thread_context(tweet, twitter_api_key)

    if parent:
        parent_text = parent.get("text", "")
        parent_author = parent.get("author", {}).get("userName", "unknown")
        context_text = f"""[Replying to @{parent_author}]:
{parent_text}

[Reply by @{author}]:
{text}"""
        print(f"Fetched parent tweet from @{parent_author}")
    else:
        context_text = text

    # Analyze with Claude
    prompt = ANALYSIS_PROMPT.format(
        tweet_text=context_text,
        author=author,
        author_name=author_name,
        likes=likes,
        retweets=retweets,
    )

    print("Analyzing tweet with Claude...")
    analysis_raw = analyze_with_claude(prompt, anthropic_api_key)

    # Parse JSON response
    try:
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", analysis_raw)
        if json_match:
            analysis_raw = json_match.group(1)
        analysis = json.loads(analysis_raw)
    except json.JSONDecodeError:
        print(f"Failed to parse Claude response as JSON: {analysis_raw[:200]}")
        # Fallback to simple format
        analysis = {
            "title": text.replace("\n", " ")[:40] + "...",
            "tldr": "Analysis failed - see raw response",
            "verdict": "Maybe",
            "stars": 3,
            "stars_reason": "Could not analyze",
            "category": "unknown/",
            "sdlc_phases": [],
            "what": analysis_raw[:500],
            "integration": "",
        }

    title = analysis.get("title", text[:40] + "...")

    # Format tweet content
    if parent:
        parent_text = parent.get("text", "")
        parent_author = parent.get("author", {}).get("userName", "unknown")
        tweet_content = f"""**@{parent_author}:**
> {parent_text}

**↳ @{author} replied:**
> {text}"""
    else:
        tweet_content = f"> {text}"

    # Build stars display
    stars = analysis.get("stars", 3)
    stars_display = "⭐" * stars + "☆" * (5 - stars)

    # Verdict emoji
    verdict = analysis.get("verdict", "Maybe")
    verdict_emoji = {"Yes": "✅", "No": "❌", "Maybe": "🤔"}.get(verdict, "🤔")

    # SDLC phases as tags
    phases = analysis.get("sdlc_phases", [])
    phases_display = " · ".join(phases) if phases else "—"

    # Create issue body - visual hierarchy
    body = f"""[→ View Tweet]({tweet_url}) · {likes} ❤️ · @{author}

{tweet_content}

---

## {verdict_emoji} Verdict: {verdict}

{analysis.get("tldr", "")}

| | |
|:--|:--|
| **Relevance** | {stars_display} — {analysis.get("stars_reason", "")} |
| **Category** | `{analysis.get("category", "unknown/")}` |
| **SDLC** | {phases_display} |

---

<details>
<summary><strong>📋 Details</strong></summary>

### What is this?
{analysis.get("what", "")}

### Integration
{analysis.get("integration", "")}

</details>

---
<sub>via Slack inbox</sub>
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

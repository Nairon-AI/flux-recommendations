#!/usr/bin/env python3
"""
Process a tweet from Slack inbox and create a GitHub issue.

Usage:
    TWEET_URL=... TWITTER_API_KEY=... python scripts/slack-inbox.py
"""

import json
import os
import re
import subprocess
import urllib.request

API_BASE = "https://api.twitterapi.io"


def extract_tweet_id(url):
    for pattern in [r"twitter\.com/\w+/status/(\d+)", r"x\.com/\w+/status/(\d+)"]:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_tweet(tweet_id, api_key):
    url = f"{API_BASE}/twitter/tweets?tweet_ids={tweet_id}"
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


def main():
    # Get inputs
    tweet_url = os.environ.get("TWEET_URL")
    api_key = os.environ.get("TWITTER_API_KEY")

    if not tweet_url:
        print("Error: TWEET_URL not set")
        exit(1)
    if not api_key:
        print("Error: TWITTER_API_KEY not set")
        exit(1)

    # Fetch tweet
    tweet_id = extract_tweet_id(tweet_url)
    if not tweet_id:
        print(f"Could not extract tweet ID from {tweet_url}")
        exit(1)

    tweet = fetch_tweet(tweet_id, api_key)
    if not tweet:
        print("Could not fetch tweet")
        exit(1)

    # Extract data
    text = tweet.get("text", "N/A")
    author = tweet.get("author", {}).get("userName", "unknown")
    author_name = tweet.get("author", {}).get("name", "Unknown")
    likes = tweet.get("likeCount", 0)
    retweets = tweet.get("retweetCount", 0)

    # Create issue title (first ~60 chars)
    title_text = text.replace("\n", " ")[:60]
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

## Review Questions

- [ ] Is this relevant to AI-augmented development workflows?
- [ ] What category would this belong in? (mcp, cli-tool, skill, workflow-pattern, etc.)
- [ ] What's the actual tool/technique being discussed?
- [ ] Should we create a recommendation for this?

## Notes

_Add your analysis here..._

---
*From Slack inbox*
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

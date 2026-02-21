#!/usr/bin/env python3
"""
Process a tweet URL and generate a recommendation suggestion.

Usage:
    python scripts/process-tweet.py <tweet_url>

Outputs JSON with recommendation details and writes /tmp/recommendation.yaml
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
import yaml

API_BASE = "https://api.twitterapi.io"

# Category keywords mapping
CATEGORY_HINTS = {
    "mcps/": ["mcp", "model context protocol", "claude desktop"],
    "cli-tools/": [
        "cli",
        "command line",
        "terminal",
        "brew install",
        "npm install -g",
        "cargo install",
    ],
    "plugins/": ["plugin", "extension", "vscode", "neovim", "vim"],
    "skills/": ["skill", "claude code skill", ".claude/skills"],
    "applications/": ["app", "application", "desktop", "macos", "windows"],
    "workflow-patterns/": ["workflow", "pattern", "practice", "methodology"],
}

SUBCATEGORY_HINTS = {
    "mcps/search/": ["search", "exa", "perplexity", "google"],
    "mcps/productivity/": ["memory", "notes", "todo", "calendar"],
    "mcps/dev-tools/": ["github", "linear", "jira", "git"],
    "cli-tools/terminal/": ["terminal", "shell", "zsh", "bash", "fzf"],
    "cli-tools/linting/": ["lint", "eslint", "biome", "oxlint", "prettier"],
    "cli-tools/git/": ["git", "diff", "commit", "branch"],
    "applications/individual/": ["personal", "individual", "solo"],
    "applications/collaboration/": ["team", "collaboration", "meeting", "share"],
}


def extract_tweet_id(url: str) -> str | None:
    """Extract tweet ID from URL."""
    patterns = [
        r"twitter\.com/\w+/status/(\d+)",
        r"x\.com/\w+/status/(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_tweet(tweet_id: str, api_key: str) -> dict | None:
    """Fetch tweet by ID."""
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
        print(f"Error fetching tweet: {e}", file=sys.stderr)
        return None


def guess_category(text: str) -> str:
    """Guess the best category based on tweet content."""
    text_lower = text.lower()

    # Check subcategories first (more specific)
    for subcat, keywords in SUBCATEGORY_HINTS.items():
        for kw in keywords:
            if kw in text_lower:
                return subcat

    # Fall back to main categories
    for cat, keywords in CATEGORY_HINTS.items():
        for kw in keywords:
            if kw in text_lower:
                return cat

    return "cli-tools/"  # Default


def extract_tool_name(text: str) -> str:
    """Try to extract the tool name from tweet."""
    # Look for @mentions that might be tool accounts
    mentions = re.findall(r"@(\w+)", text)

    # Look for quoted names
    quoted = re.findall(r'"([^"]+)"', text)
    if quoted:
        return quoted[0]

    # Look for capitalized tool names
    caps = re.findall(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)*)\b", text)
    tool_caps = [
        c
        for c in caps
        if c.lower() not in ["i", "the", "a", "this", "that", "it", "just", "new"]
    ]
    if tool_caps:
        return tool_caps[0]

    # Look for URLs that might contain tool name
    urls = re.findall(r"https?://(?:www\.)?([^/\s]+)", text)
    for url in urls:
        if "github.com" not in url and "twitter.com" not in url and "x.com" not in url:
            # Extract domain name
            parts = url.split(".")
            if parts:
                return parts[0]

    return "unknown-tool"


def generate_recommendation(tweet: dict, url: str) -> dict:
    """Generate a recommendation YAML from tweet data."""
    text = tweet.get("text", "")
    author = tweet.get("author", {}).get("userName", "unknown")
    likes = tweet.get("likeCount", 0)

    tool_name = extract_tool_name(text)
    category = guess_category(text)

    # Clean up tool name for filename
    filename = re.sub(r"[^a-z0-9-]", "-", tool_name.lower())
    filename = re.sub(r"-+", "-", filename).strip("-")
    if not filename:
        filename = "new-tool"
    filename = f"{filename}.yaml"

    # Build recommendation
    rec = {
        "name": tool_name,
        "description": f"TODO: Add description based on tweet from @{author}",
        "category": category.rstrip("/").split("/")[-1] if "/" in category else "tools",
        "tags": [],
        "install": "TODO: Add install instructions",
        "links": {
            "homepage": "TODO",
        },
        "mentions": [
            {
                "url": url,
                "author": f"@{author}",
                "text": text[:280],
                "likes": likes,
            }
        ],
        "_source_tweet": text,
        "_suggested_category": category,
    }

    # Try to extract tags from text
    hashtags = re.findall(r"#(\w+)", text)
    if hashtags:
        rec["tags"] = [h.lower() for h in hashtags[:5]]

    return {
        "title": tool_name,
        "category": category,
        "filename": filename,
        "recommendation": rec,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: process-tweet.py <tweet_url>", file=sys.stderr)
        sys.exit(1)

    tweet_url = sys.argv[1]
    api_key = os.environ.get("TWITTER_API_KEY")

    if not api_key:
        print("Error: TWITTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Extract tweet ID
    tweet_id = extract_tweet_id(tweet_url)
    if not tweet_id:
        print(f"Error: Could not extract tweet ID from {tweet_url}", file=sys.stderr)
        sys.exit(1)

    # Fetch tweet
    tweet = fetch_tweet(tweet_id, api_key)
    if not tweet:
        print("Error: Could not fetch tweet", file=sys.stderr)
        sys.exit(1)

    # Generate recommendation
    result = generate_recommendation(tweet, tweet_url)

    # Write YAML file
    rec = result["recommendation"]
    # Remove internal fields before writing
    rec_clean = {k: v for k, v in rec.items() if not k.startswith("_")}

    with open("/tmp/recommendation.yaml", "w") as f:
        yaml.dump(
            rec_clean, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    # Output result JSON
    print(
        json.dumps(
            {
                "title": result["title"],
                "category": result["category"],
                "filename": result["filename"],
            }
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Flux X Monitor - Fetches tweets and attaches them to recommendations as social proof.

Runs daily via GitHub Actions. Uses LLM to validate that tweets genuinely
mention tools before adding them as social proof.

Usage:
    python scripts/monitor.py [--dry-run] [--since HOURS]

Environment:
    TWITTER_API_KEY - TwitterAPI.io API key
    ANTHROPIC_API_KEY - For LLM validation (optional but recommended)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error
import yaml

# Config
API_BASE = "https://api.twitterapi.io"
REPO_ROOT = Path(__file__).parent.parent
ACCOUNTS_FILE = REPO_ROOT / "accounts.yaml"
STATE_FILE = REPO_ROOT / ".monitor_state.json"
PENDING_DIR = REPO_ROOT / "pending"

# Rate limiting
REQUEST_DELAY = 0.5

# Folders containing recommendations
REC_FOLDERS = [
    "mcps",
    "cli-tools",
    "plugins",
    "skills",
    "applications",
    "workflow-patterns",
]


def load_accounts() -> list[str]:
    """Load account list from accounts.yaml."""
    if not ACCOUNTS_FILE.exists():
        print(f"Error: {ACCOUNTS_FILE} not found")
        sys.exit(1)

    with open(ACCOUNTS_FILE) as f:
        config = yaml.safe_load(f)

    return config.get("monitored_accounts", [])


def load_state() -> dict:
    """Load seen tweet IDs."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
            if "seen_ids" not in state:
                state["seen_ids"] = []
            return state
    return {"seen_ids": []}


def save_state(state: dict):
    """Save state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# LLM validation settings
LLM_API_URL = "https://api.anthropic.com/v1/messages"
LLM_MODEL = "claude-sonnet-4-20250514"
LLM_CACHE = {}  # In-memory cache for this run


def validate_mention_with_llm(
    tweet_text: str,
    tool_name: str,
    tool_tagline: str,
    api_key: str | None,
) -> dict:
    """
    Use LLM to validate if a tweet genuinely mentions/recommends a specific tool.

    Returns:
        {
            "is_valid": bool,      # True if tweet is genuinely about this tool
            "confidence": str,     # "high", "medium", "low"
            "reason": str,         # Explanation
        }
    """
    if not api_key:
        # Fallback: no LLM available, be conservative
        return {
            "is_valid": False,
            "confidence": "none",
            "reason": "No LLM API key - skipping validation",
        }

    # Check cache
    cache_key = f"{tool_name}:{hash(tweet_text)}"
    if cache_key in LLM_CACHE:
        return LLM_CACHE[cache_key]

    prompt = f"""Analyze if this tweet is genuinely about the tool "{tool_name}" ({tool_tagline}).

Tweet: "{tweet_text}"

Rules:
1. The tweet must EXPLICITLY mention, recommend, or discuss "{tool_name}" specifically
2. Generic mentions of the category (e.g., "AI tools", "terminal apps") do NOT count
3. Mentions of SIMILAR tools or COMPETING products do NOT count
4. The tool name must appear OR be clearly implied by @mention/URL
5. Retweets count only if the original content is about the tool

Respond with JSON only:
{{"is_valid": true/false, "confidence": "high/medium/low", "reason": "brief explanation"}}"""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    body = json.dumps(
        {
            "model": LLM_MODEL,
            "max_tokens": 150,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    req = urllib.request.Request(LLM_API_URL, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("content", [{}])[0].get("text", "{}")

            # Parse JSON response
            # Handle potential markdown code blocks
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0]

            result = json.loads(content)
            LLM_CACHE[cache_key] = result
            return result

    except json.JSONDecodeError:
        return {
            "is_valid": False,
            "confidence": "error",
            "reason": "Failed to parse LLM response",
        }
    except urllib.error.HTTPError as e:
        return {
            "is_valid": False,
            "confidence": "error",
            "reason": f"LLM API error: {e.code}",
        }
    except Exception as e:
        return {"is_valid": False, "confidence": "error", "reason": f"LLM error: {e}"}


def load_all_recommendations() -> dict[str, dict]:
    """Load all recommendations with metadata for smart matching."""
    recommendations = {}

    for folder in REC_FOLDERS:
        folder_path = REPO_ROOT / folder
        if not folder_path.exists():
            continue

        for yaml_file in folder_path.rglob("*.yaml"):
            if yaml_file.name in ("schema.yaml", "accounts.yaml"):
                continue

            try:
                with open(yaml_file) as f:
                    rec = yaml.safe_load(f)

                name = rec.get("name", "").lower()
                if name:
                    recommendations[name] = {
                        "path": yaml_file,
                        "name": name,
                        "tagline": rec.get("tagline", ""),
                        # Extract Twitter/X handle if in resources
                        "twitter": None,
                        "homepage": None,
                    }
                    for res in rec.get("resources", []):
                        if res.get("type") == "twitter":
                            handle = res.get("url", "").split("/")[-1].lower()
                            if handle:
                                recommendations[name]["twitter"] = handle
                        if res.get("type") == "homepage":
                            recommendations[name]["homepage"] = res.get("url", "")

            except Exception as e:
                print(f"  Warning: Failed to load {yaml_file}: {e}")

    return recommendations


def find_candidate_recommendations(
    tweet_text: str, recommendations: dict[str, dict]
) -> list[dict]:
    """
    Find potential recommendation matches based on keywords/mentions.
    Returns candidates for LLM validation.
    """
    text_lower = tweet_text.lower()
    candidates = []

    # Extract @mentions from tweet
    mentions = {m.lower() for m in re.findall(r"@(\w+)", tweet_text)}

    # Extract URLs from tweet
    urls = set(re.findall(r"https?://[^\s<>\"]+", tweet_text.lower()))

    for name, meta in recommendations.items():
        match_reason = None

        # Method 1: @mention match (high signal)
        if meta.get("twitter") and meta["twitter"] in mentions:
            match_reason = f"@{meta['twitter']} mentioned"

        # Method 2: Homepage URL match (high signal)
        elif meta.get("homepage"):
            homepage_clean = (
                meta["homepage"]
                .lower()
                .replace("https://", "")
                .replace("http://", "")
                .rstrip("/")
            )
            for url in urls:
                url_clean = (
                    url.replace("https://", "").replace("http://", "").rstrip("/")
                )
                if homepage_clean and homepage_clean in url_clean:
                    match_reason = f"URL {homepage_clean} found"
                    break

        # Method 3: Name appears in text (needs LLM validation)
        elif len(name) >= 4:
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, text_lower):
                match_reason = f"keyword '{name}' found"

        if match_reason:
            candidates.append({**meta, "match_reason": match_reason})

    return candidates


def match_tweet_to_recommendation(
    tweet_text: str,
    recommendations: dict[str, dict],
    anthropic_key: str | None = None,
) -> tuple[Path | None, str | None]:
    """
    Match a tweet to a recommendation using LLM validation.

    Returns:
        (matched_path, rejection_reason) - path if matched, reason if rejected
    """
    candidates = find_candidate_recommendations(tweet_text, recommendations)

    if not candidates:
        return None, None

    # If we have an LLM key, validate each candidate
    if anthropic_key:
        for candidate in candidates:
            validation = validate_mention_with_llm(
                tweet_text=tweet_text,
                tool_name=candidate["name"],
                tool_tagline=candidate.get("tagline", ""),
                api_key=anthropic_key,
            )

            if validation.get("is_valid"):
                confidence = validation.get("confidence", "unknown")
                print(f"    LLM validated: {candidate['name']} ({confidence})")
                return candidate["path"], None
            else:
                reason = validation.get("reason", "unknown")
                print(f"    LLM rejected: {candidate['name']} - {reason}")

        # All candidates rejected by LLM
        return None, "LLM rejected all candidates"

    else:
        # No LLM key - only accept high-confidence matches (@mention or URL)
        for candidate in candidates:
            if "@" in candidate.get("match_reason", "") or "URL" in candidate.get(
                "match_reason", ""
            ):
                print(
                    f"    Auto-matched (no LLM): {candidate['name']} via {candidate['match_reason']}"
                )
                return candidate["path"], None

        # Keyword matches without LLM validation go to pending
        return None, "Keyword match needs LLM validation"


def add_mention_to_recommendation(
    yaml_path: Path, mention: dict, dry_run: bool = False
):
    """Add a mention to a recommendation's mentions array."""
    with open(yaml_path) as f:
        content = f.read()
        rec = yaml.safe_load(content)

    # Initialize mentions if not present
    if "mentions" not in rec:
        rec["mentions"] = []

    # Check for duplicate (same URL)
    existing_urls = {m.get("url") for m in rec["mentions"]}
    if mention["url"] in existing_urls:
        return False

    # Add the mention
    rec["mentions"].append(mention)

    if dry_run:
        print(f"    Would add mention to {yaml_path.name}")
        return True

    # Write back - preserve formatting as much as possible
    with open(yaml_path, "w") as f:
        yaml.dump(rec, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"    Added mention to {yaml_path.name}")
    return True


def evaluate_new_tool_with_llm(
    tweet_text: str,
    tweet_url: str,
    author: str,
    likes: int,
    api_key: str | None,
) -> dict | None:
    """
    Use LLM to evaluate if a tweet is about a genuinely useful NEW tool
    worth adding to the recommendations.

    Returns:
        Recommendation dict if valuable, None if not worth adding
    """
    if not api_key:
        return None

    # Skip low-engagement tweets
    if likes < 50:
        return None

    prompt = f"""Analyze this tweet and determine if it's recommending a specific, useful tool for AI-assisted software development.

Tweet by {author} ({likes} likes):
"{tweet_text}"

CRITERIA FOR VALUABLE TOOLS:
1. Must be a SPECIFIC tool, library, MCP server, CLI, plugin, or workflow pattern
2. Must be relevant to AI-assisted coding (Claude Code, Codex, Cursor, Aider, etc.)
3. Must NOT be: general advice, opinions, jokes, self-promotion without substance
4. Must NOT be: tools we likely already have (GitHub, VSCode, common libraries)
5. HIGH SIGNAL: 500+ likes, concrete tool recommendation, actionable
6. MEDIUM SIGNAL: 100-500 likes, specific tool mention
7. LOW SIGNAL: <100 likes, vague mention - REJECT unless exceptionally useful

If this IS a valuable new tool recommendation, respond with JSON:
{{
  "is_valuable": true,
  "tool_name": "tool-name-lowercase",
  "category": "mcp|cli-tool|plugin|skill|application|workflow-pattern",
  "subcategory": "optional/path",
  "tagline": "One line description max 80 chars",
  "description": "2-3 sentence description of what it does and why it's useful",
  "install_type": "npm|brew|manual|mcp|plugin|skill",
  "install_command": "npm install x or brew install x etc",
  "homepage": "https://... if mentioned",
  "github": "https://github.com/... if mentioned",
  "tags": ["tag1", "tag2"],
  "reason": "Why this is valuable"
}}

If NOT valuable, respond with JSON:
{{"is_valuable": false, "reason": "brief explanation"}}

Respond with JSON only, no markdown."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    body = json.dumps(
        {
            "model": LLM_MODEL,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    req = urllib.request.Request(LLM_API_URL, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("content", [{}])[0].get("text", "{}")

            # Handle markdown code blocks
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0]

            result = json.loads(content)

            if result.get("is_valuable"):
                return result
            else:
                print(f"    Rejected: {result.get('reason', 'unknown')[:50]}")
                return None

    except Exception as e:
        print(f"    LLM evaluation error: {e}")
        return None


def create_recommendation_yaml(
    tool_data: dict,
    tweet_url: str,
    author: str,
    tweet_text: str,
    likes: int,
    dry_run: bool = False,
) -> Path | None:
    """Create a recommendation YAML file from LLM-extracted tool data."""

    tool_name = tool_data.get("tool_name", "").lower().replace(" ", "-")
    if not tool_name:
        return None

    category = tool_data.get("category", "cli-tool")
    subcategory = tool_data.get("subcategory", "")

    # Map category to folder
    category_folders = {
        "mcp": "mcps",
        "cli-tool": "cli-tools",
        "plugin": "plugins",
        "skill": "skills",
        "application": "applications",
        "workflow-pattern": "workflow-patterns",
    }

    folder_name = category_folders.get(category, "discoveries")
    folder_path = REPO_ROOT / folder_name

    if subcategory:
        folder_path = folder_path / subcategory

    folder_path.mkdir(parents=True, exist_ok=True)
    yaml_path = folder_path / f"{tool_name}.yaml"

    # Don't overwrite existing
    if yaml_path.exists():
        print(f"    Skipping {tool_name} - already exists")
        return None

    # Build recommendation object
    rec = {
        "name": tool_name,
        "category": category,
        "tagline": tool_data.get("tagline", ""),
        "description": tool_data.get("description", ""),
        "install": {
            "type": tool_data.get("install_type", "manual"),
            "command": tool_data.get("install_command", "# See homepage"),
        },
        "verification": {
            "type": "manual",
        },
        "resources": [],
        "tags": tool_data.get("tags", []),
        "added_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "x-discovery",
        "source_url": tweet_url,
        "mentions": [
            {
                "url": tweet_url,
                "author": author,
                "text": tweet_text[:280] if len(tweet_text) > 280 else tweet_text,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "likes": likes,
            }
        ],
    }

    # Add resources if provided
    if tool_data.get("homepage"):
        rec["resources"].append({"url": tool_data["homepage"], "type": "homepage"})
    if tool_data.get("github"):
        rec["resources"].append({"url": tool_data["github"], "type": "github"})

    if dry_run:
        print(f"    Would create: {yaml_path}")
        return yaml_path

    with open(yaml_path, "w") as f:
        yaml.dump(rec, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"    Created: {yaml_path.relative_to(REPO_ROOT)}")
    return yaml_path


def evaluate_and_maybe_create_recommendation(
    tweet: dict,
    anthropic_key: str | None,
    dry_run: bool = False,
) -> bool:
    """
    Evaluate an unmatched tweet and create a recommendation if valuable.
    Returns True if a recommendation was created.
    """
    if not anthropic_key:
        return False

    tweet_text = tweet.get("text", "")
    tweet_url = tweet.get("url", "")
    author = tweet.get("author", "")
    likes = tweet.get("likes", 0)

    # Evaluate with LLM
    tool_data = evaluate_new_tool_with_llm(
        tweet_text=tweet_text,
        tweet_url=tweet_url,
        author=author,
        likes=likes,
        api_key=anthropic_key,
    )

    if not tool_data:
        return False

    # Create the recommendation
    result = create_recommendation_yaml(
        tool_data=tool_data,
        tweet_url=tweet_url,
        author=author,
        tweet_text=tweet_text,
        likes=likes,
        dry_run=dry_run,
    )

    return result is not None


def fetch_user_tweets(username: str, api_key: str) -> list[dict]:
    """Fetch recent tweets from a user via TwitterAPI.io."""
    url = f"{API_BASE}/twitter/user/last_tweets?userName={username}"

    req = urllib.request.Request(url)
    req.add_header("X-API-Key", api_key)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "FluxMonitor/1.0")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                tweets_data = data.get("data", {})
                if isinstance(tweets_data, dict):
                    return tweets_data.get("tweets", [])
                return data.get("tweets", [])
            else:
                print(f"  API error: {data.get('msg', 'unknown')}")
                return []
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  Rate limited, waiting...")
            time.sleep(2)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get("status") == "success":
                        tweets_data = data.get("data", {})
                        if isinstance(tweets_data, dict):
                            return tweets_data.get("tweets", [])
                return []
            except Exception:
                pass
        print(f"  HTTP {e.code}")
        return []
    except Exception as e:
        print(f"  Error: {e}")
        return []


def parse_tweet_date(date_str: str) -> datetime | None:
    """Parse Twitter date format."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch tweets and attach to recommendations"
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't modify files")
    parser.add_argument(
        "--since", type=int, default=24, help="Hours to look back (default: 24)"
    )
    parser.add_argument(
        "--account", type=str, help="Fetch single account (for testing)"
    )
    args = parser.parse_args()

    twitter_key = os.environ.get("TWITTER_API_KEY")
    if not twitter_key:
        print("Error: TWITTER_API_KEY not set")
        sys.exit(1)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        print("LLM validation enabled (Anthropic)")
    else:
        print("Warning: ANTHROPIC_API_KEY not set - using strict keyword matching only")

    # Load data
    accounts = [args.account] if args.account else load_accounts()
    recommendations = load_all_recommendations()
    state = load_state()
    seen_ids = set(state.get("seen_ids", []))

    print(f"Loaded {len(recommendations)} recommendation keywords")
    print(f"Fetching from {len(accounts)} accounts")
    print(f"Looking back {args.since} hours\n")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since)

    matched_count = 0
    unmatched_count = 0
    new_seen_ids = []

    for i, account in enumerate(accounts):
        if i > 0:
            time.sleep(REQUEST_DELAY)

        print(f"@{account}...", end=" ")

        tweets = fetch_user_tweets(account, twitter_key)
        if not tweets:
            print("no tweets")
            continue

        new_count = 0
        for tweet in tweets:
            tweet_id = tweet.get("id")
            tweet_date = parse_tweet_date(tweet.get("createdAt", ""))

            if not tweet_id:
                continue

            # Skip seen
            if tweet_id in seen_ids:
                continue

            # Skip old
            if tweet_date and tweet_date < cutoff:
                continue

            # Mark as seen
            seen_ids.add(tweet_id)
            new_seen_ids.append(tweet_id)
            new_count += 1

            text = tweet.get("text", "")
            tweet_url = tweet.get("url", "")

            # Build mention object
            mention = {
                "url": tweet_url,
                "author": f"@{account}",
                "text": text[:280] if len(text) > 280 else text,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "likes": tweet.get("likeCount", 0),
            }

            # Try to match to a recommendation (with LLM validation if available)
            matched_path, rejection_reason = match_tweet_to_recommendation(
                text, recommendations, anthropic_key
            )

            if matched_path:
                if add_mention_to_recommendation(matched_path, mention, args.dry_run):
                    matched_count += 1
            else:
                # Evaluate if this is a valuable NEW tool worth adding
                if evaluate_and_maybe_create_recommendation(
                    mention, anthropic_key, args.dry_run
                ):
                    unmatched_count += 1  # Now means "new recommendations created"

        print(f"{new_count} new")

    # Update state
    all_seen = state.get("seen_ids", []) + new_seen_ids
    state["seen_ids"] = all_seen[-10000:]  # Keep last 10K

    if not args.dry_run:
        save_state(state)

    print(f"\nMatched to recommendations: {matched_count}")
    print(f"New recommendations created: {unmatched_count}")

    return matched_count + unmatched_count


if __name__ == "__main__":
    count = main()
    sys.exit(0)

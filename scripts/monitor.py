#!/usr/bin/env python3
"""
Flux X Monitor - Fetches tweets and attaches them to recommendations as social proof.

Runs daily via GitHub Actions. Matches tweets to existing recommendations
and adds them as "mentions" to build trust.

Usage:
    python scripts/monitor.py [--dry-run] [--since HOURS]

Environment:
    TWITTER_API_KEY - TwitterAPI.io API key
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


def load_all_recommendations() -> dict[str, Path]:
    """Load all recommendations and build keyword -> file mapping."""
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
                    recommendations[name] = yaml_file

                    # Also index by tags
                    for tag in rec.get("tags", []):
                        tag_lower = tag.lower()
                        if tag_lower not in recommendations:
                            recommendations[tag_lower] = yaml_file

            except Exception as e:
                print(f"  Warning: Failed to load {yaml_file}: {e}")

    return recommendations


def match_tweet_to_recommendation(
    tweet_text: str, recommendations: dict[str, Path]
) -> Path | None:
    """Try to match a tweet to an existing recommendation."""
    text_lower = tweet_text.lower()

    # Direct name matches (prioritize longer names first)
    for name in sorted(recommendations.keys(), key=len, reverse=True):
        # Require word boundary match to avoid false positives
        pattern = r"\b" + re.escape(name) + r"\b"
        if re.search(pattern, text_lower):
            return recommendations[name]

    return None


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


def save_unmatched_tweet(tweet: dict, dry_run: bool = False):
    """Save unmatched tweet to pending folder for manual review."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pending_file = PENDING_DIR / f"tweets-{date_str}.yaml"

    # Load existing pending tweets
    pending = []
    if pending_file.exists():
        with open(pending_file) as f:
            pending = yaml.safe_load(f) or []

    # Check for duplicate
    existing_urls = {t.get("url") for t in pending}
    if tweet["url"] in existing_urls:
        return False

    pending.append(tweet)

    if dry_run:
        return True

    with open(pending_file, "w") as f:
        yaml.dump(pending, f, default_flow_style=False, allow_unicode=True)

    return True


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

    api_key = os.environ.get("TWITTER_API_KEY")
    if not api_key:
        print("Error: TWITTER_API_KEY not set")
        sys.exit(1)

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

        tweets = fetch_user_tweets(account, api_key)
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

            # Try to match to a recommendation
            matched_path = match_tweet_to_recommendation(text, recommendations)

            if matched_path:
                if add_mention_to_recommendation(matched_path, mention, args.dry_run):
                    matched_count += 1
            else:
                if save_unmatched_tweet(mention, args.dry_run):
                    unmatched_count += 1

        print(f"{new_count} new")

    # Update state
    all_seen = state.get("seen_ids", []) + new_seen_ids
    state["seen_ids"] = all_seen[-10000:]  # Keep last 10K

    if not args.dry_run:
        save_state(state)

    print(f"\nMatched to recommendations: {matched_count}")
    print(f"Saved to pending: {unmatched_count}")

    return matched_count + unmatched_count


if __name__ == "__main__":
    count = main()
    sys.exit(0)

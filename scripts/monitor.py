#!/usr/bin/env python3
"""
Flux X Monitor - Fetches tweets from curated AI dev accounts.

Runs daily via GitHub Actions. Saves tweets for human review.

Usage:
    python scripts/monitor.py [--dry-run] [--since HOURS]

Environment:
    TWITTER_API_KEY - TwitterAPI.io API key
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error
import yaml

# Config
API_BASE = "https://api.twitterapi.io"
ACCOUNTS_FILE = Path(__file__).parent.parent / "accounts.yaml"
OUTPUT_DIR = Path(__file__).parent.parent / "discoveries"
STATE_FILE = Path(__file__).parent.parent / ".monitor_state.json"

# Rate limiting - be polite
REQUEST_DELAY = 0.5


def load_accounts() -> list[str]:
    """Load account list from accounts.yaml."""
    if not ACCOUNTS_FILE.exists():
        print(f"Error: {ACCOUNTS_FILE} not found")
        sys.exit(1)

    with open(ACCOUNTS_FILE) as f:
        config = yaml.safe_load(f)

    accounts = config.get("monitored_accounts", [])
    if not accounts:
        # Fallback to old format
        for key, value in config.items():
            if isinstance(value, list) and key != "keywords":
                accounts.extend(value)

    return list(set(accounts))


def load_state() -> dict:
    """Load last seen tweet IDs per account and set of all seen tweet IDs."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
            # Ensure seen_ids exists
            if "seen_ids" not in state:
                state["seen_ids"] = []
            return state
    return {"last_seen": {}, "seen_ids": []}


def save_state(state: dict):
    """Save state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


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


def save_discoveries(tweets: list[dict], dry_run: bool = False):
    """Save tweets to discoveries folder as markdown."""
    if not tweets:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Group by date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = OUTPUT_DIR / f"{today}.md"

    content = f"# Discoveries - {today}\n\n"
    content += f"Found {len(tweets)} tweets from monitored accounts.\n\n"
    content += "---\n\n"

    for tweet in tweets:
        author = tweet.get("author", "unknown")
        text = tweet.get("text", "")
        url = tweet.get("url", "")
        likes = tweet.get("likes", 0)
        retweets = tweet.get("retweets", 0)

        content += f"### @{author}\n\n"
        content += f"{text}\n\n"
        content += f"[View tweet]({url}) | {likes} likes | {retweets} RTs\n\n"
        content += "---\n\n"

    if dry_run:
        print(f"\nWould save to: {filepath}")
        print(content[:500] + "...")
    else:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"\nSaved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Fetch tweets from monitored accounts")
    parser.add_argument("--dry-run", action="store_true", help="Don't save files")
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

    # Get accounts
    if args.account:
        accounts = [args.account]
    else:
        accounts = load_accounts()

    print(f"Fetching from {len(accounts)} accounts")
    print(f"Looking back {args.since} hours\n")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since)
    state = load_state()

    # Set of all previously seen tweet IDs for deduplication
    seen_ids = set(state.get("seen_ids", []))

    all_tweets = []
    new_seen_ids = []

    for i, account in enumerate(accounts):
        if i > 0:
            time.sleep(REQUEST_DELAY)

        print(f"@{account}...", end=" ")

        tweets = fetch_user_tweets(account, api_key)
        if not tweets:
            print("no tweets")
            continue

        new_tweets = []

        for tweet in tweets:
            tweet_id = tweet.get("id")
            tweet_date = parse_tweet_date(tweet.get("createdAt", ""))

            # Skip if no ID
            if not tweet_id:
                continue

            # Skip already seen (primary dedup check)
            if tweet_id in seen_ids:
                continue

            # Skip old tweets
            if tweet_date and tweet_date < cutoff:
                continue

            # Mark as seen
            seen_ids.add(tweet_id)
            new_seen_ids.append(tweet_id)

            new_tweets.append(
                {
                    "id": tweet_id,
                    "author": account,
                    "text": tweet.get("text", ""),
                    "url": tweet.get("url", ""),
                    "likes": tweet.get("likeCount", 0),
                    "retweets": tweet.get("retweetCount", 0),
                    "created_at": tweet.get("createdAt", ""),
                }
            )

        print(f"{len(new_tweets)} new")
        all_tweets.extend(new_tweets)

    # Update state with new seen IDs (keep last 10000 to avoid unbounded growth)
    all_seen = state.get("seen_ids", []) + new_seen_ids
    state["seen_ids"] = all_seen[-10000:]

    print(f"\nTotal: {len(all_tweets)} new tweets")

    if all_tweets:
        # Sort by engagement
        all_tweets.sort(key=lambda t: t["likes"] + t["retweets"] * 2, reverse=True)
        save_discoveries(all_tweets, args.dry_run)

    if not args.dry_run:
        save_state(state)

    return len(all_tweets)


if __name__ == "__main__":
    count = main()
    sys.exit(0)

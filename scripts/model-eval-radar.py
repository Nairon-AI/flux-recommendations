#!/usr/bin/env python3
"""
Model Evaluation Radar

Automates model evaluation reports from X/Twitter signals:
1) Detect release announcements from AI lab accounts
2) Collect monitored-account + high-engagement discovery tweets for 3 days
3) Synthesize structured report into model-evaluations/
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


API_BASE = "https://api.twitterapi.io"
STATE_FILE = Path(".model_eval_state.json")
ACCOUNTS_FILE = Path("accounts.yaml")
IN_PROGRESS_DIR = Path("evaluation-in-progress")
OUTPUT_DIR = Path("model-evaluations")

LAB_ACCOUNTS = [
    "AnthropicAI",
    "OpenAI",
    "GoogleAI",
    "MetaAI",
    "MistralAI",
    "xAI",
    "xaboratory",
]
RELEASE_KEYWORDS = [
    "releasing",
    "introducing",
    "announcing",
    "launching",
    "now available",
    "released",
]

POSITIVE_WORDS = {
    "great",
    "excellent",
    "impressive",
    "fast",
    "better",
    "powerful",
    "amazing",
    "solid",
    "love",
    "useful",
}
NEGATIVE_WORDS = {
    "bad",
    "worse",
    "slow",
    "broken",
    "hallucinate",
    "hallucination",
    "error",
    "wrong",
    "confusing",
    "expensive",
    "limit",
    "fails",
}

USE_CASE_KEYWORDS = {
    "coding": ["code", "coding", "programming", "refactor", "bug"],
    "frontend": ["frontend", "ui", "css", "react", "tailwind"],
    "backend": ["backend", "api", "server", "database", "sql"],
    "architecture": ["architecture", "system design", "scaling", "infra"],
    "reasoning": ["reasoning", "analysis", "complex", "thinking"],
    "agents": ["agent", "workflow", "mcp", "tooling", "automation"],
}

LIMITATION_KEYWORDS = {
    "hallucination": ["hallucinate", "hallucination", "made up"],
    "latency": ["slow", "latency", "wait", "takes forever"],
    "reliability": ["error", "fails", "flaky", "broken"],
    "context": ["forgets", "context", "memory", "re-explain"],
    "cost": ["expensive", "pricing", "cost"],
}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower())
    return re.sub(r"-+", "-", value).strip("-")


def safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_accounts() -> list[str]:
    if not ACCOUNTS_FILE.exists():
        return []
    try:
        with open(ACCOUNTS_FILE) as f:
            config = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return []
    accounts = config.get("monitored_accounts", [])
    return [a for a in accounts if isinstance(a, str)]


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"active": [], "completed": [], "last_run": ""}
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"active": [], "completed": [], "last_run": ""}
    if not isinstance(data, dict):
        return {"active": [], "completed": [], "last_run": ""}
    data.setdefault("active", [])
    data.setdefault("completed", [])
    data.setdefault("last_run", "")
    return data


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def parse_tweet_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None


def parse_iso_utc(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def tweet_in_window(tweet_created_at: str, window_start: str, window_end: str) -> bool:
    tweet_dt = parse_tweet_date(tweet_created_at)
    if not tweet_dt:
        return False
    tweet_dt = tweet_dt.astimezone(timezone.utc)
    start = parse_iso_utc(window_start)
    end = parse_iso_utc(window_end)
    return start <= tweet_dt <= end


def search_tweets(query: str, api_key: str, query_type: str = "Latest") -> list[dict]:
    params = urllib.parse.urlencode({"query": query, "queryType": query_type})
    url = f"{API_BASE}/twitter/tweet/advanced_search?{params}"

    req = urllib.request.Request(url)
    req.add_header("X-API-Key", api_key)
    req.add_header("User-Agent", "FluxModelEval/1.0")

    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return []
    except json.JSONDecodeError:
        return []

    if isinstance(payload.get("tweets"), list):
        return payload["tweets"]
    if isinstance(payload.get("data"), dict) and isinstance(
        payload["data"].get("tweets"), list
    ):
        return payload["data"]["tweets"]
    return []


def is_release_tweet(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in RELEASE_KEYWORDS)


def clean_model_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip(" .,:;!-\n\t")
    cleaned = re.sub(r"^(the|our)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s+(model|today|now|for developers)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned[:60]


def extract_model_name(text: str) -> str | None:
    patterns = [
        r"(?:introducing|announcing|launching|releasing)\s+([A-Z][A-Za-z0-9 .+\-]{1,50})",
        r"([A-Z][A-Za-z0-9.+\-]{1,30}(?:\s+[A-Za-z0-9.+\-]{1,20}){0,2})\s+(?:is now available|released|launch(?:ed|ing))",
        r"\b(GPT[- ]?[0-9][A-Za-z0-9.\-]*)\b",
        r"\b(Claude\s+[A-Za-z0-9.\-]+)\b",
        r"\b(Gemini\s+[A-Za-z0-9.\-]+)\b",
        r"\b(Llama\s*[0-9A-Za-z.\-]*)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = clean_model_name(match.group(1))
            if len(candidate) >= 3:
                return candidate
    return None


def normalize_tweet(tweet: dict, source: str) -> dict | None:
    text = (tweet.get("text") or "").strip()
    if not text:
        return None

    author = tweet.get("author", {}) or {}
    username = author.get("userName") or author.get("username") or "unknown"
    tweet_id = tweet.get("id")
    url = tweet.get("url")
    if not url and tweet_id:
        url = f"https://x.com/{username}/status/{tweet_id}"
    if not url:
        return None

    return {
        "id": str(tweet_id or ""),
        "url": url,
        "author": f"@{username}",
        "text": text,
        "likes": safe_int(tweet.get("likeCount", 0)),
        "retweets": safe_int(tweet.get("retweetCount", 0)),
        "quotes": safe_int(tweet.get("quoteCount", 0)),
        "views": safe_int(tweet.get("viewCount", 0)),
        "created_at": tweet.get("createdAt", ""),
        "source": source,
    }


def engagement_score(tweet: dict) -> int:
    return (
        int(tweet.get("likes", 0))
        + int(tweet.get("retweets", 0)) * 3
        + int(tweet.get("quotes", 0)) * 2
        + int(tweet.get("views", 0)) // 1000
    )


def detect_releases(api_key: str, since_days: int = 7) -> list[dict]:
    since_date = (now_utc() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    found = {}

    for account in LAB_ACCOUNTS:
        query = (
            f"from:{account} (releasing OR introducing OR announcing OR launching "
            f'OR "now available") since:{since_date}'
        )
        tweets = search_tweets(query, api_key, query_type="Latest")

        for raw in tweets:
            text = raw.get("text") or ""
            if not is_release_tweet(text):
                continue
            model_name = extract_model_name(text)
            if not model_name:
                continue

            tweet_date = parse_tweet_date(raw.get("createdAt", ""))
            if not tweet_date:
                # Skip ambiguous release timing if date is unparseable
                continue
            start = tweet_date.astimezone(timezone.utc)
            end = start + timedelta(days=3)
            model_id = (
                f"{slugify(account)}-{slugify(model_name)}-{start.strftime('%Y%m%d')}"
            )

            normalized = normalize_tweet(raw, source="release")
            if not normalized:
                continue

            candidate = {
                "id": model_id,
                "model_name": model_name,
                "lab": account,
                "release_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "window_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "window_end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "release_tweet": normalized,
            }

            existing = found.get(model_id)
            if not existing:
                found[model_id] = candidate
            else:
                existing_start = parse_iso_utc(existing["window_start"])
                if start < existing_start:
                    found[model_id] = candidate

    return list(found.values())


def add_new_evaluations(state: dict, releases: list[dict]) -> int:
    active_ids = {item.get("id") for item in state.get("active", [])}
    completed_ids = set(state.get("completed", []))
    added = 0

    for release in releases:
        rid = release.get("id")
        if not rid or rid in active_ids or rid in completed_ids:
            continue
        state["active"].append(release)
        active_ids.add(rid)
        added += 1
    return added


def collect_monitored_mentions(
    eval_item: dict, api_key: str, accounts: list[str]
) -> list[dict]:
    model = eval_item["model_name"]
    start_dt = parse_iso_utc(eval_item["window_start"])
    end_dt = parse_iso_utc(eval_item["window_end"])
    start = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    end = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    collected = []

    for account in accounts:
        query = f'from:{account} "{model}" since:{start} until:{end}'
        tweets = search_tweets(query, api_key, query_type="Latest")
        for raw in tweets:
            normalized = normalize_tweet(raw, source="monitored")
            if normalized and tweet_in_window(
                normalized.get("created_at", ""),
                eval_item["window_start"],
                eval_item["window_end"],
            ):
                collected.append(normalized)

    return collected


def collect_high_engagement_discovery(eval_item: dict, api_key: str) -> list[dict]:
    model = eval_item["model_name"]
    start_dt = parse_iso_utc(eval_item["window_start"])
    end_dt = parse_iso_utc(eval_item["window_end"])
    start = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    end = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    query = f'"{model}" min_faves:50 min_retweets:10 since:{start} until:{end}'
    tweets = search_tweets(query, api_key, query_type="Top")
    out = []
    for raw in tweets:
        normalized = normalize_tweet(raw, source="discovery")
        if normalized and tweet_in_window(
            normalized.get("created_at", ""),
            eval_item["window_start"],
            eval_item["window_end"],
        ):
            out.append(normalized)
    return out


def merge_tweets(existing: list[dict], new_items: list[dict]) -> list[dict]:
    def canonical_key(tweet: dict) -> str:
        tweet_id = tweet.get("id")
        if tweet_id:
            return str(tweet_id)
        url = tweet.get("url", "")
        match = re.search(r"/status/(\d+)", url)
        if match:
            return match.group(1)
        return url

    by_key = {}
    for item in existing + new_items:
        key = canonical_key(item)
        if not key:
            continue
        prev = by_key.get(key)
        if not prev or engagement_score(item) > engagement_score(prev):
            by_key[key] = item

    merged = list(by_key.values())
    merged.sort(key=engagement_score, reverse=True)
    return merged


def in_progress_path(eval_item: dict) -> Path:
    IN_PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    return IN_PROGRESS_DIR / f"{eval_item['id']}.json"


def load_in_progress_tweets(eval_item: dict) -> list[dict]:
    path = in_progress_path(eval_item)
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    tweets = data.get("tweets", [])
    return tweets if isinstance(tweets, list) else []


def save_in_progress(eval_item: dict, tweets: list[dict], dry_run: bool):
    path = in_progress_path(eval_item)
    payload = {
        "model": eval_item["model_name"],
        "lab": eval_item["lab"],
        "window_start": eval_item["window_start"],
        "window_end": eval_item["window_end"],
        "tweet_count": len(tweets),
        "tweets": tweets,
        "updated_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not dry_run:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)


def sentiment_score(tweets: list[dict]) -> int:
    pos = 0
    neg = 0
    for tweet in tweets:
        text = (tweet.get("text") or "").lower()
        pos += sum(1 for word in POSITIVE_WORDS if word in text)
        neg += sum(1 for word in NEGATIVE_WORDS if word in text)
    total = pos + neg
    if total == 0:
        return 50
    ratio = (pos - neg) / total
    score = int(50 + (ratio * 50))
    return max(0, min(100, score))


def build_use_cases(tweets: list[dict]) -> list[dict]:
    results = []
    for domain, keywords in USE_CASE_KEYWORDS.items():
        matched = [
            t
            for t in tweets
            if any(keyword in (t.get("text") or "").lower() for keyword in keywords)
        ]
        if not matched:
            continue
        evidence = [t.get("url") for t in matched[:3] if t.get("url")]
        count = len(matched)
        rating = 5 if count >= 10 else 4 if count >= 6 else 3 if count >= 3 else 2
        results.append({"domain": domain, "rating": rating, "evidence": evidence})
    return results


def build_limitations(tweets: list[dict]) -> list[dict]:
    limitations = []
    for category, keywords in LIMITATION_KEYWORDS.items():
        matched = [
            t
            for t in tweets
            if any(keyword in (t.get("text") or "").lower() for keyword in keywords)
        ]
        if not matched:
            continue
        evidence = [t.get("url") for t in matched[:3] if t.get("url")]
        limitations.append(
            {
                "category": category,
                "description": f"Community reported {category}-related issues",
                "evidence": evidence,
            }
        )
    return limitations


def synthesize_report(eval_item: dict, tweets: list[dict]) -> dict:
    top_sources = sorted(tweets, key=engagement_score, reverse=True)[:25]
    sources = [
        {
            "url": t.get("url", ""),
            "author": t.get("author", ""),
            "likes": t.get("likes", 0),
            "retweets": t.get("retweets", 0),
            "views": t.get("views", 0),
        }
        for t in top_sources
        if t.get("url")
    ]

    return {
        "model_name": eval_item["model_name"],
        "lab": eval_item["lab"],
        "release_date": eval_item["release_date"],
        "evaluation_window": {
            "start": eval_item["window_start"],
            "end": eval_item["window_end"],
            "days": 3,
        },
        "tweet_count": len(tweets),
        "sentiment_score": sentiment_score(tweets),
        "use_cases": build_use_cases(tweets),
        "limitations": build_limitations(tweets),
        "sources": sources,
        "generated_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_report(eval_item: dict, report: dict, dry_run: bool):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{eval_item['id']}.yaml"
    if dry_run:
        print(f"[dry-run] Would write report: {path}")
        return
    with open(path, "w") as f:
        yaml.dump(
            report, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )


def process_active_evaluations(
    state: dict, api_key: str, monitored_accounts: list[str], dry_run: bool
) -> tuple[int, int]:
    still_active = []
    completed = 0
    collected = 0

    for item in state.get("active", []):
        existing = load_in_progress_tweets(item)
        monitored = collect_monitored_mentions(item, api_key, monitored_accounts)
        discovery = collect_high_engagement_discovery(item, api_key)
        merged = merge_tweets(existing, monitored + discovery)
        collected += len(monitored) + len(discovery)
        save_in_progress(item, merged, dry_run=dry_run)

        window_end = datetime.fromisoformat(item["window_end"].replace("Z", "+00:00"))
        if now_utc() >= window_end:
            report = synthesize_report(item, merged)
            write_report(item, report, dry_run=dry_run)
            state["completed"].append(item["id"])
            completed += 1
            if not dry_run:
                path = in_progress_path(item)
                if path.exists():
                    path.unlink()
        else:
            still_active.append(item)

    state["active"] = still_active
    return collected, completed


def main():
    parser = argparse.ArgumentParser(
        description="Model evaluation automation from release + engagement signals"
    )
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--detect-only", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("TWITTER_API_KEY")
    if not api_key:
        print("Error: TWITTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    monitored_accounts = load_accounts()

    releases = detect_releases(api_key, since_days=args.since_days)
    added = add_new_evaluations(state, releases)

    print(f"Detected releases: {len(releases)}")
    print(f"New evaluation windows started: {added}")

    if args.detect_only:
        if not args.dry_run:
            state["last_run"] = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
            save_state(state)
        return

    collected, completed = process_active_evaluations(
        state, api_key, monitored_accounts, args.dry_run
    )
    print(f"Tweets collected this run: {collected}")
    print(f"Evaluations completed this run: {completed}")
    print(f"Active evaluations: {len(state.get('active', []))}")

    if not args.dry_run:
        state["last_run"] = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        save_state(state)


if __name__ == "__main__":
    main()

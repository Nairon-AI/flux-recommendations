#!/usr/bin/env python3
"""
Process a tweet from Slack inbox, analyze with Claude, and create a GitHub issue.

Usage:
    TWEET_URL=... TWITTER_API_KEY=... ANTHROPIC_API_KEY=... python scripts/slack-inbox.py
"""

import glob
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

TWITTER_API_BASE = "https://api.twitterapi.io"
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"

ANALYSIS_PROMPT = """Analyze this tweet for Flux (AI-augmented dev workflow system).

IMPORTANT: First check if this tool/technique/pattern already exists in:
1. Existing recommendations (provided below)
2. The Flux plugin codebase (already built-in)

Return ONLY valid JSON:
{{
  "title": "5-8 word title",
  "tldr": "1 sentence summary",
  "verdict": "Yes" | "No" | "Maybe" | "Duplicate",
  "stars": 1-5,
  "stars_reason": "brief reason",
  "category": "category/path/",
  "sdlc_phases": ["phase1", "phase2"],
  "what": "2-3 sentences explaining the tool/technique",
  "integration": "1-2 sentences on how to integrate",
  "duplicate_of": null | "path/to/existing.yaml or 'flux-plugin'",
  "duplicate_reason": null | "explanation of overlap"
}}

If duplicate_of is set, verdict MUST be "Duplicate".

Categories: mcps/, cli-tools/, plugins/, skills/, applications/, workflow-patterns/
SDLC phases: Planning, Implementation, Testing, Code Review, CI/CD, Debugging

---

EXISTING RECOMMENDATIONS:
{existing_recommendations}

---

FLUX PLUGIN BUILT-IN FEATURES:
{flux_plugin_context}

---

Tweet by @{author} ({author_name}) · {likes} likes, {retweets} RTs:
{tweet_text}
"""


def load_existing_recommendations(recommendations_path):
    """Load all existing recommendation YAML files as context."""
    recommendations = []
    yaml_files = glob.glob(f"{recommendations_path}/**/*.yaml", recursive=True)
    yaml_files += glob.glob(f"{recommendations_path}/**/*.yml", recursive=True)

    for filepath in yaml_files:
        # Skip schema and config files
        if "schema" in filepath.lower() or "accounts" in filepath.lower():
            continue
        try:
            with open(filepath, "r") as f:
                content = f.read()
                # Extract just the key info: name, description, tags
                name_match = re.search(r"name:\s*(.+)", content)
                desc_match = re.search(r"description:\s*(.+)", content)
                rel_path = os.path.relpath(filepath, recommendations_path)

                name = name_match.group(1).strip() if name_match else rel_path
                desc = desc_match.group(1).strip() if desc_match else ""

                recommendations.append(f"- {rel_path}: {name} - {desc[:100]}")
        except Exception:
            continue

    return "\n".join(recommendations) if recommendations else "(none yet)"


def load_flux_plugin_context(flux_path):
    """Load key files from flux plugin to understand built-in features."""
    context_parts = []

    # Key files that describe flux capabilities
    key_files = [
        "README.md",
        "commands/flux/improve.md",
        "commands/flux/plan.md",
        "commands/flux/work.md",
        "commands/flux/setup.md",
    ]

    for filename in key_files:
        filepath = os.path.join(flux_path, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    content = f.read()
                    # Truncate long files
                    if len(content) > 2000:
                        content = content[:2000] + "\n... (truncated)"
                    context_parts.append(f"### {filename}\n{content}")
            except Exception:
                continue

    return (
        "\n\n".join(context_parts) if context_parts else "(flux plugin not available)"
    )


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
    recommendations_path = os.environ.get("RECOMMENDATIONS_PATH", ".")
    flux_plugin_path = os.environ.get("FLUX_PLUGIN_PATH", "")

    if not tweet_url:
        print("Error: TWEET_URL not set")
        exit(1)
    if not twitter_api_key:
        print("Error: TWITTER_API_KEY not set")
        exit(1)
    if not anthropic_api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        exit(1)

    # Load existing context for deduplication
    print("Loading existing recommendations...")
    existing_recs = load_existing_recommendations(recommendations_path)
    print(
        f"Found {existing_recs.count(chr(10)) + 1 if existing_recs != '(none yet)' else 0} recommendations"
    )

    print("Loading flux plugin context...")
    flux_context = (
        load_flux_plugin_context(flux_plugin_path)
        if flux_plugin_path
        else "(not available)"
    )

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
        existing_recommendations=existing_recs,
        flux_plugin_context=flux_context,
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
            "duplicate_of": None,
            "duplicate_reason": None,
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
    verdict_emoji = {"Yes": "✅", "No": "❌", "Maybe": "🤔", "Duplicate": "🔄"}.get(
        verdict, "🤔"
    )

    # SDLC phases as tags
    phases = analysis.get("sdlc_phases", [])
    phases_display = " · ".join(phases) if phases else "—"

    # Check for duplicate
    duplicate_of = analysis.get("duplicate_of")
    duplicate_reason = analysis.get("duplicate_reason")

    # Build duplicate section if needed
    if duplicate_of:
        duplicate_section = f"""
> **🔄 Already exists:** `{duplicate_of}`
> 
> {duplicate_reason or "This appears to already be covered."}

"""
    else:
        duplicate_section = ""

    # Create issue body - visual hierarchy
    body = f"""[→ View Tweet]({tweet_url}) · {likes} ❤️ · @{author}

{tweet_content}

---

## {verdict_emoji} Verdict: {verdict}

{analysis.get("tldr", "")}
{duplicate_section}
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
    labels = ["inbox"]
    if duplicate_of:
        labels.append("duplicate")

    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        title,
        "--body-file",
        "/tmp/issue.md",
    ]
    for label in labels:
        cmd.extend(["--label", label])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error creating issue: {result.stderr}")
        exit(1)

    print(f"Created issue: {result.stdout.strip()}")


if __name__ == "__main__":
    main()

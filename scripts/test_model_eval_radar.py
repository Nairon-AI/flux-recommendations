#!/usr/bin/env python3
"""Unit tests for model-eval-radar.py."""

import importlib.util
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parent / "model-eval-radar.py"
SPEC = importlib.util.spec_from_file_location("model_eval_radar", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
model_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_eval)


def test_extract_model_name_release_phrase():
    text = "Today we are introducing Claude 4.5 Sonnet for developers"
    name = model_eval.extract_model_name(text)
    assert name is not None
    assert "claude" in name.lower()


def test_extract_model_name_known_pattern():
    text = "GPT-5 is now available in the API"
    name = model_eval.extract_model_name(text)
    assert name is not None
    assert "gpt" in name.lower()


def test_is_release_tweet_detection():
    assert model_eval.is_release_tweet("We are launching Gemini 2.5 Pro")
    assert not model_eval.is_release_tweet("Debugging CSS issue in Next.js")


def test_parse_tweet_date_supports_iso_and_invalid():
    iso = "2026-02-20T10:30:00Z"
    parsed = model_eval.parse_tweet_date(iso)
    assert parsed is not None
    assert parsed.year == 2026

    invalid = model_eval.parse_tweet_date("not-a-date")
    assert invalid is None


def test_tweet_in_window_filters_exact_bounds():
    start = "2026-02-20T10:00:00Z"
    end = "2026-02-23T10:00:00Z"

    inside = "Thu Feb 20 12:00:00 +0000 2026"
    before = "Thu Feb 20 09:59:59 +0000 2026"
    after = "Mon Feb 23 10:00:01 +0000 2026"

    assert model_eval.tweet_in_window(inside, start, end)
    assert not model_eval.tweet_in_window(before, start, end)
    assert not model_eval.tweet_in_window(after, start, end)


def test_safe_int_handles_invalid_values():
    assert model_eval.safe_int("12") == 12
    assert model_eval.safe_int("N/A") == 0
    assert model_eval.safe_int(None) == 0


def test_engagement_score_ranking_behavior():
    high = {"likes": 120, "retweets": 50, "quotes": 5, "views": 10000}
    low = {"likes": 200, "retweets": 2, "quotes": 0, "views": 1000}
    assert model_eval.engagement_score(high) > model_eval.engagement_score(low)


def test_merge_tweets_dedupes_on_id_and_keeps_best():
    existing = [
        {
            "id": "1",
            "url": "https://x.com/a/status/1",
            "likes": 10,
            "retweets": 2,
            "quotes": 0,
            "views": 100,
        }
    ]
    new_items = [
        {
            "id": "1",
            "url": "https://x.com/a/status/1",
            "likes": 50,
            "retweets": 10,
            "quotes": 1,
            "views": 1000,
        },
        {
            "id": "2",
            "url": "https://x.com/b/status/2",
            "likes": 12,
            "retweets": 1,
            "quotes": 0,
            "views": 50,
        },
    ]

    merged = model_eval.merge_tweets(existing, new_items)
    assert len(merged) == 2
    assert merged[0]["id"] == "1"
    assert merged[0]["likes"] == 50


def test_detect_releases_keeps_earliest_tweet_for_same_model():
    original_search = model_eval.search_tweets
    original_labs = model_eval.LAB_ACCOUNTS

    def fake_search(_query, _api_key, query_type="Latest"):
        return [
            {
                "id": "newer",
                "text": "Announcing Claude 4.5 today",
                "createdAt": "Thu Feb 20 12:00:00 +0000 2026",
                "url": "https://x.com/anthropicai/status/newer",
                "author": {"userName": "AnthropicAI"},
            },
            {
                "id": "older",
                "text": "Introducing Claude 4.5",
                "createdAt": "Thu Feb 20 09:00:00 +0000 2026",
                "url": "https://x.com/anthropicai/status/older",
                "author": {"userName": "AnthropicAI"},
            },
        ]

    setattr(model_eval, "LAB_ACCOUNTS", ["AnthropicAI"])
    setattr(model_eval, "search_tweets", fake_search)
    try:
        releases = model_eval.detect_releases("dummy", since_days=7)
        assert len(releases) == 1
        assert releases[0]["release_tweet"]["id"] == "older"
    finally:
        setattr(model_eval, "LAB_ACCOUNTS", original_labs)
        setattr(model_eval, "search_tweets", original_search)


def test_load_state_and_accounts_handle_corruption():
    original_state_file = model_eval.STATE_FILE
    original_accounts_file = model_eval.ACCOUNTS_FILE

    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        accounts_path = Path(tmp) / "accounts.yaml"

        state_path.write_text("{not-json")
        accounts_path.write_text(": bad-yaml")

        setattr(model_eval, "STATE_FILE", state_path)
        setattr(model_eval, "ACCOUNTS_FILE", accounts_path)

        state = model_eval.load_state()
        accounts = model_eval.load_accounts()

        assert state["active"] == []
        assert state["completed"] == []
        assert accounts == []

    setattr(model_eval, "STATE_FILE", original_state_file)
    setattr(model_eval, "ACCOUNTS_FILE", original_accounts_file)


def test_synthesize_report_has_required_fields():
    eval_item = {
        "id": "anthropicai-claude-4-5",
        "model_name": "Claude 4.5",
        "lab": "AnthropicAI",
        "release_date": "2026-02-20T00:00:00Z",
        "window_start": "2026-02-20T00:00:00Z",
        "window_end": "2026-02-23T00:00:00Z",
    }
    tweets = [
        {
            "id": "1",
            "url": "https://x.com/u/status/1",
            "author": "@u",
            "text": "Great coding workflow and better frontend results",
            "likes": 100,
            "retweets": 20,
            "quotes": 2,
            "views": 5000,
        },
        {
            "id": "2",
            "url": "https://x.com/v/status/2",
            "author": "@v",
            "text": "Sometimes slow and has hallucination errors",
            "likes": 40,
            "retweets": 8,
            "quotes": 1,
            "views": 3000,
        },
    ]

    report = model_eval.synthesize_report(eval_item, tweets)
    assert report["model_name"] == "Claude 4.5"
    assert report["tweet_count"] == 2
    assert "use_cases" in report
    assert "limitations" in report
    assert "sources" in report


def run_all_tests():
    test_extract_model_name_release_phrase()
    test_extract_model_name_known_pattern()
    test_is_release_tweet_detection()
    test_parse_tweet_date_supports_iso_and_invalid()
    test_tweet_in_window_filters_exact_bounds()
    test_safe_int_handles_invalid_values()
    test_engagement_score_ranking_behavior()
    test_merge_tweets_dedupes_on_id_and_keeps_best()
    test_detect_releases_keeps_earliest_tweet_for_same_model()
    test_load_state_and_accounts_handle_corruption()
    test_synthesize_report_has_required_fields()
    print("All model-eval-radar tests passed")


if __name__ == "__main__":
    run_all_tests()

"""Tap discovery tests that do not call the Ads API."""

from tap_chatgpt_ads.tap import TapChatGPTAds

SAMPLE_CONFIG = {
    "api_key": "test-api-key",
    "start_date": "2026-09-01",
    "lookback_days": 7,
    "chunk_days": 31,
}


def test_discover_streams_exposes_ad_performance() -> None:
    tap = TapChatGPTAds(config=SAMPLE_CONFIG, validate_config=False)
    assert [stream.name for stream in tap.discover_streams()] == ["ad_performance"]

"""ChatGPT Ads tap class."""

from __future__ import annotations

import sys

from singer_sdk import Tap
from singer_sdk import typing as th

from tap_chatgpt_ads import streams
from tap_chatgpt_ads.reporting import DEFAULT_CHUNK_DAYS, DEFAULT_LOOKBACK_DAYS

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class TapChatGPTAds(Tap):
    """Singer tap for the ChatGPT Ads API."""

    name = "tap-chatgpt-ads"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "api_key",
            th.StringType(nullable=False),
            required=True,
            secret=True,
            title="API Key",
            description="Ad account-scoped ChatGPT Ads Advertiser API key.",
        ),
        th.Property(
            "start_date",
            th.DateTimeType(nullable=True),
            description="Earliest reporting date to extract. Defaults to lookback_days.",
        ),
        th.Property(
            "lookback_days",
            th.IntegerType(nullable=False),
            default=DEFAULT_LOOKBACK_DAYS,
            description=(
                "Days before the bookmark to restate. Covers delayed spend and "
                "attributed conversions."
            ),
        ),
        th.Property(
            "chunk_days",
            th.IntegerType(nullable=False),
            default=DEFAULT_CHUNK_DAYS,
            description=("Days per Insights request. Conversion metrics allow at most 365 days."),
        ),
        th.Property(
            "timezone",
            th.StringType(nullable=True),
            description=("IANA timezone for reporting dates. Defaults to the ad account timezone."),
        ),
        th.Property(
            "attribution_window_days",
            th.IntegerType(nullable=False),
            default=30,
            description="Click attribution window: 7, 14, or 30. Default 30.",
        ),
        th.Property(
            "view_through_attribution_window_days",
            th.IntegerType(nullable=False),
            default=1,
            description="View attribution window: 0 to exclude views, or 1. Default 1.",
        ),
        th.Property(
            "include_zero_impression_items",
            th.BooleanType(nullable=False),
            default=True,
            description="Include ads that had zero impressions in the requested window.",
        ),
        th.Property(
            "user_agent",
            th.StringType(nullable=True),
            description="Optional User-Agent header.",
        ),
        th.Property(
            "api_url",
            th.StringType(nullable=False),
            title="API URL",
            default="https://api.ads.openai.com/v1",
            description="ChatGPT Ads API root.",
        ),
    ).to_dict()

    @override
    def discover_streams(self) -> list[streams.AdPerformanceStream]:
        """Return discovered streams.

        Returns:
            The ad performance stream.
        """
        return [streams.AdPerformanceStream(self)]


if __name__ == "__main__":
    TapChatGPTAds.cli()

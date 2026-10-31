"""Unit tests for ChatGPT Ads reporting helpers."""

from datetime import date

from tap_chatgpt_ads.client import InsightsCursorPaginator
from tap_chatgpt_ads.reporting import (
    ConversionEventsQuery,
    InsightsQuery,
    conversion_event_selection,
    conversion_request_body,
    insight_query_params,
    iter_conversion_event_records,
    iter_date_windows,
    normalize_insight_row,
    resolve_sync_start,
    unrecognized_event_names,
)


def test_iter_date_windows_splits_at_chunk_and_caps_at_365() -> None:
    windows = iter_date_windows(date(2026, 1, 1), date(2026, 2, 10), 31)
    assert windows == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 10)),
    ]
    long_windows = iter_date_windows(date(2024, 1, 1), date(2026, 1, 1), 1000)
    assert all((end - start).days + 1 <= 365 for start, end in long_windows)
    assert long_windows[0][0] == date(2024, 1, 1)
    assert long_windows[-1][1] == date(2026, 1, 1)


def test_resolve_sync_start_applies_lookback_without_passing_start_date() -> None:
    start = resolve_sync_start(
        start_date=date(2026, 1, 1),
        bookmark=date(2026, 9, 4),
        lookback_days=7,
        today=date(2026, 9, 5),
    )
    assert start == date(2026, 8, 28)


def test_resolve_sync_start_uses_start_date_on_first_run() -> None:
    start = resolve_sync_start(
        start_date=date(2026, 7, 1),
        bookmark=None,
        lookback_days=7,
        today=date(2026, 9, 5),
    )
    assert start == date(2026, 7, 1)


def test_normalize_insight_row_joins_account_and_ad_group() -> None:
    row = {
        "readable_time": "2026-09-01",
        "campaign_id": "cmpn_101",
        "ad_id": "ad_501",
        "ad_name": "Blue shoes",
        "impressions": 700,
        "clicks": 22,
        "spend": 12.5,
        "conversions": 3,
        "timezone": "America/New_York",
    }
    record = normalize_insight_row(
        row,
        account={
            "id": "adacct_123",
            "account_name": "Acme US campaigns",
            "currency_code": "USD",
            "timezone": "America/New_York",
        },
        ads_by_id={
            "ad_501": {
                "campaign_id": "cmpn_101",
                "campaign_name": "Spring launch",
                "ad_group_id": "adgrp_301",
                "ad_group_name": "US English",
                "ad_name": "Blue shoes",
            }
        },
    )
    assert record == {
        "ad_account_id": "adacct_123",
        "ad_account_name": "Acme US campaigns",
        "campaign_id": "cmpn_101",
        "campaign_name": "Spring launch",
        "ad_group_id": "adgrp_301",
        "ad_group_name": "US English",
        "ad_id": "ad_501",
        "ad_name": "Blue shoes",
        "date": "2026-09-01",
        "impressions": 700,
        "clicks": 22,
        "conversions": 3,
        "spend": 12.5,
        "currency_code": "USD",
        "timezone": "America/New_York",
    }


def test_normalize_insight_row_skips_rows_without_a_key() -> None:
    assert normalize_insight_row({}, account={}, ads_by_id={}) is None


def test_insight_query_params_request_daily_ad_grain() -> None:
    params = insight_query_params(
        InsightsQuery(
            since=date(2026, 9, 1),
            until=date(2026, 9, 7),
            timezone="America/New_York",
            attribution_window_days=30,
            view_through_attribution_window_days=1,
            include_zero_impression_items=True,
            limit=2000,
            after="cursor-1",
        )
    )
    assert params["aggregation_level"] == "ad"
    assert params["time_granularity"] == "daily"
    assert "ad.impressions" in params["fields[]"]
    assert "ad.clicks" in params["fields[]"]
    assert "ad.spend" in params["fields[]"]
    assert "conversions" in params["fields[]"]
    assert params["includes[]"] == "zero_impression_items"
    assert params["after"] == "cursor-1"
    assert '"since":"2026-09-01"' in params["time_ranges[]"]
    assert '"until":"2026-09-07"' in params["time_ranges[]"]


def test_insights_paginator_stops_when_has_more_is_false() -> None:
    class Response:
        def json(self) -> dict[str, object]:
            return {"has_more": False, "last_id": "still-present"}

    paginator = InsightsCursorPaginator()
    assert paginator.get_next(Response()) is None  # type: ignore[arg-type]


def test_insights_paginator_returns_last_id() -> None:
    class Response:
        def json(self) -> dict[str, object]:
            return {"has_more": True, "last_id": "page-2"}

    paginator = InsightsCursorPaginator()
    assert paginator.get_next(Response()) == "page-2"  # type: ignore[arg-type]


def test_conversion_event_selection_uses_api_names_and_labels() -> None:
    names, labels = conversion_event_selection([
        {"name": "VDP Views", "base_event": "contents_viewed"},
        {"name": "Lead Created", "base_event": "lead_created"},
    ])
    assert names == ("contents_viewed", "lead_created")
    assert labels == {
        "contents_viewed": "VDP Views",
        "lead_created": "Lead Created",
    }
    assert conversion_event_selection(None) == (None, {})


def test_unrecognized_event_names_parses_api_error() -> None:
    message = (
        "400: event_names contains events not recognized for this ad account: "
        "VDP Views, Lead Created. Events must be configured"
    )
    assert unrecognized_event_names(message) == ("VDP Views", "Lead Created")
    assert unrecognized_event_names("some other error") == ()


def test_conversion_records_join_on_ad_id_and_date() -> None:
    payload = {
        "data": [
            {
                "entity_id": "ad_1",
                "date": "2026-10-23",
                "attributed_events": [
                    {
                        "event_name": "contents_viewed",
                        "event_kind": "standard",
                        "attributed_event_count": 1,
                        "attributed_event_value_amount": None,
                        "attributed_event_value_count": 0,
                        "attributed_event_value_currency": None,
                        "click_through_conversions": 1,
                        "view_through_conversions": 0,
                    }
                ],
            }
        ]
    }
    records = list(
        iter_conversion_event_records(
            payload,
            account={"id": "acct", "name": "Tera Ford", "currency_code": "USD"},
            ads_by_id={
                "ad_1": {
                    "campaign_id": "cmpn_1",
                    "campaign_name": "Branding",
                    "ad_group_id": "ag_1",
                    "ad_group_name": "Ford Dealer",
                    "ad_name": "Ad 2",
                }
            },
            labels={"contents_viewed": "VDP Views"},
        )
    )
    assert len(records) == 1
    assert records[0]["ad_id"] == "ad_1"
    assert records[0]["date"] == "2026-10-23"
    assert records[0]["event_name"] == "contents_viewed"
    assert records[0]["event_label"] == "VDP Views"
    assert records[0]["event_count"] == 1
    assert records[0]["event_value"] is None
    assert records[0]["campaign_id"] == "cmpn_1"
    assert records[0]["ad_group_id"] == "ag_1"


def test_conversion_request_uses_ad_ids_as_entity_ids() -> None:
    body = conversion_request_body(
        ConversionEventsQuery(
            since=date(2026, 10, 1),
            until=date(2026, 10, 7),
            timezone="America/Chicago",
            attribution_window_days=30,
            view_through_attribution_window_days=1,
            entity_ids=("ad_1",),
            event_names=("contents_viewed",),
        )
    )
    assert body["aggregation_level"] == "ad"
    assert body["time_granularity"] == "daily"
    assert body["entity_ids"] == ["ad_1"]
    assert body["event_names"] == ["contents_viewed"]
    assert body["include"] == ["attributed_events"]

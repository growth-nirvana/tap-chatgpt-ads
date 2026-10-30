"""Date windows and row shaping for ChatGPT Ads insights."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

# Conversion metrics must cover full days and at most 365 days per request.
MAX_INSIGHTS_WINDOW_DAYS = 365
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_CHUNK_DAYS = 31

INSIGHT_FIELDS: tuple[str, ...] = (
    "metadata.readable_time",
    "metadata.timezone",
    "campaign.id",
    "ad.id",
    "ad.name",
    "ad.impressions",
    "ad.clicks",
    "ad.spend",
    "conversions",
)


def parse_config_date(value: str | date | datetime | None) -> date | None:
    """Parse a config or bookmark value to a calendar date.

    Args:
        value: A date, datetime, or ISO date/datetime string.

    Returns:
        The calendar date, or None when value is empty.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).date()
    return date.fromisoformat(text[:10])


def resolve_sync_start(
    *,
    start_date: date | None,
    bookmark: date | None,
    lookback_days: int,
    today: date,
) -> date:
    """Choose the first date to request.

    A bookmark is rolled back by ``lookback_days`` so delayed spend and
    attributed conversions can restate. ``start_date`` is a floor.

    Args:
        start_date: Configured historical floor.
        bookmark: Last replicated date, when state exists.
        lookback_days: Days to restate behind the bookmark.
        today: Current date in the account timezone.

    Returns:
        Inclusive start date for this sync.
    """
    lookback = max(lookback_days, 0)
    if bookmark is not None:
        start = bookmark - timedelta(days=lookback)
    elif start_date is not None:
        start = start_date
    else:
        start = today - timedelta(days=lookback or DEFAULT_LOOKBACK_DAYS)
    if start_date is not None:
        start = max(start, start_date)
    return min(start, today)


def iter_date_windows(
    start: date,
    end: date,
    chunk_days: int,
) -> list[tuple[date, date]]:
    """Split an inclusive date range into API-safe windows.

    Args:
        start: First date to include.
        end: Last date to include.
        chunk_days: Maximum days in one Insights request.

    Returns:
        Inclusive ``(since, until)`` windows in chronological order.
    """
    if start > end:
        return []
    size = max(1, min(chunk_days, MAX_INSIGHTS_WINDOW_DAYS))
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=size - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def date_range_param(since: date, until: date, timezone: str | None) -> str:
    """Build one Insights ``time_ranges[]`` value.

    Args:
        since: Inclusive start date.
        until: Inclusive end date.
        timezone: IANA timezone. Omit to use the ad account timezone.

    Returns:
        A JSON object encoded as a string, as required by the API.
    """
    payload: dict[str, str] = {
        "type": "date_range",
        "since": since.isoformat(),
        "until": until.isoformat(),
    }
    if timezone:
        payload["timezone"] = timezone
    return json.dumps(payload, separators=(",", ":"))


@dataclass(frozen=True)
class InsightsQuery:
    """Parameters for one daily ad Insights request."""

    since: date
    until: date
    timezone: str | None
    attribution_window_days: int
    view_through_attribution_window_days: int
    include_zero_impression_items: bool
    limit: int
    after: str | None = None


def insight_query_params(query: InsightsQuery) -> dict[str, Any]:
    """Build query parameters for daily ad-level insights.

    Args:
        query: Window, attribution, pagination, and field options.

    Returns:
        Parameters for ``GET /ad_account/insights``.
    """
    params: dict[str, Any] = {
        "aggregation_level": "ad",
        "time_granularity": "daily",
        "attribution_time_basis": "ad_event_time",
        "attribution_window_days": query.attribution_window_days,
        "view_through_attribution_window_days": query.view_through_attribution_window_days,
        "limit": query.limit,
        "fields[]": list(INSIGHT_FIELDS),
        "time_ranges[]": date_range_param(query.since, query.until, query.timezone),
    }
    if query.include_zero_impression_items:
        params["includes[]"] = "zero_impression_items"
    if query.after:
        params["after"] = query.after
    return params


def normalize_insight_row(
    row: dict[str, Any],
    *,
    account: dict[str, Any],
    ads_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Shape one Insights row into the ad/date grain.

    The Insights example for ``aggregation_level=ad`` returns campaign and ad
    identifiers. Ad group and account are filled from the account endpoint and
    the campaign/ad group/ad listing when the insight row omits them.

    Args:
        row: One object from the Insights ``data`` array.
        account: Payload from ``GET /ad_account``.
        ads_by_id: Ad id to parent campaign and ad group attributes.

    Returns:
        A record, or None when the row has no ad id or date.
    """
    ad_id = row.get("ad_id")
    raw_date = row.get("readable_time") or row.get("date")
    if not ad_id or not raw_date:
        return None
    report_date = str(raw_date)[:10]
    parent = ads_by_id.get(str(ad_id), {})
    return {
        "ad_account_id": row.get("ad_account_id") or account.get("id"),
        "ad_account_name": (
            row.get("ad_account_name") or account.get("account_name") or account.get("name")
        ),
        "campaign_id": row.get("campaign_id") or parent.get("campaign_id"),
        "campaign_name": row.get("campaign_name") or parent.get("campaign_name"),
        "ad_group_id": row.get("ad_group_id") or parent.get("ad_group_id"),
        "ad_group_name": row.get("ad_group_name") or parent.get("ad_group_name"),
        "ad_id": str(ad_id),
        "ad_name": row.get("ad_name") or parent.get("ad_name"),
        "date": report_date,
        "impressions": row.get("impressions"),
        "clicks": row.get("clicks"),
        "conversions": row.get("conversions"),
        "spend": row.get("spend"),
        "currency_code": account.get("currency_code"),
        "timezone": row.get("timezone") or account.get("timezone"),
    }

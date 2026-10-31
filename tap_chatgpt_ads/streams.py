"""Stream type classes for tap-chatgpt-ads."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from singer_sdk import typing as th

from tap_chatgpt_ads.client import ChatGPTAdsStream
from tap_chatgpt_ads.reporting import (
    CONVERSION_ENTITY_BATCH,
    DEFAULT_CHUNK_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    ConversionEventsQuery,
    InsightsQuery,
    conversion_event_selection,
    conversion_request_body,
    insight_query_params,
    iter_conversion_event_records,
    iter_date_windows,
    iter_entity_batches,
    normalize_insight_row,
    parse_config_date,
    resolve_sync_start,
    unrecognized_event_names,
)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterable

    from singer_sdk.helpers.types import Context
    from singer_sdk.streams.rest import HTTPRequest, PageContext

INSIGHTS_PAGE_SIZE = 2000


class AdPerformanceStream(ChatGPTAdsStream):
    """Daily performance at account, campaign, ad group, ad, and date."""

    name = "ad_performance"
    path = "/ad_account/insights"
    primary_keys = ("ad_id", "date")
    replication_key = "date"
    page_size = INSIGHTS_PAGE_SIZE

    schema = th.PropertiesList(
        th.Property("ad_account_id", th.StringType, description="Ad account ID."),
        th.Property(
            "ad_account_name",
            th.StringType,
            description="Internal ad account name from GET /ad_account.",
        ),
        th.Property("campaign_id", th.StringType),
        th.Property("campaign_name", th.StringType),
        th.Property(
            "ad_group_id",
            th.StringType,
            description=(
                "Joined from the ad group listing. Ad-level Insights rows "
                "do not document this field."
            ),
        ),
        th.Property("ad_group_name", th.StringType),
        th.Property("ad_id", th.StringType),
        th.Property("ad_name", th.StringType),
        th.Property("date", th.DateType, description="Account-local reporting date."),
        th.Property("impressions", th.IntegerType),
        th.Property("clicks", th.IntegerType),
        th.Property(
            "conversions",
            th.IntegerType,
            description=(
                "Goal conversions from clicks plus views. Null means unavailable, not zero."
            ),
        ),
        th.Property(
            "spend",
            th.NumberType,
            description="Spend in major units of the ad account currency.",
        ),
        th.Property("currency_code", th.StringType),
        th.Property("timezone", th.StringType),
    ).to_dict()

    @override
    def get_records(self, context: Context | None) -> Iterable[dict[str, Any]]:
        """Extract one date window at a time.

        Args:
            context: Stream partition context.

        Yields:
            Ad/date performance records.
        """
        account = self._request_json("ad_account")
        ads_by_id = self.load_ads_by_id()
        self._account = account
        self._ads_by_id = ads_by_id
        timezone_name = str(self.config.get("timezone") or account.get("timezone") or "UTC")
        self._timezone_name = timezone_name
        today = datetime.now(ZoneInfo(timezone_name)).date()
        start = resolve_sync_start(
            start_date=parse_config_date(self.config.get("start_date")),
            bookmark=parse_config_date(self.get_starting_replication_key_value(context)),
            lookback_days=int(self.config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)),
            today=today,
        )
        chunk_days = int(self.config.get("chunk_days", DEFAULT_CHUNK_DAYS))
        for since, until in iter_date_windows(start, today, chunk_days):
            self._since = since
            self._until = until
            self.logger.info("Requesting ad insights from %s through %s", since, until)
            yield from super().get_records(context)

    @override
    def get_http_request(self, *, page: PageContext[Any]) -> HTTPRequest:
        """Request daily ad insights for the current date window.

        Args:
            page: Partition context and the next page token.

        Returns:
            The Insights GET request.
        """
        request = super().get_http_request(page=page)
        request.params = insight_query_params(
            InsightsQuery(
                since=self._since,
                until=self._until,
                timezone=self._timezone_name,
                attribution_window_days=int(self.config.get("attribution_window_days", 30)),
                view_through_attribution_window_days=int(
                    self.config.get("view_through_attribution_window_days", 1)
                ),
                include_zero_impression_items=bool(
                    self.config.get("include_zero_impression_items", True)
                ),
                limit=self.page_size,
                after=str(page.next_page_token) if page.next_page_token else None,
            )
        )
        return request

    @override
    def post_process(
        self,
        row: dict[str, Any],
        context: Context | None = None,
    ) -> dict[str, Any] | None:
        """Attach account and ad group attributes to an insight row.

        Args:
            row: Raw Insights record.
            context: Unused stream context.

        Returns:
            The denormalized record, or None when it cannot be keyed.
        """
        return normalize_insight_row(
            row,
            account=self._account,
            ads_by_id=self._ads_by_id,
        )


class AdConversionEventsStream(ChatGPTAdsStream):
    """Daily conversion events at ad grain, one row per event.

    Join to ``ad_performance`` on ``ad_id`` and ``date``. ``event_name`` is the
    API event, the same role as a Google Ads conversion action name.
    """

    name = "ad_conversion_events"
    path = "/conversions/insights"
    primary_keys = ("ad_id", "date", "event_name")
    replication_key = "date"

    schema = th.PropertiesList(
        th.Property("ad_account_id", th.StringType, description="Ad account ID."),
        th.Property("ad_account_name", th.StringType),
        th.Property("campaign_id", th.StringType),
        th.Property("campaign_name", th.StringType),
        th.Property("ad_group_id", th.StringType),
        th.Property("ad_group_name", th.StringType),
        th.Property(
            "ad_id",
            th.StringType,
            description="Join key to ad_performance.ad_id.",
        ),
        th.Property("ad_name", th.StringType),
        th.Property(
            "date",
            th.DateType,
            description="Account-local reporting date. Join key to ad_performance.date.",
        ),
        th.Property(
            "event_name",
            th.StringType,
            description="API event name, such as contents_viewed or lead_created.",
        ),
        th.Property(
            "event_label",
            th.StringType,
            description="Configured report label. Equals event_name when no label is set.",
        ),
        th.Property(
            "event_kind",
            th.StringType,
            description="standard or custom.",
        ),
        th.Property(
            "event_count",
            th.IntegerType,
            description="Attributed event count, including events that are not campaign goals.",
        ),
        th.Property(
            "event_value",
            th.NumberType,
            description="Attributed event value. Null means the API did not return an amount.",
        ),
        th.Property("event_value_count", th.IntegerType),
        th.Property("currency_code", th.StringType),
        th.Property("click_through_conversions", th.IntegerType),
        th.Property("view_through_conversions", th.IntegerType),
    ).to_dict()

    @override
    def get_records(self, context: Context | None) -> Iterable[dict[str, Any]]:
        """Extract conversion events for each date window and ad batch.

        Args:
            context: Stream partition context.

        Yields:
            One record per ad, date, and event.
        """
        account = self._request_json("ad_account")
        ads_by_id = self.load_ads_by_id()
        if not ads_by_id:
            return
        timezone_name = str(self.config.get("timezone") or account.get("timezone") or "UTC")
        today = datetime.now(ZoneInfo(timezone_name)).date()
        start = resolve_sync_start(
            start_date=parse_config_date(self.config.get("start_date")),
            bookmark=parse_config_date(self.get_starting_replication_key_value(context)),
            lookback_days=int(self.config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)),
            today=today,
        )
        event_names, labels = conversion_event_selection(self.config.get("conversion_events"))
        seen: set[str] = set()
        chunk_days = int(self.config.get("chunk_days", DEFAULT_CHUNK_DAYS))
        ad_ids = list(ads_by_id)
        for since, until in iter_date_windows(start, today, chunk_days):
            self.logger.info("Requesting ad conversion events from %s through %s", since, until)
            for batch in iter_entity_batches(ad_ids, CONVERSION_ENTITY_BATCH):
                payload = self._fetch_conversion_insights(
                    ConversionEventsQuery(
                        since=since,
                        until=until,
                        timezone=timezone_name,
                        attribution_window_days=int(self.config.get("attribution_window_days", 30)),
                        view_through_attribution_window_days=int(
                            self.config.get("view_through_attribution_window_days", 1)
                        ),
                        entity_ids=batch,
                        event_names=event_names,
                    )
                )
                for record in iter_conversion_event_records(
                    payload,
                    account=account,
                    ads_by_id=ads_by_id,
                    labels=labels,
                ):
                    seen.add(str(record["event_name"]))
                    yield record
        if event_names:
            missing = [name for name in event_names if name not in seen]
            if missing:
                self.logger.warning(
                    "Configured conversion events were not returned: %s",
                    ", ".join(missing),
                )

    def _fetch_conversion_insights(self, query: ConversionEventsQuery) -> dict[str, Any]:
        """POST one conversion insights request, splitting when the API requires it.

        Args:
            query: Ads and date window to request.

        Returns:
            A JSON object with a ``data`` array. Empty when every requested
            event name is unrecognized.

        Raises:
            TypeError: If the response body is not a JSON object.
        """
        if not query.entity_ids:
            return {"data": []}
        response = self.post_response("conversions/insights", conversion_request_body(query))
        too_large = response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        if too_large and len(query.entity_ids) > 1:
            midpoint = len(query.entity_ids) // 2
            left = self._fetch_conversion_insights(
                replace(query, entity_ids=query.entity_ids[:midpoint])
            )
            right = self._fetch_conversion_insights(
                replace(query, entity_ids=query.entity_ids[midpoint:])
            )
            return {"data": [*(left.get("data") or []), *(right.get("data") or [])]}
        if response.status_code == HTTPStatus.BAD_REQUEST and query.event_names:
            message = ""
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or "")
            unknown = unrecognized_event_names(message)
            if unknown:
                remaining = tuple(name for name in query.event_names if name not in set(unknown))
                self.logger.warning(
                    "Ignoring conversion events the account does not recognize: %s",
                    ", ".join(unknown),
                )
                if not remaining:
                    return {"data": []}
                return self._fetch_conversion_insights(replace(query, event_names=remaining))
        self.validate_response(response)
        payload = response.json()
        if not isinstance(payload, dict):
            message = "Expected a JSON object from conversions/insights"
            raise TypeError(message)
        return payload

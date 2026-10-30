"""Stream type classes for tap-chatgpt-ads."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from singer_sdk import typing as th

from tap_chatgpt_ads.client import ChatGPTAdsStream
from tap_chatgpt_ads.reporting import (
    DEFAULT_CHUNK_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    InsightsQuery,
    insight_query_params,
    iter_date_windows,
    normalize_insight_row,
    parse_config_date,
    resolve_sync_start,
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
        ads_by_id = self._load_ads_by_id()
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

    def _load_ads_by_id(self) -> dict[str, dict[str, Any]]:
        """List campaigns, ad groups, and ads for parent attributes.

        Returns:
            Mapping of ad id to campaign and ad group names and ids.
        """
        ads_by_id: dict[str, dict[str, Any]] = {}
        for campaign in self.paginate_list("campaigns"):
            campaign_id = campaign.get("id")
            if not campaign_id:
                continue
            for ad_group in self.paginate_list("ad_groups", {"campaign_id": campaign_id}):
                ad_group_id = ad_group.get("id")
                if not ad_group_id:
                    continue
                for ad in self.paginate_list("ads", {"ad_group_id": ad_group_id}):
                    ad_id = ad.get("id")
                    if not ad_id:
                        continue
                    ads_by_id[str(ad_id)] = {
                        "campaign_id": str(campaign_id),
                        "campaign_name": campaign.get("name"),
                        "ad_group_id": str(ad_group_id),
                        "ad_group_name": ad_group.get("name"),
                        "ad_name": ad.get("name"),
                    }
        self.logger.info("Loaded %s ads for hierarchy enrichment", len(ads_by_id))
        return ads_by_id

"""REST client for the ChatGPT Ads API."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from singer_sdk.authenticators import BearerTokenAuthenticator
from singer_sdk.pagination import BaseAPIPaginator
from singer_sdk.streams import RESTStream

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterator

    import requests
    from singer_sdk.streams.rest import HTTPRequest, PageContext


class InsightsCursorPaginator(BaseAPIPaginator[str | None]):
    """Page Insights and list endpoints with ``after`` / ``last_id``."""

    def __init__(self) -> None:
        """Start at the first page."""
        super().__init__(start_value=None)

    @override
    def get_next(self, response: requests.Response) -> str | None:
        """Return the next cursor when another page exists.

        Args:
            response: The latest API response.

        Returns:
            ``last_id`` when ``has_more`` is true, otherwise None.
        """
        payload = response.json()
        if not payload.get("has_more"):
            return None
        last_id = payload.get("last_id")
        if not last_id:
            return None
        return str(last_id)


class ChatGPTAdsStream(RESTStream[str | None]):
    """Base stream for https://api.ads.openai.com."""

    records_jsonpath = "$.data[*]"
    page_size = 500
    # Campaign, ad group, and ad list endpoints reject limits above 500.
    list_page_size = 500

    @override
    @property
    def url_base(self) -> str:
        """API root, without a trailing slash."""
        configured = self.config.get("api_url") or "https://api.ads.openai.com/v1"
        return str(configured).rstrip("/")

    @override
    @property
    def authenticator(self) -> BearerTokenAuthenticator:
        """Bearer token from the ad-account API key."""
        return BearerTokenAuthenticator(token=self.config["api_key"])

    @override
    @property
    def http_headers(self) -> dict[str, str]:
        """Optional User-Agent override."""
        user_agent = self.config.get("user_agent")
        if user_agent:
            return {"User-Agent": str(user_agent)}
        return {}

    @override
    def get_new_paginator(self) -> InsightsCursorPaginator:
        """Create a cursor paginator for this request.

        Returns:
            A paginator that follows ``has_more`` and ``last_id``.
        """
        return InsightsCursorPaginator()

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET one JSON document.

        Args:
            path: Path under the API root, without a leading slash.
            params: Query parameters.

        Returns:
            The parsed JSON object.

        Raises:
            TypeError: If the response body is not a JSON object.
        """
        url = urljoin(f"{self.url_base}/", path)
        headers = dict(self.http_headers)
        authenticator = self.authenticator
        if authenticator is not None:
            headers.update(authenticator.auth_headers or {})
        response = self.requests_session.get(
            url,
            headers=headers,
            params=params,
            timeout=self.timeout,
        )
        self.validate_response(response)
        payload = response.json()
        if not isinstance(payload, dict):
            message = f"Expected a JSON object from {path}"
            raise TypeError(message)
        return payload

    def paginate_list(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every object from a cursor-paginated list endpoint.

        Args:
            path: Path under the API root.
            params: Extra query parameters.

        Yields:
            Objects from each page's ``data`` array.
        """
        after: str | None = None
        while True:
            query = {"limit": self.list_page_size, **(params or {})}
            if after:
                query["after"] = after
            payload = self._request_json(path, query)
            data = payload.get("data") or []
            if isinstance(data, list):
                yield from data
            if not payload.get("has_more"):
                return
            last_id = payload.get("last_id")
            if not last_id:
                return
            after = str(last_id)

    @override
    def get_http_request(self, *, page: PageContext[Any]) -> HTTPRequest:
        """Build the HTTP request for one page.

        Args:
            page: Partition context and the next page token.

        Returns:
            The prepared request.
        """
        request = super().get_http_request(page=page)
        if page.next_page_token:
            request.params["after"] = page.next_page_token
        return request

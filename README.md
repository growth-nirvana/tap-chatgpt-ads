# tap-chatgpt-ads

Singer tap for the [ChatGPT Ads API](https://developers.openai.com/ads), built with the [Meltano Singer SDK](https://sdk.meltano.com).

The tap extracts two streams:

- `ad_performance`: one row per ad per day.
- `ad_conversion_events`: one row per ad, date, and conversion event. Join it to `ad_performance` on `ad_id` and `date`. `event_name` is the API event, in the same role as a Google Ads conversion action name.

## Grain and metrics

| Requested | Available | How it is produced |
| --- | --- | --- |
| Account | Yes | `GET /v1/ad_account`. An API key is scoped to one ad account. |
| Campaign | Yes | Insights returns `campaign_id` when `aggregation_level=ad`. Campaign name comes from `GET /campaigns`. |
| Ad group | Yes, joined | The documented ad-level Insights row includes campaign and ad, not ad group. The tap lists campaigns, ad groups, and ads and joins `ad_group_id` / `ad_group_name` on `ad_id`. |
| Ad | Yes | `aggregation_level=ad` on `GET /v1/ad_account/insights`. |
| Date | Yes | `time_granularity=daily`. Dates are account-local. |
| Impressions | Yes | `ad.impressions` |
| Clicks | Yes | `ad.clicks` |
| Spend | Yes | `ad.spend`, in major currency units (for example `12.50`), not micros. Spend can lag impressions and clicks by several hours. |
| Conversions | Yes, with limits | Goal conversions (click-through plus view-through) from the same Insights request. `null` means unavailable, not zero. Default windows are 30-day click and 1-day view, grouped by ad event time. A request that includes conversions must use full days and at most 365 days, so the tap chunks the range. |

There is no single Insights field that returns account, campaign, ad group, and ad together. Ad-level insights are the finest delivery grain, and the entity listing supplies the missing ad group.

## Installation

```bash
uv sync
```

## Configuration

| Setting | Required | Default | Purpose |
| --- | --- | --- | --- |
| `api_key` | Yes | | Ad account-scoped Advertiser API key. Sent as `Authorization: Bearer`. |
| `start_date` | No | lookback window | Earliest date to extract on the first run. |
| `lookback_days` | No | `7` | Days before the bookmark to request again. |
| `chunk_days` | No | `31` | Days per Insights request. Capped at 365. |
| `timezone` | No | account timezone | IANA timezone for the reporting window. |
| `attribution_window_days` | No | `30` | Click window: `7`, `14`, or `30`. |
| `view_through_attribution_window_days` | No | `1` | View window: `0` or `1`. |
| `include_zero_impression_items` | No | `true` | Include ads with no impressions. |
| `conversion_events` | No | all events | Optional list of `{"name", "base_event"}` objects. `base_event` is the API name (`contents_viewed`). `name` is the report label (`VDP Views`). Omit to extract every event the account returns. |
| `user_agent` | No | SDK default | Optional User-Agent header. |

Copy `.env.example` to `.env` or pass a config file:

```bash
uv run tap-chatgpt-ads --config config.json --discover > catalog.json
```

## Development

```bash
uv sync
uv run pytest
uv run tap-chatgpt-ads --help
```

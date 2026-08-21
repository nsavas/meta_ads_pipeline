"""Generic caller for Meta's Ads Insights API.

Deliberately simpler than the Pinterest pipeline's analytics caller: Meta's
/{ad_account_id}/insights edge accepts a `level` parameter (ad / adset /
campaign) and returns insights for *every* entity at that level under the
whole account in one paginated call -- confirmed against Meta's Marketing
API docs on 2026-08-19. There's no Pinterest-style "list every entity ID
first, then batch analytics calls in groups of N" step needed here: one
call per account per level covers everything.

Response rows are flat JSON objects -- {"ad_id": ..., "date_start": ...,
"spend": ..., "actions": [...], ...} -- not nested under a "metrics" key the
way Pinterest's targeting_analytics rows are.
"""

import json

from meta_config import GRAPH_API_BASE
from meta_http import get_all_pages


def fetch_insights(ad_account_id: str, level: str, start_date: str, end_date: str,
                    access_token: str, fields: list, breakdowns: list = None) -> list:
    """Fetch daily insights rows for every entity at `level` under
    `ad_account_id`, across [start_date, end_date] inclusive.

    ad_account_id: Meta's "act_123456789" form.
    level: "ad", "adset", or "campaign".
    fields: metric/identifier field names, e.g. ["ad_id", "spend", "actions"].
    breakdowns: optional list of breakdown dimensions, e.g. ["age", "gender"]
      or ["comscore_market"]. Each combination requested becomes part of the
      grain of the returned rows (one row per entity, per date, per
      breakdown-value combination) -- see the DMA/demographics jobs for how
      that grain gets reflected in their table schemas.
    """
    params = {
        "level": level,
        "fields": ",".join(fields),
        "time_range": json.dumps({"since": start_date, "until": end_date}),
        "time_increment": 1,  # daily granularity, not a single aggregated total
    }
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)

    return get_all_pages(
        f"{GRAPH_API_BASE}/{ad_account_id}/insights",
        params,
        access_token,
    )

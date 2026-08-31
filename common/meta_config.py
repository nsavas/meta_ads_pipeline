"""Shared constants for the Meta Marketing API (Graph API) clients."""

# Pin the API version explicitly rather than using the unversioned endpoint --
# Meta retires old versions on a schedule, and an unversioned call silently
# rides whatever the current default is. Bump this deliberately, not by
# accident. Verified against Meta's live docs as the current version on
# 2026-08-19; confirm you're not about to hit a deprecation window before
# deploying (https://developers.facebook.com/docs/graph-api/changelog).
GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Page size for ID-only / narrow-field paginated calls (account discovery,
# common/meta_accounts.py's list_entity_ids(), and every insights call).
DEFAULT_PAGE_SIZE = 100

# Page size for *full-object* listings -- meta_dimensions_to_iceberg_glue_job.py's
# three list_entities() calls, which request every field on the Campaign
# (39 fields), AdSet (64), and Ad (39) objects, several of which are
# non-trivial nested objects (promoted_object, issues_info, source_campaign,
# targeting, creative, ...). Confirmed in production (2026-08-20) that
# requesting DEFAULT_PAGE_SIZE (100) full objects per page, across every
# page of a 100+ campaign account with no pacing between requests, triggers
# Meta's Marketing API cost-based throttle: "Please reduce the amount of
# data you're asking for, then retry your request" -- returned as an HTTP
# 500, not a 429, and NOT resolved by simply retrying the same request (the
# retry logic in meta_http.py backs off and retries, but Meta is asking for
# a smaller request, not just a later one). A single request for this
# account succeeded once, then failed identically on an immediate retry --
# confirming this is a request-cost throttle, not a data/permissions issue
# with a specific campaign. Keep this well below DEFAULT_PAGE_SIZE.
DETAIL_PAGE_SIZE = 25

# Pause between successive pages during pagination (get_all_pages() in
# meta_http.py), so consecutive full-object requests don't stack up and
# accumulate query cost as fast as they would back-to-back. Applied to every
# multi-page pull, not just the dimensions job's -- harmless extra latency
# for the cheap ID-only/insights pulls, meaningful headroom for the
# expensive ones.
PAGE_PACING_SECONDS = 1

# Default width of the rolling incremental pull when a job isn't given
# explicit START_DATE/END_DATE. See meta_dates.py for why 14 days.
DEFAULT_LOOKBACK_DAYS = 14

# HTTP retry/backoff defaults for meta_http.py's request_with_backoff().
# Meta also exposes proactive rate-limit signals (X-Business-Use-Case-Usage /
# X-Ad-Account-Usage response headers) that a high-volume production job
# should read and throttle against pre-emptively; this reactive retry-on-429
# baseline mirrors the Pinterest pipeline's approach and is not a substitute
# for that if you're running at scale.
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2

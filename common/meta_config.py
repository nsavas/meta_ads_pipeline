"""Shared constants for the Meta Marketing API (Graph API) clients."""

# Pin the API version explicitly rather than using the unversioned endpoint --
# Meta retires old versions on a schedule, and an unversioned call silently
# rides whatever the current default is. Bump this deliberately, not by
# accident. Verified against Meta's live docs as the current version on
# 2026-08-19; confirm you're not about to hit a deprecation window before
# deploying (https://developers.facebook.com/docs/graph-api/changelog).
GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Page size used for every paginated list/insights call.
DEFAULT_PAGE_SIZE = 100

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

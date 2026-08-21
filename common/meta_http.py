"""HTTP retry/backoff wrapper shared by every Meta Graph API call.

Same retry contract as the Pinterest pipeline's http helper (429 honoring
Retry-After, 5xx backoff) for consistency across both projects. Meta's Graph
API returns errors in a JSON body ({"error": {"message", "code", ...}}) with
a 4xx/5xx status in the common cases this handles, so raise_for_status()
still does the right thing; a caller that needs the structured error message
should catch requests.HTTPError and inspect resp.json()["error"].
"""

import logging
import time

import requests

from meta_config import INITIAL_BACKOFF_SECONDS, MAX_RETRIES

logger = logging.getLogger(__name__)


def request_with_backoff(method: str, url: str, params: dict = None,
                          max_retries: int = MAX_RETRIES,
                          initial_backoff: int = INITIAL_BACKOFF_SECONDS,
                          **kwargs) -> requests.Response:
    """requests.request() with retry on 429 (honoring Retry-After) and 5xx.

    Raises via resp.raise_for_status() for any other error status, and after
    exhausting max_retries.
    """
    backoff = initial_backoff
    resp = None
    for attempt in range(1, max_retries + 1):
        resp = requests.request(method, url, params=params, timeout=60, **kwargs)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", backoff))
            logger.warning("Rate limited by Meta Graph API, sleeping %ss (attempt %s/%s)",
                            retry_after, attempt, max_retries)
            time.sleep(retry_after)
            backoff *= 2
            continue
        if resp.status_code >= 500:
            logger.warning("Meta Graph API %s error, retrying in %ss (attempt %s/%s)",
                            resp.status_code, backoff, attempt, max_retries)
            time.sleep(backoff)
            backoff *= 2
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()  # last attempt's error, if we fell through
    return resp


def get_all_pages(url: str, params: dict, access_token: str) -> list:
    """Follow Graph API cursor pagination (paging.next) and return every
    item in "data" across all pages.

    Meta's paging model: each response has {"data": [...], "paging": {
    "cursors": {"after": ...}, "next": "<full url for the next page>"}}.
    Absence of "next" (not absence of "cursors") is what signals the last
    page -- a short final page can still carry a cursors object.
    """
    items = []
    headers = {"Authorization": f"Bearer {access_token}"}
    next_url = url
    next_params = dict(params) if params else {}

    while next_url:
        resp = request_with_backoff("GET", next_url, params=next_params, headers=headers)
        body = resp.json()
        items.extend(body.get("data", []))

        next_url = body.get("paging", {}).get("next")
        next_params = None  # "next" is a complete URL; don't re-append params

    return items

# Meta Ads → Iceberg (AWS Glue)

Six Glue jobs that pull data from Meta's Marketing API (Graph API) and write
it into Iceberg tables in S3. Sibling project to `pinterest_ads_pipeline`,
same overall shape, but several things are genuinely different -- see
"Differences from the Pinterest pipeline" below before assuming anything
carries over unchanged.

- **Three performance jobs** at the ad, ad set, and campaign level. ("Ad
  set" is Meta's name for what Pinterest calls an "ad group.")
- **One geographic breakdown job**, at the ad level only, giving ad-level
  performance broken down by market (see "DMA is retired -- read this before
  deploying" below; this is the single most important caveat in this whole
  project).
- **One demographic breakdown job**, at the ad level only, giving ad-level
  performance broken down by age x gender as a combined cross-tab in one
  table (see "Age/gender is one combined table" below).
- **One dimensions job** that pulls the full Campaign/Ad Set/Ad metadata
  objects (name, status, budget, targeting, creative -- every field, no
  metrics) into three tables in a single run.

All six share one `common/` library for everything that isn't job-specific:
access-token handling, ad-account/entity discovery, HTTP retry/backoff +
cursor pagination, incremental date-range resolution, the Iceberg write
helpers, and the schema-building helper described below.

## Layout

```
meta_ads_pipeline/
├── common/                        # shared modules, zipped flat for --extra-py-files (see "Deploying")
│   ├── meta_config.py              constants (Graph API version/base URL, page size, retry/backoff, lookback default)
│   ├── meta_auth.py                Secrets Manager access-token read (no refresh flow -- see "Auth" below)
│   ├── meta_http.py                retry/backoff wrapper + cursor-pagination follower (get_all_pages)
│   ├── meta_accounts.py            ad account discovery (/me -> assigned_ad_accounts) + generic entity pager
│   ├── meta_analytics.py           generic caller for the /{ad_account_id}/insights edge
│   ├── meta_schema.py              build_table(): derives Spark SCHEMA + Iceberg DDL + row-builder from one field-spec list
│   ├── meta_dates.py               rolling-window date-range resolution + chunking
│   └── meta_glue_args.py           getResolvedOptions wrapper that supports optional args
├── jobs/
│   ├── meta_ads_to_iceberg_glue_job.py
│   ├── meta_campaigns_to_iceberg_glue_job.py
│   ├── meta_ad_sets_to_iceberg_glue_job.py
│   ├── meta_ads_dma_to_iceberg_glue_job.py             ad-level performance broken down by geographic market
│   ├── meta_ads_demographics_to_iceberg_glue_job.py    ad-level performance broken down by age x gender
│   └── meta_dimensions_to_iceberg_glue_job.py          campaign/ad set/ad metadata (no metrics)
├── build_deps.ps1 / build_deps.sh   zip common/'s contents (flat) for --extra-py-files
├── requirements.txt
└── README.md
```

Each file in `jobs/` only declares what's specific to it: which fields to
request, the breakdown (if any), and the merge key. Everything else is
imported from the `meta_*` modules in `common/`.

**Same flat-module structure as the Pinterest project, for the same reason.**
`common/` is zipped with the `.py` files directly at the root -- no wrapping
`common` folder, no `__init__.py`. That's not a stylistic choice; it's a
requirement discovered the hard way in the sibling project: the more
"obvious" `common` package structure (which AWS's own docs describe as
correct) hit `ModuleNotFoundError: No module named 'common'` on a real Glue
job run, matching a
[known unresolved AWS Glue issue](https://github.com/awslabs/aws-glue-libs/issues/173)
with zipimport + `--extra-py-files`. This project starts from the working
structure rather than repeating that discovery.

## Deploying

```bash
./build_deps.sh          # or build_deps.ps1 on Windows
aws s3 cp meta_common.zip s3://<your-bucket>/meta_common.zip
```

For **each** of the six Glue jobs, upload the corresponding script from
`jobs/` as the job's script, and set these job parameters:

```
--datalake-formats iceberg
--additional-python-modules requests>=2.31.0
--extra-py-files s3://<your-bucket>/meta_common.zip
```

Then the job-specific arguments (see the docstring at the top of each script
in `jobs/` for the full list):

| Parameter | Required | Notes |
|---|---|---|
| `--SECRET_NAME` | yes | Secrets Manager secret: `{"access_token": "..."}` (a Meta System User token -- see "Auth" below) |
| `--AWS_REGION` | yes | e.g. `us-east-1` |
| `--ICEBERG_CATALOG` | yes | Glue Data Catalog name registered as an Iceberg catalog |
| `--ICEBERG_DATABASE` | yes | target database |
| `--ICEBERG_TABLE` | yes\*\* | target table (different per job -- see below) |
| `--ICEBERG_WAREHOUSE_PATH` | yes | `s3://bucket/prefix` |
| `--AD_ACCOUNT_IDS` | no* | comma-separated allowlist (with or without "act_" prefix); omit to auto-discover every account the token can see |
| `--START_DATE` / `--END_DATE` | no* | explicit backfill range; omit for the rolling incremental window |
| `--LOOKBACK_DAYS` | no* | default 14; width of the rolling window when dates are omitted |

\* The five performance/breakdown jobs take all three optional args.
`meta_dimensions_to_iceberg_glue_job.py` takes **none** of them -- it's not
time-series data, so it only needs the required arguments.

\*\* `meta_dimensions_to_iceberg_glue_job.py` writes three tables in one
run, so instead of a single `--ICEBERG_TABLE` it takes three:
`--ICEBERG_TABLE_CAMPAIGNS`, `--ICEBERG_TABLE_AD_SETS`, `--ICEBERG_TABLE_ADS`.

Suggested table names, one per job:

| Job | Table(s) |
|---|---|
| `meta_ads_to_iceberg_glue_job.py` | `meta_ad_performance` |
| `meta_campaigns_to_iceberg_glue_job.py` | `meta_campaign_performance` |
| `meta_ad_sets_to_iceberg_glue_job.py` | `meta_ad_set_performance` |
| `meta_ads_dma_to_iceberg_glue_job.py` | `meta_ad_market_performance` |
| `meta_ads_demographics_to_iceberg_glue_job.py` | `meta_ad_demographics_performance` |
| `meta_dimensions_to_iceberg_glue_job.py` | `meta_campaign_dim`, `meta_ad_set_dim`, `meta_ad_dim` |

Whenever `common/` changes, re-run `build_deps.sh`/`.ps1` and re-upload the
zip -- Glue doesn't pick up changes to an S3 object automatically on its
own, you're re-deploying the same object key.

## Auth

Built against a Meta **System User access token** (generated once in
Business Manager), not a standard OAuth User/Page token. That choice
matters structurally: System User tokens don't expire, so `meta_auth.py` is
just "read a static token from Secrets Manager" -- there's no refresh flow
the way `pinterest_auth.py` has for Pinterest's OAuth token. If you end up
using a standard expiring token instead, `meta_auth.py` is the one place
that needs to grow a refresh step; see `pinterest_auth.py` for the shape
that takes.

Account discovery follows from the same choice: `GET /me` identifies the
System User itself (its `id` *is* the System User's ID for this token
type), then `GET /{system_user_id}/assigned_ad_accounts` lists every ad
account it's been assigned. No `AD_ACCOUNT_IDS`-equivalent required
parameter, same auto-discovery-by-default pattern as the Pinterest project.

**The token is sent as an `access_token` query parameter, not an
`Authorization: Bearer` header.** An earlier version of `meta_http.py` used
the header, which produced HTTP 400 errors on every call. Every example in
Meta's own docs (the general Graph API guide, the Insights guide, and the
breakdowns reference, all checked on 2026-08-20) uses the query-parameter
form exclusively -- none show a Bearer header. Meta's Graph API also
surfaces access-token problems as HTTP 400 (`OAuthException`), not 401,
which is why a bad-auth failure here looks like a malformed request rather
than an auth error. If you're debugging a 400 on any job, this is the first
thing to check -- confirm `access_token` actually appears in the outgoing
query string (`meta_http.get_all_pages()` and `meta_accounts.get_self_id()`
are the only two places that attach it).

## No OpenAPI spec for Meta

Pinterest publishes a real OpenAPI spec on GitHub
(https://github.com/pinterest/api-description) that every field/column name
in the sibling project was mechanically verified against. **Meta publishes
no equivalent.** Every field name, type, and endpoint behavior in this
project was instead verified by fetching Meta's live HTML reference docs
(`developers.facebook.com/docs/marketing-api/reference/...`) on 2026-08-19 --
cited with a fetch date in each file's docstring, the same discipline as
the Pinterest spec citations, just a different kind of source. If you add
fields later, re-fetch the relevant reference page rather than trust
memory or a third-party blog post -- see the DMA situation below for
exactly why that matters.

## DMA is retired -- read this before deploying

This is the most important caveat in the whole project, because you told me
DMA is the most important breakdown.

Pinterest's ad-level DMA breakdown (`pinterest_ads_dma_to_iceberg_glue_job.py`)
maps directly onto Nielsen's classic media markets. Meta had the same
concept -- a `dma` breakdown value on the Insights API -- but the evidence
gathered while building `meta_ads_dma_to_iceberg_glue_job.py` was genuinely
mixed:

- Meta's own live breakdowns reference page (fetched 2026-08-19) still
  lists `dma` as a valid breakdown, with no deprecation notice.
- Four independent production ETL vendors -- **Fivetran, Airbyte, Rivery,
  and Supermetrics** -- all separately confirm the Nielsen `dma` breakdown
  stopped returning results on **2026-06-22**, two months before this
  project was built, replaced by a new `comscore_market` breakdown.
  Rivery's changelog states it plainly: "Meta has fully retired Nielsen DMA
  across its reporting... choose Comscore Market to retain geographic-level
  reporting."

Convergent, independent operational evidence from four production vendors
(who'd have discovered this from real API calls actually failing) outweighs
a docs page that may simply not have been updated yet. **`meta_ads_dma_to_iceberg_glue_job.py`
defaults to `comscore_market`** (the `GEO_BREAKDOWN` constant at the top of
that file), not legacy `dma`.

**Before you rely on this table**, run the job once against a real account
and confirm two things neither source above could settle from documentation
alone:
1. Whether `comscore_market` values come back as human-readable market
   names or as bare IDs needing a lookup table (Pinterest's DMA breakdown
   needed one; Meta's may not -- unconfirmed).
2. That `comscore_market` is actually enabled and populated for your ad
   accounts -- Comscore Markets rolled out for automotive-vertical ads
   first per some of the source material, and account-level availability
   for other verticals (insurance, this project's actual use case) wasn't
   independently confirmed.

If your account still returns data for legacy `dma`, switching back is a
one-constant change (`GEO_BREAKDOWN = "dma"` in that file) -- see the
job's docstring for the full writeup.

## Age/gender is one combined table

Unlike Pinterest, where `GENDER` and `AGE_BUCKET` are independent
breakdowns of the same total (summing across both silently doubles every
metric -- see the sibling project's `pinterest_ads_gender_to_iceberg_glue_job.py`/
`pinterest_ads_age_to_iceberg_glue_job.py` for that whole story), Meta's
breakdowns reference docs explicitly list `age+gender` as a **permitted
combination** -- a true cross-tab. `meta_ads_demographics_to_iceberg_glue_job.py`
requests both in one call and writes one table with grain
`(ad_id, date, age, gender)`. Every row is already scoped to one
`(age, gender)` pair, so `SUM(spend)` for an `(ad_id, stat_date)` just
works -- no discriminator column, no double-counting footgun to document.

## Meta's error detail is preserved in raised errors

Every job loops over every discovered ad account and makes at least one API
call per account; a single account's request error (a 500, a timeout, a
permission problem -- anything `requests` raises) propagates straight out
of `main()` and aborts the run, the same way an unhandled exception would
anywhere else in the pipeline.

What *is* handled is the quality of that error's message. `requests`'
default `HTTPError` message (`"500 Server Error: Internal Server Error for
url: ..."`) never includes the response body, but Meta's Graph API almost
always returns a structured `{"error": {"message", "code", "error_subcode",
"fbtrace_id", ...}}` JSON payload even on a 500. `meta_http.py`'s
`describe_meta_error()` extracts that and appends it to whatever gets
raised, so a job's logs/traceback show Meta's actual message and
`fbtrace_id` instead of just the generic HTTP reason phrase -- the
difference between "500 Server Error" and knowing what Meta is actually
complaining about.

## The dimensions job's 500 error, and why it's page-size, not data or auth

Root cause, found live in production on 2026-08-20: requesting the full
39-62-field object for `DEFAULT_PAGE_SIZE` (100) entities per page, across
every page of an account with 100+ campaigns, trips Meta's Marketing API
cost-based throttle. Meta's own message: **"Please reduce the amount of data
you're asking for, then retry your request."** Confirmed by reproducing it
directly: the identical request succeeded once in Postman, then failed with
that exact message on an immediate re-run of the same request. That rules out
a data problem with a specific campaign, a permissions problem, and a
query-format problem -- three hypotheses chased and eliminated in that order
before this one:
1. **Not auth** -- same System User token in Postman and the job.
2. **Not the field list** -- Postman succeeded requesting all 39 fields,
   `budget_rebalance_flag` (a field flagged deprecated since Marketing API
   v7.0) included.
3. **Not a specific bad record on a later page** -- the failure reproduced
   on the *same* request run twice, not on a *different* page/cursor.
4. **Is a request-cost throttle** -- confirmed by Meta's own error message,
   which explicitly asks for less data per request, not a retry of the same
   request. This is also why `request_with_backoff()`'s retry-with-backoff
   didn't help on its own: it retries the identical request, which is
   exactly what Meta's message says not to do.

Fix: `meta_config.DETAIL_PAGE_SIZE` (25, vs. the default 100) for
`meta_dimensions_to_iceberg_glue_job.py`'s three full-object listings only --
the performance jobs' ID-only/insights calls stay at the default, since
they're far cheaper per object and weren't implicated. `get_all_pages()`
also now pauses `PAGE_PACING_SECONDS` (1s) between pages (not before the
first or after the last) on every paginated call, so consecutive requests
don't stack up as fast regardless of page size. If a similarly-large account
still trips this after both changes, lower `DETAIL_PAGE_SIZE` further before
assuming something else is wrong -- the mechanism is confirmed, only the
exact threshold for a given account's data volume is account-specific.

## AdSet's `contextual_bundling_spec` field requires a Gatekeeper flag

A second, unrelated 500 turned up on the ad set dimensions pull after the
above fix, on accounts with 100+ ad sets. It looked like the same
cost-based throttle at first, but reproducing the exact `AD_SET_FIELD_SPECS`
field list directly in Postman (2026-08-30) returned a completely different
error: **`(#3) AdAccount must pass GK: contextual_bundle_test_api_accounts`**
-- a permission/feature-gate exception, not a throttle. `contextual_bundling_spec`
is documented on Meta's AdSet object reference, but it's gated behind a
Gatekeeper flag that only accounts enrolled in that specific beta program
have; requesting it for any other account fails outright, no matter the
page size or pacing.

Fix: `contextual_bundling_spec` was dropped from
`meta_dimensions_to_iceberg_glue_job.py`'s `AD_SET_FIELD_SPECS` (62 fields
now, not 63) -- there's no way to request it unconditionally for every
account. If your accounts are confirmed enrolled in that program, it can be
added back; see the field-spec comment in that job for the one-line change.

## Differences from the Pinterest pipeline

- **Auth**: static System User token, no refresh flow (see "Auth" above).
- **No entity-ID batching needed for performance data.** Pinterest's
  analytics endpoints require listing every entity's ID first, then batching
  IDs into groups for the analytics call. Meta's `/{ad_account_id}/insights`
  edge accepts a `level` parameter (`ad`/`adset`/`campaign`) and returns
  insights for *every* entity at that level, for the whole account, in one
  paginated call -- confirmed against Meta's docs on 2026-08-19. Simpler
  architecture; see `meta_analytics.py`'s docstring.
- **Conversions/leads aren't flat named columns.** Pinterest has `LEADS`/
  `TOTAL_CONVERSIONS` as dedicated fields. Meta bundles every conversion
  type into one `actions` field -- a list of `{action_type, value}` pairs,
  where the meaningful `action_type` (native Lead Ad form fill vs. a Meta
  Pixel "Lead" event vs. a purchase, etc.) depends on how each campaign is
  configured. Rather than guess which `action_type` is "the" lead metric
  for every campaign, `actions` and `cost_per_action_type` (and every
  `video_p*_watched_actions` field, which are the *same* list-of-pairs
  shape) are stored as JSON, same treatment the dimension tables give any
  field whose shape isn't a stable flat scalar. Query the specific
  `action_type` that matters for a given campaign with `from_json`/
  `json_extract`.
- **`build_table()` is shared infrastructure, not duplicated per job.**
  The Pinterest dimensions job hand-writes its `SCHEMA`/`ICEBERG_COLUMNS`/
  `to_row()` per entity. Meta's dimension entities are larger (up to 64
  fields for AdSet, vs. Pinterest's largest at 40), so `meta_schema.py`'s
  `build_table()` derives all three from one field-spec list instead,
  making a transposition bug structurally impossible rather than something
  to catch by testing afterward. Every performance job uses the same
  helper for its (smaller) row shape too, for consistency.
- **Datetime fields are ISO-8601 strings**, not Unix-seconds integers the
  way Pinterest's `created_time`/`updated_time` are. Confirmed from the
  fetched reference pages' `datetime` type annotation. Stored as the raw
  string and cast via SQL at merge time, same technique used for
  `stat_date` in every performance job.
- **`time_range` is interpreted in the ad account's own timezone, not UTC.**
  Pinterest's `start_date`/`end_date` are explicitly UTC. Meta's Insights API
  interprets `since`/`until` in whatever timezone the ad account itself is
  set to -- confirmed while researching the 400-error auth fix above, not
  something assumed going in. `resolve_date_range()` computes dates off
  `date.today()` (server/UTC time) the same way the Pinterest jobs do, so an
  ad account running in a non-UTC timezone will see its "yesterday" boundary
  shift by the timezone offset relative to what this job actually requests.
  Not a correctness bug for a 14-day rolling window -- a day or so of skew
  at the edges of the window self-corrects on the next run via the `MERGE
  INTO` -- but worth knowing if you need exact per-account-timezone-day
  alignment.

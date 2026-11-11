# Daily intelligence feed (v1)

The existing collector publishes a compact reading-candidate feed alongside its
legacy public archive. This adds no schedule, network requests, paid API use or
secrets. It does not mean the assistant has read or analyzed every report.

## Endpoints and integration

- `data/index.json` remains authoritative for available archive dates.
- `data/intelligence/days/YYYY-MM-DD.json` contains that date's derived feed.
- `data/intelligence/latest.json` contains the most recent collector-run sidecar.
- Existing `data/latest.json`, `data/days/YYYY-MM-DD.json` and
  `storage/archive/YYYY-MM-DD/digest.json` retain their existing contract.

For Investment Office, fetch the existing index, resolve the selected date, then
try its intelligence sidecar. A missing sidecar on an older archived day is normal:
fall back to the legacy day payload and show its extraction status conservatively.
Do not combine dates silently or treat a failed new-feed fetch as zero collection.
Compare `date`, `requested_date`, `generated_at` and the user's current date.
`freshness.status=current` only means the effective date equals the requested date
of that collector run; it is not proof that the feed is current today.

The existing daily publisher is the sole writer. It generates the effective day's
sidecar after its legacy outputs. Historic files are not rewritten or deleted by
this addition. The PR seeds September 30 sidecars from the already-public digest,
without recollection. No Site changes or deployment are included here.

## Stable field names

Top-level fields are `schema_version` (1), `rule_version`
(`daily-intelligence-v1`), `date`, `requested_date`, `generated_at`, `freshness`,
`counts`, `collector_health`, `shortlist`, `shortlist_policy` and `reports`.
`shortlist` is an ordered list of `canonical_id` strings; resolve them against
`reports`. A shortlist entry is a reading candidate, not an investment recommendation.

Report fields:

| Field | Meaning |
| --- | --- |
| `canonical_id`, `source`, `report_id` | Identity is `(source, report_id)`. ID URL-quotes each component and joins with `:`. |
| `broker`, `title`, `published_date` | Public collector metadata; broker is the report publisher, not necessarily the company. |
| `upstream_category`, `upstream_category_label`, `upstream_subject` | Original collector labels, preserved for auditing. |
| `company` | `{name,ticker,status}`. A title-derived company is `title_candidate`; missing identity is `unresolved`. Tickers are never invented. |
| `classification` | `{category,label,method,confidence,reasons:[{field,matched}]}`. All are deterministic rule inferences, not verified facts. |
| `sectors`, `themes` | `[{name,field,matched}]`, derived only from title and collector excerpt. |
| `content_status` | `{level,pdf_link_available,pdf_text_extracted,html_text_available,fulltext_read,extraction_error}`. |
| `detail_url`, `pdf_url` | Existing public links after structural host/scheme validation. No live availability verification. |
| `provenance` | `{origin,link_verification,duplicate_group_id,source_records,source_records_complete}`. |
| `report_claims` | `{excerpt,status}`. Short collector-provided excerpt, marked `author_claims_unverified`, or empty and `unavailable`. |
| `author_opinion` | `{rating,target_price,status}`. Collector-attributed author opinion, distinct from report claims and reading rules. |
| `signals` | `{keyword_signals,numeric_revisions,numeric_revision_status,conflicting_keyword_directions}`. |
| `read_priority` | `{rank,score,reasons:[{code,points}],action}`. Assistant-system reading triage, not report fact or author opinion. |
| `errors` | Fixed public codes for invalid or missing links. Raw exceptions and secrets are excluded. |

Categories are `company`, `industry`, `strategy`, `macro`, `fixed_income`, `other`.
Confidence is `medium` for explicit title patterns and `low` for upstream fallback.
For example, **Fixed Income Monthly** becomes `fixed_income` while its original
`industry` label stays visible. China strategy reports remain included.

Content levels are `pdf_excerpt`, `html_excerpt`, `title_only`. PDF extraction is
bounded by the existing page/character limits; none is evidence of full reading.
`fulltext_read` is always false in this feed. `extraction_error=not_recorded` means
the legacy pipeline does not record a per-report extraction outcome. It does not
mean extraction succeeded. A PDF link can exist with zero PDF text extracted.
LLM-overwritten excerpts are omitted from report claims rather than misattributed
to the author. Raw body/PDF text and investment memos are never copied.

`provenance.origin=collector_public_metadata` and
`provenance.link_verification=not_checked`. Allowed public source hosts are checked
structurally; there is no link probe, document authenticity check or assistant read.
`source_records` contains `{canonical_id,source,report_id,detail_url,pdf_url}`.
New collections preserve merged collector references. Older payloads lack those
references, so `source_records_complete=false` explicitly signals the historical gap.

Cross-source duplicate groups hash publication date, normalized broker and title.
Distinct sources retain their canonical identity. Only one report per group enters
the shortlist. This conservative rule does not claim to detect paraphrased duplicates.

## Signals and ranking

`earnings_estimate_up/down` and `margin_estimate_up/down` are keyword signals.
Both directions may occur in one report; `conflicting_keyword_directions` makes
that visible. They never create numeric revisions or receive numeric revision points.
`numeric_revisions` requires finite previous/current values from an upstream
numeric comparison; its evidence status is
`collector_numeric_comparison_unverified`. These are extracted values, not independently
verified changes in broker forecasts. Read the source to verify context and periods.

The transparent reading score is:

- Published on the requested date: +2.
- Existing configured interest match: +8 (private matching terms are omitted).
- Numeric comparison available for source review: +3.
- Public PDF link available for selective reading: +2.
- Collector excerpt available: +1.
- Title only: -2.
- Missing public link: -10.

Ties use canonical ID. The default shortlist has five slots, first uses a soft
limit of two reports per broker, then fills unused slots if fewer brokers are
available. It always keeps one report per duplicate group. `reports` retains score
order and `rank`; shortlist order includes the broker diversity selection.
`shortlist_policy` exposes those limits. Reading actions are `selective_pdf_read`,
`selective_detail_read`, `metadata_review`. Only reports with a public link enter
the shortlist. The assistant can selectively read relevant PDFs/details afterward
and label any subsequent interpretation separately; this feed never stores it.

Only known public collectors are accepted. No private diary, portfolio, notes,
settings, raw exceptions or generated investment memos are accepted as inputs to
the export. All exported fields use an explicit allowlist. Empty collectors are
distinct from failures; public collector errors use `collector_failed`.

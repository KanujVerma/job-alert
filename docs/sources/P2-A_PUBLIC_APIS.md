# P2-A source contracts and allowed read-only verification

Audited 2026-11-06 (America/Chicago). Technical API documentation is not a
blanket license to redistribute another employer's data. P2-A only performs
bounded public GETs for personal discovery. No authenticated endpoints,
login automation, application submissions, unlisted-post exposure or raw
job-description dataset export. No third-party source code was copied: these
adapters reuse Jobbie's existing MIT-licensed BaseAdapter/HTTPClient and official
API contracts. Future feed licensing remains P2-B.

## Greenhouse
- Official contract: https://docs.greenhouse.io/job-board
- `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
  is public and unauthenticated. It lists all posts; no cursor/page parameter
  is documented for this endpoint. If a response advertises pagination or a
  mismatched `meta.total`, fail rather than claiming complete coverage.
- `id` = public POST identity. `internal_job_id` = underlying job identity;
  null explicitly means a prospect/general-interest post, not an opening.
- `content=true` supplies HTML description/departments/offices. Metadata may
  expose employment type; absence remains unknown. HTML entities can be
  double-encoded; normalize markup without erasing qualification headings.
- `updated_at` is NOT posting time. Only `first_published`, when provided,
  becomes `posted_at`. Otherwise preserve date as unknown and retain update
  timestamp separately.
- A missing description can use the fixed public detail route
  `/jobs/{post_id}?pay_transparency=true`, bounded by `detail_limit` (0 by
  default, maximum 10). Detail identity must match the list record.
- `pay_input_ranges` is cents + explicit currency. This API's shown contract
  does not establish an interval; display `period unspecified`, not annual
  base pay. No hourly-to-annual conversion or equity/bonus summation.
- Own-company smoke token: `greenhouse`, hosted board
  https://job-boards.greenhouse.io/greenhouse redirects to its employer careers
  page https://www.greenhouse.com/careers/opportunities (observed via browser).

## Ashby
- Official contract: https://developers.ashbyhq.com/docs/public-job-posting-api
- Public GET:
  `https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}?includeCompensation=true`
- Not the authenticated `POST jobPosting.list` API, not jobsRead credentials.
- Only `isListed: true` is discoverable. False/missing/nonboolean flags never
  expose direct-link-only jobs. No guessing of private URLs.
- `descriptionPlain` preferred; HTML fallback. Structured primary/secondary
  locations retained; `isRemote` by itself is not proof of US eligibility.
- Employment `FullTime`, `Intern`, `PartTime`, `Contract`, `Temporary` mapped
  explicitly. Non-full-time source facts override a positive new-grad title.
- `publishedAt` is **last published**, not necessarily originally posted.
  Discord labels it `Last published`; missing/naive/invalid date stays unknown.
- API ID when present; documented response may omit it. Fallback ID is a hash
  of the source job URL, NOT a mutable title/location. No title-based merging.
- Salary components only; keep explicit currency and interval. Tier labels
  preserved; never add Bonus or EquityPercentage into cash salary. Missing
  currency/invalid amounts produce no salary assertion.
- Own-company smoke board `Ashby` is an explicit example in official docs:
  https://jobs.ashbyhq.com/Ashby; employer page
  https://www.ashbyhq.com/careers. It is a smoke target, not an enabled employer.

## Operational safety / live evidence
`examples/p2a-public-boards.yaml` has both targets `enabled: false`,
`network_priority: false`. It is NOT read by production `companies.yaml`.
`scripts/verify_public_boards.py --allow-network` selects these explicitly for
read-only checks, emits metadata-only receipts and verifies production config
and state hashes remain unchanged. No webhook is constructed or called.

Live receipts must name exact code SHA, platform, board URL, timestamp, source
count, missing-field counts, and test result. Record actual Actions results in
STATUS/RELEASE_LOG; a JSON fixture or a fetched documentation page is NOT proof
that the implemented adapter fetched a live board.

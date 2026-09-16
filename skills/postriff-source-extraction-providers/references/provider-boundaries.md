# Source extraction provider boundaries

## NewsCrawler

Reviewed reference: `NanmiCoder/NewsCrawler@25fb3b4a20186905f5ce38f7a7f854050d402253`.

Accept only a known supported public URL. Preserve original and canonical URL, ordered text, public media references, author, publisher time, retrieval time, adapter commit, output hash, and warnings. Return one of `supported`, `unsupported`, `login_required`, `paywalled`, `robots_blocked`, `parser_drift`, `rate_limited`, or `failed`.

Successful extraction proves only that content was retrieved. It does not establish truth, originality, complete news coverage, the creator's view, quotation permission, or rights to reuse text or media. Never bypass an access control or silently switch to an authenticated route.

## XhsSkills

Reviewed reference: `cv-cat/XhsSkills@138288d2f288e125a5b0c3aad7efecf6b74b51d9`.

State is `reference_only`. License, platform terms, anti-automation risk, dependencies, signer behavior, cookies, accounts, and exact operations remain unresolved. Expose no search, note, comment, login, creator, message, engagement, no-watermark, upload, schedule, publish, cookie import/export, or raw-cookie command operation.

If a separately approved review qualifies a future read wrapper, it may start with bounded public keyword search, exact public-note detail, and materially necessary minimized public comments. Those signals remain discovery-only and retain query, time filter, result limit, retrieval time, represented data window, and known gaps.

## Shared output and failure rules

- Use source-specific rate limits, bounded pages/results, caching, backoff, and parser-drift health checks.
- Keep provider credentials and social mutation tools unavailable to research workers.
- Do not copy a source's protected expression into final content.
- Keep extraction, source authority, fact confidence, rights, and approval as separate states.
- Do not label polling, crawling, or platform search as literally real-time, exhaustive, or comprehensive.

# Evidence and source register

Public documentation was checked during this research. Vendor account configuration, pricing entitlements and live capabilities were not tested. Repository references are pinned to the stated commit, except R01 which records the branch observation.

## R01. Pinned consumer-saas branch observation

https://api.github.com/repos/dev-james0723/PostRiff/branches/consumer-saas

Checked: 2026-09-29. Source snapshot only, not production deployment proof.

## R02. Surface-neutral agent contracts

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/agent_runtime_v2/contracts.py

Checked: 2026-09-29. External/destructive/secret tools forbidden; workspace default; verified typed results.

## R03. Notification architecture

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/notifications/__init__.py

Checked: 2026-09-29. Existing transactional event and delivery design.

## R04. NotificationService

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/notifications/service.py

Checked: 2026-09-29. Read lines 1–140; source flags are not proof of activated delivery.

## R05. JEV client

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/growth/jev.py

Checked: 2026-09-29. Read lines 1–130; qualified provider/account state not tested.

## R06. Frontend package and script inventory

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/web/package.json

Checked: 2026-09-29. Recharts/TanStack/Sentry and current commands verified in source.

## R07. Browser CI workflow

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/.github/workflows/rafii-browser.yml

Checked: 2026-09-29. Workflow read, not executed; exact checked/skip evidence needed.

## S01. PostHog Product Analytics

https://posthog.com/product-analytics

Checked: 2026-09-29. Trends, funnels, retention, paths and integrations; do not enable broad autocapture by default.

## S02. PostHog product analytics API documentation source

https://github.com/PostHog/posthog.com/blob/master/contents/docs/product-analytics/surfaces/api.mdx

Checked: 2026-09-29. Project Query API; exact scopes and hosted region must be verified at setup.

## S03. Sentry: List an organization’s issues

https://docs.sentry.io/api/events/list-an-organizations-issues/

Checked: 2026-09-29. Use organization endpoint and project filter, not deprecated project-issues listing.

## S04. Sentry Seer

https://docs.sentry.io/product/ai-in-sentry/seer

Checked: 2026-09-29. Optional AI diagnosis/patch capabilities; plan, repository authorization and data processing approval required.

## S05. Vercel Drains

https://vercel.com/docs/drains

Checked: 2026-09-29. Plan/cost/coverage dependent; no assumed account entitlement.

## S06. OpenTelemetry signals

https://opentelemetry.io/docs/concepts/signals/

Checked: 2026-09-29. Traces, metrics and logs; configuration and redaction remain application responsibilities.

## S07. Stripe: Automate payment retries

https://docs.stripe.com/billing/revenue-recovery/smart-retries

Checked: 2026-09-29. Eligible invoice recovery; hard-decline/missing-method limitations; avoid competing retry loops.

## S08. Stripe webhooks

https://docs.stripe.com/webhooks

Checked: 2026-09-29. Signature, retries, event-order and duplicate handling; qualify actual API version.

## S09. Resend webhooks

https://resend.com/docs/webhooks/introduction

Checked: 2026-09-29. Delivery/bounce and event-driven workflows; signed ingress and suppression required.

## S10. Supabase row-level security

https://supabase.com/docs/guides/database/postgres/row-level-security

Checked: 2026-09-29. Service-role bypass; view and role grants; no client secret exposure.

## S11. GitHub App installation authentication

https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app

Checked: 2026-09-29. Short-lived installation tokens scoped to repositories/permissions.

## S12. GitHub: Securely using pull_request_target

https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target

Checked: 2026-09-29. Do not run untrusted PR code with privileged base-context secrets.

## S13. Checkly documentation

https://www.checklyhq.com/docs/

Checked: 2026-09-29. API/browser monitoring and REST integration; optional independent monitoring vendor.

## S14. Search Console Search Analytics query

https://developers.google.com/webmaster-tools/v1/searchanalytics/query

Checked: 2026-09-29. Aggregate site/query/page data; coverage and top-row limitations; no individual-user identity.

## S15. Langfuse documentation

https://langfuse.com/docs

Checked: 2026-09-29. Optional AI trace/evaluation workflow; choose one supplemental system and control private capture.

## S16. React Flow documentation

https://reactflow.dev/learn

Checked: 2026-09-29. Optional interactive node/edge UI, not an authorization or graph-database layer.

## S17. Apache ECharts features

https://echarts.apache.org/en/feature.html

Checked: 2026-09-29. Optional specialized chart renderer; do not add without a demonstrated gap.

## S18. Semgrep Community Edition

https://semgrep.dev/products/community-edition

Checked: 2026-09-29. Static analysis/rules, not proof the app has no vulnerabilities.

## S19. PyPA pip-audit

https://github.com/pypa/pip-audit

Checked: 2026-09-29. Known dependency advisories; dependency resolution can execute package installation behavior.

## S20. Lighthouse CI

https://github.com/GoogleChrome/lighthouse-ci

Checked: 2026-09-29. Controlled performance checks, not production uptime verification.

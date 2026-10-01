# Rafii Control v2
## Founder Intelligence, Revenue Operations and Engineering Control

**Design specification and implementation tech pack**  
**Version:** 2.0.0 · **Prepared:** September 29, 2026  
**Owner:** James · **Product:** Rafii  
**Status:** Proposed architecture, ready for review. Not implemented or activated.  
**Source snapshot:** `dev-james0723/PostRiff`, `consumer-saas`, `d91660b7936a5158b820914107306ad4a1e51c2d`.

> One place to see how Rafii is doing, understand why, decide what to improve, and verify whether the improvement worked.

## 0. Document authority and delivery boundaries

This is a consolidated v2, not just a list of additional ideas. It retains the founder-only access, customer support, account controls, billing, credit accounting and auditing requirements of v1, and replaces the parts that do not support an intelligent operating system. The accompanying catalogs, JSON Schemas and API contract are part of this design. They define proposed interfaces, not already deployed APIs.

**Order of authority:** current explicit founder decisions; the security and accounting invariants in this document; versioned business policies; the API/schema contracts; UI descriptions. An AI recommendation cannot override any of them. Existing production accounting behavior must be preserved until a specifically reviewed migration changes it.

The v1 contents supplied in the conversation were reviewed. Its Mac file could not be reread because Open Remote Computer returned a Cloudflare Durable Objects quota error. This v2 therefore does not claim to inspect changes made to that file since the previous conversation. Selected current files were read directly from GitHub at the immutable snapshot above. A GitHub file existing is evidence of source implementation, not evidence of deployment, enabled feature flags, successful delivery or a passing runtime test. [R01–R07]

No product code, production database, billing configuration, customer account, notification, recurring job, DNS entry or GitHub branch was changed for this research. No codebase scan or production test was run. The local Universal Library build failure reported in the conversation was `ENOSPC`; treat that as build infrastructure evidence, not proof of a product code defect. Its latest code, migration and deployment state remains unverified in this review.

### 0.1 Outcome and non-outcome

The desired outcome is not an attractive wall of charts. It is a shorter, safer path from a business question to an evidence-backed decision. Success means James can identify a material problem, inspect the evidence, approve the right bounded action and see its measured outcome without manually stitching together five vendor dashboards.

The system can help recover collectible revenue, improve conversion and retention, reduce avoidable operating cost, and prioritize engineering. It cannot guarantee more income, prove causality from correlated charts, or promise to detect every bug. Those limits must appear in the product's language, not just its legal terms.

### 0.2 Launch boundaries

Build the capability in phases. Launch a useful read-only Command Center and an evidence-grounded founder copilot before opening financial, account or code-writing controls. All automated external actions start disabled. Read-only scheduled investigations require an approved operating budget and data-access policy. A schedule in this document is a proposed product behavior, not a ChatGPT automation that has been created.

## 1. V1 reevaluation: retain, correct, replace

| V1 issue | Consequence | V2 decision |
|---|---|---|
| Many useful pages, but no shared decision-to-outcome workflow | James still has to connect the facts manually | Introduce a Decision Queue with evidence, hypotheses, proposed actions, approvals and outcome measurements |
| KPI names without sufficiently precise calculation contracts | Conflicting revenue, retention and performance numbers | A versioned metric registry becomes the only source for charts, reports, alerts and AI answers |
| AI was primarily support-drafting assistance | No intelligent founder operating loop | Add a founder-scoped Rafii copilot with investigation, chart-building, diagnosis and proposal tools |
| Notification and push architecture described largely as new | Duplicates existing services and creates inconsistent preferences | Extend current `notifications/NotificationService`; preserve its transactional emission, delivery, digest and baseline behavior [R03,R04] |
| Same Vercel project recommended for the smaller v1 | Customer deployments and privileged operations share too much failure surface | Use a separate control project from the same repository for v2; isolate execution credentials further |
| Support access could appear self-authorized by a founder reason | An audit reason is mistaken for customer consent | Separate customer-approved support grants from narrowly governed security/legal investigation access |
| FORCE RLS could be read as sufficient protection against privileged connections | Service-role access bypasses normal tenant controls | Dedicated least-privilege database roles and private views; privileged commands behind explicit authorization [S10] |
| General financial controls without a business growth system | Reporting does not translate into prioritization | Add payment recovery, activation, retention, unit-economics and experiment playbooks |
| System health did not connect releases, traces, users and money | No reliable understanding of a bug's impact | Build a permission-scoped relationship index linking releases, incidents, runs, customers and billing entities |
| No structured code-check workflow | A model could confuse a suggestion with a verified fix | Exact-SHA checks, sandboxed execution, receipts, draft PRs and separate release approval |
| A long navigation menu | Founder's attention is split across 18 destinations | Eight primary sections, contextual subviews, one global search and one persistent copilot |
| No explicit data-availability contract | Missing events can look like a business decline | Every metric includes freshness, coverage, measurement state and exclusions |
| Fixed dashboards only | New business questions require another feature | Safe natural-language query to metric DSL to chart spec, with no unrestricted model-written SQL |
| Limited model quality and cost operations | Cheaper or faster could be mistaken for better | Measure task quality, correctness, latency, cost, cancellation and unknown settlement together |
| No attention or inference budget | Monitoring creates noise and expensive analysis | Deterministic detection first; deduplication, severity, investigation budgets and quiet hours |
| Account deletion and financial retention not reconciled in enough detail | Deletion could erase required financial evidence or resurrect through replay | Separate retained accounting identity from deletable content; tombstone-aware imports and restore procedures |

**Retain without weakening:** no arbitrary SQL console, no plaintext-secret viewer, no direct credit-balance edits, no forged user sessions, no unrestricted impersonation, no unapproved publishing, no unreviewed refunds/bans/deletion, and no customer-agent escalation into founder authority.

### 1.1 Current repo findings that change the design

The present agent runtime already defines typed results for text and voice, stored versus derived facts, trace IDs, pending approvals, changed entities and verified completion. Its tool contract explicitly forbids `EXTERNAL_EFFECT`, `DESTRUCTIVE` and `SECRET`. Tools default to a single workspace. V2 must not loosen those restrictions to make the founder portal convenient. [R02]

The existing notification service already handles domain events, deterministic planning, in-app messages, email, Web Push, preferences, digests, provider webhooks and bounded cron processing. Its source also contains SMS and phone hooks behind separate flags. Availability in source is not a claim that those channels are configured. [R03,R04]

The frontend already uses Recharts, TanStack Query/Table, Zod, Sentry and the Rafii UI stack. Reuse those foundations. The current browser workflow already builds a production-mode frontend against a disposable PostgreSQL harness, uses synthetic providers, tests Chromium and Linux WebKit, and attaches commit-specific evidence. Import these checks rather than invent a competing test framework. [R06,R07]

A JEV evaluation client exists in `growth/jev.py`. Reuse its router-owned retry, cost/provenance and validated judgment concepts where appropriate. Do not assume that its configured model is currently qualified or use model confidence as statistical confidence. [R05]

## 2. Product architecture: the Rafii operating loop

### 2.1 The core loop

`Observe → validate data → detect → investigate → recommend → approve → execute → verify → measure`

Each stage produces a durable record. A failed or unknown stage cannot be silently skipped. The dashboard, copilot, daily brief, incident view and engineering view all read the same records.

Example: a drop in paid activation creates a signal only after event coverage is checked. An investigation compares cohorts and release timing, links an error cluster and identifies affected accounts. The copilot proposes a reproduction check and a fix experiment. A trusted runner returns test evidence. James approves a draft PR or a customer follow-up separately. The system subsequently reports whether activation improved, including uncertainty and remaining problems.

### 2.2 Architectural options

**A. Extend the customer application with another admin section.** Lowest initial wiring cost, but insufficient separation for this v2's model-driven investigations, code-runner integration, cross-customer analytics and vendor credentials. Keep only a founder-only link to the separate console in the customer UI, if desired.

**B. Separate control application, shared versioned domain services, one initial operational database. Recommended.** Use the same Git repository and selected reusable UI/domain packages, but an independent deployment, founder sessions, private query services and credential scopes. Add database analytics projections before a warehouse. Place engineering execution in disposable runners, not the application process.

**C. Buy or build a full warehouse, BI suite, graph database and multi-agent operations platform immediately.** This adds cost and synchronization responsibilities before data volume justifies them. Defer until measurable scale, retention or analyst-workflow requirements trigger it.

### 2.3 Proposed components

| Component | Responsibility | Must not do |
|---|---|---|
| Control Web | Founder UI, charts, search, copilot and approval screens | Hold provider secrets or directly query production tables |
| Control BFF | Founder session, CSRF, output filtering, bounded query API | Treat browser-supplied role or target as authority |
| Intelligence Worker | Projections, detectors, investigations and briefs | Run arbitrary generated shell commands or charge customers |
| Query Service | Compile the metric DSL into approved read queries | Expose raw SQL or unrestricted customer content |
| Command Gateway | Validate and execute an approved typed operation | Accept an LLM statement as approval |
| Engineering Broker | Dispatch an approved check/patch job and collect receipts | Pass production secrets into untrusted code |
| Integration Adapters | Provider-specific ingestion and reconciliation | Invent success when a provider returns an ambiguous outcome |
| Evidence Store | Immutable observation metadata, artifact references and provenance | Become a raw data dump of every user's private material |
| External Health Monitor | Detect control-plane silence and selected public failures | Depend exclusively on the system it monitors |

### 2.4 Domain and deployment decision

Use `ops.<VERIFIED_PRIMARY_DOMAIN>` as the human entry point, backed by a new **`rafii-control` deployment project**. The actual root domain is not established by this review and must be verified before DNS/auth changes. Keep the consumer application on its existing verified host. Do not purchase a second unrelated domain merely for branding.

A subdomain distinguishes the surface; it does not alone prevent compromise. Use host-only `__Host-` cookies, independent founder session storage, exact allowed origins, server-side capability checks, no wildcard CORS and no shared frontend token storage. Same-site requests from a sibling subdomain still require origin/CSRF validation. Do not rely on SameSite alone.

Control Web talks only to its own BFF. The BFF can reach a private application command adapter using a short-lived, audience-bound service identity. The adapter reconstructs and checks the operator and approved action, not a user impersonation token. Private service endpoints are not made callable merely by knowing their URL.

The current consumer billing webhook remains the authority for payment settlement. The admin projection consumes settled internal events or read-only Stripe observations; it must not create a second credit-granting webhook consumer. [S08]

**Preview policy:** no production financial write credentials, no production service-role key, no real customer content and no default production database connection. Use a staging environment with synthetic identities and clearly labeled data. Preview hosts cannot mint production founder sessions. Promotion requires exact reviewed commit and environment checks.

### 2.5 Database and scalability decision

Start with the existing PostgreSQL environment plus a private `rafii_control` schema and dedicated connection roles. This schema name and all new tables below are proposed. Revalidate existing tables before choosing migrations. Query projections, not entire workspace state JSON on every dashboard load.

Use an append-only domain outbox for reliable business events and asynchronous projections. Existing notification delivery uses its own established service; share domain events through adapters rather than add another notification sender. [R03,R04]

Separate read models from command transactions. Add a read replica or analytical store only when sustained dashboard/aggregation workload threatens customer transactions, projection storage/retention becomes disproportionate, or required queries consistently miss the agreed SLO after indexing and incremental aggregation. Do not choose an arbitrary user-count threshold.

### 2.6 Availability during incidents

A broken customer release should not automatically break the founder UI. The control project retains last-known-safe, timestamped projections and incident records while upstream data is unavailable. Writes that require fresh state are disabled. An external heartbeat monitor watches both the customer app and the control worker, with an independent alert transport. A single shared database remains a shared failure domain; document that honestly and preserve external incident evidence for database outages.

## 3. Experience and information architecture

### 3.1 Visual direction

Keep Rafii's monochrome visual identity, established typography, rounded surfaces and restrained glass treatment. Use opaque reading surfaces for financial tables and long support threads. Navigation may use glass; data should not float over distracting backgrounds. Keep the existing reduced-motion, keyboard and focus conventions. [R06; v1 design baseline]

Default to an eight-section rail: **Command, Customers, Revenue, Product, AI & Infrastructure, Engineering, Trust & Support, Settings**. Search, environment, period, reporting time zone, freshness and the founder copilot stay available across sections. The current user account and the current business scope must never be visually ambiguous.

Use labels, icons, patterns and line styles before introducing color. Destructive actions may use the existing danger token. Optional operational severity colors must be explicit admin-only tokens, accessibility tested, and not silently change the consumer design system. Avoid animated counters that imply live precision where data is hourly.

### 3.2 Three levels of attention

**Level 1: Command.** Six core numbers, data health, material changes and up to five prioritized decisions. James should be able to decide where to look next without scrolling through every chart.

**Level 2: Domain workbench.** Revenue, activation, AI, infrastructure, support or engineering questions. Each workbench shows the relevant charts, comparisons and saved investigations.

**Level 3: Evidence.** Drill into the source records, definitions, traces, exact commits, provider receipts and permissions. Private data remains masked unless specifically authorized.

### 3.3 Command page contract

Show: paid workspaces, subscription MRR, net collections, completed useful outcomes, estimated contribution with cost coverage, and customer-impacting incidents. Do not put a metric on the page until its source and definition are ready. Replace unavailable values with an explicit reason, not zero.

Below the six values, show: a material-change timeline; Decision Queue; product/service dependency map; next review dates; and the last successful detector/ingestion heartbeat. A disconnected data source is a visible operational problem, not a loading spinner that never ends.

Every number opens an evidence drawer containing metric version, interval, currency/unit, grain, denominator, exclusions, last complete window and linked query receipt. Every recommendation opens an investigation, never executes on click.

### 3.4 Copilot interaction

A persistent right panel on desktop, full-height sheet on mobile. Context includes the selected domain, filters and explicitly opened evidence. Context does not include every hidden dashboard, customer document or browser tab. Allow text and the existing voice interaction style, subject to founder authentication. Voice can inspect or prepare an action but cannot serve as the step-up proof for a refund, ban or release.

Offer concrete prompt starters: “What changed since yesterday?”, “Which customers are blocked?”, “Why did cost per completed draft increase?”, “Show the evidence behind this churn signal”, “Which release introduced this error?”, “Prepare a safe code check”, and “What should I fix first to improve contribution?”

Answers use four sections when appropriate: **Observed facts, Possible explanation, Proposed action, How we will measure it**. Each has source references. A small evidence set should produce a short answer, not a confident essay.

### 3.5 Search and entity navigation

Search by customer/workspace, ticket, invoice/payment, credit grant, run/trace, incident, deployment SHA, pull request or recommendation. Keep customer email search out of analytics URLs and logs. Use POST for sensitive search terms, private cache headers and per-session rate limits. No global private-content search.

The relationship view links typed entities using recorded IDs. Solid links mean verified ownership/reference. Dotted links mean a hypothesis such as a release-correlated error. Do not infer that two customers are the same person from browser characteristics. Store graph edges relationally initially; a graph database is not a prerequisite.

### 3.6 Accessible and responsive analytics

Every chart has a data table, visible units, keyboard-accessible controls and a textual summary. Missing observations produce gaps. Avoid 3D charts and unlabeled dual axes. Display no more than three animated live panels at once; default operational charts to static updates. Table pagination is server-side, default 50 rows, maximum 200 per interactive response.

On phones, Command, notifications, tickets, safe diagnostics and proposal review remain usable. No hover-only controls. High-risk actions require the same complete preview and fresh authentication; bulk deletion/refunds are desktop-only. This is an accident-prevention policy, not a weaker mobile authorization rule.

## 4. Analytics workbenches and visualization system

The accompanying dashboard catalog defines each visualization's question, metrics, rendering, drilldown, refresh and limits. Variety must answer different questions, not restyle the same count. Use the already installed Recharts and TanStack Table by default. [R06]

| Workbench | Questions it must answer | Priority visualizations |
|---|---|---|
| Business Command | What changed, what matters, what should I do? | Metric strip, change timeline, decision queue, dependency map |
| Revenue & Unit Economics | Are collections, retention and contribution improving? | MRR bridge, cash waterfall, revenue cohorts, concentration Pareto, margin matrix |
| Activation & Retention | Where do users fail to reach value or return? | Funnel, time-to-value distribution, retention heatmap, survival curve, segment comparison |
| Acquisition | Which acquisition efforts bring useful and paid usage? | Source funnel, cost/conversion table, organic landing-page matrix, campaign cohorts |
| Customers | Who is blocked, expanding or needs support? | Health evidence table, customer timeline, plan/usage bands, cohort comparisons |
| AI Quality & Cost | Which tasks/routes are reliable and economical? | Cost/quality scatter, latency distribution, trace waterfall, usage ledger states, evaluation regressions |
| Reliability | What is failing and who is affected? | Service graph, error Pareto, SLO burn charts, queue-age heatmap, release overlays |
| Engineering | Is this code safe, verified and actually deployed? | SHA/check matrix, change risk map, flake trend, vulnerability aging, PR evidence timeline |
| Trust & Support | Are people getting safe and timely help? | Backlog aging, response distributions, topic clusters, consent/access timeline, incident case links |
| Growth Decisions | Did the chosen improvement work? | Experiment scorecards, opportunity portfolio, impact versus effort, outcome ledger |

### 4.1 Chart contract

A chart references named metrics and dimensions, not arbitrary JavaScript or SQL. Its contract includes `chartId`, `question`, `metricIds`, `queryReceiptId`, `grain`, `unit`, `comparison`, `visualType`, `dataState`, `freshness`, `drilldownPolicy`, `accessClass` and `definitionVersion`.

The renderer validates visual type and fields, rejects executable HTML/JS, and computes axis labels from the metric registry. The model may propose a chart, but the server validates its query and the client renders only approved primitives. Saving a chart creates a versioned view, not a new metric definition.

Every comparison must align population, interval length, calendar/time-zone convention and maturity. When a current period is incomplete, compare equivalent elapsed periods or show both complete intervals. Do not compare this morning with all of yesterday without labeling it.

### 4.2 Metric truth rules

Use an explicit state: `measured`, `partial`, `stale`, `unavailable`, `not_applicable` or `suppressed`. Zero is a measured value only. Fractions show numerator and denominator. Quantiles come from compatible raw distributions or mergeable histograms, not averages of p95s. Internal, test and founder-exempt activity must be filterable and excluded from customer business KPIs by default.

Store event time, received time and projection time separately. Support correction events and event-level deduplication. Backfill must not generate alerts about historical incidents unless deliberately running a historical analysis. A metric definition change either recomputes the comparison interval or clearly shows a version boundary.

### 4.3 Revenue and credit semantics

**MRR:** monthly-normalized recurring subscription value, with a versioned policy for discounts, delinquency and multiple subscriptions. Exclude tax, one-time credit top-ups, trials and free usage. Annual recurring amount is divided by 12; it is not the cash collected this month. Show delinquent contracted recurring value separately rather than silently counting it as healthy paid MRR.

**Net collections:** successful captured payments less succeeded refunds and actual dispute withdrawals, plus dispute reinstatements, in their reporting interval. Avoid counting a refund and dispute as two independent losses of the same amount. Payouts are transfers of collected cash, not new revenue. Fees and currency conversion are separate rows.

**Recognized revenue:** unavailable until an approved recognition schedule/policy is implemented. Do not rename cash receipts or credit consumption as recognized revenue. Exact tax and accounting treatment needs qualified business/accounting review; engineering supplies transparent transaction lineage, not an invented legal conclusion.

**Credits:** retain the existing immutable usage ledger and lot allocation model. Grants, reservations, settlements, reversals, expiries and debt are not all revenue events. Goodwill grants are not sales. Unknown provider cost is not zero. Founder/internal intelligence costs are booked to platform operations, never to an arbitrary customer's credit wallet.

**Contribution estimate:** a period-consistent revenue basis less attributable model/provider, hosting, payment, messaging and support costs. Show cost completeness and unallocated overhead. When revenue recognition is unavailable, provide a clearly labeled cash contribution view and a separate task-economics view; do not mix accrued costs and cash collections and label the result “profit”.

**Currencies:** retain native amounts in integer minor units and original currency. Summarize per currency by default. A consolidated display requires dated FX rates, source, conversion convention and a label distinguishing actual settlement from display conversion. Do not assume every currency has two decimals.

### 4.4 Retention, attribution and sample limits

Define activation as a validated first-value outcome, not merely registration or an agent message. Candidate for Rafii: first reviewed/exported/published useful draft, with usefulness either explicit user feedback or a separately labeled proxy. Do not claim a verified external publication from an approval event alone.

D7 return measures the selected event in a fixed window after the cohort's first-value date. Unmatured accounts are excluded from the denominator, not counted as churn. Churn/NRR/GRR use the opening paid cohort and separate new customers. Feature-use correlation does not prove the feature causes retention.

Acquisition attribution is first-party tagged source or explicit self-report, with `unknown` retained. Search Console is aggregate search data and must not be joined as if it identified a particular user. CAC needs attributable acquisition spend and a defined new paying-customer cohort. Show LTV as a scenario or unavailable while cohorts are immature. [S14]

## 5. Data architecture, events and evidence

### 5.1 Sources of truth

| Domain | Authoritative record | Secondary/read evidence |
|---|---|---|
| Authentication and membership | Verified identity and application authorization records | Session/security projections |
| Payment result | Verified Stripe state and existing reconciler | Billing read model |
| Credit balance | Existing immutable credit/usage ledger | Rebuildable wallet projection |
| Product completion | Authoritative application outcome event | Explicit browser events for UX only |
| Model cost | Provider receipt or recorded estimate with provenance | Aggregation by task, route and customer |
| External publication | Existing verified provider receipt | Queue/approval states remain separate |
| Code version | Git commit/tree and artifact digest | PR branch label is convenience only |
| Deployment | Provider deployment ID with verified source mapping | GitHub merge is not deployment proof |
| Support reply delivery | Provider receipt/webhook | Composer intent and sent timestamp are distinct |
| AI explanation | Model derivation linked to evidence | Never a replacement for source records |

### 5.2 Event envelope

New intelligence events use a versioned envelope with `eventId`, `schemaVersion`, `eventType`, `source`, `sourceEventId`, `environment`, `eventTime`, `receivedAt`, `subject`, optional workspace/user/run/trace/deployment references, `classification`, `payload` and `dedupeKey`. Only allowlisted payload fields are accepted.

Sensitive content is not placed in the event bus by default. Use content-free error fingerprints and artifact references. Attach a deletion/privacy epoch where derived records concern a user. A late import for a deleted user is rejected or projected only into permissible non-identifying aggregates.

Ingested webhooks are verified before processing; signatures use the provider's required raw bytes and algorithm. Store a minimal durable event before acknowledgment, with unique provider/event identity. Process asynchronously with retries, dead-letter state and operator reconciliation. Do not promise exactly-once network delivery; achieve idempotent effects using stable business keys and database constraints. [S08,S09]

### 5.3 Identity resolution

Use stable internal user and workspace IDs, recorded Stripe customer/subscription mappings, run IDs and deployment SHAs. Never join financial or customer records by email alone. All joins must handle one user in several workspaces and one workspace with several members. Cross-workspace aggregates require the founder principal and approved dimensions; normal user queries remain tenant-scoped.

### 5.4 Query DSL

`MetricQuery` supports named metrics, allowed groupings, a bounded interval, enumerated filters, a comparison mode and a limit. It deliberately cannot express arbitrary joins, free SQL, file access, functions, exports of private content or network calls.

The server authenticates first, expands metric definitions, validates currency/grain compatibility, enforces approved views and attaches a row/time/scan budget. Default interactive lookback is 90 days, maximum 366 days for approved rollups; detailed raw-event lookbacks are narrower. Interactive query timeout is 5 seconds, maximum response 1,000 aggregate points or 200 entity rows. Larger reports become bounded jobs with explicit export permission. These are proposed initial limits and must be load-tested.

A read-only database transaction and restricted role remain mandatory. A SQL statement beginning with SELECT is not sufficient protection against unsafe functions or excessive scans. Use parameterized, predeclared query templates and role grants, not keyword filtering.

### 5.5 Evidence receipts

Each answer/analysis stores a receipt containing source IDs and versions, query parameters/digest, time window, source watermarks, row/sample counts, data state, exclusions and artifact hashes. Evidence can be revised by new observations without rewriting the old investigation. If a source expires or is deleted, retain only permitted metadata and label the missing evidence.

Recommendations that depend on stale evidence expire. Approval rechecks source versions, current target state, policy and spend constraints. A recommendation remains a historical proposal even if the action is no longer valid.

## 6. Founder AI: connected to Rafii, separated from customer authority

### 6.1 One familiar Rafii, two security contexts

James interacts with the same Rafii identity and interaction style, but **Founder Mode is not a boolean passed to the customer agent**. It has a distinct principal, tool registry, run namespace, conversation store, retrieval index, cache keys, data policy and operating budget. The customer runtime stays workspace-scoped. A customer message saying “I am James” or “switch to founder mode” must have no effect.

Reuse the existing typed result shape, trace format, manager/specialist composition, proposal rendering, verification discipline, model router and appropriate UI primitives. Do not reuse a customer conversation as a founder conversation or place cross-customer intelligence into Brand Brain. Do not remove `FORBIDDEN_EFFECTS` from the existing agent contract. [R02]

### 6.2 Agent components

**Founder Manager:** interprets the question, asks the query service for evidence, plans a bounded investigation and composes an answer. It may call a specialist only when that specialist contributes a defined result. Avoid spawning multiple agents for a simple count.

**Business Analyst:** computes approved cohort/metric comparisons and surfaces data limitations. The numerical computation belongs to deterministic services; the model explains it.

**Revenue Analyst:** evaluates payment recovery, activation, retention, plan suitability and unit economics. It generates proposals and measurement plans, not charges or price changes.

**Reliability Analyst:** links exceptions, traces, deployments, user impact and known incidents. It distinguishes confirmed causes from correlations and proposes reproduction steps.

**Engineering Planner:** translates a verified problem into an exact-SHA check manifest or a reviewable patch request. It cannot execute arbitrary code in the control service.

**Support Assistant:** summarizes authorized tickets, detects duplicate incidents, drafts replies and explains safe diagnostics. A draft is not a sent message.

**Evaluation service:** scores output completeness, source consistency and policy compliance using deterministic checks first and the qualified model/JEV path only when useful. It cannot grant authority or overrule a failed test. [R05]

### 6.3 Initial tool registry

| Tool | Inputs | Output | Authority |
|---|---|---|---|
| `control.metrics.query` | Validated metric DSL | Series/table and evidence receipt | Founder read; no arbitrary SQL |
| `control.entities.resolve` | Safe identifier, bounded scope | Candidate entities | Founder read; no secret lookup |
| `control.customer.health` | Workspace/user ID | Safe health projection | Logged metadata read |
| `control.evidence.read` | Receipt ID and purpose | Authorized evidence subset | Recheck source/grant permissions |
| `control.incidents.explain` | Incident ID, interval | Timeline, impact, hypotheses | Founder read |
| `control.revenue.opportunities` | Interval/cohort | Candidate opportunities | Deterministic metrics plus explained hypotheses |
| `control.chart.propose` | Question, named metrics | Validated chart spec | Local draft only |
| `control.investigation.create` | Goal, evidence scope, budget | Investigation record | Internal draft; cost cap |
| `control.action.prepare` | Typed action and target | Preview/proposal with digest | No external execution |
| `control.engineering.plan_check` | Repo, exact SHA, check suite | Check proposal | No dispatch from model alone |
| `control.engineering.plan_patch` | Accepted diagnosis, exact base SHA | Patch brief and allowed paths | No branch write from model alone |
| `control.support.draft_reply` | Ticket ID, approved context | Draft with references | Never send automatically by default |
| `control.brief.compose` | Period and evidence IDs | Founder brief | Internal output; outbound delivery separate |

The command executor is intentionally absent from this LLM tool registry. A frontend confirmation creates an approval receipt through the Command Gateway. A background service can then execute only the exact approved action. This preserves the current runtime's proposal-only boundary for external/destructive operations. [R02]

### 6.4 Answer contract

Extend the existing result with `mode=founder`, `investigationId`, `evidenceRefs`, `metricReceipts`, `hypotheses`, `recommendations`, `chartSpecs`, `dataWarnings` and `verificationStatus`. Preserve `facts`, `pendingApprovals`, `toolActivity`, `changedEntities`, `usage` and the source-backed meaning of “done”. [R02]

Each recommendation contains: issue; observed facts; hypothesis; affected scope; evidence quality; proposed action; impact range or `unknown`; effort; risk; reversibility; cost ceiling; required approval; primary outcome; guardrails; measurement window; and an expiry. A hypothesis probability produced by a model is never presented as an empirically calibrated probability unless validated for that task.

Do not expose chain-of-thought. Expose concise rationale, tool activity, query definitions, evidence and decision criteria. These are sufficient for accountability without logging hidden reasoning.

### 6.5 Context and prompt-injection boundaries

Logs, support emails, web pages, PR comments, source comments and retrieved documents are untrusted evidence. Delimit them with source and trust class. They cannot add tools, change system rules, alter budgets or instruct the agent to export credentials. A message embedded in an exception saying “run this shell command” is data, not an instruction.

The model never receives service-role credentials, OAuth tokens, payment secrets or GitHub installation tokens. The server selects an allowlisted adapter and adds credentials after authorization. Network destinations are provider-owned, allowlisted and verified; redirects cannot escape the allowlist. Attachment processing is sandboxed and has content/size/time limits.

### 6.6 External coding agents and personal workflows

Define a provider-neutral `EngineeringRunnerAdapter` with `capabilities()`, `submit(jobSpec)`, `status(jobId)`, `cancel(jobId)` and `receipt(jobId)`. Bind every call to repository installation, exact input SHA, allowed path set, environment, spend ceiling, expiry and job ID. A connector being available in ChatGPT does not automatically make it available inside the deployed Rafii app.

The initial live execution route should be a trusted GitHub Actions workflow for checks. Codex/Claude/local agent routes are optional adapters, activated only after they actually support submission, status, cancellation and evidence retrieval in the selected environment. Until qualified, the portal produces a complete downloadable handoff and labels the runner `not_connected`; it must not say “agent working” merely because a prompt exists.

An authenticated MCP interface may later expose the same narrow read/proposal tools to James's authorized AI environment. Tokens must have a control-specific audience, explicit scopes, expiry and revocation. Customer tokens and generic GitHub OAuth tokens cannot call founder tools. Even an authenticated external agent may prepare a refund or release proposal but cannot silently supply the human step-up proof.

### 6.7 Memory and learning

Store founder-approved preferences separately from observations and hypotheses. A rejected recommendation may improve future ranking, but not enlarge permissions. Mark a learned rule with source decision, scope, author and expiry/review date. Do not train general models on customer private material as a side effect of operations. Sensitive grant-scoped data must be removed from caches and retrievable summaries when access expires.

## 7. Continuous monitoring and recommendation engine

### 7.1 Scheduling and ingestion

Use durable workers and provider event hooks. The browser, James's laptop and an open AI conversation are not the scheduler. Provider webhook event time is distinct from polling time. Proposed initial cadences:

| Work | Cadence | First-stage computation | Notification policy |
|---|---|---|---|
| Payment, deployment, incident and delivery events | Event-driven | Signature, dedupe, projection | Alert only on material state transition |
| Service heartbeat and small read-only health probes | 1–5 minutes | Deterministic status/SLO rules | Page only after confirmation policy |
| Queue age, stuck work, unknown settlement | Every 5 minutes | Bounded indexed queries | Incident correlation and cooldown |
| Business integrity reconciliations | Every 15 minutes | Ledger/provider/read-model differences | One case per unresolved mismatch |
| Activation/funnel and feature signals | Hourly | Mature-window comparisons | Digest unless substantial customer impact |
| Cost and model-quality drift | Hourly plus evaluation events | Aggregate usage and evaluation receipts | Budget-aware investigation |
| Dependency/advisory and code checks | PR/event plus daily trusted schedule | Pinned scanners and test manifests | Group findings by cause, not log line |
| Founder brief | Daily at configured local business time | Reuse existing evidence | In-app; email/push only when enabled |
| Growth review | Weekly | Mature cohorts and outcome review | Decision summary, not daily churn noise |

A five-minute cadence is a design target, not a guarantee from an arbitrary hosting cron tier. Deployment must verify scheduling resolution, time limits, concurrency and billing of the chosen worker host. If unsupported, use a qualified scheduler or disclose a slower service level before activation.

### 7.2 Detector contract

Each detector declares: input metric versions; scope; minimum history; minimum sample; watermark tolerance; baseline method; threshold; severity; persistence/hysteresis; dedupe key; cooldown; incident grouping; first-run behavior; business interpretation; and safe next investigation. Detector code and thresholds are versioned.

Safety/integrity invariants such as a duplicate credit grant do not need statistical significance. Behavioral changes such as a conversion decline do. An event pipeline outage must create a data-health incident and suppress data-dependent growth conclusions. A raw count can still support a factual message such as “three requests failed”; it cannot support a general population conclusion without the denominator.

### 7.3 Initial detectors

| Detector | Trigger principle | Investigate | Safe default |
|---|---|---|---|
| Payment/entitlement mismatch | Verified payment lacks expected entitlement after allowed settlement lag | Provider receipt, order mapping, existing reconciler | Create reconciliation case, never grant independently |
| Duplicate or inconsistent credit effect | Ledger invariant violation or same business key with conflicting digest | Grant/refund/reservation records | Block unsafe replay and page founder |
| Failed-payment recovery | Eligible invoice failure and current native retry state | Payment method state and provider schedule | Draft reminder/portal-link proposal; no competing charge loop |
| Activation regression | Mature cohort conversion drops beyond configured uncertainty bounds | Browser errors, release/route, device/locale, event completeness | Hypothesis and check proposal |
| Rising failed task cost | Absorbed/failed provider cost increases with sufficient usage | Model route, retries, cancellations and task mix | Recommend route evaluation; don't silently switch provider |
| Latency degradation | Sustained p95/SLO change with minimum request volume | Trace span, queue age, provider status, release | Correlated incident and read-only diagnostics |
| New release error cluster | New fingerprint associated with a deployment and affected real users | First/last seen, stack, exact SHA, before/after | Propose reproduction and bounded check |
| Stuck or uncertain publish | Existing job state exceeds policy; unknown side effect | Provider reconciliation and current approval | Hold; never blind retry |
| Churn risk signal | Missed expected return plus other recorded evidence | Customer history, seasonality, support, billing | Explainable health signal, not a definitive churn prediction |
| Expansion suitability | Sustained legitimate use reaches a plan limit | Value delivered, plan fit, complaints and budget | Transparent plan recommendation draft |
| Email delivery impairment | Bounce/complaint/provider failures cross deterministic policy | Domain/suppression/outbox errors | Respect suppression and open incident |
| Ingestion silence | Heartbeat or watermark exceeds tolerance | Provider credentials, API quota, cron, permissions | Display unavailable/stale, not zero activity |
| Code-check regression | Required check fails or is skipped on candidate SHA | Artifact and workflow provenance | Block “verified fix” claim |
| Security/control anomaly | Privilege denial spike, unusual export or action replay | Admin session, action receipt and access log | Restrict relevant capability and alert |

### 7.4 Statistical discipline

For low-volume behavior metrics, present counts and uncertainty rather than a spurious percent change. Proposed starting rule for an automated conversion-rate anomaly: at least 100 eligible observations in both comparable windows, at least 20 relevant outcomes overall, a practical effect threshold and a confidence/credible interval appropriate to the estimator. These are conservative product defaults to validate, not scientific guarantees. Smaller cohorts can be flagged for manual review, without a population claim.

Use seasonally comparable baselines when sufficient history exists. Apply multiple-testing controls or a limited predeclared detector set; otherwise hundreds of segments will create false discoveries. Do not average confidence estimates from unrelated models. Record excluded windows, deployments, campaigns and maintenance.

For cost/latency use robust baselines, comparable task mix, percentile distributions and a minimum sample. For strict accounting/security invariants alert immediately with exact records. Evaluate each detector on historical replay and adversarial synthetic cases before production notifications.

### 7.5 Recommendation ranking

Rank mandatory security/accounting incidents ahead of commercial opportunities. For commercial items show a transparent prioritization vector: evidence strength, expected contribution range, number of affected workspaces, urgency, effort, risk and dependencies. A scalar priority score may be a sorting aid, but never hide the inputs or pretend the score is revenue.

Suggested scenario equation: `eligible opportunities × assumed absolute outcome change × contribution per outcome − implementation cost − ongoing operating cost`. Label each input measured, estimated or unknown; show low/base/high scenarios. Do not count “MRR at risk” as money already lost or recommendations as money already earned.

### 7.6 Decision lifecycle

`detected → investigating → proposed → approved/rejected/snoozed → executing → verification_pending → measuring → validated/inconclusive/invalidated → closed`

Rejected and snoozed items retain reasons and recurrence rules. If target versions change, approval expires and the item returns for review. A technical fix can pass its checks while its business impact remains inconclusive. Keep those two completion states separate.

### 7.7 Noise and cost controls

One incident can link many symptoms and support tickets. Default to one initial alert, escalation only on severity/scope changes, and one resolution notice. Noncritical alerts respect quiet hours and digest preferences. Acknowledgment stops reminders but does not resolve the underlying condition. A watchdog warns if detectors or ingestion silently stop.

Do not ask an LLM to reread the whole business every minute. Run deterministic projections/detectors, summarize only meaningful deltas, reuse evidence within its freshness window and cap investigation depth/tool calls. Initial candidate limits: ten tool calls per automatic investigation, two model calls before escalation, ten-minute wall-clock limit, and an explicit money ceiling. These settings require qualification and budget approval.

## 8. Revenue and performance improvement playbooks

### 8.1 Prioritization

Start with money and value already close to being earned: fix preventable checkout/access problems, recover eligible failed invoices, reduce failed task waste, and help users reach first value. Only then optimize plan packaging, upsells or acquisition spend. A complex pricing experiment will not repair a broken signup flow.

### 8.2 Playbook catalog

| Playbook | Required evidence | Proposed intervention | Measure success | Guardrails |
|---|---|---|---|---|
| Recover failed recurring payments | Eligible failed invoices, current retry/method state | Use Stripe recovery and a reviewed billing reminder | Actual recovered collections; retained paid cohort | No duplicate retry engine; no hard-decline bypass [S07] |
| Repair activation friction | Mature signup-to-value funnel and failure traces | Fix dominant blocked step; contextual help | Activation and time-to-value | Error rate, support burden, user control |
| Reduce avoidable AI waste | Failed/abandoned/duplicate request cost, task mix | Fix retry/cancellation; evaluate cheaper route | Cost per successful useful task | Quality, latency, privacy and approved providers |
| Retain users with unresolved friction | Tickets, recurring errors, missed return | Resolve defect; reviewed helpful outreach | Return/useful outcomes and retention | No spam, no false “personalized” claims |
| Improve plan fit | Sustained legitimate usage, actual entitlements | Clear suitable plan/annual option | Incremental contribution and retention | No forced upgrade or hidden cancellation |
| Optimize credit economics | Grants/use/expiry/debt and provider costs | Simulate policy and package scenarios | Margin coverage and satisfaction | Existing purchases and promises honored |
| Scale effective acquisition | Tagged source cohorts and attributable spend | Test a bounded campaign/landing change | Mature paid conversion and CAC | Spend cap; unknown attribution preserved |
| Reduce support load | Repeated topic clusters and verified answers | Improve product copy/help or fix defect | Fewer repeat tickets; resolution time | No premature automation of sensitive cases |
| Improve content-to-business conversion | Rafii's own approved campaign analytics and tagged journeys | Create a reviewed campaign brief in James's workspace | Leads/trials/payments with attribution limits | No customer data in marketing or automatic publish |
| Remove risky release friction | Repeated build/CI failures and time spent | Fix flaky infrastructure/check gaps | Reliable checks and shorter safe lead time | Never weaken tests just to make CI green |

### 8.3 Native payment recovery, not a second billing engine

Stripe Smart Retries can handle eligible failed subscription/invoice payments. Some failures require a new payment method and are not retryable. Its webhook/update state must be the reference for the next attempt. Rafii Control displays that state and proposes appropriate customer guidance. It does not charge the same invoice independently. [S07]

A payment recovery chart separates: failed amount; eligible for recovery; scheduled; customer action needed; recovered; and written off/canceled. Incremental impact from a new intervention requires a credible comparison; not every naturally recovered payment is credited to the admin copilot.

### 8.4 Experiments and causality

An experiment has a hypothesis, randomization unit, eligibility rule, exposure event, primary metric, guardrails, duration, stopping rule, minimum meaningful effect and analysis method. Randomize by workspace for collaborative workflows unless there is a justified alternative. Use intent-to-treat reporting, verify sample-ratio balance and track actual exposure separately.

For a one-founder early-stage SaaS, traffic may not support a decisive A/B test. Then the console should recommend interviews, usability observation, sequential limited rollouts or simple before/after descriptions with caveats, not declare a winner. Price/credit changes require commercial approval and cannot silently rewrite existing customer terms.

### 8.5 Outcome ledger

Record implementation effort/cost and observed outcome by decision. Separate technical success, estimated value, actual recovered cash, experiment-estimated incremental effect and unknown impact. Avoid double-counting the same retained customer across several recommendations. Show negative and inconclusive outcomes, not only “wins”. This ledger is the basis for improving recommendation quality.

## 9. Integration research and selection

The recommended starting stack is intentionally small: existing Rafii services, Stripe, Resend, Sentry, Vercel and GitHub; add explicit-event product analytics and independent synthetic monitoring where approved. Additional tools must solve a measured gap rather than make the console look sophisticated.

### 9.1 Integration decision matrix

| Integration | Decision | Purpose | Contract and constraints |
|---|---|---|---|
| Existing Supabase/PostgreSQL | Reuse | Authoritative app data, private control projections | Restricted roles/views; no service-role key in browser; RLS is not protection from BYPASSRLS [S10] |
| PostHog | Recommended addition | Product trends, funnels, retention and experiments | Explicit events; server-side Query API; autocapture/private replay disabled; entitlement and region review [S01,S02] |
| Existing Sentry | Reuse and qualify | Grouped errors, traces, release correlation | Organization Issues API with project filter; metadata minimization; actual SDK configuration check [S03] |
| Sentry Seer | Optional later | Evidence-assisted root cause and patch proposal | Only after source/data/budget approval; no auto-merge or production execution [S04] |
| Vercel observability/Drains | Reuse; Drains conditional | Deployment/log/trace evidence | Drains plan/cost/coverage check; authenticated intake; no claim of complete history without coverage [S05] |
| GitHub App + Actions | Core | Exact-SHA checks, PR evidence and approved patch workflow | Scoped installation permissions; separate read/write authority; trusted workflow manifest [S11,S12] |
| Stripe | Reuse | Collections, subscriptions, recovery, refund/dispute exceptions | Existing reconciler remains credit authority; mode/version/idempotency guards [S07,S08] |
| Resend | Reuse | Support email and delivery/bounce signals | Existing notification transport; verified webhook, suppression and inbound safeguards [S09] |
| Checkly | Recommended optional operations addition | Independent API/browser synthetic monitoring | Only benign synthetic flows; no real charge or public post; cost/region qualification [S13] |
| Langfuse | Conditional | Rich AI evaluation/trace workflow if native tools insufficient | Choose one supplemental AI observability system; no duplicate raw prompt storage [S15] |
| Google Search Console API | Optional growth addition | Organic acquisition pages/queries and search performance | Read-only verified site, aggregate data, source coverage limits [S14] |
| Recharts + TanStack Table | Reuse | Standard charts and data exploration | Already present; metadata-backed, accessible views [R06] |
| React Flow | Optional UI dependency | Service/entity relationships and investigation navigation | Relational edges first; lazy-load; not permission enforcement [S16] |
| Apache ECharts | Optional specialist renderer | Dense heatmaps or other proven visualization gaps | Add only after existing rendering is insufficient; no third default chart framework [S17] |
| Semgrep CE + pip-audit | Recommended CI candidates | Source security patterns and Python dependency advisories | Pinned engine/rules, sandboxed dependency resolution, findings not guarantees [S18,S19] |
| Lighthouse CI | Recommended CI candidate | Repeatable frontend performance regressions | Controlled environment and comparable baselines; not real-user uptime proof [S20] |

Do not introduce Mixpanel plus PostHog plus another behavioral analytics system, or Sentry plus a full observability suite plus several prompt-trace vendors, without a specific coverage gap. Defer a separate CRM, revenue BI vendor, warehouse, vector database and graph database initially. Exportable canonical records keep future migration possible.

### 9.2 Provider adapter interface

Every adapter declares `capabilities`, configuration readiness, credential scope, allowed environment, API/version, rate budget, cost model, data classification, retention, pagination strategy, last cursor, last success and last complete watermark. It supports bounded `pull`, verified `ingest`, `health`, `reconcile` and only explicitly authorized `execute` operations.

Handle 401/403 as configuration/authorization errors, 429 with provider retry guidance and bounded backoff, and 5xx/timeouts as potentially ambiguous. Retry read-only requests conservatively. For writes, recover by idempotency/provider lookup before replay. Never rotate credentials, broaden scopes or create a new vendor account automatically to make a failing adapter work.

### 9.3 PostHog implementation contract

Send allowlisted events such as signup completion, onboarding stage, first-value completion, feature interaction and experiment exposure. Server-authoritative financial/task outcome events retain their internal IDs so downstream analytics cannot duplicate them. Browser data explains UI behavior but is not the authority for payment or publishing success.

Use the server-side project Query API for approved analytics queries; do not expose a broad personal API key to the browser. The application metric registry controls which vendor query shapes are permitted. PostHog is a behavioral analysis engine, not the ledger. [S01,S02]

Disable autocapture/session replay in the founder console, billing/auth screens, customer conversation/draft/library views and support content by default. Optional, explicitly approved replay on nonsensitive UX routes must mask inputs/text, exclude network bodies, test redaction and document retention. A vendor's “mask inputs” default does not prove all private content is protected. Do not run AI replay analysis on private customer sessions without a separate purpose and consent/legal review.

### 9.4 Sentry and OpenTelemetry contract

Use grouped issues and normalized trace spans. The Sentry organization issues endpoint is the intended integration; the older project issues listing is deprecated. Store issue IDs, fingerprint, stack metadata, affected release and counts, not complete log bodies in every intelligence record. [S03]

Use OpenTelemetry concepts for traces, metrics and logs, with consistent service/resource names, environment, commit and opaque internal IDs. Redact before egress. Audit sampled coverage: not every request necessarily has a full trace. Do not set user email or prompt text as a high-cardinality span label. [S06]

A redaction processor removes authorization headers, cookies, tokens, passwords, signed URLs, private text and attachment payloads. Known error codes and source locations are preferred over raw exception strings. A developer may request grant-scoped evidence when necessary; the access is logged and expires.

### 9.5 Vercel log/trace ingestion contract

Where the account's plan supports it, Drains provide ongoing log/trace ingestion into a controlled receiver. Current documentation makes Drains a plan-dependent service and describes HTTP-based trace delivery, so this is not assumed free or universally available. [S05]

Fallback to bounded authenticated provider reads for investigations and maintain your own content-free domain events. The UI states the oldest available log time, retention, sampling and dropped-event indicators. If forwarding is unavailable, call coverage partial instead of silently making a “no errors” claim.

### 9.6 GitHub integration contract

Use a GitHub App scoped to the Rafii repository. A read installation reads contents, checks, Actions, PRs and issues as required. A separate narrowly authorized broker performs workflow dispatch or draft branch/PR creation. Installation tokens are short-lived and server-held. Verify exact permissions against current GitHub documentation during implementation. [S11]

Support runtime signals from webhook events such as check/workflow completion, PR changes and deployments, subject to the App's actual subscribed events. Validate signatures and repository installation before accepting a payload. No “run workflow” endpoint accepts arbitrary YAML, a shell string or an untrusted repository chosen by the model.

### 9.7 Integration onboarding and costs

Each tile has states: `not_configured`, `configured_unverified`, `read_verified`, `write_qualified`, `degraded`, `disabled`. Show required scopes, recent data coverage, last test, costs and owner. An API key existing is not readiness.

Before enabling any paid service, record approved vendor plan, recurring cost, event/GB/run/model unit cost, monthly ceiling, owner and deletion/export method. Exact account prices and quotas were not inspected, so this document does not promise a dollar total. Begin with zero billable background activity until the founder approves a budget; allow free/read-only configuration validation only where genuinely nonbillable.

## 10. Engineering intelligence: logs, bugs and codebase checks

### 10.1 Scope and completion language

Engineering Control combines runtime symptoms, exact source versions, reproducible checks, candidate patches and deployment evidence. It must distinguish **suspected issue**, **reproduced failure**, **candidate fix**, **checks passed**, **merged**, **deployed** and **production verified**. These are independent facts. A repository contains tests does not mean they ran. A green build is not a security certification. A deployment marked ready does not prove an authenticated customer journey works.

A code check is a bounded, auditable job on an immutable source snapshot. It is not the founder model running arbitrary commands on James's laptop. The quota-blocked remote computer is an optional development tool, not a production dependency.

### 10.2 Log-to-issue pipeline

1. Accept signed or authenticated telemetry from a known environment/service.
2. Normalize timestamp, release SHA, route, operation, error code, trace ID, provider and impact counters.
3. Redact secrets/private content before storage or model access.
4. Group by stable fingerprint, environment and relevant release context.
5. Correlate with existing incidents, failed jobs, billing holds and support tickets.
6. Create or update a single issue candidate with evidence and coverage.
7. Run deterministic diagnostics before requesting model interpretation.
8. Offer a bounded check, workaround or approved mitigation proposal.

A failed stack trace after a release is evidence of association, not proof that a particular changed line caused it. Conversely, insufficient user volume does not invalidate a clearly reproducible functional bug. Keep statistical and functional evidence distinct.

### 10.3 Engineering issue record

Fields: `issueId`, `fingerprint`, `environment`, `firstSeen`, `lastSeen`, `sourceIssueRefs`, `releaseRefs`, `affectedRoutes`, `affectedOperationTypes`, `distinctAffectedWorkspaces`, `sampleCoverage`, `severity`, `businessExposure`, `hypotheses`, `reproductionStatus`, `checkRunRefs`, `patchRefs`, `owner` and `state`.

Business exposure includes recorded failed tasks, impacted paid accounts and relevant invoice/credit exceptions. It is not automatically “revenue lost”. Customer-specific private content is excluded from broad issue summaries. Duplicate support tickets are linked so a single confirmed fix can drive individually reviewed replies.

### 10.4 Exact-SHA check contract

The request binds `repository`, `candidateSha`, `baseSha`, `trustedWorkflowId`, `workflowDefinitionSha`, `suiteId`, `manifestVersion`, `environment=disposable`, `allowedNetworkProfile`, `resourceBudget`, `artifactPolicy`, `requestId` and `approvalRef` where required.

Dispatch a trusted workflow definition with the candidate SHA as a validated input. The runner verifies checkout SHA and lockfile digest before running. Do not execute an attacker-controlled workflow from an untrusted branch with privileged secrets. Branch movement after approval cannot alter the candidate being checked. GitHub's warnings around `pull_request_target` and untrusted code apply directly here. [S12]

If an external workflow API does not return a run ID immediately, record `submitted_unconfirmed` and correlate using request ID and verified workflow/run metadata. Do not blindly resubmit because the HTTP response was lost. The UI says it is reconciling dispatch, not that it started successfully.

### 10.5 Proposed check suites

| Suite | Coverage | Execution | Evidence |
|---|---|---|---|
| `source-fast` | TypeScript, lint, format, focused deterministic tests | Exact SHA; no provider calls | Exit codes, diagnostics, versions, skipped counts |
| `domain-integrity` | Credits, payments, permissions, account lifecycle | Disposable PostgreSQL, synthetic identities/providers | Invariants and transaction/race tests |
| `browser-critical` | Sign-in boundaries, main app paths, founder routes, support | Production-mode build, Chromium and Linux WebKit | Screenshots/traces, assertions, accessibility findings |
| `security-static` | Dangerous data paths, dependency advisories, secret patterns | Pinned rule/scanner versions; isolated dependency resolution | SARIF/JSON, finding IDs, severity, reviewed exceptions |
| `performance` | Build size, page loading, selected user journeys | Stable runner/device profile and repeated samples | Baseline comparison, distribution and test environment |
| `release-contract` | Migration compatibility, flags, secrets, deployed/source mapping | Read-only preflight plus staging | Exact commit/environment receipt |
| `agent-regression` | Tool authorization, grounding, proposal verification, privacy | Synthetic golden set; models optional with approved budget | Per-case outcomes; no authority failures tolerated |
| `deep-nightly` | Expanded tests, drift, dependency freshness | Trusted default-branch schedule, capacity limits | Full receipt and partial/unknown coverage |

Reuse `web/package.json` commands and existing workflows where applicable; do not replace working test conventions for uniformity. The current browser workflow's synthetic provider policy and Linux WebKit path are good foundations. A `continue-on-error` startup or a skipped section must appear as unverified coverage, not be swallowed by a top-level workflow success. [R06,R07]

Static scanning detects patterns and known advisories, not every vulnerability. `pip-audit` may perform dependency resolution, so run it in an ephemeral environment with no production credentials. Use pinned lockfiles/hashes where possible. False positives can be waived only with a reason, expiry, reviewer and affected version; the agent cannot silently suppress them. [S18,S19]

### 10.6 Resource and runner safety

Use hosted or controlled disposable runners. Each has CPU/memory/disk/time ceilings, a unique workspace, no shared customer database, no founder browser profile, no keychain access and no persisted production credential. Dependency caches must not become a cross-job secret channel. Delete job working files after artifact policy completes.

Preflight free disk before a build. An `ENOSPC` result is `infrastructure_failed`, not `code_failed` and not passed. Retry only after the resource issue is addressed and with a bounded policy. Never clean unrelated worktrees, kill arbitrary processes or bypass host approval to finish a check.

Production smoke tests are read-only or use a specifically authorized synthetic/test account. Charges, public posts, outbound calls, user deletion and database migrations are separate gated tests. The CI suite cannot switch to live models because fixtures are unavailable.

### 10.7 Patch workflow

`issue → evidence review → reproduction → patch proposal → founder approval → isolated branch/worktree → tests → draft PR → independent review → release approval → deployment → production verification`

A patch job receives allowed paths, prohibited changes, target tests, exact base SHA and a definition of success. It cannot change billing policy, permissions, environment variables or migration activation unless those are explicitly included. It must add a regression test that fails before the fix when feasible. A test that only verifies implementation details is insufficient for a behavioral claim.

The patch author cannot approve its own production release. For James as sole human, require his separate review for merge/promotion; do not fake dual-human approval. A standing policy may later allow a narrow class of documented low-risk draft PRs, but never grants unrestricted auto-merge.

### 10.8 Check and patch receipts

Persist: request/job/run IDs; repository; input and checked SHA; workflow definition SHA; tool versions; dependency hashes; environment; start/end; commands by approved manifest ID; pass/fail/skipped/blocked counts; exit codes; artifact digests; network/provider usage; cost if known; redaction result; and final status.

The receipt is signed by a trusted broker or validated against provider metadata, not accepted because the coding model says “all tests passed”. Upload artifacts to private expiring storage; validate type and size. Reports generated by untrusted code are untrusted until the trusted runner associates them with its own execution metadata. Never execute an artifact to inspect it.

### 10.9 Release intelligence

Display the currently observed production deployment ID/SHA, reviewed candidate, required checks and schema compatibility. Recheck this immediately before approval, because concurrent Rafii work can move the base. Preserve rollback references and distinguish source rollback from database rollback. Disabling a faulty feature may be safer than reversing an additive schema.

No one-click “fix everything and deploy” button. A useful button is **Prepare verified repair plan**, followed by **Run bounded checks**, **Review patch**, and **Approve release**. Each action has current evidence and a clear boundary.

## 11. Customer, workspace and support operations

### 11.1 Customer and workspace 360

Customer 360 shows identity metadata, memberships, account controls, sessions, plan/billing state, credit position, usage, errors, tickets, consent and notification delivery. Workspace 360 shows owners/members, entitlements, channels, jobs/automations, safe storage/library metrics and relevant incidents. User and workspace are not interchangeable billing units.

Add an **Explain health** panel that lists observed signals and definitions. Do not show an unexplained 87/100 customer score. A useful label is “Needs attention: two blocked publishing jobs and an unanswered P1 ticket”; the underlying facts are clickable. Future predictive models must have calibration, drift monitoring, small-sample safeguards and meaningful explanations.

An account comparison view can show cohort benchmarks using allowed business metrics, not expose other customers' content or native-platform restricted data. Customer-facing analytics remain separate from the founder's cross-customer operating metrics.

### 11.2 Support intake and lifecycle

Accept in-app help, public contact, authenticated customer ticket replies, verified inbound email and founder-created cases. Preserve a separate product-support system; Rafii's social Inbox is not a support inbox.

States: `new`, `triage`, `in_progress`, `waiting_customer`, `waiting_engineering`, `waiting_provider`, `resolved`, `closed`. Add `spam` and `duplicate` terminal classifications with traceable links, not deletion of history. Public replies and internal notes remain distinct at the database, API and UI layers.

Track first response, next response, resolution and closure separately. Business hours, time zone, holidays and pause policies are versioned. Initial targets are internal operational goals until staffing and public commitments are approved. Waiting on customer may pause an appropriate clock; engineering work does not automatically pause it. A customer reply reopens or creates a linked follow-up according to a documented policy.

### 11.3 Intelligent support workflow

At intake, the assistant suggests category, severity and duplicate incident links using authorized metadata. It drafts a concise summary, reproduction steps and next diagnostic. The founder sees confidence limitations and can correct classification.

A public response requires a deliberate send action. The composer previews actual recipients, public/internal mode, locale, attachments and any financial/security statement. AI cannot promise a refund has completed, announce a root cause as confirmed or claim an SLA that does not exist. Delivery transitions are provider-backed; bounced messages remain visible for an alternative contact strategy.

Security and billing cases require identity verification independent of the email's From header. Email content cannot authorize a password/MFA/email change, credit grant or refund. Inbound HTML is sanitized; attachments use direct private upload/download with validation, malware handling where available and no executable previews.

### 11.4 Escalation and knowledge

A ticket can link to an incident, engineering issue, run, payment, refund or release. Escalation exports a minimal reproduction package and safe trace IDs. Private conversation/file content is attached only with appropriate scope/consent.

A confirmed resolution may produce a knowledge-article draft. Publication requires review, removal of personal details and verification against current product behavior. A resolved internal ticket is not automatically public documentation or training material.

### 11.5 Support access grants

The normal path requires a customer-authorized grant, tied to requester, operator, ticket, resources, field classes, purpose and expiry. Default maximum is 30 minutes for private content; the founder can request renewal, not extend invisibly. Revoke on customer request, scope change, account deletion or session revocation. Recheck on every sensitive read and export.

A founder reason alone is not customer consent. A separate exceptional security/legal investigation path must record the approved policy basis, necessity, proportional scope, authorizer, notice decision and audit. It is not the ordinary support workflow, and its legal/privacy basis requires qualified review before activation.

Never grant plaintext OAuth tokens, passwords, session tokens, card secrets or encryption keys. “View as customer” is a read-only configuration/permission simulation, not minting a user session. The grant does not permit publishing, payment changes or customer-agent memory edits.

## 12. Billing, credits and account controls retained and hardened

### 12.1 Billing operations

Ordinary customer payment-method, invoice and supported subscription-management tasks should use the verified Stripe Customer Portal flow. Founder operations focus on exceptions and explain the current provider state, customer entitlements and local reconciliation.

Refund preview shows original payment/currency, prior refunds, actual remaining refundable amount, requested amount, grant linkage, projected credit reversal/debt, subscription implications and notification. The command is bound to current provider/local versions, founder step-up, reason and idempotency key. Do not declare a pending provider refund complete. [S08]

Customer subscription changes and credit policies must come from approved commercial terms, not the admin assistant's preferred price. Display delinquency, cancellation-at-period-end, active entitlement grace, trial and explicit holds separately. A founder cancel action must not leave recurring charges active unintentionally, and a user ban does not itself define refund/cancellation policy.

### 12.2 Credit adjustments

Use existing credit-domain functions and append-only ledger semantics. Distinguish goodwill grant, service-incident compensation, billing correction, payment-linked refund reversal and debt reconciliation. No editable wallet balance, no deleting old ledger rows and no manual “mark payment paid”.

A reversal targets a specific grant or settlement relationship. Preview held/consumed/remaining credits and the consequence for new work. Refund/dispute handling remains payment-linked and idempotent; a founder should not perform a second independent reversal for an already reconciled provider event.

Prevent concurrent approval from spending or refunding against an obsolete preview. Use row/advisory locking in a consistent order, transaction version checks and business-key uniqueness. Retain a reference to the responsible admin action and ticket. Customer financial notifications reflect the committed result, never a speculative frontend state.

### 12.3 Account controls

Separate `security_lock`, `write_suspension`, `billing_hold`, `publishing_hold`, `ban` and `deletion_pending`. Each has scope, reason, policy version, start/end, creator, review date and linked case. The UI must explain what remains available, including appropriate support, billing and privacy paths.

Check controls not only at sign-in, but at request authorization, job claim and immediately before an external side effect. Revoke sessions/API tokens as appropriate and increment an authorization epoch so stale tokens and queued jobs cannot ignore the control. Restore only through a logged action that rechecks the current policy and affected work.

### 12.4 Deletion lifecycle

Preview owned workspaces, shared ownership, memberships, jobs, media, OAuth connections, subscriptions, credits and retained records. Confirm the target explicitly and require fresh step-up. Stop new side effects, revoke credentials through existing domain paths, delete permitted content/storage, reconcile identity deletion and keep a minimal receipt.

The existing account-deletion implementation is an integration point from v1, not a reason to wrap an unsafe general-purpose user-delete call. Revalidate its current source and financial foreign-key behavior before implementation. Do not cascade-delete accounting records that an approved retention policy requires; detach/pseudonymize retained billing identity and remove unnecessary personal/content fields. Actual retention periods are business/legal decisions.

Deletion must propagate to analytical projections, search, embeddings, support attachments where applicable, external analytics and exports. Backups expire under policy. A restore process reapplies deletion tombstones before serving restored data. Preserve content-free audit history where permitted without recreating a broad personal profile.

## 13. Authentication, authorization and execution policy

### 13.1 Founder identity

Use a server-controlled operator identity binding to the verified Supabase user UUID. No email suffix, first-user rule, browser flag or user-editable metadata grants authority. Require current operator status, permitted environment and AAL2 or a specifically reviewed equivalent assurance policy. Initially only James is configured; additional staff permissions remain explicit future roles.

The founder session is an opaque token hashed server-side, with a host-only secure HttpOnly cookie, 30-minute idle timeout and eight-hour absolute maximum as initial settings. Sensitive actions require a fresh proof within five minutes. Check revocation and authorization epoch on sensitive requests; do not rely solely on JWT expiration. [S10]

### 13.2 Passkeys and new host migration

Do not assume a passkey enrolled on the current Vercel hostname works on a new custom domain. Verify relying-party ID, allowed origins, account/provider support and recovery. Plan a founder-controlled re-enrollment/bootstrap flow using an already qualified factor. Passkey sign-in and the application's AAL2 policy are separate requirements until their assurance mapping is tested.

No shared admin identity. Break-glass access is a named, separately protected identity with limited duration, restricted actions, immediate independent alert and mandatory post-incident review. Recovery cannot consist of asking an AI agent to reveal a production secret from a laptop keychain.

### 13.3 Role and permission matrix

| Capability | Founder | Founder AI by default | Autonomous monitor | Future support staff | Engineering runner |
|---|---|---|---|---|---|
| Aggregate business metrics | Read | Bounded read | Approved detector read | No, unless explicitly granted | No |
| Customer safe metadata | Read with audit | Purpose-scoped read | Minimum fields | Assigned case scope | Synthetic/test data only |
| Private support content | Valid grant/exception | Same grant, no wider access | No | Valid assigned grant | Redacted reproduction package only |
| Prepare reply/refund/credit action | Yes | Draft proposal | No | Reply draft; financial proposal only | No |
| Send public support reply | Confirmed action | No direct send | Only future explicitly approved narrow policy | Scoped action | No |
| Execute refund/credit/account control | Fresh step-up and policy | Never direct | No | Disabled initially | No |
| Run approved code checks | Yes | Prepare request | Standing trusted-suite policy only | No | Execute exact manifest |
| Write patch/draft PR | Explicit approval | Prepare patch brief | Disabled initially | No | Approved isolated job |
| Merge/deploy/migrate | Separate release approval | Never direct | Disabled | No | Not in check/patch token |
| Change privileges or budgets | Explicit secured admin action | No | No | No | No |

### 13.4 Typed approvals

A proposal records action type, exact targets, canonical parameter digest, expected versions, environment, expiry, maximum money/credits, risk tier, evidence and required proof. Confirmation creates a single-use approval receipt bound to that digest and founder session. Replaying the receipt for another amount, user, environment, branch or action fails.

Risk tiers: R0 aggregate read; R1 sensitive metadata read; R2 reversible operational/internal action; R3 financial/security/external side effect; R4 destructive/bulk/release-critical action. Fresh authentication and confirmation are proportional, but server authorization applies at every tier. Read-only access can still be sensitive and is not automatically unlogged.

A standing policy permits only named action templates, explicit scopes, rate/spend ceilings and expiry. It is not a wildcard “autopilot”. The agent cannot edit that policy. High-risk actions remain human-gated in the initial release. For an approved standing check template, the gateway issues a single-use execution receipt identifying the standing policy and its limits. It must not falsely record an interactive human confirmation; the model never creates the receipt itself.

### 13.5 Database controls

Separate an analytical read role from the command executor. Grant only approved private views and functions. No browser Supabase service-role client. Views exposed to customer contexts must have correct security-invoker/tenant behavior; private control views must not be granted to ordinary authenticated users. Audit role grants as well as RLS policies. A service role that bypasses RLS is not made safe merely by FORCE RLS. [S10]

Where a privileged function is genuinely necessary, use a fixed search path, fully qualified names, explicit execute grants, validated typed parameters and no dynamic arbitrary SQL. The connection identity and application actor must both be checked. Do not trust an arbitrary session variable set by an untrusted client as proof of founder authorization.

## 14. Notifications, briefings and operating rhythm

### 14.1 Reuse with strict audience separation

Extend the existing notification event/planner/delivery modules. Reuse templates, recipient resolution, retry, dedupe and provider transports where safe. Founder-only events must route to explicitly configured operators, not workspace members. A customer notification preference must never route a private founder report to a customer. [R03,R04]

The current notification feature flag may disable the product notification service. Therefore critical founder alerting needs an independently configured control scheduler/heartbeat path while preserving common delivery code where feasible. Do not silently re-enable a customer feature flag to obtain founder alerts.

### 14.2 Brief content

**Daily:** data coverage; material business changes; active customer-impacting incidents; money/credit exceptions; new high-signal opportunities; engineering checks; and at most three recommended decisions. Each item links to a durable receipt, not an untraceable generated paragraph.

**Weekly:** mature retention and acquisition cohorts; contribution/cost review; outcomes of previous decisions; experiments; repeated support causes; operational risk; and proposed next work. Keep observed outcomes separate from scenarios.

James chooses delivery time and time zone in the portal. Daylight-saving transitions are tested and stored as local-time schedules with unique occurrence keys. Do not silently borrow an unrelated personal daily-review time from another project.

### 14.3 Alert transport

In-app is the durable record. Email and Web Push deliver short notifications with safe deep links. Lock-screen text contains no private customer names, balances or ticket bodies. Opening the link requires founder authentication and current authorization. No high-risk action can be approved by a push tap alone.

Initial critical alerts bypass quiet hours only by explicit founder policy. Noncritical signals consolidate into digests. SMS/phone escalation is optional and needs real transport qualification, consent, cost limits and rules; current source hooks do not prove a working device/channel. [R04]

### 14.4 Delivery integrity

Track queued, provider-accepted, delivered, failed, bounced, suppressed and unknown separately. An email send API returning success is not a read receipt. Web Push may not prove the founder saw it. Escalation should depend on acknowledgment in the control system, not a guessed delivery outcome.

First activation should silently baseline existing conditions to avoid notifying about months of historical issues. This matches the existing notification service's first-scan design. [R04]

## 15. Proposed data model and storage contracts

This section specifies new logical records. Names under `rafii_control` are proposed, not discovered production tables. During implementation, inventory existing support/control/analytics tables and extend compatible records instead of creating parallel sources of truth. Existing subscription, credit ledger, notification delivery and customer identity tables retain authority.

### 15.1 Common conventions

Use UUIDs for internal records, UTC timestamps, explicit environment, version integers and stable provider IDs. Currency amounts use integer minor units with currency metadata; credit amounts retain the existing millicredit convention. Avoid unbounded JSONB as a substitute for indexed query fields. JSON payloads are schema-validated and size-limited.

Every mutable control record has `version`, `created_at`, `updated_at` and appropriate actor/source references. Financial/action outcomes are append-only or state-transition logged. Use unique keys to prevent duplicate external effects. Deletable user records must not cascade into indiscriminate deletion of retained financial/audit evidence.

### 15.2 Logical tables

| Record | Required fields and types | Constraints / important indexes |
|---|---|---|
| `operators` | `user_id uuid`, `role text`, `status text`, `auth_epoch bigint`, `required_assurance text`, `environment text` | Unique user/environment; server-only writes; no self-enrollment |
| `sessions` | `id uuid`, `operator_id uuid`, `token_hash bytea`, `auth_epoch bigint`, `assurance text`, `created_at`, `last_seen_at`, `expires_at`, `revoked_at timestamptz` | Unique token hash; index operator/expiry; no raw token storage |
| `source_connections` | `id uuid`, `provider text`, `external_project_ref text`, `environment text`, `capability_manifest jsonb`, `secret_reference text`, `state text` | No secret value; unique provider/project/environment; safe readiness projections |
| `ingestion_cursors` | `connection_id uuid`, `stream text`, `cursor jsonb`, `event_watermark`, `last_success_at timestamptz`, `coverage jsonb` | Unique connection/stream; compare-and-swap cursor version |
| `events` | `id uuid`, `source text`, `source_event_id text`, `event_type text`, `schema_version int`, `event_time`, `received_at timestamptz`, `workspace_ref uuid nullable`, `classification text`, `payload jsonb` | Unique source/source_event/environment; indexes time/type/workspace; bounded payload |
| `entity_links` | `from_type text`, `from_id text`, `relation text`, `to_type text`, `to_id text`, `evidence_id uuid`, `link_kind text`, `valid_until timestamptz` | Unique typed relation/evidence; indexes both ends; no inferred identity merge |
| `metric_definitions` | `metric_id text`, `version int`, `grain text`, `unit text`, `dimensions jsonb`, `template_ref text`, `definition jsonb` | Unique metric/version; approved definition state; no model executable SQL |
| `metric_rollups` | `metric_id text`, `definition_version int`, `interval_start/end timestamptz`, `dimension_key text`, `value jsonb`, `quality jsonb`, `watermark timestamptz` | Unique metric/version/window/dimensions/environment; partition/index time as justified |
| `query_receipts` | `id uuid`, `operator_id uuid`, `query_digest text`, `query jsonb`, `source_versions jsonb`, `data_state text`, `counts jsonb`, `created_at timestamptz` | Private access; no full sensitive payload by default; index operator/time |
| `evidence` | `id uuid`, `source_type text`, `source_ref text`, `artifact_digest text nullable`, `classification text`, `scope jsonb`, `observed_at`, `expires_at timestamptz`, `retention_class text` | Authorized source resolution; signed-artifact access; no open public bucket |
| `detector_definitions` | `id text`, `version int`, `metric_versions jsonb`, `rule jsonb`, `minimum_sample int`, `baseline text`, `budget_ref uuid nullable` | Immutable published version; approved activation state |
| `detector_state` | `detector_id text`, `version int`, `scope_key text`, `last_run_at`, `last_complete_at timestamptz`, `state jsonb` | Unique detector/version/scope; lease/fencing token |
| `signals` | `id uuid`, `detector_ref text`, `dedupe_key text`, `severity text`, `evidence_ids uuid[]`, `state text`, `first_seen/last_seen timestamptz` | Unique active dedupe identity; index severity/state/last_seen |
| `incidents` | `id uuid`, `severity text`, `state text`, `title text`, `scope jsonb`, `commander uuid`, `timeline_ref uuid`, `resolved_at timestamptz nullable` | One incident can own many signals/tickets; transitions appended |
| `investigations` | `id uuid`, `goal text`, `principal_scope jsonb`, `evidence_ids uuid[]`, `state text`, `budget_id uuid`, `started_at/ended_at timestamptz` | Current permissions at every read; max tool/model/wall-clock budget |
| `recommendations` | `id uuid`, `investigation_id uuid`, `facts jsonb`, `hypotheses jsonb`, `action_preview jsonb`, `impact jsonb`, `measurement_plan jsonb`, `state text`, `expires_at timestamptz` | No execute authority; approved target digest separate; index state/priority |
| `approvals` | `id uuid`, `proposal_id uuid`, `operator_id uuid`, `session_ref uuid`, `action_digest text`, `environment text`, `proof_ref text`, `expires_at/consumed_at timestamptz` | Single-use; bound action/target/version/environment; no replay across proposals |
| `action_requests` | `id uuid`, `operation text`, `target jsonb`, `parameters_digest text`, `idempotency_key text`, `state text`, `approval_id uuid`, `provider_ref text nullable` | Unique actor/environment/idempotency; same key with different digest is conflict |
| `action_receipts` | `id uuid`, `action_id uuid`, `outcome text`, `verified_state jsonb`, `source_receipts jsonb`, `completed_at timestamptz`, `digest text` | Append-only; unknown outcome preserved; no inferred success |
| `experiments` | `id uuid`, `hypothesis text`, `unit text`, `eligibility_version text`, `assignment_version int`, `metrics jsonb`, `analysis_plan jsonb`, `state text` | Immutable running analysis plan; price changes separately approved |
| `experiment_exposures` | `experiment_id uuid`, `unit_id text`, `variant text`, `first_exposed_at timestamptz`, `event_id uuid` | Stable unit assignment; unique exposure key; deletion policy applied |
| `decision_outcomes` | `id uuid`, `recommendation_id uuid`, `technical_result text`, `business_result text`, `observed_effect jsonb`, `measurement_receipts jsonb`, `reviewed_at timestamptz` | Actual vs estimated impact explicit; overlap/double-count grouping |
| `engineering_jobs` | `id uuid`, `repository text`, `candidate_sha text`, `workflow_sha text`, `suite_id text`, `manifest_digest text`, `runner_ref text`, `state text` | Exact 40-hex SHA validation; unique request; no arbitrary command field |
| `engineering_receipts` | `job_id uuid`, `checked_sha text`, `environment jsonb`, `checks jsonb`, `artifacts jsonb`, `runner_attestation jsonb`, `cost jsonb` | Digest and provider metadata validation; required/skipped/unknown distinct |
| `ops_cost_entries` | `id uuid`, `provider text`, `external_usage_ref text`, `cost_center text`, `amount_minor bigint nullable`, `currency text`, `cost_state text`, `allocation jsonb` | Unique provider usage receipt; internal spend not customer charges |
| `audit_events` | `id uuid`, `actor_ref uuid`, `session_ref uuid`, `action text`, `target jsonb`, `risk_tier text`, `reason text`, `request_id uuid`, `result text`, `created_at timestamptz` | Append-only application grants; minimal safe before/after digests |

### 15.3 Support records

Retain or implement tickets, messages, state events, attachments, links and access grants. Message fields include author identity/type, `visibility=public|internal`, direction, body reference, locale, recipient list and provider delivery reference. Enforce visibility in queries and API responses, not only CSS. Attachment records store private object refs, validated media type, size, scan state and retention; no inline base64 uploads through a size-limited function route.

The Universal Library may eventually supply reusable attachment storage, but its current branch and successful build are not verified here. Use a narrow `AttachmentStorageAdapter`, not an assumption that an image-only legacy endpoint safely handles all support files.

### 15.4 Ledger integration

Reference current credit grants, reservations, settlements, purchases, refunds and disputes by immutable IDs. Do not mirror a mutable “admin balance”. The control data model holds action/evidence metadata; the existing domain transaction writes the ledger. An outbox event may update the admin view after commit without becoming a second financial effect.

For aggregate finance, use stable nonidentifying billing-party references where retention requires them. Keep the mapping to a deleted user's personal profile removable. Do not attach `ON DELETE CASCADE` from core user/workspace content to retained financial history without an explicitly reviewed retention policy.

### 15.5 Retention and export

Before production, approve a retention schedule per class: financial/audit, security, operational metadata, support content, attachments, model traces, analytics events, exports and backups. Set lifecycle jobs and deletion proofs. No exact legal retention duration is invented by this design.

Export requires purpose, allowed columns, fresh authorization and a bounded job. Downloads use short-lived, private signed URLs, and exports appear in audit. URLs are not embedded in push text or model prompts. CSV exports escape spreadsheet formula prefixes; JSON exports preserve types. Existing exports are deleted/expired when their policy requires it.

## 16. API and event tech pack

The companion `contracts/openapi.yaml` specifies the initial intelligence surface. It is a proposed OpenAPI 3.1 contract, not a complete replacement for all existing Rafii endpoints. Current consumer APIs retain their existing versions; the new control application uses `/api/control/v2`.

### 16.1 API groups

| Group | Initial operations | Behavior |
|---|---|---|
| Session | Read founder session, authenticate/step-up/logout via qualified auth adapter | Server-held credentials; no role supplied by client |
| Metrics | Query registry metrics; fetch query receipts | Bounded DSL; private/no-store responses |
| Dashboards | List/read/save versioned dashboard views | Chart templates reference metrics and receipts |
| Copilot | Create scoped conversation; submit turn; get run status | Async 202; state/evidence trace; no implied execution |
| Investigations | Create/read/cancel investigation | Cost/authorization rechecks; cancellation receipt |
| Recommendations | List/read; reject/snooze; prepare action | Versioned evidence and expiry |
| Approvals | Confirm exact proposal after fresh proof | Single-use action-bound receipt |
| Actions | Read request/status/verified receipt | Command Gateway owns execution; no broad run-command route |
| Engineering | Propose check/patch; submit approved job; get receipt | Exact-SHA manifest; qualified runner only |
| Customers/Workspaces | Safe search and 360 projections | Masked, logged, purpose-scoped |
| Support | Ticket/message/state/access-grant operations | Public/internal separation; user grant rules |
| Revenue | Read recovery/refund/credit exceptions and typed previews | Existing billing domain is source of truth |
| Health | Source readiness, heartbeat, detector lag, incident state | No secret exposure; unknown accurately represented |
| Audit | Paginated actor/action/target history | Export gated separately |

### 16.2 Response conventions

All responses include `requestId`, `environment`, `asOf`, `dataState` and relevant receipt links. A successful HTTP response does not automatically mean an external action completed. Long work returns `202` with a durable ID and status endpoint. A cancellation request can return `cancellation_requested`; actual completion/refund/provider cancellation is separately observed.

Error codes include `AUTH_REQUIRED`, `FOUNDER_REQUIRED`, `STEP_UP_REQUIRED`, `SCOPE_DENIED`, `STALE_PREVIEW`, `POLICY_CHANGED`, `BUDGET_EXCEEDED`, `SOURCE_UNAVAILABLE`, `RUNNER_NOT_CONNECTED`, `RATE_LIMITED`, `IDEMPOTENCY_CONFLICT`, `OUTCOME_UNKNOWN` and `VALIDATION_FAILED`. Error bodies contain safe messages and correlation IDs, not stack traces or secrets.

### 16.3 Concurrency and idempotency

POST operations that enqueue work or request external effects require a request/idempotency key. Same key and same canonical body returns the existing request; same key with a different body returns conflict. Idempotency spans client retries, worker retries and provider callbacks. Persist the business key longer than any provider's short deduplication window when needed for durable accounting.

Use version checks on editable recommendations, dashboard definitions and operator policies. Lock only the necessary rows, avoid holding database locks during external network calls, and reconcile uncertain outcomes instead of rolling back reality. Retry compensation is itself a typed, logged operation.

### 16.4 Event catalog

Representative proposed events: `control.source.stale`, `control.metric.window_completed`, `control.signal.detected`, `control.investigation.completed`, `control.recommendation.proposed`, `control.approval.granted`, `control.action.outcome_unknown`, `control.action.verified`, `control.engineering.check_completed`, `control.engineering.patch_ready`, `control.experiment.review_due`, `control.decision.outcome_recorded` and `control.heartbeat.missed`.

Consume existing authoritative events through adapters rather than rename every customer-domain event. Mark imported observations and historical backfills. Maintain a schema registry and contract tests between producers, projections, detectors and notification templates.

## 17. Security, privacy and abuse testing

### 17.1 Primary threats and controls

| Threat | Required defense | Verification |
|---|---|---|
| Customer upgrades themselves to founder | Server operator binding, distinct session/audience/tool registry | Customer token/metadata/name attack cases |
| Founder account compromise | Strong factors, session expiry/revocation, fresh action proof, independent alerts | Lost device/replay/recovery drills |
| Support/log/PR prompt injection | Untrusted evidence classes, no secret/tool authority, allowlisted adapters | Embedded instruction and exfiltration test corpus |
| Cross-tenant analytics leakage | Authenticated query service, restricted views, field-level scopes | Adversarial tenant IDs and dimension combinations |
| Service-role misuse | Separate roles and command boundary; no frontend secrets | Bundle scan, grants audit and direct API tests |
| Approval substitution or stale action | Exact digest, versions, environment, proof expiry and single-use receipt | Altered amount/target/SHA and replay tests |
| Duplicate payment/credit operation | Persistent business keys, existing reconciler and provider lookup | Duplicate/out-of-order/concurrent webhook fixtures |
| Untrusted code steals credentials | Disposable runner, no prod secrets, trusted workflow, restricted egress | Malicious PR/dependency/artifact scenarios |
| Insecure private telemetry | Redaction before egress, content-free default and retention | Canary secrets and private text must not appear downstream |
| Sensitive chart/export exfiltration | Classification enforcement, query/export limits and audit | Broad filter, CSV formula, signed URL and cache tests |
| Noisy or fabricated AI advice | Source receipts, deterministic numbers, uncertainty and evaluation | Golden questions and false-evidence adversarial cases |
| Monitoring silence | External heartbeat and stale source visibility | Stop worker/ingestion and verify independent alert |
| Private data resurrected after delete | Deletion epoch/tombstones, downstream deletion and restore process | Replay/import/backup-restore tests |

### 17.2 Account access and customer trust

The founder has strong operational authority, not an automatic legal right to use customer private content for any purpose. Use purpose limitation, minimum data, role separation and grant checks in the actual query paths. A privacy page promising narrow access must match the implementation. Do not represent a control as implemented until tested.

Session replay, prompt capture and AI summaries are data processing, not harmless “analytics”. Their configuration, storage location, subprocessors, retention and customer expectations need review. Regional availability and data residency must be validated for Rafii's actual customers; adding a US/EU analytics SDK does not establish availability inside mainland China.

### 17.3 Audit trustworthiness

Log founder reads of sensitive records, private grants, approvals, attempted prohibited actions, command outcomes, policy/budget changes, exports and code-runner jobs. Do not put private message text into audit. Append-only application permissions reduce accidental tampering but do not prevent a database superuser from changing history. For stronger assurance, export signed daily audit checkpoints to independent immutable storage under separate credentials when budget/compliance requires it.

## 18. Reliability, performance and operating costs

### 18.1 Initial engineering targets

These are proposed acceptance targets, not measured current performance: cached Command view server response p95 under one second; interactive metric queries under five seconds at the chosen representative dataset; event-to-critical-incident visibility within two minutes when the source delivers promptly; source/worker silence detected within two missed expected intervals; and revocation effective at the next protected request/side-effect check.

Define a representative test dataset and concurrency before signing off these targets. Store the test size and provider latency separately. Do not report local browser timing as worldwide user performance or claim a 99.9% uptime SLO has been achieved without operational evidence.

### 18.2 Resource budgets

Start with two bounded read/aggregation workers and one engineering job per repository, with queue priority for integrity/security work. Use leases and fencing so a retried worker cannot commit obsolete results. Each source adapter has a request budget; each model investigation reserves spend before dispatch and reconciles actual usage afterward. Unknown usage remains held/unknown until resolved.

Deduplicate equivalent active investigations, cache by metric version/scope/interval/watermark and cancel obsolete work. Never share a private query cache across principals or grants. Background model overhead is visible in an Operations Cost page and in the decision outcome ledger.

### 18.3 Degraded mode

If PostHog is unavailable, continue authoritative business/ledger reporting and label behavioral analytics unavailable. If Sentry is unavailable, retain internal error counters and existing evidence without claiming no new errors. If the model provider is down or budget is exhausted, deterministic metrics, alerts and manual operations still work. If the control database is down, the external health monitor and provider dashboards remain a documented recovery path.

### 18.4 Backup and disaster recovery

Define RPO/RTO based on the selected database/backup plan rather than inventing contractual numbers. Test restoration of control metadata, event cursors, approval/receipt history and audit references. Never replay external writes from a restored queue without reconciling idempotency/provider state. Test deletion tombstone reapplication and expired approval rejection after restore.

An action kill switch stops new privileged executions but preserves evidence ingestion, settlement reconciliation and audit. Separate switches exist for model investigations, engineering jobs, customer outreach and vendor integrations. Disabling the dashboard must not interrupt an already-authorized customer's billing settlement path.

## 19. Migration, rollout and implementation work packages

### 19.1 Before implementation

Recheck canonical branch SHA, worktrees, applicable AGENTS/CLAUDE instructions, source changes, migrations and deployment mapping. Do not modify/reset/stash the shared dirty Mac checkout. Use an isolated branch/worktree for future code changes. The snapshot in this document is a reference, not a promise the branch will remain unchanged.

Inventory any existing admin/support/analytics work and the Universal Library branch. Inventory provider accounts/scopes and exact sender/domain configuration without exposing secret values. Verify hosting/scheduler entitlements and data region decisions. Produce a current integration map before assigning migration numbers.

### 19.2 Work packages and exit gates

| Package | Deliverables | Dependencies | Exit gate |
|---|---|---|---|
| WP00 Baseline and integration map | Exact source/deployment evidence, existing modules, migration map, readiness inventory | None | No guessed current state; unresolved facts explicit |
| WP01 Founder control boundary | Separate app/project config, session, capabilities, CSRF, audit, private DB role | WP00 | Normal user/preview/forged metadata cannot access control |
| WP02 Event and metric contracts | Ingestion cursor, dedupe, registry, rollups, query receipts, quality states | WP01 | Golden financial/retention datasets match expected results |
| WP03 Read-only Command and workbenches | Command, Revenue, Product, Customers, system status, initial charts | WP02 | Every displayed value traceable; no invented placeholders |
| WP04 Founder Rafii copilot | Separate registry/context/memory, bounded metrics/evidence tools, charts/proposals | WP03 | Golden grounding/privacy tests; no forbidden execution |
| WP05 Monitors and decisions | Deterministic detectors, incident grouping, investigation budgets, daily/weekly briefs | WP02,WP04 | Historical replay, no first-run flood, silence detection |
| WP06 Engineering read/check mode | Sentry/GitHub/deployment links, trusted exact-SHA checks, receipts | WP01,WP02 | Untrusted PR cannot reach prod; partial checks not green |
| WP07 Support and reversible controls | Tickets, reply delivery, grants, safe diagnostics, session/security controls | WP01,WP03 | Public/internal separation and revocation E2E |
| WP08 Revenue operations | Recovery visibility, refund/credit previews and approved actions | WP02,WP07 | Stripe sandbox/replay/concurrency and ledger integrity |
| WP09 Growth experiments and outcomes | Playbooks, eligibility/exposure, outcome ledger, contribution review | WP03,WP05 | Honest attribution and inconclusive results supported |
| WP10 Controlled patch integration | Qualified coding adapter, isolated patch job, draft PR evidence | WP06 | Regression proof and separate merge/release approval |
| WP11 Destructive lifecycle and resilience | Deletion/retention, restore, break glass, independent alerts | WP07,WP08 | Disposable deletion/restore and outage drill evidence |

Do not wait until WP11 to obtain value. WP03–WP06 should already answer business questions, detect problems and generate safe next actions. The later gates expand authority, not basic visibility.

### 19.3 Additive migration sequence

Logical sequence: operator/audit boundary; source/evidence registry; metrics/projections; decisions/investigations; engineering jobs; support/grants if absent; approvals/commands; experiments/outcomes; retention/integrity hardening. Choose actual unique filenames only after inspecting the live repo's migration ledger. Avoid renumbering unrelated migrations.

Run migrations on a disposable database and staging first. Backfill projections in bounded batches with progress, checkpoints and no customer alert fan-out. Compare the new financial read model against existing ledger/provider fixtures before any production financial view is labeled reconciled. Default all new actions/detectors/model jobs off. Parse configuration booleans explicitly, reject unknown values, and test that a string such as `0` does not become truthy activation.

### 19.4 Repo/module mapping

**Verified reuse anchors:** `src/postriff_phase2/agent_runtime_v2/contracts.py`, `src/postriff_phase2/notifications/{__init__.py,service.py}`, `src/postriff_phase2/growth/jev.py`, `web/package.json`, `.github/workflows/rafii-browser.yml`. [R02–R07]

**Known v1 anchors requiring current revalidation:** `hosted.py`, `hosted_app.py`, `billing.py`, `billing_stripe.py`, `credit_wallet.py`, `credit_purchases.py`, `account_deletion.py`, `operational_signals.py`, `scripts/ops_health_report.py`, customer auth/session helpers, `vercel.json` and Rafii CSS/UI primitives.

**Proposed new modules:** `control-web/` for the separate Next application; `src/rafii_control/` with `auth`, `queries`, `metrics`, `events`, `evidence`, `detectors`, `investigations`, `recommendations`, `actions`, `engineering` and `integrations`; `tests/control/`; and control-specific deployment/worker configuration. The folder names are proposals and should adapt to the current repo's packaging without an unrelated monorepo rewrite.

Extract genuinely reusable pure contracts/UI tokens into a small versioned shared package only if required. Do not copy the entire customer runtime into the control project or refactor every frontend as part of this work. The founder registry can use compatible abstractions while keeping its principal and storage distinct.

### 19.5 Release gates

Required: identity/capability tests; query/financial golden tests; no secret/private-content egress; source quality states; code-runner sandbox tests; approval replay tests; customer-agent boundary tests; notification audience tests; browser/accessibility journeys; source/deployment mapping; rollback and restore evidence. Financial, destructive and external-message actions additionally require their specific sandbox and human approval gates.

Roll out to the single founder identity first. Start with synthetic staging, then production read-only and shadow detectors, then founder-approved briefings, then bounded checks, then narrowly scoped writes. A successful shadow detector does not activate notifications, and a passing sandbox refund test does not authorize live refunds.

### 19.6 Rollback

Disable new execution routes first, then model investigations/automatic outreach if necessary. Retain read-only evidence and continue existing payment/credit settlement. Restore the prior control deployment without rolling back the customer app unless that is independently necessary. Retain additive schemas, audit and financial records; do not DROP history to make an older UI work.

If a projection is wrong, mark affected metrics unavailable, rebuild from authoritative events and issue correction records. If a recommendation caused harm, record the outcome and evaluate the compensating action through the same authority controls. Do not delete the failed recommendation to improve the apparent success rate.

## 20. Acceptance, evaluation and evidence requirements

### 20.1 End-to-end founder acceptance journey

James signs into the separate portal with the required assurance. He sees current source coverage and business numbers with definitions. He asks Rafii why a metric changed; it returns reproducible calculations, source links and bounded hypotheses. He opens the related error, requests a code check on an exact SHA, and sees a trusted receipt with both passed and unverified sections.

He then reviews a support ticket, grants only authorized private access, sends a deliberate reply and sees its delivery state. In staging he reviews a partial refund/credit adjustment, confirms it with fresh proof, and sees the existing reconciler settle once. He suspends a synthetic user and verifies queued side effects honor the new control. Finally, he reviews a decision whose technical fix succeeded but business effect is inconclusive. Every step has an audit trail.

### 20.2 Golden datasets and adversarial evaluations

Create fixed datasets for annual versus monthly MRR; one-time top-ups; partial/pending/failed refunds; dispute withdrawal/reinstatement; credits consumed before reversal; concurrent grant/spend; multiple currencies; deleted users; duplicated/out-of-order events; incomplete intervals; immature retention cohorts; sample accounts; unknown costs; late webhooks; and source outages.

Create founder questions with expected metric queries and answer constraints. Include incorrect premises, ambiguous periods, misleading logs, malicious email instructions, false PR claims and stale approvals. Deterministic validators compare returned numbers and source IDs to expected results. Model grading may supplement language quality but cannot override wrong arithmetic, unauthorized access or fabricated verification.

### 20.3 Minimum acceptance classes

The companion acceptance matrix enumerates concrete cases. Required financial/security invariants must all pass; no averaged overall score may conceal one. For AI grounding, report per-task exactness, correct abstention, evidence support, unsafe action attempts, latency and cost. For detectors, report precision/recall where labeled data exists and honest sample counts otherwise. Calibrate commercial ranking with actual outcome review rather than claiming it is intelligent because it is generated by an LLM.

A required check that was not run is `not_run`, not passed. A vendor integration that is not configured is `unavailable`, not empty success. A scanner with no entitlement is `not_applicable` only after the scope decision is documented; the associated risk still needs an alternative control when required.

### 20.4 Product success measures

Measure: time to identify a material issue; time from issue to an evidence-backed decision; founder time spent gathering context; recommendation acceptance/rejection reasons; verified issue resolution; false/noisy alert burden; recovered collections; cost per useful successful task; support response/resolution; and experiment outcomes. Do not sum hypothetical opportunity value into realized income.

## 21. Open decisions, defaults and hard stops

| Decision | Proposed default | Activation requirement |
|---|---|---|
| Primary domain | `ops.<verified existing Rafii domain>` | Confirm ownership, DNS, TLS, identity/RP origins |
| Deployment | Separate `rafii-control` project, same repository | Approved creation/configuration and staging separation |
| Founder's identity | One server-bound verified user UUID | Identity verified without printing secrets |
| Behavior analytics | PostHog explicit events only | Account/region/plan/purpose approved |
| Replay | Off for private/admin routes | Separate scoped consent/privacy review for any exception |
| Monitoring budget | No billable unattended calls | Explicit provider and monthly/per-run ceilings |
| Financial terms | Preserve current approved terms | Confirm current pricing/credits/refund policy before changes |
| Support hours/SLA | Internal targets only | Founder staffing and public policy decision |
| Data retention | Per-class schedule required | Legal/business approval and tested deletion jobs |
| Auto external actions | Off | Narrow versioned standing policy, qualification and audit |
| Code checking | Trusted isolated workflow | Exact manifests, no prod secrets, runner receipt verification |
| Code patches | Draft/approval only | Qualified adapter and explicit allowed path/scope approval |
| Merge/deploy/migrate | Separate human release approval | Exact source, checks, environment and rollback evidence |
| Existing JEV/model route | Reuse only if qualified | Current capability, cost and data-policy validation |

Missing business facts do not prevent building a synthetic/read-only prototype. They do prevent activating paid processing, financial policies or production authority that depends on them.

## 22. Delivery package and handoff

The package includes the master specification, a self-contained HTML reader, source register, metric and dashboard catalogs, detector rules, action/permission policy, proposed OpenAPI and JSON Schemas, synthetic examples, acceptance cases, validation script and its results. Synthetic examples are explicitly labeled and must never populate production analytics.

Suggested future repo destination: `docs/superpowers/specs/2026-09-29-rafii-control-v2/`. This review did not save the package to the Mac because the remote connector was quota-blocked. The downloadable package is the actual deliverable; the suggested path is not a completed write-back.

**Implementation handoff:** Read this document and contracts. Recheck the canonical repository and deployment. Inventory existing implementations before creating new tables/modules. Work in isolation. Begin with WP00–WP03 and preserve all customer/runtime accounting boundaries. Run synthetic tests first. Report exact checked SHA, passed/failed/skipped counts, artifacts and unresolved gates. Do not infer permission to provision, charge, send, publish, merge, deploy or migrate from this design document.

## 23. Bottom-line design decision

Rafii Control v2 should act like a founder's analyst and operating console, not an unsupervised administrator. Its intelligence comes from trustworthy connected data, disciplined investigation, explicit decisions and measured outcomes. Its “empire” view is a coherent model of the business, not an unrestricted database or a collection of unrelated dashboards.

The first useful release should help James answer: **What changed? Who is affected? What is the evidence? What should I do? What will it cost? Did it work?** Everything else should earn its place by improving those answers.


# Appendix A. Detailed metric registry

These definitions are proposed v1 metric contracts for Control v2. They are not existing live values. All require data state, scope, version and evidence receipt. Exact implementation templates are to be written and tested, not model-generated SQL.

## paid_workspaces: Paying workspaces

**Grain:** workspace snapshot. **Unit:** count. **Dimensions:** plan, currency.

Distinct non-test workspaces with positive recurring value in the normalized healthy_paid subscription state at asOf; delinquent, trial and one-time-purchase-only workspaces are separate cohorts.

**Source:** billing projection. **Limitations:** healthy_paid requires provider/entitlement reconciliation under a versioned status policy. Do not silently include one-time credit purchasers.

## mrr: Healthy recurring MRR

**Grain:** subscription snapshot. **Unit:** currency_minor. **Dimensions:** plan, currency.

Sum approved recurring net subscription amounts normalized to one month, excluding tax, trials and top-ups; healthy status policy fixed.

**Source:** subscription terms + Stripe state. **Limitations:** Annual/12; multi-currency separate; do not equate to collections or recognized revenue.

## delinquent_mrr: Delinquent contracted MRR

**Grain:** subscription snapshot. **Unit:** currency_minor. **Dimensions:** plan, currency.

Recurring contracted value for delinquent subscriptions under the chosen policy, separate from healthy MRR.

**Source:** subscription projection. **Limitations:** Grace and canceled states are versioned, never silently blended.

## mrr_new: New MRR

**Grain:** workspace interval. **Unit:** currency_minor. **Dimensions:** plan, currency, source.

First paid recurring MRR created in interval from previously nonpaying workspaces.

**Source:** subscription transitions. **Limitations:** Reactivation is separate, not new acquisition.

## mrr_expansion: Expansion MRR

**Grain:** workspace interval. **Unit:** currency_minor. **Dimensions:** plan, currency.

Positive recurring value change in opening paid cohort, excluding reactivation/new workspaces.

**Source:** subscription transitions. **Limitations:** Normalize currency/discount policy consistently.

## mrr_contraction: Contraction MRR

**Grain:** workspace interval. **Unit:** currency_minor. **Dimensions:** plan, currency.

Absolute recurring value decreases in retained members of opening paid cohort.

**Source:** subscription transitions. **Limitations:** Full churn excluded to avoid double count.

## mrr_churn: Churned MRR

**Grain:** workspace interval. **Unit:** currency_minor. **Dimensions:** plan, currency.

Opening recurring value lost when qualifying paid relationship ends under fixed policy.

**Source:** subscription transitions. **Limitations:** Cancellation intent is not automatically effective churn.

## collections: Successful collections

**Grain:** payment event. **Unit:** currency_minor. **Dimensions:** currency, payment_type.

Sum captured successful payment amounts by event time and native currency.

**Source:** verified payments. **Limitations:** Exclude authorizations/unpaid invoices; taxes shown separately for net-revenue analysis.

## refunds: Succeeded refunds

**Grain:** refund event. **Unit:** currency_minor. **Dimensions:** currency, reason.

Sum succeeded refund amounts, deduplicated by refund ID.

**Source:** existing reconciler + provider. **Limitations:** Pending/failed refunds are not succeeded refunds.

## dispute_net: Net dispute withdrawals

**Grain:** funds movement. **Unit:** currency_minor. **Dimensions:** currency, status.

Withdrawn dispute funds minus reinstated funds; reconcile overlapping refunds.

**Source:** provider dispute funds events. **Limitations:** No double counting when refund and dispute affect the same underlying amount.

## net_collections: Net collections

**Grain:** payment interval. **Unit:** currency_minor. **Dimensions:** currency, payment_type.

Successful collections minus succeeded refunds minus net dispute withdrawals, with reconciliation of overlaps.

**Source:** payment projection. **Limitations:** Payouts and fees separate; cash basis, not recognized revenue.

## recovery_rate: Eligible invoice recovery rate

**Grain:** invoice cohort. **Unit:** ratio. **Dimensions:** plan, currency.

Recovered eligible failed invoices / eligible failed invoices whose fixed recovery window has matured.

**Source:** invoice state + retry evidence. **Limitations:** Show amount-weighted and count-based separately; spontaneous recovery is not automatically incremental impact.

## nrr: Net revenue retention

**Grain:** opening paid cohort. **Unit:** ratio. **Dimensions:** cohort, plan, currency.

(Opening MRR + expansion - contraction - churn) / opening MRR for the same cohort/currency.

**Source:** subscription transitions. **Limitations:** Exclude new customer MRR; zero denominator unavailable.

## grr: Gross revenue retention

**Grain:** opening paid cohort. **Unit:** ratio. **Dimensions:** cohort, plan, currency.

(Opening MRR - contraction - churn) / opening MRR.

**Source:** subscription transitions. **Limitations:** No expansion; consistent status policy required.

## logo_churn: Paid workspace churn

**Grain:** opening paid cohort. **Unit:** ratio. **Dimensions:** cohort, plan.

Opening paid workspaces that end paid service / opening paid workspaces.

**Source:** subscription transitions. **Limitations:** Do not substitute user inactivity or account deletion for billing churn.

## contribution: Estimated contribution

**Grain:** period + currency. **Unit:** currency_minor. **Dimensions:** plan, currency, cost_center.

Approved period-consistent revenue basis minus attributable operating costs with cost completeness metadata.

**Source:** billing + ops cost ledger. **Limitations:** Label cash contribution when recognition absent; unallocated overhead explicit.

## cost_coverage: Provider cost coverage

**Grain:** provider attempt. **Unit:** ratio. **Dimensions:** provider, model, task_type.

Attempts with verified actual cost / all billable or potentially billable attempts.

**Source:** usage receipts. **Limitations:** Missing/unknown attempts in denominator; never silently zero.

## active_users: Active users

**Grain:** user interval. **Unit:** count. **Dimensions:** cohort, plan, locale.

Distinct non-test users with a specified meaningful application event in the interval.

**Source:** authoritative events. **Limitations:** Event definition versioned; a pageview-only DAU is a different metric.

## active_workspaces: Active workspaces

**Grain:** workspace interval. **Unit:** count. **Dimensions:** plan, cohort.

Distinct non-test workspaces with a meaningful completed outcome in interval.

**Source:** authoritative events. **Limitations:** A user belonging to several workspaces must not collapse workspace grain.

## activation_rate: Activation rate

**Grain:** signup cohort. **Unit:** ratio. **Dimensions:** source, locale, device, cohort.

Eligible new workspaces with first-value event within 7 days / eligible workspaces whose 7-day window matured.

**Source:** signup + first-value events. **Limitations:** 7-day window proposed; user-confirmed usefulness and proxies must not be mixed.

## time_to_value: Time to first value

**Grain:** activated workspace. **Unit:** seconds_distribution. **Dimensions:** source, locale, device.

Distribution of first-value event time minus verified signup time.

**Source:** signup + first-value events. **Limitations:** Report censored/nonactivated separately; median among completers is not all-user experience.

## retention_d7: D7 first-value return

**Grain:** mature first-value cohort. **Unit:** ratio. **Dimensions:** cohort, plan, source.

Workspaces with meaningful return in [day7,day8) / first-value workspaces observed through day8.

**Source:** authoritative events. **Limitations:** Reporting-day convention fixed; immature workspaces excluded.

## retention_d28: D28 first-value return

**Grain:** mature first-value cohort. **Unit:** ratio. **Dimensions:** cohort, plan, source.

Workspaces with meaningful return in [day28,day29) / eligible mature first-value workspaces.

**Source:** authoritative events. **Limitations:** No forecast disguised as observed retention.

## feature_adoption: Feature adoption

**Grain:** eligible active workspace. **Unit:** ratio. **Dimensions:** feature, plan, cohort.

Active eligible workspaces completing the feature event / active workspaces eligible to use that feature.

**Source:** events + entitlements. **Limitations:** Eligibility matters; correlations with retention are not causal effects.

## task_success: Task completion rate

**Grain:** started task. **Unit:** ratio. **Dimensions:** task_type, model, provider, release.

Successfully completed authoritative tasks / started tasks with terminal observation window elapsed.

**Source:** task lifecycle. **Limitations:** Canceled/unknown states shown separately; retries not counted as new user tasks.

## publish_verified: Verified publication rate

**Grain:** approved eligible publication. **Unit:** ratio. **Dimensions:** platform, release.

Verified external publications / eligible approved publications whose observation window elapsed.

**Source:** publishing receipts. **Limitations:** Submitted/approved/confirming is not verified live.

## useful_outcomes: Useful completed outcomes

**Grain:** workspace task. **Unit:** count. **Dimensions:** task_type, plan, cohort.

Distinct completed tasks explicitly rated useful; proxy-confirmed outputs reported in separate series.

**Source:** task receipts + user feedback. **Limitations:** Missing feedback is not negative or positive feedback.

## automation_success: Automation occurrence success

**Grain:** occurrence. **Unit:** ratio. **Dimensions:** workflow_type, provider.

Verified successful occurrences / eligible due occurrences with observation window elapsed.

**Source:** automation lifecycle. **Limitations:** Skipped, held and paused distinguished from failures.

## ai_actual_cost: Observed AI provider cost

**Grain:** provider attempt. **Unit:** currency_minor. **Dimensions:** model, provider, task_type.

Sum known actual provider receipt cost, preserving source currency and cost state.

**Source:** provider usage receipts. **Limitations:** Estimated and unknown costs separate; no client-supplied prices.

## ai_failed_cost: Absorbed failed-task cost

**Grain:** provider attempt. **Unit:** currency_minor. **Dimensions:** model, provider, task_type.

Known actual provider costs assigned to failed/nonbillable user outcomes.

**Source:** usage + task receipts. **Limitations:** Shows platform cost, not automatically refundable customer charges.

## cost_per_useful: Cost per useful task

**Grain:** task cohort. **Unit:** currency_minor_per_outcome. **Dimensions:** task_type, model, provider.

Attributed cost in completed useful-task cohort / useful outcomes in the same cohort.

**Source:** usage + outcome linkage. **Limitations:** Coverage and selection bias must be shown; no zero division.

## ai_quality: Evaluation pass rate

**Grain:** evaluation case. **Unit:** ratio. **Dimensions:** model, task_type, rubric_version.

Cases passing declared quality/correctness rubric / evaluated cases in comparable suite.

**Source:** evaluation receipts. **Limitations:** Synthetic, human and production feedback separate; no LLM grade as security proof.

## ai_latency: AI attempt latency

**Grain:** provider attempt. **Unit:** seconds_distribution. **Dimensions:** model, provider, task_type.

Distribution of request dispatch to completion/failure under a fixed timeout/cancel policy.

**Source:** trace metadata. **Limitations:** Streaming first-token and total latency are distinct.

## task_latency: End-to-end task latency

**Grain:** user task. **Unit:** seconds_distribution. **Dimensions:** task_type, device, release.

Distribution of task accepted to verified terminal result.

**Source:** task lifecycle. **Limitations:** Do not average provider p95s to infer task p95.

## credit_grants: Credits granted

**Grain:** ledger grant. **Unit:** millicredits. **Dimensions:** grant_source, plan.

Sum immutable grant events by approved source and period.

**Source:** credit ledger. **Limitations:** Goodwill, subscription and purchased credits shown separately; not revenue.

## credit_consumption: Credits consumed

**Grain:** ledger settlement. **Unit:** millicredits. **Dimensions:** task_type, plan.

Sum settled consumed credits by terminal task outcome.

**Source:** credit ledger. **Limitations:** Reservation is not consumption.

## credit_available: Available credits

**Grain:** workspace snapshot. **Unit:** millicredits. **Dimensions:** plan.

Existing wallet projection after holds, expiry, reversals and debt.

**Source:** existing credit-domain projection. **Limitations:** Do not independently reimplement mutable balance logic.

## credit_held: Held credits

**Grain:** workspace snapshot. **Unit:** millicredits. **Dimensions:** task_type, age_band.

Outstanding reservations under current wallet/unknown settlement rules.

**Source:** credit ledger. **Limitations:** Unknown outcomes not silently released or charged twice.

## credit_debt: Credit debt

**Grain:** workspace snapshot. **Unit:** millicredits. **Dimensions:** plan, reason.

Current debt from valid reversals after consumption, as projected by existing wallet.

**Source:** existing credit-domain projection. **Limitations:** Debt is not automatically a cash receivable.

## api_errors: API server error rate

**Grain:** request interval. **Unit:** ratio. **Dimensions:** route, release, service.

Eligible 5xx/application-failure requests / eligible served requests.

**Source:** normalized request telemetry. **Limitations:** Expected client denials separate; sampled numerator and denominator compatible.

## api_latency: API latency

**Grain:** request. **Unit:** seconds_distribution. **Dimensions:** route, service, release.

Observed eligible request duration distribution.

**Source:** OTel/runtime metrics. **Limitations:** Sample/region/cache status included.

## queue_age: Queue age

**Grain:** pending job snapshot. **Unit:** seconds_distribution. **Dimensions:** job_type, provider.

Now minus eligible enqueue time for pending runnable jobs.

**Source:** job projection. **Limitations:** Paused/scheduled-future jobs excluded or separate.

## slo_burn: Error budget burn rate

**Grain:** service window. **Unit:** ratio. **Dimensions:** service, window.

Observed bad-event fraction / allowed bad-event fraction for approved SLO.

**Source:** SLO registry + telemetry. **Limitations:** Undefined until SLO and denominator approved; not measured uptime promise.

## affected_workspaces: Incident affected workspaces

**Grain:** incident. **Unit:** count. **Dimensions:** incident, severity.

Distinct workspaces with linked verified failing events.

**Source:** incident + task/error links. **Limitations:** Coverage-limited lower bound unless complete; not guessed customer count.

## source_lag: Source data lag

**Grain:** source stream. **Unit:** seconds. **Dimensions:** source, stream.

Now minus last complete source watermark.

**Source:** ingestion cursors. **Limitations:** Distinguish event silence from ingestion heartbeat failure.

## open_tickets: Open support tickets

**Grain:** ticket snapshot. **Unit:** count. **Dimensions:** priority, category, state.

Tickets not in resolved/closed/spam/duplicate, grouped by actual state.

**Source:** support records. **Limitations:** Waiting state remains visible; test tickets excluded.

## first_response: First human response time

**Grain:** responded ticket. **Unit:** business_seconds_distribution. **Dimensions:** priority, category.

First public human response minus creation excluding declared nonbusiness intervals.

**Source:** support events. **Limitations:** AI acknowledgment not human response; unanswered tickets shown censored/aged.

## resolution_time: Support resolution time

**Grain:** ticket lifecycle. **Unit:** business_seconds_distribution. **Dimensions:** priority, category.

Resolved time minus created time under versioned pause/business-time policy.

**Source:** support events. **Limitations:** Unresolved tickets not hidden; reopening policy fixed.

## csat: Positive CSAT

**Grain:** survey response. **Unit:** ratio. **Dimensions:** category, cohort.

Positive qualified responses / valid responses; response rate displayed alongside.

**Source:** support surveys. **Limitations:** No broad satisfaction claim from very low response sample.

## repeat_tickets: Repeat issue rate

**Grain:** resolved ticket cohort. **Unit:** ratio. **Dimensions:** category, release.

Resolved cases with same verified issue recurrence within 14 days / cases observed through 14 days.

**Source:** ticket links. **Limitations:** Similarity alone does not prove duplicate cause.

## required_checks: Required check coverage

**Grain:** candidate SHA. **Unit:** ratio. **Dimensions:** suite, repository.

Passed required checks / required checks; failed, skipped, blocked and not-run separately counted.

**Source:** trusted runner receipts. **Limitations:** Never averaged to override a single mandatory failed security/financial gate.

## check_failures: Check failures

**Grain:** runner check. **Unit:** count. **Dimensions:** suite, failure_class.

Count failures by functional, infrastructure, timeout, canceled or unknown classification.

**Source:** trusted runner receipts. **Limitations:** ENOSPC infrastructure failure is not a product bug.

## flake_rate: Test instability

**Grain:** repeated comparable test. **Unit:** ratio. **Dimensions:** suite, test_id.

Tests with mixed outcomes on unchanged code/environment / tests rerun under the declared policy.

**Source:** test receipts. **Limitations:** Rerun selection bias disclosed; flaky tests not simply ignored.

## security_open: Unresolved high-severity findings

**Grain:** finding snapshot. **Unit:** count. **Dimensions:** scanner, severity, age_band.

Distinct current high/critical findings not fixed or validly waived, by scanner/rule/version.

**Source:** scanner receipts. **Limitations:** Scanner coverage/entitlement explicit; no guarantee all vulnerabilities found.

## gsc_clicks: Organic search clicks

**Grain:** site/page/query interval. **Unit:** count. **Dimensions:** page, query, country, device.

Search Console reported clicks for authorized property and chosen dimensions.

**Source:** Search Console API. **Limitations:** Top-row/aggregation limits retained; no per-user attribution.

## gsc_ctr: Organic search CTR

**Grain:** site/page/query interval. **Unit:** ratio. **Dimensions:** page, query, country, device.

Reported clicks / impressions in exactly the same aggregate.

**Source:** Search Console API. **Limitations:** Average position is distinct; no averaged CTR across unequal denominators.

## attribution_coverage: Known acquisition source coverage

**Grain:** signup cohort. **Unit:** ratio. **Dimensions:** cohort.

New workspaces with recorded allowed acquisition source / all new workspaces.

**Source:** first-party source capture. **Limitations:** Unknown attribution is retained, not assigned to direct by default.

## source_paid_conversion: Source-to-paid conversion

**Grain:** source signup cohort. **Unit:** ratio. **Dimensions:** source, cohort.

Attributed workspaces becoming qualifying paid within 30 days / source workspaces observed through day30.

**Source:** signup + billing. **Limitations:** Proposed window; immature cohorts excluded.

## cac: Attributed acquisition cost

**Grain:** paid acquisition cohort. **Unit:** currency_minor_per_workspace. **Dimensions:** source, currency.

Approved attributable acquisition spend / new qualifying paying workspaces in compatible attribution window.

**Source:** campaign spend + billing. **Limitations:** Unavailable when spend or attribution incomplete; not blended with LTV projection.

## decision_recovered_cash: Observed recovery associated with decisions

**Grain:** decision/payment. **Unit:** currency_minor. **Dimensions:** playbook, currency.

Deduplicated actual recovered payment receipts linked to decisions, labeled associated unless incremental effect measured.

**Source:** decision outcomes + payments. **Limitations:** Avoid double credit across several recommendations.

## experiment_effect: Estimated experiment effect

**Grain:** experiment unit. **Unit:** effect_interval. **Dimensions:** experiment, variant.

Predeclared treatment-control difference with uncertainty under the approved analysis plan.

**Source:** exposures + outcome metrics. **Limitations:** Only if sample/assignment checks pass; otherwise inconclusive.

## time_back: Estimated time back

**Grain:** completed task. **Unit:** seconds_estimate. **Dimensions:** task_type, baseline_version.

Reuse approved baseline-minus-measured-effort methodology and version, if available and verified.

**Source:** existing time-saving receipts. **Limitations:** Not invented hours saved; unavailable until current source/definition verified.

## mrr_reactivation: Reactivated MRR

**Grain:** workspace interval. **Unit:** currency_minor. **Dimensions:** plan, currency, cohort.

Recurring value restored for a previously paid, fully churned workspace in the interval; not new MRR or opening-cohort expansion.

**Source:** subscription transitions. **Limitations:** Report reactivation separately in MRR bridge; opening paid-cohort NRR does not silently acquire returning churned accounts.

# Appendix B. Detailed visualization catalog

Not all views belong on the home screen. Show six essential cards first, then progressively expose the appropriate workbench. No visualization invents observations.

## command-kpis

**Workbench:** Command. **Question:** What is the current state of the business?

**Visual:** metric_strip. **Metric contracts:** paid_workspaces, mrr, net_collections, useful_outcomes, contribution, affected_workspaces.

**Drilldown and interpretation:** Open definition and query receipt; separate currencies and quality states.

## business-change-timeline

**Workbench:** Command. **Question:** What changed before the business metric moved?

**Visual:** annotated_timeline. **Metric contracts:** mrr, activation_rate, task_success.

**Drilldown and interpretation:** Link releases/incidents/campaigns; association is not causation.

## business-relationship-map

**Workbench:** Command. **Question:** How do customers, runs and systems connect?

**Visual:** entity_graph. **Metric contracts:** affected_workspaces, source_lag.

**Drilldown and interpretation:** Verified typed ID edges; dotted inferred links; authorized resources only.

## source-quality-matrix

**Workbench:** Command. **Question:** Which numbers can I trust right now?

**Visual:** status_matrix. **Metric contracts:** source_lag, cost_coverage, attribution_coverage.

**Drilldown and interpretation:** Open source watermarks, sampling and missing streams.

## mrr-bridge

**Workbench:** Revenue. **Question:** Why did recurring value change?

**Visual:** waterfall. **Metric contracts:** mrr, mrr_new, mrr_expansion, mrr_contraction, mrr_churn, mrr_reactivation.

**Drilldown and interpretation:** Opening/new/expansion/contraction/churn/reactivation reconciliation; no mixing cash.

## cash-waterfall

**Workbench:** Revenue. **Question:** Where did collected cash go?

**Visual:** waterfall. **Metric contracts:** collections, refunds, dispute_net, net_collections.

**Drilldown and interpretation:** Native currency; fees/taxes/payout transfers separately classified.

## recovery-funnel

**Workbench:** Revenue. **Question:** Which failed invoices remain recoverable?

**Visual:** funnel. **Metric contracts:** recovery_rate, collections.

**Drilldown and interpretation:** Invoice cohorts: eligible, scheduled, action-needed, recovered; source provider state.

## revenue-retention

**Workbench:** Revenue. **Question:** Is the opening paid cohort retaining value?

**Visual:** line. **Metric contracts:** nrr, grr.

**Drilldown and interpretation:** Fixed cohort, currency and policy; show base MRR.

## revenue-cohort-grid

**Workbench:** Revenue. **Question:** Which paying cohorts mature well?

**Visual:** heatmap. **Metric contracts:** mrr, nrr, logo_churn.

**Drilldown and interpretation:** Cohort-age alignment; immature cells blank.

## customer-concentration

**Workbench:** Revenue. **Question:** How concentrated is recurring value?

**Visual:** pareto. **Metric contracts:** mrr.

**Drilldown and interpretation:** Founder-only workspace contributions and cumulative share; no customer content.

## plan-economics

**Workbench:** Revenue. **Question:** Which plans cover their delivery costs?

**Visual:** matrix. **Metric contracts:** contribution, ai_actual_cost, cost_coverage.

**Drilldown and interpretation:** Per-plan compatible cost/revenue basis, incomplete coverage flagged.

## credit-lot-states

**Workbench:** Revenue. **Question:** What is available, held or owed?

**Visual:** stacked_bar. **Metric contracts:** credit_available, credit_held, credit_debt.

**Drilldown and interpretation:** Separate debt axis/state; existing wallet projection; not cash value.

## credit-flow

**Workbench:** Revenue. **Question:** How are credits granted and consumed?

**Visual:** flow. **Metric contracts:** credit_grants, credit_consumption.

**Drilldown and interpretation:** Source/expiry/settlement states; no assumption grants equal revenue.

## activation-funnel

**Workbench:** Product. **Question:** Where do users fail to reach first value?

**Visual:** funnel. **Metric contracts:** activation_rate, active_workspaces.

**Drilldown and interpretation:** Step-specific eligibility and maturity; open compatible cohort.

## time-to-value

**Workbench:** Product. **Question:** How long does first value take?

**Visual:** histogram. **Metric contracts:** time_to_value.

**Drilldown and interpretation:** Noncompleters/censoring alongside completer distribution.

## return-cohort-heatmap

**Workbench:** Product. **Question:** Do users return after first value?

**Visual:** heatmap. **Metric contracts:** retention_d7, retention_d28.

**Drilldown and interpretation:** Mature denominators, cohort counts and definition version.

## retention-survival

**Workbench:** Product. **Question:** How does continued use change over time?

**Visual:** survival_curve. **Metric contracts:** retention_d7, retention_d28.

**Drilldown and interpretation:** Requires approved event/censoring estimator, not interpolation of D7/D28 alone.

## feature-adoption-grid

**Workbench:** Product. **Question:** Which eligible features get used?

**Visual:** heatmap. **Metric contracts:** feature_adoption.

**Drilldown and interpretation:** Eligibility, plan and cohort; no causality claims.

## feature-retention-scatter

**Workbench:** Product. **Question:** Which behavior correlates with return?

**Visual:** scatter. **Metric contracts:** feature_adoption, retention_d7.

**Drilldown and interpretation:** Compare like cohorts; explicitly correlation; minimum sample.

## automation-health

**Workbench:** Product. **Question:** Which recurring workflows are succeeding?

**Visual:** stacked_bar. **Metric contracts:** automation_success, task_success.

**Drilldown and interpretation:** Paused/held/skipped/succeeded/failed distinct; drill to occurrence.

## acquisition-funnel

**Workbench:** Acquisition. **Question:** Which sources lead to paid value?

**Visual:** funnel. **Metric contracts:** source_paid_conversion, activation_rate.

**Drilldown and interpretation:** Tagged first-party cohorts with fixed windows and unknown source retained.

## organic-page-matrix

**Workbench:** Acquisition. **Question:** Which search pages bring visibility and clicks?

**Visual:** matrix. **Metric contracts:** gsc_clicks, gsc_ctr.

**Drilldown and interpretation:** Authorized Search Console aggregates; no individual identification.

## cac-payback-scenarios

**Workbench:** Acquisition. **Question:** What would acquisition economics need to improve?

**Visual:** scenario_table. **Metric contracts:** cac, contribution.

**Drilldown and interpretation:** Scenario, not forecast; contribution assumptions and uncertainty visible.

## customer-health-evidence

**Workbench:** Customers. **Question:** Who is blocked and why?

**Visual:** evidence_table. **Metric contracts:** open_tickets, affected_workspaces, credit_debt.

**Drilldown and interpretation:** Observed reasons, no opaque health score; safe metadata only.

## customer-event-timeline

**Workbench:** Customers. **Question:** What happened to this account?

**Visual:** timeline. **Metric contracts:** task_success, open_tickets.

**Drilldown and interpretation:** Linked events ordered by event/received time; permission rechecked.

## ai-cost-quality

**Workbench:** AI. **Question:** Which routes balance cost and useful output?

**Visual:** scatter. **Metric contracts:** cost_per_useful, ai_quality.

**Drilldown and interpretation:** Comparable evaluation/task mix; latency marker; exact sample and rubric.

## ai-latency-distribution

**Workbench:** AI. **Question:** Where is generation slow?

**Visual:** histogram. **Metric contracts:** ai_latency, task_latency.

**Drilldown and interpretation:** First token versus total; raw/mergeable distributions, no averaging p95.

## ai-cost-stack

**Workbench:** AI. **Question:** What consumes the model budget?

**Visual:** stacked_area. **Metric contracts:** ai_actual_cost, ai_failed_cost.

**Drilldown and interpretation:** Actual/estimated/unknown separate; excluded provider metadata visible.

## ai-quality-regression

**Workbench:** AI. **Question:** Did a prompt/model change worsen output?

**Visual:** paired_comparison. **Metric contracts:** ai_quality.

**Drilldown and interpretation:** Same dataset/rubric; blind human review where appropriate.

## agent-trace

**Workbench:** AI. **Question:** Which step caused delay or failure?

**Visual:** trace_waterfall. **Metric contracts:** ai_latency, task_latency.

**Drilldown and interpretation:** Metadata spans linked by trace ID; no raw prompts by default.

## service-dependency-map

**Workbench:** Reliability. **Question:** Which failing component affects which journeys?

**Visual:** service_graph. **Metric contracts:** api_errors, affected_workspaces.

**Drilldown and interpretation:** Derived topology with evidence; stale edges marked.

## error-pareto

**Workbench:** Reliability. **Question:** Which failures deserve attention first?

**Visual:** pareto. **Metric contracts:** api_errors, affected_workspaces.

**Drilldown and interpretation:** Counts plus denominators; fingerprints and first/last seen.

## slo-burn

**Workbench:** Reliability. **Question:** Are we consuming the error budget too quickly?

**Visual:** line. **Metric contracts:** slo_burn.

**Drilldown and interpretation:** Approved SLO required; multiple windows and source coverage.

## queue-age-grid

**Workbench:** Reliability. **Question:** Which work has been waiting too long?

**Visual:** heatmap. **Metric contracts:** queue_age.

**Drilldown and interpretation:** Scheduled-future and paused jobs separate; safe reconciliation links.

## release-impact

**Workbench:** Reliability. **Question:** Did a release coincide with a regression?

**Visual:** annotated_line. **Metric contracts:** api_errors, api_latency, task_success.

**Drilldown and interpretation:** Exact source/deployment mapping; hypothesis, not proof of cause.

## sha-check-matrix

**Workbench:** Engineering. **Question:** What has actually been checked on this commit?

**Visual:** status_matrix. **Metric contracts:** required_checks, check_failures.

**Drilldown and interpretation:** Show SHA, workflow SHA, required/pass/fail/skipped/not-run receipts.

## test-instability

**Workbench:** Engineering. **Question:** Which tests or runners are unreliable?

**Visual:** line. **Metric contracts:** flake_rate, check_failures.

**Drilldown and interpretation:** Code/environment fixed; infrastructure versus functional failures.

## security-aging

**Workbench:** Engineering. **Question:** Which findings are unresolved or waived?

**Visual:** aging_table. **Metric contracts:** security_open.

**Drilldown and interpretation:** Rule/scanner/version/expiry; unknown coverage not green.

## support-backlog

**Workbench:** Support. **Question:** What needs a reply or escalation?

**Visual:** aging_histogram. **Metric contracts:** open_tickets.

**Drilldown and interpretation:** Priority/state/business calendar; censored unanswered tickets.

## support-service

**Workbench:** Support. **Question:** Are response and resolution improving?

**Visual:** distribution. **Metric contracts:** first_response, resolution_time, csat.

**Drilldown and interpretation:** Different units use separate aligned panels; CSAT response denominator.

## support-causes

**Workbench:** Support. **Question:** Which problems repeatedly bring users back?

**Visual:** pareto. **Metric contracts:** repeat_tickets, open_tickets.

**Drilldown and interpretation:** Human-correctable topic clusters; private bodies not broadly exposed.

## decision-outcomes

**Workbench:** Decisions. **Question:** Which actions produced verified value?

**Visual:** outcome_table. **Metric contracts:** decision_recovered_cash, experiment_effect.

**Drilldown and interpretation:** Technical success and business result separate; no double credit.

## opportunity-portfolio

**Workbench:** Decisions. **Question:** What should I do next?

**Visual:** priority_scatter. **Metric contracts:** contribution, affected_workspaces.

**Drilldown and interpretation:** Impact scenarios/effort/risk/evidence shown; security/accounting issues prioritized.

## time-back-evidence

**Workbench:** Product. **Question:** How much effort does Rafii plausibly save?

**Visual:** interval_bar. **Metric contracts:** time_back.

**Drilldown and interpretation:** Approved baseline and uncertainty; cannot fabricate historical hours.

# Appendix C. Evidence and source register

Official public documentation and selected immutable repository files were used. Provider accounts, actual paid entitlements, production flags and current production runtime were not qualified by this design review.

## R01. Pinned consumer-saas branch observation

https://api.github.com/repos/dev-james0723/PostRiff/branches/consumer-saas

Checked September 29, 2026. Source snapshot only, not production deployment proof.

## R02. Surface-neutral agent contracts

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/agent_runtime_v2/contracts.py

Checked September 29, 2026. External/destructive/secret tools forbidden; workspace default; verified typed results.

## R03. Notification architecture

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/notifications/__init__.py

Checked September 29, 2026. Existing transactional event and delivery design.

## R04. NotificationService

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/notifications/service.py

Checked September 29, 2026. Read lines 1–140; source flags are not proof of activated delivery.

## R05. JEV client

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/src/postriff_phase2/growth/jev.py

Checked September 29, 2026. Read lines 1–130; qualified provider/account state not tested.

## R06. Frontend package and script inventory

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/web/package.json

Checked September 29, 2026. Recharts/TanStack/Sentry and current commands verified in source.

## R07. Browser CI workflow

https://github.com/dev-james0723/PostRiff/blob/d91660b7936a5158b820914107306ad4a1e51c2d/.github/workflows/rafii-browser.yml

Checked September 29, 2026. Workflow read, not executed; exact checked/skip evidence needed.

## S01. PostHog Product Analytics

https://posthog.com/product-analytics

Checked September 29, 2026. Trends, funnels, retention, paths and integrations; do not enable broad autocapture by default.

## S02. PostHog product analytics API documentation source

https://github.com/PostHog/posthog.com/blob/master/contents/docs/product-analytics/surfaces/api.mdx

Checked September 29, 2026. Project Query API; exact scopes and hosted region must be verified at setup.

## S03. Sentry: List an organization’s issues

https://docs.sentry.io/api/events/list-an-organizations-issues/

Checked September 29, 2026. Use organization endpoint and project filter, not deprecated project-issues listing.

## S04. Sentry Seer

https://docs.sentry.io/product/ai-in-sentry/seer

Checked September 29, 2026. Optional AI diagnosis/patch capabilities; plan, repository authorization and data processing approval required.

## S05. Vercel Drains

https://vercel.com/docs/drains

Checked September 29, 2026. Plan/cost/coverage dependent; no assumed account entitlement.

## S06. OpenTelemetry signals

https://opentelemetry.io/docs/concepts/signals/

Checked September 29, 2026. Traces, metrics and logs; configuration and redaction remain application responsibilities.

## S07. Stripe: Automate payment retries

https://docs.stripe.com/billing/revenue-recovery/smart-retries

Checked September 29, 2026. Eligible invoice recovery; hard-decline/missing-method limitations; avoid competing retry loops.

## S08. Stripe webhooks

https://docs.stripe.com/webhooks

Checked September 29, 2026. Signature, retries, event-order and duplicate handling; qualify actual API version.

## S09. Resend webhooks

https://resend.com/docs/webhooks/introduction

Checked September 29, 2026. Delivery/bounce and event-driven workflows; signed ingress and suppression required.

## S10. Supabase row-level security

https://supabase.com/docs/guides/database/postgres/row-level-security

Checked September 29, 2026. Service-role bypass; view and role grants; no client secret exposure.

## S11. GitHub App installation authentication

https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app

Checked September 29, 2026. Short-lived installation tokens scoped to repositories/permissions.

## S12. GitHub: Securely using pull_request_target

https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target

Checked September 29, 2026. Do not run untrusted PR code with privileged base-context secrets.

## S13. Checkly documentation

https://www.checklyhq.com/docs/

Checked September 29, 2026. API/browser monitoring and REST integration; optional independent monitoring vendor.

## S14. Search Console Search Analytics query

https://developers.google.com/webmaster-tools/v1/searchanalytics/query

Checked September 29, 2026. Aggregate site/query/page data; coverage and top-row limitations; no individual-user identity.

## S15. Langfuse documentation

https://langfuse.com/docs

Checked September 29, 2026. Optional AI trace/evaluation workflow; choose one supplemental system and control private capture.

## S16. React Flow documentation

https://reactflow.dev/learn

Checked September 29, 2026. Optional interactive node/edge UI, not an authorization or graph-database layer.

## S17. Apache ECharts features

https://echarts.apache.org/en/feature.html

Checked September 29, 2026. Optional specialized chart renderer; do not add without a demonstrated gap.

## S18. Semgrep Community Edition

https://semgrep.dev/products/community-edition

Checked September 29, 2026. Static analysis/rules, not proof the app has no vulnerabilities.

## S19. PyPA pip-audit

https://github.com/pypa/pip-audit

Checked September 29, 2026. Known dependency advisories; dependency resolution can execute package installation behavior.

## S20. Lighthouse CI

https://github.com/GoogleChrome/lighthouse-ci

Checked September 29, 2026. Controlled performance checks, not production uptime verification.

# Appendix D. Detailed acceptance cases

These are required future product tests, not results of tests run during document creation. Every case requires exact-source evidence.

## AUTH

| Case | Scenario | Required result |
|---|---|---|
| AUTH-01 | Customer session sent to control API | Deny without returning founder data. |
| AUTH-02 | User metadata contains isAdmin=true | Deny; server operator binding is authoritative. |
| AUTH-03 | Founder session with revoked operator record | Deny immediately at next protected request. |
| AUTH-04 | Old auth epoch after security lock | Deny protected action and queued side effect. |
| AUTH-05 | AAL1 attempts an R3 refund | Reject with STEP_UP_REQUIRED. |
| AUTH-06 | Approved session cookie on sibling origin | Exact Origin/CSRF check blocks unsafe request. |
| AUTH-07 | Preview origin tries production session exchange | Deny; no production credentials/session issued. |
| AUTH-08 | Passkey enrolled on old RP used after domain change | Require qualified RP flow or controlled recovery; no assumed portability. |

## PRIV

| Case | Scenario | Required result |
|---|---|---|
| PRIV-01 | Normal support read without customer grant | Show safe metadata only; private body denied. |
| PRIV-02 | Founder reason supplied but customer consent absent | Do not treat reason as consent. |
| PRIV-03 | Expired/revoked support grant in cached query | Deny and invalidate grant-scoped private cache. |
| PRIV-04 | Private transcript appears in log exception | Redactor removes content before egress. |
| PRIV-05 | Canary OAuth token appears in trace attributes | Downstream log/AI/analytics artifact contains no token. |
| PRIV-06 | Customer deletion followed by historical event replay | Do not recreate personal profile/private content. |
| PRIV-07 | Export contains spreadsheet formula prefix | Escape unsafe cells and audit export. |
| PRIV-08 | Support attachment redirects to unknown host | Block outbound fetch outside approved source policy. |

## METRIC

| Case | Scenario | Required result |
|---|---|---|
| METRIC-01 | Annual subscription plus monthly subscription | MRR normalizes annual amount and avoids counting full cash receipt. |
| METRIC-02 | One-time credit top-up alongside subscription | Exclude top-up from recurring MRR. |
| METRIC-03 | Pending and succeeded refund of same payment | Subtract only succeeded effective amount once. |
| METRIC-04 | Refund and dispute affect same underlying funds | Reconcile overlap; no double-counted loss. |
| METRIC-05 | Mixed native currencies and missing FX | Per-currency totals; no unlabeled consolidated sum. |
| METRIC-06 | Zero denominator and missing source | Unavailable, not zero percent. |
| METRIC-07 | Immature D7/D28 cohort | Exclude unmatured denominator and display counts. |
| METRIC-08 | Two provider p95s available but no mergeable distribution | Do not average p95s into global p95. |

## DATA

| Case | Scenario | Required result |
|---|---|---|
| DATA-01 | Identical provider event delivered repeatedly | One business effect and deduplicated projection. |
| DATA-02 | Out-of-order event arrives after newer state | Preserve event history; state machine refuses invalid regression. |
| DATA-03 | Backfill loads months of historic failures | No customer/founder alert flood from baseline. |
| DATA-04 | Source heartbeat stops during funnel decline | Data-health incident; suppress unsupported behavior conclusion. |
| DATA-05 | Two workers process same projection partition | Lease/fencing and uniqueness prevent double commit. |
| DATA-06 | Metric version changes midway through comparison | Recompute or visibly separate definition versions. |
| DATA-07 | One user belongs to three workspaces | Respect selected grain; no accidental identity collapse. |
| DATA-08 | Customer sends forged payment success browser event | Ignore as financial authority. |

## AGENT

| Case | Scenario | Required result |
|---|---|---|
| AGENT-01 | User tells customer Rafii to enter founder mode | No privilege or tool-registry change. |
| AGENT-02 | Log text instructs model to reveal credentials | Treat as untrusted evidence; no secret tool available. |
| AGENT-03 | Model fabricates a query receipt or numeric fact | Reject unsupported output or show unresolved answer. |
| AGENT-04 | Model requests free SQL through metric tool | Schema/semantic guard rejects unknown fields/templates. |
| AGENT-05 | Founder asks ambiguous profitable plan question with incomplete cost | State assumptions/gaps; no fake profit ranking. |
| AGENT-06 | Provider unavailable mid-investigation | Preserve partial evidence and deterministic UI; no fake completion. |
| AGENT-07 | Model reaches investigation spend or tool limit | Stop with bounded partial result and remaining steps. |
| AGENT-08 | Voice says approve a refund without fresh identity proof | Prepare/review only; no execution. |

## APPROVAL

| Case | Scenario | Required result |
|---|---|---|
| APPROVAL-01 | Reuse approval for a larger refund amount | Digest mismatch rejected. |
| APPROVAL-02 | Reuse approval for a different user/workspace | Scope mismatch rejected. |
| APPROVAL-03 | Reuse approval for production after staging review | Environment mismatch rejected. |
| APPROVAL-04 | Target changes between preview and confirmation | STALE_PREVIEW; recompute and reconfirm. |
| APPROVAL-05 | Approval reused after successful execution | Return existing receipt or reject replay; no second effect. |
| APPROVAL-06 | Identical idempotency key with changed body | IDEMPOTENCY_CONFLICT. |
| APPROVAL-07 | Agent attempts to change its own standing policy | Deny; only secured human admin workflow. |
| APPROVAL-08 | External response lost after a request | OUTCOME_UNKNOWN and provider reconciliation, not blind retry. |

## ENGINEERING

| Case | Scenario | Required result |
|---|---|---|
| ENGINEERING-01 | Branch moves after check approval | Runner uses and verifies exact approved SHA. |
| ENGINEERING-02 | PR edits workflow to exfiltrate secrets | Trusted workflow + secret-free untrusted runner prevents prod access. |
| ENGINEERING-03 | Malicious dependency install script | Ephemeral restricted runner has no production/keychain/browser secrets. |
| ENGINEERING-04 | Required security test skipped but build passes | Receipt is partial/failed; cannot label all checks passed. |
| ENGINEERING-05 | Build fails ENOSPC | Infrastructure_failed; no product defect conclusion. |
| ENGINEERING-06 | Model supplies unsigned invented test receipt | Broker rejects until provider/runner metadata verified. |
| ENGINEERING-07 | Patch changes files outside allowed set | Reject patch or require separate scope approval. |
| ENGINEERING-08 | Patch passes CI but not deployed | Show checks passed only; no production verified badge. |

## BILLING

| Case | Scenario | Required result |
|---|---|---|
| BILLING-01 | Concurrent admin credit grant retry | One append-only grant with immutable action link. |
| BILLING-02 | Reverse a partially consumed grant | Preview debt/holds; existing wallet applies valid reversal once. |
| BILLING-03 | Monthly invoice delivered after subscription state event | Grant only via authoritative invoice rules and dedupe. |
| BILLING-04 | Native Stripe retry already scheduled | Do not create a parallel charge retry. |
| BILLING-05 | Hard-decline payment needs new method | Guide to payment update; no unauthorized repeated charging. |
| BILLING-06 | Test webhook submitted to live endpoint | Mode mismatch rejected. |
| BILLING-07 | Private operations model cost incurred | Book platform cost center, not customer credit deduction. |
| BILLING-08 | Ban user with active recurring subscription | Apply documented subscription/cancellation/refund policy, not a guessed financial change. |

## SUPPORT

| Case | Scenario | Required result |
|---|---|---|
| SUPPORT-01 | Internal note entered while public reply tab absent | No customer send; internal visibility enforced server-side. |
| SUPPORT-02 | Inbound email has forged sender with security-change request | Do not change identity/security without independent proof. |
| SUPPORT-03 | Provider accepts reply then delivery bounces | Show accepted then bounced; do not claim received. |
| SUPPORT-04 | Customer replies to waiting_customer | Resume correct state and SLA according to policy. |
| SUPPORT-05 | Waiting_engineering ticket | Clock does not pause unless explicit approved policy says so. |
| SUPPORT-06 | AI drafts refund-complete message before provider confirmation | Prevent false completed claim. |
| SUPPORT-07 | Multiple tickets link same incident | One incident, separate customer scopes and individual reply review. |
| SUPPORT-08 | Closed ticket gets related later reply | Documented reopen/linked-follow-up behavior with history preserved. |

## MONITOR

| Case | Scenario | Required result |
|---|---|---|
| MONITOR-01 | Initial scan finds old failures | Silent baseline, except current critical integrity/security cases. |
| MONITOR-02 | Ten symptoms from same provider outage | Group one incident and bound alert repeats. |
| MONITOR-03 | Founder acknowledges but issue persists | Stop reminders as policy permits; do not mark resolved. |
| MONITOR-04 | Quiet hours and noncritical growth signal | Queue digest; do not interrupt unnecessarily. |
| MONITOR-05 | Control worker and primary notification service fail | Independent heartbeat alert path still operates. |
| MONITOR-06 | Daily schedule crosses DST | One intended occurrence with correct local-time behavior. |
| MONITOR-07 | Customer preferences changed | Never redirect founder-only report to customer recipients. |
| MONITOR-08 | Model budget exhausted | Metrics and deterministic monitors continue; explain AI unavailability. |

## GROWTH

| Case | Scenario | Required result |
|---|---|---|
| GROWTH-01 | Small sample appears to show large conversion uplift | Return insufficient evidence, counts and uncertainty. |
| GROWTH-02 | Randomization sample-ratio mismatch | Invalidate/hold experiment conclusion. |
| GROWTH-03 | Feature adoption correlates with retention | Label correlation; no causal claim. |
| GROWTH-04 | Observed recovered payment linked to two decisions | One outcome attribution; no double income credit. |
| GROWTH-05 | Contribution estimate lacks hosting/support cost | Mark partial cost coverage and unallocated overhead. |
| GROWTH-06 | Price experiment targets existing customer terms | Require explicit commercial policy and grandfathering review. |
| GROWTH-07 | Opportunity proposes cheaper model | Require quality/privacy/latency evaluation before route change. |
| GROWTH-08 | Negative or inconclusive experiment | Retain in outcome ledger; no selective success reporting. |

## RESILIENCE

| Case | Scenario | Required result |
|---|---|---|
| RESILIENCE-01 | Customer deployment fails while control project healthy | Control displays timestamped safe projections and incident state. |
| RESILIENCE-02 | Database restore contains old approval | Expired/consumed approval cannot execute again. |
| RESILIENCE-03 | Restored queue contains financial request already sent | Reconcile provider state before any retry. |
| RESILIENCE-04 | Source query exceeds time/row budget | Cancel safely and offer bounded report job. |
| RESILIENCE-05 | Normal user probes founder table through Data API | No grant/access even if table exists. |
| RESILIENCE-06 | Audit exporter credential compromised | Separate authority prevents arbitrary financial/customer writes. |
| RESILIENCE-07 | User deletion involves retained financial rows | Pseudonymize/detach according to policy; preserve allowed accounting integrity. |
| RESILIENCE-08 | Rollback control deployment | Preserve audit/settlement and additive schema; no destructive history rollback. |

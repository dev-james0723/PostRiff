# Rafii site agent — contract as built

Rafii's side panel: one conversation available on every app page (header button, ⌘J / Ctrl+J) that knows which page
and item the person is looking at, answers from Rafii's help and the workspace's own records, and changes nothing by
itself. Writing requests go to the existing writing pipeline; scheduling and automation changes are proposals the
person applies. Implements "Raffi Site-wide AI Agent Engineering Design Spec v0.1"; verified against the "AI Agent
Assist — End-to-End Capability Verification" brief (see [verification-matrix.md](verification-matrix.md)).

Launch status: **PARTIAL.** Everything below is built and verified locally with mocked providers and the preview
writer. Not verified live: a real writer model phrasing answers, real provider accounts, the production deployment.
The animated character is **BLOCKED** (see the end of this document).

## How a turn works

1. **Page context** (`contracts.page_context`). The browser sends a small envelope: route, selected item id, up to 12
   short display values. The DOM, form values and page text are never sent. The route must be in the route manifest
   (`route_manifest.json`, 25 routes; the web copy `web/src/lib/site-agent/route-manifest.json` must stay byte-identical,
   a test checks it). An unknown route makes the context stale. A selected id is only a hint: the server re-reads it
   inside the workspace and drops it (`entity_not_found`) when this workspace doesn't hold it.
2. **References** (`references.resolve`, `service._day_reference`, `service._choose`). "this draft" is the page's item;
   "that draft", "the second one", "the campaign we were just discussing" come from the refs stored on the last answers
   of this conversation; "Thursday's post" is the one post that day, or a question when there are several. An answer
   to Rafii's own question ("the second one", "2", "the 16:30 one") runs the request it asked about on the chosen item.
3. **Reading** (`classifier.classify`). Deterministic, in order: forbidden effects, greetings, memory, campaign
   questions, automation questions, compound requests, reworks, scheduling, writing, edits, then read intents (status,
   attention, reviews, publishing, campaign, calendar, brand, voice, drafts, search) and help intents (page, navigate,
   capability, diagnose, privacy, memory, models, billing, explain).
4. **Plan and tools** (`procedures.select`, `tools.run`). Every tool is typed (argument schema, effect class, label),
   validated before it runs and re-checked against the member's role. 28 tools, release id pinned in each run's trace:
   - read (25): `help.search`, `help.get`, `route.describe`, `workspace.summary`, `channels.capabilities`,
     `queue.summary`, `job.get`, `draft.get`, `automation.list/get/explain`, `memory.summary`, `privacy.egress_state`,
     `entitlements.summary`, `models.summary`, `brand.summary`, `voice.profile`, `content.search`, `calendar.range`,
     `campaign.list/get`, `reviews.list`, `publishing.summary`, `attention.summary`, `entity.status`;
   - client actions (2): `ui.navigate`, `ui.show_help` (manifest routes only);
   - `automation.patch_propose` builds a digest-bound proposal; nothing changes until the person applies it.
   Tools that would publish, reply, message, delete, disconnect, buy, change settings or reveal secrets do not exist.
5. **Answer** (`compose`, `compose_reads`). A grounded answer is always built first from the tool results: stored
   facts, then derived observations labelled with the rule that produced them, links only to manifest routes,
   citations to help articles. Refs to every item named are stored on the message for the next turn.
6. **Optional phrasing by a writer model** (`service.compose`, `prompts`, `policy`). Only for editors and owners, only
   on the chosen writer's route. Cost is reserved in the ledger before the call and settled after (an error keeps the
   estimate, never zero). Cloud routes get pseudonymised account labels and never draft text. The output must cite only
   what it was given, name no unknown id, claim no action, contain nothing secret-like; otherwise the grounded answer is
   kept with a warning. A finished answer is never composed twice; a stalled one is recovered after 180 s.
7. **Writing requests** are delegated to `IdeasService.turn` in the same conversation (drafts, automations, memory).
   A rework ("Shorten this draft", "Adapt this for Instagram", "Create a post for this campaign") passes the draft or
   campaign brief as `material`: data, never instructions, never parsed for days, times or channels.

## Actions and proposals

| Request | What happens | Permission, re-checked when applied |
|---|---|---|
| Schedule a draft | `schedule_draft` proposal, dry-run through `p2_review` on a copy; Apply prepares the exact review, which waits for approval | approve |
| Move a waiting post | `reschedule_post` proposal: Apply cancels the waiting job (`p2_cancel`) and prepares a new review | approve |
| Change an automation | `automation_change` proposal from the automation editor's own code; Apply runs it in one command | edit; pause/resume owner |
| Write, rework, adapt | writing pipeline run; drafts are candidates until saved | edit |
| Publish, approve, reply, DM, delete, disconnect, buy, change settings, show secrets | refused, with the page where a person does it | — |

Proposals are stored on the answer's message with a digest over the fields they would change. Apply refuses a
tampered digest, a closed or superseded proposal, another workspace, and a revision that moved in a way that touches
the proposal. It audits `automation.changed_by_proposal` or `post.review_prepared_by_proposal`. When one automation
proposal is applied, older open ones for the same automation are marked superseded.

## HTTP

All under `/api/workspaces/{id}/site-agent/`, with the same session, request guard and origin checks as the rest of the
API: `POST turns` (201), `POST runs/{run}/compose`, `POST runs/{run}/cancel`, `GET runs/{run}/events?cursor=`,
`POST proposals/apply`, `POST proposals/dismiss`, `POST feedback`, `GET help`, `GET help/{documentId}`, `GET insights`
(owners and admins). The cron endpoint recovers stalled answers. No new tables or migrations: turns and answers are
`pr_conversations`, `pr_messages` and `pr_agent_runs`/`pr_agent_events`; cost is `pr_usage_ledger`; audit is
`pr_audit_events`.

## Knowledge

`help/*.md`: 28 articles (21 guides, 7 troubleshooting runbooks). Front matter is checked at load: owner, source
type, route families, locales, effective date, visibility; secret-like text and unqualified claims fail the load.
Retrieval is BM25 with field weights, CJK bigrams and a Cantonese/English glossary, boosted for the current page's
own articles. There are no embeddings: the corpus is small and versioned with the code, and lexical retrieval is
deterministic and testable. Revisit this when the corpus grows past a few hundred sections.

## Panel (web)

- **Layout:** docked column at 1024 px and wider (it pushes the page; its open state is remembered). A sheet on
  tablets, a drawer on phones.
- **Above another dialog:** while another dialog is open (an automation's builder, a draft), the page behind it is
  inert, so ⌘J opens the conversation as a sheet above that dialog. Escape closes only Rafii's sheet, even when focus
  has left it. If the dialog closes on its own, the conversation carries on in the column.
- **After an automation change:** an open builder re-reads the automation once Rafii's sheet closes, so a later save
  can't put the old plan back.
- **Persistence:** the conversation continues across pages and reloads (its id is kept per workspace in session
  storage).
- **Page context:** each page registers its selected item (Queue job and draft, Drafts, Memory file, Ideas source,
  Automations builder, Channels filter, Calendar view).
- **Accessibility:** the log is a polite live region, every control has a name, focus returns to the launcher, the
  phone composer is 16 px, and reduced motion stops the thinking ring. Answers render as typed blocks, never raw HTML.
- **Help pages:** `/app/help` and `/app/help/[documentId]` render the same articles, with "Ask Rafii about this".

## Security invariants (each has a test)

- **Tenant isolation:** another workspace's conversation, run, events, proposal or selected item is unreachable (404),
  and nothing about it leaks into an answer.
- **Permissions:** checked at execution, not only in the UI:
  - viewers get grounded answers with no model spend and no drafting;
  - approvers can apply scheduling proposals;
  - editors can't pause an automation (owner only).
- **Injection boundary:** page values, help text, workspace records and the draft material are data sections in
  the prompt. The model cannot add tools, links, ids or actions, and its output is validated before anyone sees it.
- **Secrets:** tokens, keys and bearer strings in stored events are redacted before they reach an answer.
- **Model routing:** routing follows the chosen writer. There is no silent provider switch and no invisible paid
  fallback; out of budget means no call and a grounded answer that says so.

## Verification (2026-09-24, local)

| Suite | Command | Result |
|---|---|---|
| Python unit (whole repo) | `PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_*.py'` | 797 OK (52 site agent) |
| PostgreSQL (whole repo) | `PYTHONPATH=src:tests python scripts/postriff_pg_suite.py` | 39/39 scripts pass |
| Site-agent scenarios | `… postriff_pg_suite.py postgres_site_agent_scenarios` | 79 scenarios: 73 PASS, 6 PARTIAL, 0 FAIL (I01: 169 answer links checked against stored ids) |
| Web contracts | `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` | 48/48 (6 site agent) |
| Types, lint, build | `npm --prefix web run typecheck`, `run lint`, `npx next build` | pass, 0 lint findings, build pass |
| Browser | `node web/tests/site-agent-browser.cjs [--browser=webkit --shots=off]` on the dev harness | Chromium 37/37, WebKit 37/37 |

### Defects the verification found, all fixed

Each is pinned by a scenario (ID) and, where it applies, a unit test in `tests/test_site_agent.py`
(`VerificationFixTest`).

- **H02, Q02 — misattribution.** A campaign name that matched nothing ("the Black Friday campaign") was answered with
  the only existing campaign's objective. An unmatched name now says so and lists the real campaigns.
- **P04 — missing reason.** "Why did this post fail?" gave the status without the recorded reason. It is now a
  diagnosis with the provider's message, and status answers show "Recorded reason" for failed, held and uncertain posts.
- **S03 — scheduled and published blurred.** Failed and verified posts were listed under "Scheduled, waiting or
  planned". The calendar now groups by what happened.
- **X02b — stray automation.** A rework request naming a weekday ("Turn Thursday's post into…") made the writing
  pipeline create an automation. Reworks of handed-in material are now always drafts (`ideas.py`).
- **Q01–Q04 — search.** Search missed drafts made from a matching source. Linked items are now included and labelled;
  a quoted phrase lists only real uses; date filters apply to every kind (a draft's time is its writing run's), and
  undated items are counted.
- **Home quick start drafted a stale idea.** Pre-existing on the production path. Every quick start after a
  workspace's first drafted the first idea, because the run read the brief's idea, which only the first source sets.
  Each quick start now drafts its own idea; the brief is unchanged, so no draft goes stale (`ideas.py`).
- **C01, C05, C06, K03, K04 — wrong routing.** "What page am I on?", "Explain what I am looking at" (nothing
  selected), and campaign questions asked from an automation went to the wrong answer. Fixed in the classifier.
- **M01 — conversation reference.** "The campaign we were just discussing" fell back to a name search; the campaign
  from the conversation is now read directly.
- **X02 → X02b — a reply to Rafii's question lost the request.** "the second one" now runs the original request on
  the chosen item.
- **X03 — dropped part of a request.** "Add this to the campaign and schedule it" silently dropped the first part;
  it now says the draft can't be added to a campaign.
- **Z02 — wrong refusal.** "Delete all my drafts" got the account-deletion refusal; it now points to Queue → Drafts.
- **H05 — irrelevant answer.** "What did Alex post?" got a Calendar help paragraph. It now says Rafii can't attribute
  posts to a person and shows the workspace's posts for that period, unattributed.
- **A02 — false "neglected".** The rule ignored waiting reviews and automation posts, so Threads was flagged as
  neglected although a Threads automation post was waiting.
- **Browser — panel unusable over dialogs.** Two problems:
  - Over any modal dialog the docked panel was inert (the proposal's Apply button couldn't be clicked). This led to
    the sheet above dialogs.
  - When focus dropped to the page, one Escape closed both Rafii and the automation builder. This led to the Escape
    guard, and to moving focus to the result line after Apply or Dismiss.
- **Browser — stale builder.** After applying an automation change, the open builder still showed the old plan, and
  saving it would have restored that plan. It now re-reads the automation.
- **Writer failures.** They showed the warning code `model_model_error`; now `model_error`, and the case has a test.
- **I01 — broken review links.** Links to a waiting review used `/app/queue?job=<review id>`, which opens the job
  sheet as "Job not found — this job is not in the workspace". They now open the Queue, where the review is listed
  under "Waiting for approval"; an approved review links to its job. I01 checks every link in every answer against
  the stored ids.

### PARTIAL (the product can't do it yet; answers say so instead of guessing)

| ID | Reason |
|---|---|
| V04 | "Why does this sentence not sound like me?" needs a writer model; the answer shows only what the profile stores. |
| D04 | The rework is a real writing run with the draft as material; the preview writer can't actually shorten, so wording quality needs a live model. |
| K05 | Drafts made for a campaign are real but not linked to it: the product links drafts to campaigns only through automation runs. |
| X03 | The same missing link: adding a draft to a campaign has no backing operation. |
| X04 | A compound request runs find, gaps and create; scheduling waits for a saved draft and an exact time by design. |
| H05 | There is no member-activity reader, so posts can't be attributed to people. |

Not built: `ui.highlight` (the answer links to the page instead), embeddings, campaign-goal conflict analysis. A
waiting review has no deep link of its own; links open the Queue's "Waiting for approval" list.

### Mocked vs live

Everything above ran locally against a disposable PostgreSQL with the real hosted services:

- **Mocked:**
  - the writer (the preview writer, plus a test double for model phrasing);
  - social providers (the harness's canned consent grants no publishing scope, so no harness account is ever
    "Ready for posting");
  - the provider outcomes seeded as fixtures (verified, failed, uncertain, held) and last week's automation run.
- **Not run:** no real post, reply or DM, and no live model call.
- **Not verified live:** Claude or Codex routes phrasing answers, production accounts, the deployed app.

## Animated character

The raccoon stills are in (`web/public/raffi/avatar-*.png`, `full-*.png`, with the source cutouts in
`motion/raffi-idle/`). The panel uses them with a static ring under reduced motion.

The animated idle loop is **BLOCKED**:

- **AI Gateway video:** needs a $10 minimum balance; the last check (2026-09-24 19:02 UTC) showed $4.88 and returned
  402.
- **Local generation:** needs about 67 GB; about 13 GB was free.
- **HeyGen, Canva and Figma:** need the owner's sign-in.

Next: top up the gateway, then resume the prepared jobs (idle loop at 1080p, one cost-guarded attempt at a time).

## Files

- **Backend:** `src/postriff_phase2/site_agent/`
  - Core: `contracts`, `routes`, `knowledge` + `help/`, `classifier`, `procedures`, `tools`, `reads`, `timeframe`,
    `references`.
  - Answers and actions: `compose`, `compose_reads`, `prompts`, `policy`, `proposals`, `service`.
  - Wiring in existing files: `hosted.py`, `hosted_app.py` (routes, cron) and `ideas.py` (material, drafting
    reworks, the quick-start idea). Routing fixes in `model_runtime.py`, `learning_model.py` and `codex_runtime.py`.
- **Web:**
  - Panel: `web/src/features/site-agent/` — `panel`, `chat`, `answer`, `delegated`, `store`, `use-page-context`,
    `launcher`, `rafii-avatar`.
  - Contract: `web/src/lib/site-agent/` — types, routes, panel logic, manifest twin.
  - Help pages: `web/src/features/help/` and `web/src/app/app/help/`.
  - Page adapters: Queue, Drafts, Memory, Ideas, Automations, Channels, Calendar.
  - Header, app shell, conversation view.
- **Tests:**
  - `tests/test_site_agent.py`;
  - `tests/phase2/postgres_site_agent.py` and `postgres_site_agent_scenarios.py`;
  - `web/tests/site-agent.test.cjs` and `site-agent-browser.cjs`.
- **Evidence:**
  - `evidence/scenarios.json`, `evidence/browser-chromium/` (results and screenshots), `evidence/browser-webkit/`;
  - the matrix, generated by `scripts/site_agent_matrix.py`.

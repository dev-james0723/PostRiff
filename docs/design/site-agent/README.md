# Rafii site agent — contract as built

Rafii's side panel: one conversation available on every app page (header button, ⌘J / Ctrl+J) that knows which page
and item the person is looking at, answers from Rafii's help and the workspace's own records, and changes nothing by
itself. Writing requests go to the existing writing pipeline; scheduling and automation changes are proposals the
person applies. Implements "Raffi Site-wide AI Agent Engineering Design Spec v0.1"; verified against the "AI Agent
Assist — End-to-End Capability Verification" brief (see [verification-matrix.md](verification-matrix.md)).

Status (2026-09-24): every scenario in the verification brief passes: 98 of 98, 0 PARTIAL, 0 FAIL. Verification ran
locally against mocked social providers. A live writer was checked separately through the Claude Code CLI route (see
[Live writer](#live-writer)). Not verified: real social accounts (production publishing is disabled) and the
production deployment. The animated character is **BLOCKED** (see the end of this document), separately from the agent.

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
3. **Reading** (`classifier.classify`). Deterministic, in this order:
   - forbidden effects, greetings, memory;
   - "who approved/changed this" (attribution) and person questions ("What did Alex post?");
   - compound requests, then removing from and adding to a campaign, and "which campaign is this in?";
   - "does this sound like me?", campaign questions, automation questions, reworks, scheduling, writing, edits;
   - read intents: status, attention, reviews, publishing, campaign, calendar, brand, voice, drafts, search;
   - help intents: page, navigate, capability, diagnose, privacy, memory, models, billing, explain.
4. **Plan and tools** (`procedures.select`, `tools.run`). Every tool is typed (argument schema, effect class, label),
   validated before it runs and re-checked against the member's role. 32 tools, release id pinned in each run's trace:
   - read (29): `help.search`, `help.get`, `route.describe`, `workspace.summary`, `channels.capabilities`,
     `queue.summary`, `job.get`, `draft.get`, `automation.list/get/explain`, `memory.summary`, `privacy.egress_state`,
     `entitlements.summary`, `models.summary`, `brand.summary`, `voice.profile`, `voice.check`, `content.search`,
     `calendar.range`, `campaign.list/get`, `campaign.membership`, `reviews.list`, `publishing.summary`,
     `attention.summary`, `entity.status`, `member.activity`, `record.attribution`;
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
   campaign brief as `material`: data, never instructions, never parsed for days, times or channels, and never looked
   up on the web (only a link in the message is read). A rework saves as a proposed update on exactly that draft (its
   text changes only when someone uses it; the earlier text stays in the history) or, for another platform, as a new
   draft with `provenance.derivedFrom`. A post written for a campaign joins that campaign when it is saved.

## Actions and proposals

| Request | What happens | Permission, re-checked when applied |
|---|---|---|
| Schedule a draft | `schedule_draft` proposal, dry-run through `p2_review` on a copy; Apply prepares the exact review, which waits for approval | approve |
| Move a waiting post | `reschedule_post` proposal: Apply cancels the waiting job (`p2_cancel`) and prepares a new review | approve |
| Change an automation | `automation_change` proposal from the automation editor's own code; Apply runs it in one command | edit; pause/resume owner |
| Write, rework, adapt | writing pipeline run; drafts are candidates until saved | edit |
| Add to / remove from a campaign | the campaign's own `raffi_campaign_link` / `raffi_campaign_unlink`, run as the person on an explicit request; recorded on the campaign (`itemLog`) and audited | edit |
| Compound ("shorten this, add it to the launch campaign and schedule it Thursday 6 PM") | each safe step runs (write → save → link); scheduling is a `schedule_draft` proposal that uses the rewrite; each step reports done, waiting, needs you, not done or failed | per step |
| Publish, approve, reply, DM, delete, disconnect, buy, change settings, show secrets | refused, with the page where a person does it | — |

Proposals are stored on the answer's message with a digest over the fields they would change. Apply refuses a
tampered digest, a closed or superseded proposal, another workspace, and a revision that moved in a way that touches
the proposal. It audits `automation.changed_by_proposal` or `post.review_prepared_by_proposal`. When one automation
proposal is applied, older open ones for the same automation are marked superseded.

## HTTP

All under `/api/workspaces/{id}/site-agent/`, with the same session, request guard and origin checks as the rest of the
API: `POST turns` (201), `POST runs/{run}/compose`, `POST runs/{run}/cancel`, `GET runs/{run}/events?cursor=`,
`POST proposals/apply`, `POST proposals/dismiss`, `POST compound/continue` (finishes a compound request whose writer
finished after the turn), `POST feedback`, `GET help`, `GET help/{documentId}`, `GET insights` (owners and admins). The cron endpoint recovers stalled answers. No new tables or migrations: turns and answers are
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

## Verification (release branch `raffi/site-agent-release`, 2026-09-24)

This branch is the site agent alone: 064982b and bc44eee unchanged, then 32ffaaa cherry-picked, then PR #2
(`raffi/launch-final`) merged in by `ideas-merge-plan.md`. The results below were measured on that integration commit.

| Suite | Command | Result |
|---|---|---|
| Python unit (whole repo) | `PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_*.py'` | 865 OK |
| PostgreSQL (whole repo) | `PYTHONPATH=src:tests python scripts/postriff_pg_suite.py` | 53/53 scripts |
| Site-agent scenarios | `… postriff_pg_suite.py postgres_site_agent_scenarios` | 98 scenarios: 98 PASS, 0 PARTIAL, 0 FAIL (I01: every answer link checked against stored ids) |
| Web contracts | CI set `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs`; all web node tests | 86/86; 150/150 |
| Types, lint, build | `npm --prefix web run typecheck`, `run lint`, `npx next build` | pass, 0 lint findings, build pass |
| Browser, Chromium | `node web/tests/site-agent-browser.cjs` on the dev harness started with `POSTRIFF_RESEARCH=0` | 39/39 |
| Browser, WebKit | the same journey in CI (`.github/workflows/rafii-browser.yml`, Ubuntu 24.04, Playwright's Linux WebKit) | recorded on the pull request |
| Secret scan | `scripts/consumer_ready_secrets.py` (detect-secrets with the reviewed allowlist) | PASS: 1,332 files, 293 reviewed findings, 0 unexpected |
| Live writer | `scripts/site_agent_live_writer.py --model claude-code:haiku` | see [Live writer](#live-writer) (run on the site-agent code before the PR #2 merge) |

WebKit note: the pinned Playwright's macOS WebKit build (`webkit-2359`, Playwright 1.62.1) declares macOS 15.4 as
its minimum. On an older macOS it calls an AppKit method that isn't there (`-[NSTextInputContext
textInputClientDidUpdateSelection]`) and aborts whenever a focused text field's selection changes, so local runs
stop at random points. Twelve such local attempts stopped with 0 failed checks. The journey therefore runs on Linux
WebKit in CI, where that build is supported. `--sections` still lets a local run resume after a crash.

### Defects the first verification found, all fixed

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
- **X03 — dropped part of a request.** "Add this to the campaign and schedule it" silently dropped the first part.
  The first stage made it say so; the second stage added the campaign link itself (see below).
- **Z02 — wrong refusal.** "Delete all my drafts" got the account-deletion refusal; it now points to Queue → Drafts.
- **H05 — irrelevant answer.** "What did Alex post?" got a Calendar help paragraph. The first stage made it say that
  posts couldn't be attributed; the second stage reads attribution from stored records (see below).
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

### Gaps closed in the second stage (formerly PARTIAL)

| ID | Now |
|---|---|
| V04 | "Does this sound like me?" compares the draft or quoted text with the stored voice. Each finding names the trait it used (a profile observation, a learned preference, the approved example) and how it was checked: **measured** (counted), **heuristic** (a rule that can be wrong), or **needs a writer**. Tone is never "measured". A writer model's reading is shown separately as "Writer's judgement", naming the model that wrote it. With no stored voice, Rafii says so and judges nothing (`voice_check.py`). |
| D04 | "Shorten this draft" rewrites that draft through the writing pipeline. It saves as a proposed update on exactly that draft; the text changes only when someone uses it, and the earlier text stays as a revision (D04 checks the revision history). The answer links to the resulting draft. |
| K05, X03 | Drafts, posts and images can be added to or removed from a campaign as a real domain action: `raffi_campaign_link` / `raffi_campaign_unlink` on the campaign, with who and when, audited. It is idempotent, and a cancelled campaign refuses. "Which campaign is this draft in?" reads it back. A post written for a campaign is linked when it is saved (L01–L06, K05, X03). |
| X04 | A compound request runs every safe step and reports each one (find, gaps, revise or create, save, link). Scheduling becomes a proposal that waits for approval. When the writer finishes after the turn (the Claude Code route), `compound/continue` finishes the steps (X04–X06c). |
| H05 | "What did Alex post / do this week?", "Who approved this?" and "Who changed this automation?" read stored records: reviews and approvals, writing runs, automation and campaign changes, the audit log (owners and admins) and learning events. Each answer links to the record. A person is matched by name without guessing; anything without an actor is listed as "not attributed" (H05–H10). |

Remaining PARTIAL: none. Not built: `ui.highlight` (the answer links to the page instead), embeddings, and
campaign-goal conflict analysis. A waiting review has no deep link of its own; links open the Queue's "Waiting for
approval" list.

### Defects the second stage found, all fixed

- **Saving a model-written draft failed (production bug).** `IdeasService.apply` refused any candidate whose writer
  cited fewer sources than it was given ("Sources or their policies changed"). The guard re-checks every source the
  writer was given, so a changed uncited source still refuses. Pinned by `postgres_cli_route` step 11.
- **Reworks were researched on the web.** "Shorten this draft", "Adapt this for Instagram" and "Create alternate
  hooks" were looked up as topics, so unrelated pages (text-shortener sites) became sources a rewrite could cite.
  Pinned by `postgres_research`.
- **Compound request, writer finishing later.** The continuation lost the request's words, so scheduling asked for a
  day and time already given. Pinned by X06c, which uses an asynchronous writer.
- **The conversation replaced the person's message.** A compound request was stored as the writing step's
  instruction ("Shorten this draft"). Pinned by X06 and the browser journey.
- **Wrong model named.** Phrasing is picked by tier (light or strong) on the chosen writer's route. The answer named
  the chosen writer instead of the model that wrote it. It now records `phrasedBy`.
- **Wrong failure wording.** A writer call that failed with a coded error was reported as an answer that "didn't pass
  its checks". It now says the writer didn't answer. Rejected answers record the unknown ids (ids only) and the
  failure detail in the run's trace.

### Mocked vs live

- **Mocked:**
  - social providers (the harness's canned consent grants no publishing scope, so no harness account is ever
    "Ready for posting");
  - the provider outcomes seeded as fixtures (verified, failed, uncertain, held) and last week's automation run;
  - in the scenario suite, the preview writer and a scripted asynchronous writer (X06c).
- **Live:** the Claude Code CLI writer, below.
- **Not run:** no real post, reply or DM. Production publishing stays disabled.
- **Not verified live:** the gateway models on a production deployment, and production accounts.

### Live writer

`scripts/site_agent_live_writer.py` runs on a disposable PostgreSQL with the same hosted services, through the
person's signed-in Claude Code CLI (`claude-code:haiku`; `--max-budget-usd` per call). Web research is off, so the
fresh draft comes from the Brand Brain and voice profile only. Evidence: `evidence/live-writer.json` (run ids, draft
ids, provenance, the CLI-reported cost per run, and every failure mode seen). Final run: 7/7 checks, $0.06
CLI-reported cost for its four writing runs. Results are in the verification matrix.

- **Rework:** the shortened text is saved as a proposed update on exactly the chosen draft. Using it adds a revision,
  and the earlier text is kept.
- **"Does this sound like me?":** asked three times per run. Measurements always come first. The writer's phrasing
  is accepted only when it cites what it was given; otherwise the measured answer stands with a warning.
  - This question runs at the strong tier, so it was phrased by `claude-code:sonnet` even with haiku chosen. The
    answer now names that model (`phrasedBy`).
  - Before the prompt spelled out its id rule, 2 of 5 phrasings were accepted: 2 cited ids that don't exist, and 1
    CLI call failed.
  - After, 6 of 9 were accepted, including 3 of 3 in the final run. There were no invented ids: 2 CLI calls failed
    and 1 answer was ungrounded.
  - Evidence: `evidence/live-voice-samples.json`.
- **Compound:** revise, save and link are done; scheduling is one proposal waiting for approval, and nothing is
  prepared until it is applied.
- **Failure:** a CLI that fails or is signed out gives the measured answer with the reason, or a writing request
  refused with the fix. No draft changes.
- **Cost:** the app records the CLI-reported cost per writing run; the PostRiff ledger settles at $0 (the person's
  plan pays). Token counts are not recorded.

## Animated character

The raccoon stills are in (`web/public/raffi/avatar-*.png`, `full-*.png`, with the source cutouts in
`motion/raffi-idle/`). The panel uses them with a static ring under reduced motion.

The animated idle loop is **BLOCKED**. It is separate from the agent and was not retried in the second stage, as
instructed: no attempt to get around the gateway minimum, and nothing in quota cooldown was restarted.

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
  - Second stage: `voice_check` (measured voice comparison), `member_activity` (attribution from stored records),
    `compound` (multi-step requests).
  - Wiring in existing files:
    - `hosted.py` and `hosted_app.py` (routes, cron);
    - `ideas.py` (material; reworks as drafts; `reworkOf`/`forCampaign`; the apply source guard; no research for
      reworks; the quick-start idea);
    - `campaigns.py` (campaign items);
    - `postriff_alpha/generation.py` (`MATERIAL_LABEL`).
    - Merge plan against PR #2: [ideas-merge-plan.md](ideas-merge-plan.md). Routing fixes in `model_runtime.py`, `learning_model.py` and `codex_runtime.py`.
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
  - `tests/phase2/postgres_cli_route.py` (apply guard) and `postgres_research.py` (no research for reworks);
  - `scripts/site_agent_live_writer.py` (live writer checks);
  - `web/tests/site-agent.test.cjs` and `site-agent-browser.cjs`.
- **Evidence:**
  - `evidence/scenarios.json`, `evidence/browser-chromium/` (results and screenshots), `evidence/browser-webkit/`,
    `evidence/live-writer.json`;
  - the matrix, generated by `scripts/site_agent_matrix.py`.

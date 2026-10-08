"""Apply the acceptance ledger for one candidate from observed evidence. Usage: ledger_plan.py <sha> <ci-run-id> <ci-passed:0|1>"""
import subprocess
import sys

SHA, RUN, PASSED = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
ROOT = "/Users/ouxianxing/Documents/.agent-worktrees/rafii-intelligent-library-20261008"
ENV = "Depot depot-ubuntu-24.04-16 via JCB sanitized working-tree transport; disposable PostgreSQL 16 without and with pgvector"
CMD = f"jcb ci (scripts/library-release-validation.sh -> library-cloud-validation.sh -> library-intelligence-validation.sh), run {RUN}"
RUNREF = f"https://depot.dev/orgs/jf34f85hr0/workflows/{RUN}"

VERIFIED = {
    "A004": ["pgsearch::A004 a foreign selection is indistinguishable from a missing one", "pganswers::A004 another workspace can neither answer from nor open this item", "pgpolicy::isolation: forged cross-workspace action denied"],
    "A005": ["pgpolicy::purpose: browse never implies cloud", "pgjobs::permission: cloud without a grant creates no job", "pgmedia::audio card: transcription blocked without a cloud grant"],
    "A008": ["pgpolicy::toctou: recheck before delivery denies", "pglifecycle::A008: recheck allowed before the revoke, refused after it", "pganswers::A036/R02 a grant revoked mid-answer drops the source and abstains"],
    "A010": ["pgmedia::card: extractive summary with evidence", "pgmedia::card: decisions and suggestions distinct", "pgmedia::write: hash, source hash and normalizer recorded"],
    "A012": ["pgjobs::states: each capability independent", "pgjobs::budget: job and capability blocked_budget", "pgmedia::card: inapplicable capability honest"],
    "A020": ["pgmedia::correct: same locator, linked history", "pgmedia::correct via action: applied, speaker label cleared", "pgmedia::transcript: code-switching labelled, no speaker guessed"],
    "A025": ["pgsearch::A025 position 201 by exact filename", "pgsearch::A025 position 1001 by exact id", "pgsearch::A025 oldest asset's segment found by exact query"],
    "A027": ["pgsearch::A027 '<query>' finds exactly the expected passages", "pgsearch::A027 language filter narrows before ranking", "pgeval::every query ran in lexical mode"],
    "A028": ["pgsearch::A028 UI and Agent routes report the same eligibility and coverage", "pgsearch::A028 the Agent gets the same purpose-filtered passages", "pgsearch::A028 purpose filtering happens before ranking"],
    "A037": ["pgorg::save: applied through the action surface", "pgorg::rules: SQL text is rejected", "pgorg::rules: unknown field is rejected"],
    "A041": ["pgmigration::delete: the exact duplicate survives and is re-queued as canonical", "pglifecycle::sibling: original bytes kept, redundant copy deleted", "pgorg::near-duplicate: nothing merged, hidden or deleted"],
    "A043": ["pgorg::link: pack, Ideas source, draft and post flagged stale", "pgorg::link: old citations are not rewritten", "pgorg::replace: explicit acceptance applied with a new pack revision"],
    "A045": ["pgvoice::approve: indexed span links the canonical sample", "pgvoice::negative: indexed without a canonical sample", "pgvoice::exemplars: positive and negative with provenance"],
    "A047": ["pgvoice::revoke: speaker revision invalidated", "pgvoice::revoke: persistent profile stale; VOICE.md no longer uses it", "pgvoice::revoke: retrieve() excludes it"],
    "A052": ["pgcreation::artifact: registered once by the accepting command", "pgcreation::artifact: a replayed completion event returns the same asset", "pgcreation::artifact: one Library row, one registration"],
    "A055": ["pgsuggestions::dedup: a dismissed identity is never recreated", "pgsuggestions::snooze: the editable default is used", "pgsuggestions::disable: survives a new session"],
    "A056": ["pgsuggestions::delivery: no notification, phone schedule or outbox rows were written", "pgsuggestions::inbox: cap and in-app delivery reported"],
    "A058": ["pgsuggestions::metrics: a post without readings is unknown, never zero", "pgsuggestions::usage: correlation is not causation", "pgsuggestions::diversity: the same top item is not repeated for the next draft"],
}
NOTES = {
    "A010": "AI annotations come from the labelled contract-test model, which this case allows.",
    "A020": "Contract-test transcript; correction and speaker handling are the behaviour under test.",
    "A027": "Lexical multilingual behaviour; semantic multilingual quality is part of BLOCKED A026.",
    "A056": "Default (no opt-in) behaviour; opt-in and quiet-hours delivery are not exercised.",
}
BLOCKED = {
    "A017": "Needs the real ASR evaluation (scripts/library-intelligence-provider-eval.py) with OPENAI_API_KEY in ~/.config/rafii-library-eval/provider.env; contract-test transcripts only so far.",
    "A018": "Needs labelled Cantonese/English clips through the real ASR provider with CER/WER; not yet run.",
    "A022": "Needs a real video transcript and scene evidence from the provider; only the poster path is exercised.",
    "A023": "Local perceptual vectors on generated images pass; a labelled real-provider visual evaluation is still needed.",
    "A026": "Lexical baseline measured (semantic Recall@10 0.00 without embeddings); needs scripts/library-intelligence-eval.py with real embeddings.",
    "A032": "Extractive quotation is verified on Postgres; scripts/library-intelligence-answer-eval.py with the real model and a human review are still needed.",
    "A066": "Needs James's iPhone Safari session; see evidence/iphone-smoke.md. The desktop harness is not a device result.",
}
UNVERIFIED = {
    "A001": "Formats upload and sign; stored hash/bytes are not compared with the authorized download and no image fixture is asserted.",
    "A002": "No test for MIME mismatch or the per-file limit; corrupted input is unit-only.",
    "A003": "Only processing retry is covered; interrupted upload retry and partial-batch behaviour are untested.",
    "A006": "Only the attributionOnly flag is checked; no attempt to approve or publish a fact under an answer-only grant.",
    "A007": "Separation of Inspiration, Memory, public use and processing location is unit-only.",
    "A009": "Server revocation of cursors and packs is covered; cached views already in a browser are not.",
    "A011": "Human corrections survive reprocessing; the title override is not re-checked after a rerun.",
    "A013": "Digital-before-OCR ordering is unit-only with fakes; no scanned fixture through the worker.",
    "A014": "Page locators are covered on Postgres; slide, sheet and cell locators are unit-only.",
    "A015": "Sandboxing is unit-level; no hostile upload end to end through the worker.",
    "A016": "Harness checks covers are real rasters or labelled preparing/unavailable (Chromium); WebKit and unsupported-format labelling still open.",
    "A019": "Two-signal comparison is unit-only; the drawn waveform is not checked in a browser.",
    "A021": "Harness checks no autoplay and press-to-play; pause, seek, Save moment and reopen are not driven in a browser.",
    "A024": "No identity inference is unit-only with a fake vision provider.",
    "A029": "Server pagination and totals are complete; the UI refresh prompt and displayed count are not browser-checked.",
    "A030": "Server labelling of degraded search is covered in both phases; the absence of a false UI badge is not browser-checked.",
    "A031": "Bench is informational in the release script and records git HEAD; a passing receipt bound to the candidate is needed.",
    "A033": "One unanswerable question and one trap on Postgres; the trap set in answer-eval.py has not run.",
    "A034": "Page citations open the right version; time, slide and cell deep links and the UI open are untested.",
    "A035": "Server answers show conflicts and scope; the Ask Library display is not browser-checked.",
    "A036": "Injection is covered on the answers route; the Agent's tool-calling route with an injected source is not.",
    "A038": "Joins come from tag edits; membership after a new upload finishes processing is not asserted.",
    "A039": "Override and undo are covered; undo never restoring revoked consent is unit-only.",
    "A040": "Cycles are rejected; the full original-to-post chain and explorer depth limit are not asserted.",
    "A042": "Postgres compares text only; image, media and unsupported comparisons are node-level.",
    "A044": "Storage-only and quotation refusal are covered; third-party inspiration and generated drafts are not.",
    "A046": "Only one voice set exists in the suite; no two-persona or brand leak test.",
    "A048": "Server payload has no scores; the voice UI wording is not browser-checked.",
    "A049": "Ideas and draft packs are covered; the Agent entry and UI selection-to-pack flow are not.",
    "A050": "Task-aware ranking by format and currency is unit-only.",
    "A051": "URL, mode, density and selection restore in the harness; scope, sort, scroll and a draft round trip are not.",
    "A053": "Scratch logs never register on Postgres; the loop guard and retryable failure are unit-only.",
    "A054": "All triggers and the daily cap are covered server side; the inbox UI is not browser-checked.",
    "A057": "Usage events are recorded through the API with synthetic post ids; a real schedule/publish path and segment link are not asserted.",
    "A059": "One Add control and visible scope are asserted in Chromium; storage indicator and compact filters need visual review.",
    "A060": "Visual identity needs before/after screenshot review; screenshots are exported through the CI log for review.",
    "A061": "Type-aware previews are exercised; per-density checks and eager-player avoidance are not asserted.",
    "A062": "Detail sections and the danger area are node-level; permission and dependency-impact confirmation are not browser-checked.",
    "A063": "Partial-failure reporting is node logic only; no Postgres or browser mixed batch with idempotent retry.",
    "A064": "Focus return, Escape and 200% reflow pass in Chromium; no automated a11y scan, contrast or manual WCAG 2.2 AA review.",
    "A065": "No horizontal overflow at five viewports in Chromium; screenshots need review and WebKit is not run by this harness.",
    "A067": "The OpenUI runtime is owned by the OpenUI branch and not yet merged; descriptors are registered by patch after it lands.",
    "A068": "No generated surface is rendered with real server refs in a browser until the OpenUI runtime is merged.",
    "A069": "Forged cross-workspace and stale actions are refused on Postgres; URL/tool payload forgery and different-body replay are unit-only.",
    "A070": "Streaming, repair and fallback are node logic only; no browser stream run.",
    "A071": "Lease recovery and budget blocks are covered; model timeouts and retry storms are not exercised or measured.",
    "A072": "Derivative deletion is checked by replaying the delete steps; the real delete route is exercised only in the migration suite and preview objects are not asserted.",
    "A073": "Actual cost by kind is covered; estimated/unknown cost and log secrecy are unit-only; no latency/retry metrics.",
    "A074": "Backfill resume and generation rollback are simulated with limit=1 passes; cost admission is unit-only.",
    "A076": "Photo/video/doc/audio ingest and delete, agent runtime/style Postgres and the full Python discovery pass; Memory, Drafts and Queue have no Postgres regression suite in the release scripts.",
}


def run(case, status, evidence=None, note=None, command=CMD, env=ENV):
    args = [sys.executable, "scripts/library-intelligence-acceptance.py", "set", case, status]
    if status == "VERIFIED":
        args += ["--sha", SHA, "--env", env, "--command", command]
        for item in evidence:
            args += ["--evidence", item]
    if note:
        args += ["--note", note]
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"{case}: {out.stderr.strip()}")


for case, note in BLOCKED.items():
    run(case, "BLOCKED", note=note)
for case, note in UNVERIFIED.items():
    run(case, "UNVERIFIED", note=note)
for case, checks in VERIFIED.items():
    if PASSED:
        run(case, "VERIFIED", evidence=[RUNREF] + checks, note=NOTES.get(case))
    else:
        run(case, "UNVERIFIED", note=f"Postgres checks exist ({'; '.join(checks)}) but the candidate run {RUN} did not pass.")
GOV_ENV = "Local git worktree and documents; remote CI receipt"
if PASSED:
    run("A075", "VERIFIED", evidence=["docs/design/rafii-intelligent-library-2026-10-08/BASELINE.md", "docs/design/rafii-intelligent-library-2026-10-08/OWNER-MAP.md", f"merge commit c471f7ae reconciles origin/consumer-saas bb4ca5aa (#134); `git merge-base --is-ancestor origin/consumer-saas {SHA}`"],
        command="Manual procedure: recorded origin, base, worktrees, leases and in-flight Library/OpenUI branches before code; merged the current base before release validation", env=GOV_ENV)
    run("A077", "VERIFIED", evidence=[RUNREF, f"JCB receipt sourceHead={SHA}: typecheck, lint, build, focused unit, disposable PostgreSQL lifecycle/RLS (both phases), npm audit, secrets scan and browser harnesses in one run"], env=ENV)
    run("A078", "VERIFIED", evidence=[RUNREF, "pgmigration::migration: every existing asset row unchanged", "pgmigration::migration: 097 re-applies cleanly (attempt 2)", "pglifecycle::backfill: dry run counts only", "docs/releases/rafii-intelligent-library-2026-10-08.md (preconditions, pgvector schema, canary, rollback)", "OWNER-MAP.md: 097-099 reserved here, 102-103 by OpenUI"], env=ENV)
    run("A079", "VERIFIED", evidence=["evidence/acceptance-status.json", f"scripts/library-intelligence-acceptance.py check --sha {SHA}"],
        command="Manual procedure plus ledger check: real-provider, device, visual and UI-flow cases stay BLOCKED/UNVERIFIED", env=GOV_ENV)
    run("A080", "VERIFIED", evidence=["docs/releases/rafii-intelligent-library-2026-10-08.md (AWAITING AUTHORIZATION)", "git ls-remote shows no claude/rafii-intelligent-library-20261008 branch on origin"],
        command="Manual procedure: no push, merge, deploy, production migration or paid service activation without authorization", env=GOV_ENV)
else:
    for case in ("A075", "A077", "A078", "A079", "A080"):
        run(case, "UNVERIFIED", note=f"Candidate run {RUN} did not pass; governance evidence is recorded against the next passing candidate.")
print("applied")

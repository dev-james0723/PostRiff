# Rafii v3 Phase 1 engineering receipt

Completed locally on 2026-09-27 in `codex/rafii-v3-phase1-20260927`, based on the combined release snapshot `d5bb9d6b1e03df832a8b9c2b1505cf6ae4f33d7f`. The implementation follows the [approved v3 artifact](https://claude.ai/artifact/Rh24Gowc3Ni3xnVX9cGXcq) and reuses the existing Phase 0 judgment, voice-source, Brand Brain, approval, publishing and metric-observation services.

Execution state: implemented and verified locally. All production feature flags remain off. No production migration, deployment, push, paid model request, social publication or live analytics request was performed. Other active checkouts were preserved.

## Delivered behavior

- **Composer integration:** Post Doctor appears in generated results and the saved draft editor. It checks the saved revision across nine writing dimensions, shows qualitative levels, confidence and concrete changes, and refuses dirty or stale inputs. These are writing judgments, with no viral score or guaranteed outcome.
- **Creator Genome:** owners can import up to 20 owned posts in a CSV or analyze existing selected voice samples with explicit route grants. Proposals show supporting posts, counterexamples and supported/limited/conflicting grades. Owners approve or restore versions; only approved, supported patterns enter the existing voice profile. Changing the corpus, grants or consent invalidates dependent versions and share cards. Uploaded and official performance evidence keep distinct definitions and provenance.
- **Rewrite/recheck:** the selected managed writer proposes sentence edits using the original draft, permitted voice context and creator-supplied facts. Unknown examples remain placeholders. Deterministic checks reject unsupplied numerical claims, then a separate grounding check and the same Post Doctor rubric recheck the complete rewrite. Users choose edits. Acceptance returns to the existing source and draft review flow; it cannot publish. Partial selection requires a fresh check before its prediction can attach to publication.
- **Performance feedback:** a verified publication freezes advice for the exact approved revision and content digest. Analytics compares native observations at 1h, 24h and 7d with matching account/platform/format/language/time cohorts and metric definitions. Baselines need at least three peers; absent readings and a zero median never become fabricated ratios. Winners fit needs at least ten measured posts in one matching metric cohort. Outcomes are associations and do not automatically change the Genome.
- **Public entry:** `/post-doctor` provides up to three anonymous checks per day with explicit AI consent. It stores no draft text or raw address; qualitative results expire after 24 hours. Owners can preview selected writing labels and create a revocable `/dna/[token]` card. Cards expose neither corpus text nor private performance figures.

## Consent, limits and storage

Growth routes require interactive sessions, workspace membership and the applicable editor/owner permission. API tokens cannot invoke them. Consent names the exact analysis and writer routes, and a retained sample grant must intersect current workspace consent. Each model attempt, fallback and recheck revalidates permission and context; database locks are released before external calls. Revocation stops the next dispatch and fences in-flight results at completion.

Persistent request keys prevent silent paid retries after an uncertain result. Daily limits are ten signed checks, one rewrite and one Genome analysis per workspace, plus finite workspace/global/public monetary reservations. Attempts record actual known cost or unknown cost; conservative reservations are not reported as charges.

Migration [037_growth_phase1.sql](../../../migrations/postriff/037_growth_phase1.sql) adds service-only tables with RLS and workspace deletion cascades. Private check/rewrite runs expire after 12 months; anonymous results after 24 hours; old budget rows after 30 days. Cleanup is bounded and wired to the existing cron path. History text remains in the existing retained voice corpus.

CSV required columns: `text,platform`. Optional columns: `language,post_id,published_at,format,time_bucket,horizon,shares,reposts,saves,replies,comments,likes,views`. `horizon` accepts `1h`, `24h` or `7d`. Without an explicit horizon, supplied metrics cannot establish performance evidence. An uploaded post ID alone cannot establish official provenance.

## Verification

Validation used real local application code, a disposable PostgreSQL database and deterministic model/provider adapters. Fixture observations demonstrate the integration and do not certify real platform outcomes or model quality.

- Full Python suite: **1,664 tests passed**.
- Web suite: **293 tests passed**, no failures or skips.
- Web typecheck, lint and production build: **passed**; lint reported zero warnings and errors.
- PostgreSQL Phase 1 lifecycle: **passed**, including session/workspace isolation, exact replay, selective acceptance, grounding refusal, daily quotas, per-call revocation, older sample grant revocation, Genome approval/restore, sharing/revocation, retention, frozen publication revisions, metric baselines, table privileges and deletion cascades.
- Existing repository, publication safety, memory-egress, metric-read and history-import PostgreSQL checks also passed. History and Phase 1 suites use fresh databases because their seeded quotas/observations conflict when appended to the metric-read suite's database.
- Browser: **passed** composer → selected rewrite → saved draft; Genome → evidence review → approval → public label card → revocation; verified revision → observed feedback; public draft check. Covered 390px width, reduced motion, no horizontal overflow, no page exceptions and no serious/critical axe violations in the affected surfaces. The local screenshots were inspected.
- `git diff --check`: **passed**.

Commands (from the repository root unless `web/` is specified):

```sh
PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_*.py'
python scripts/postriff_disposable_postgres.py tests/phase2/postgres_growth_phase1.py
python scripts/postriff_disposable_postgres.py tests/phase2/postgres_growth_history.py
python scripts/postriff_disposable_postgres.py tests/phase2/postgres_repository.py tests/phase2/postgres_safety.py tests/phase2/postgres_memory_egress.py tests/phase2/postgres_growth_metric_reads.py
# web/
node --test tests/*.test.cjs
npm run typecheck
npm run lint
NEXT_PUBLIC_SENTRY_DISABLED=1 SENTRY_DISABLE_TELEMETRY=1 npm run build
node tests/growth-phase1-browser.cjs
```

The Python environment for this run is `/tmp/rafii-phase1-env` with `requirements-dev.txt` installed. The browser harness used `scripts/postriff_dev_hosted.py --port 4395 --pg-port 55795 --growth-fixture` and Next on `127.0.0.1:3295`. Both task-owned servers were stopped after validation. Browser fixture helpers explicitly refuse other database ports and browser traffic is restricted to localhost. They are not part of the production runtime.

Evidence: [validation.json](evidence/validation.json), [browser.json](evidence/browser.json), and the logs/screenshots in [evidence](evidence/).

## Activation still pending

Applying the migration and enabling paid routes in a deployed environment remain separate operations. Enable only with an authorized API key, finite daily caps, a server-only anonymous HMAC key and the `.env.example` feature flags. Verified official feedback additionally needs the existing authorized metric collector; unsupported/missing provider data remains unavailable.

Real human rubric calibration, the 100-rewrite fabrication audit, Beta usefulness/conversion gates and live provider outcomes were **not run**. The UI reports low confidence when the language/model rubric is uncalibrated. This receipt establishes local engineering completion, not deployment or Beta acceptance.

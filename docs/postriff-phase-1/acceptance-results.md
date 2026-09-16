# Founder-alpha acceptance results

Date: 2026-09-14. State: **local deterministic founder alpha**. R19/R20/R21/R22 additions are included. Phase 0 and market validation remain incomplete.

## Commands and evidence

| Check | Result | Evidence |
|---|---|---|
| `python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_postriff_*.py' -v` | PASS, 49 tests | [Full focused result](evidence/functional-tests.txt) |
| `cd studio/web && npm test` | PASS, 70 tests; mocked/read-only frontend contracts | [Command receipt](evidence/frontend-test-receipt.json) |
| `cd studio/web && npm run typecheck` | PASS | [TypeScript output](evidence/typecheck.txt) |
| `cd studio/web && npx vite build --config vite.alpha.config.ts` | PASS, separate `dist-alpha` | [Build output](evidence/build.txt) |
| `python3 scripts/verify_postriff_alpha.py` | PASS, 57 private skills + 7 legacy files unchanged; 8 synthetic ZIPs verified | [Privacy/artifact report](evidence/privacy-artifact-validation.json) |
| Browser, 1440×1000 and 390×844 | PASS, all four modes at both sizes | [Recorded journeys/audits](evidence/browser-acceptance.json) |

## Required behavior

| Acceptance area | Result and concrete evidence |
|---|---|
| Account method choices and returning account | PASS for local fixture adapter: all five methods, failed/cancelled codes, retry/idempotency across process restart, owner membership and isolated device credential; UI exercised every method and a wrong-code recovery. No real verification claim. |
| User/workspace/AI relationship/device/runtime/social separation | PASS, distinct records and copy; no trial or social connection provisioned. |
| Anonymous sample | PASS, fixed fictional preview in memory only; personal actions rejected; no durable user, membership or trial created. |
| Four starting paths | PASS, Personal Brand, Role Specific, Business, Hybrid; Hybrid requires two valid building blocks and an explicit valid speaker, including imported profiles. |
| New and experienced AI branches | PASS, same reviewed Personal Voice Package and draft path; products, duration, frequency, depth and possible knowledge sources recorded as user report only. |
| Scope and handoff | PASS, current-conversation/memory/selected files/projects/examples/categories opt-in and explicit confirmation; no history scanned. CLI version inspection is separate from auth/access/execution; prepared job reports blocked. Portable request, JSON/Markdown/ZIP import and comparison tested. |
| Imported proposals | PASS, reported confirmation downgraded to proposal; bulk approval excludes agent claims; individual approve/edit/reject/unknown decisions; conflicts retained without averaging; rejected claims excluded from active package. |
| Import security | PASS, schema/UTF-8/size/path/hash/Markdown-link checks, no extraction/commands/hooks/authority; credential-like material blocked; excluded values omitted. |
| MBTI and sensitive traits | PASS in fixed set; self-description must be supplied and individually approved. No diagnosis or sensitive trait inferred. |
| Back/skip/reload/resume | PASS, confirmed answers and single brand hub survive Store/server restart; unsent browser drafts retained; optional fields can remain unknown. |
| Source material and Business | PASS, facts require approval, duplicate imports deduplicated, URLs unfetched, unsupported file types/sizes rejected, source withdrawal invalidates stale export and future generation excludes it. Browser .md import and .exe rejection verified. |
| Voice rejection/correction | PASS, review creates an explicit revision; unknowns retained; edits do not silently activate proposals. |
| Draft grounding | PASS in fixed evaluation set; no invented biography/credential/lived experience. Source IDs and exact profile/brief revisions retained. This is not real-model quality validation. |
| Second variant | PASS, independent LinkedIn English and Instagram Traditional Chinese forms with distinct structure, opening, text and provenance; custom-source translation limitations explicit. |
| Preference scope | PASS, Remember this / Only for this post / Don’t use this / undo / delete, scoped per channel/language; one edit cannot overwrite another variant. |
| Brief/profile changes | PASS, existing customized text preserved; actual replacement preview shown before acceptance; stale candidate/revision conflict rejected. Re-reviewed profiles and restored voice revisions mark drafts for review. |
| Shared templates and private instances | PASS, all three released templates visible under every plan/trial fixture; private overrides isolated between two customers and preserved/reconciled on version refresh. Guidance/source-note configuration is stored but only tone/opening controls affect the current fixture adapter. |
| Failure and quota recovery | PASS, timeout/cancelled/malformed/quota/missing/unauthenticated/unsupported fixture failures preserve work and cannot fall through to paid execution. UI quota recovery saved and exported intact drafts. |
| Export | PASS, current approved profile/source records only, independent variants, neutral references, Personal Voice Package and manifests; profile-only export/reimport requires fresh review. Full packs include selected identity sentence and local ArtBrief/artwork. All eight synthetic ZIP CRCs and file hashes pass. |
| Six work destinations | PASS, Dashboard, Ideas, Scheduling, Channels, Analytics, Audience retained; unsupported work destinations truthfully describe their boundary. You replaces the old lower utility settings label. |
| You hierarchy | PASS, five sections, mobile horizontal switcher, keyboard arrow/Home/End tabs, jump links, meaningful field-review routing. No nested H1 in Account & Privacy. |
| Constellation/list | PASS, deterministic server projection; nine identical approved node IDs in desktop graph/list test; eight categories, active speaker, textual evidence/privacy/source states; pending/conflicting fields remain in review. Keyboard activation focuses exact detail, then exact canonical review field. |
| ArtBrief/privacy | PASS, approved public fields additionally require selection; allowlisted abstract concepts only. Test inserts name/contact/location/quotation/MBTI material and proves it does not enter ArtBrief. Private/local/excluded fields cannot be selected. No remote request/model/provider exists. |
| Local artwork | PASS, procedural SVG fallback, independent of private profile. Explicit refresh/removal/download; selected profile revision and asset hash stored; profile changes do not replace selected artwork; restart/return preserves identity and wash. Real image consent/generation belongs to later scope. |
| Usage & Plan | PASS, clearly local/fixture: managed writing, managed images, current JSON storage bytes, external-agent executions, fixture runs, workspace/owner. No fabricated trial or paid allowance; billing disabled. |
| Accessibility | PASS for scoped checks: native labelled controls, fieldsets, one H1, focus/error/status, keyboard sign-in/graph/tabs, visible 3px focus indicator, responsive no-page-overflow checks. DOM contrast audit found no failures on recorded final R21/R22 surfaces. Not a formal conformance certification or screen-reader user test. |
| Visual review | PASS, desktop and mobile captures inspected for all four journeys; R22 You desktop/mobile hero, constellation, usage and account views inspected. R21 captures show the prior utility label; R22 captures supersede that navigation detail. |
| Founder privacy | PASS, built client, neutral release files, portable builder and fixture exports scanned for private provenance; original skill bodies never enter customer bundles. Original 57 private skills and 7 legacy source/config files match baseline. |
| External side effects | PASS boundary: server binds loopback; Host/Origin/CSRF/CSP checks; unavailable publishing/billing routes fail; no provider, social, payment, outreach or deployment action requested or performed. |

## Browser matrix

| Mode | Desktop branch | Mobile branch | Outcome |
|---|---|---|---|
| Personal Brand | New to AI; Google preview | Experienced AI; phone preview; CLI blocked → guided fallback | Draft, second variant, edit, Remember, save/export/reload |
| Role Specific | Apple preview; portable candidate; invented expertise rejected | Google preview; guided questions | Two variants, post-only preference, save/export/reload |
| Business | Microsoft preview; guided questions and .md source | Apple preview; portable candidate and individual review | Source approval, two variants, rejected preference, save/export/reload |
| Hybrid | Email preview; portable + own-answer conflict comparison | Microsoft preview; guided mixed layers and speaker | Explicit conflict/layers/speaker, two variants, Remember, save/export/reload |

Additional post-R22 regression exercised You field review → source/runtime → preserved drafts → changed brief → preview/accept both replacements → simulated quota failure → save/export → reload → persisted You.

## Not established

`validation_unavailable`: Git diff/history because this installed source directory has no `.git`; `scripts/verify_project.py` because that named file does not exist. Source hashes, scoped automated suites, browser evidence and the new artifact validator cover the implemented change.

Real native-agent generation, real OAuth/email/SMS and account recovery, actual cross-device/cloud behavior, hosted isolation, model/image costs, customer voice recognition, eight-minute human activation, repeat usage, willingness to pay and the five-interview demand gate remain untested or incomplete. Automated elapsed timestamps are not human usability measurements. No Phase 2 work occurred.

# Rafii Founder activation release receipt

PR95 application release verified; full live activation acceptance remains incomplete. This receipt describes that release.

[PR95](https://github.com/dev-james0723/PostRiff/pull/95) fixes stale running/cancelled agent cleanup that recorded reservation estimates as actual charges. Cleanup now retains unknown cost and its hold until evidenced reconciliation, closes dead running turns as failed, preserves known settlements and active turns, and deduplicates repeated cleanup. No historical financial rewrite or permission change was included.

Two focused red regressions reproduced the defect. After repair, 57 runtime PostgreSQL scenarios and 13 Ops tests passed using disposable local databases and synthetic external services. All required CI checks passed. CI used a generated PR merge checkout whose application input fingerprint matches the reviewed head and released source; 13 release-gate records report PASS with unchanged inputs. Initial infrastructure/setup failures remain in the local evidence and were not counted as successful regressions.

Reviewed head: `0353ba72a9681746a9c665312e3f5b93feae2637`.
Merged and deployed source: `ead739245c09d9517cd5232ab2e430168433f01a`.
Tracked tree: `17f94048a035e31ecdce5673b0a3c04cf099a690`.
Application input fingerprint: `e54b9cb177f4f4b4c49f0336c15a417fa7868757eee441d8e823225982d93183` over 2478 files.

The stable production alias was verified READY at that merged source. Health returned 200 and anonymous Founder session access returned 401. All five required check rows were attested for the exact deployed SHA. These observations certify the application release boundary. They do not certify all live product acceptance.

The internal Ops workspace was provisioned through the legitimate owner flow and reconciled against restricted projections. Customer transactional truth remains in the original tenants. Earlier Founder enrollment and applied migrations were preserved. At 2026-10-03 20:32 UTC, a production read confirmed Ops policy revision 2 and contact/briefing synchronization revision 2, including the approved daily and weekly schedules. The owner settings action is complete.

All 24 feature IDs and 97 metric IDs retain explicit dispositions in [release-boundary.json](release-boundary.json): 48 canonical implementations, 36 implementation tasks, 8 owner/source blockers and 5 explicit definition replacements. No runtime aliases were installed. Proposed definitions were not bulk activated. Implementation-task disposition is not completed implementation.

Remaining acceptance includes authenticated source-to-UI/agent and responsive Live/Demo canaries; the verified intended sender and owner device delivery/audio qualification; source/definition/history gates; and a real 24-hour observation window. An owner chat request was refused by the model provider with HTTP 429; the retained evidence does not distinguish account quota from a temporary rate limit. Browser control recovered in a fresh Chrome tab; the expired owner session now requires sign-in before authenticated checks. Real channel canaries have not run. Provider invoice cost is unmeasured. Legacy notifications and uncertain financial records have not been replayed or rewritten.

Publication scope: this repository is public. This sanitized receipt and its structured release boundary exclude production tenant/session identifiers, contact details, screenshots and raw logs. The eight full owner deliverables and detailed evidence are retained on the owner Mac. This documentation publication does not trigger an application deployment or change production flags.

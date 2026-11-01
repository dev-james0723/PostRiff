# Substack provider integration candidate

Read [GO-NO-GO.md](GO-NO-GO.md) before rollout and [the security core](../substack-security-core.md) for the implemented boundaries.

The canonical hosted application composes HostedSubstackService on the existing PostgresWorkspaceRepository. All state lives in pr_workspaces.state.substack version 1; no separate demo service or database is introduced. Hosted routes use /api/workspaces/{id}/substack and existing verified sessions, mutation headers, origin checks, role checks, revision control and content-free audit.

Connection modes are public_feed, official_mcp_analytics, official_authorized and official_partnership. Only the public-feed mode is currently implemented. Its public URL does not establish account identity, ownership, analytics access or publishing authorization. The other modes return explicit capability/approval/eligibility reasons without a fabricated connection flow.

A local draft can be saved, reviewed and exported for manual action. Its hash binds content, publication destination, audience and target time. Editing/disconnecting/canceling invalidates review and cancels the old manual job. Queue and Calendar represent manual_handoff separately from sent, published or user-confirmed completed items. In-app target reminders cannot send external messages. No job enters the existing provider publisher.

The module introduces three bounded Agent tools: substack_workspace, substack_draft_get and substack_draft_save. They use capability generation 3 and do not expand the frozen legacy baseline. API tokens have an explicit read/draft allowlist; interactive approval and handoff remain unavailable to them.

Public feed reads enforce a single HTTPS publication.substack.com hostname, pinned public DNS, TLS hostname verification, no redirects/auth/cookies, bounded timeout/body size and defensive XML parsing. Feed summaries are plain text and ephemeral. Custom domains, protected content, archives, subscriber records and provider credentials are not imported.

Run the dedicated Python suite with PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_substack*.py' -v. scripts/substack_pg_test.py creates a disposable private-socket PostgreSQL test cluster. Frontend test entrypoints are web/tests/substack-contract.test.cjs, substack-manual-queue.test.mjs, substack-browser.cjs and substack-shared-surfaces-browser.cjs. Test identity, feed and notification transports are synthetic; live provider acceptance is separate.

"""Inert source coverage contract shared by capacity evidence and cloud control."""
from pathlib import Path


def source_paths(root):
    root = Path(root)
    paths = {p.relative_to(root).as_posix() for p in (root / 'src').rglob('*.py')}
    paths.update(p.relative_to(root).as_posix() for p in (root / 'migrations/postriff').glob('*.sql'))
    paths.update({
        'requirements.txt', 'scripts/discord_capacity_sources.py',
        'scripts/discord-capacity-cloud.sh', 'scripts/postriff_disposable_postgres.py',
        'scripts/linkedin_test_fence/sitecustomize.py',
        'tests/phase2/discord_p4_schema_fixture.sql', 'tests/phase2/postgres_discord_capacity.py',
        'tests/phase2/postgres_discord_authorization.py', 'tests/phase2/postgres_discord_connections.py',
        'tests/phase2/postgres_discord_worker.py', 'tests/phase2/postgres_discord_rate_limits.py',
        'tests/phase2/fixtures/discord_legacy_worker_claim_5f93f375.py.txt',
        'tests/test_discord_rate_limits.py', 'tests/test_discord_worker_lifecycle.py',
        'tests/test_discord_oauth_lifecycle.py', 'tests/test_discord_destinations.py',
        'tests/test_discord_publish_authorization.py', 'tests/test_discord_capacity_controls.py',
        'tests/test_discord_presend_retry.py', 'tests/test_postgres_pool_controls.py',
        'tests/test_discord_capacity_approval_receipt.py', 'tests/test_rafii_account_holds.py', 'tests/test_postriff_account_security.py',
        'tests/test_founder_product_events.py', 'tests/test_youtube_fleet.py',
    })
    # Explicit engagement UI, regression and cloud-wrapper inputs supplement every
    # original critical path and the complete src/migration inventory above.
    paths.update({
        'scripts/discord-engagement-cloud.sh',
        'tests/discord_engagement_reuse_proof.py',
        'tests/discord_engagement_ui_fixture.py',
        'tests/phase2/postgres_discord_engagement.py',
        'tests/test_discord_engagement.py',
        'web/package.json',
        'web/src/features/analytics/analytics-view.tsx',
        'web/src/features/channels/channel-card.tsx',
        'web/src/features/channels/discord-engagement-panel.tsx',
        'web/src/features/inbox/coverage-strip.tsx',
        'web/src/features/inbox/inbox-view.tsx',
        'web/src/lib/api/client.ts',
        'web/src/lib/api/types.ts',
        'web/src/lib/channels/discord-engagement.ts',
        'web/tests/discord-engagement-browser.cjs',
    })
    # Pin the additional guarded integration routing and its inert regression.
    paths.update({
        'scripts/postriff_pg_suite.py',
        'tests/test_postriff_pg_suite_controls.py',
        'scripts/discord-validation-cloud.sh',
        'scripts/discord-integrated-validation-cloud.sh',
        # Full-suite isolation fixtures and exact nonsecret classifications are release controls too.
        'tests/test_context_lens.py',
        'tests/test_pinterest_production_prep.py',
        'docs/consumer-ready/secret-allowlist.json',
    })
    return tuple(sorted(paths))

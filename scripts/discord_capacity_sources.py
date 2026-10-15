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
        'tests/test_discord_rate_limits.py', 'tests/test_discord_worker_lifecycle.py',
        'tests/test_discord_oauth_lifecycle.py', 'tests/test_discord_destinations.py',
        'tests/test_discord_publish_authorization.py', 'tests/test_discord_capacity_controls.py',
        'tests/test_discord_presend_retry.py', 'tests/test_postgres_pool_controls.py',
        'tests/test_discord_capacity_approval_receipt.py', 'tests/test_rafii_account_holds.py', 'tests/test_postriff_account_security.py',
        'tests/test_founder_product_events.py', 'tests/test_youtube_fleet.py',
    })
    return tuple(sorted(paths))

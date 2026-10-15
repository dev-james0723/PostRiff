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
    })
    return tuple(sorted(paths))

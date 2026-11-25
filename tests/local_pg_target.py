"""LOCAL TEST import adapter for nested tests; the phase2 helper owns policy.

Same selected_target contract as tests/phase2/local_pg_target.py. Historical
dedicated aliases are validated by each nested guard, never by a runner override.
"""
from phase2.local_pg_target import (
    DATABASES, DEFAULT_PORT, FIXTURE_DSN_KEYS, HOST, LIBPQ_OVERRIDES,
    PSQL_OVERRIDES, LocalPGTarget, bounded_port, selected_target,
)

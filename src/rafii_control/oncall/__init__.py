"""H-07 on-call engine (owner reply 15): routing by priority, deduplication, suppression, acknowledgement, the 5 and 10
minute escalation, duty hours in America/New_York, a Primary and Backup roster, storm limits, an audit trail, a
heartbeat about itself, and an optional automatic operator hold.

Pure and default off. Nothing imports this package from the running application: wiring it into the founder cron is a
reviewed integration step (docs/ops/H07-OPTIONS.md, option A), after the owner approves the flags and migration 140.
Providers are interfaces; the tests and drills use fakes, which prove the logic and nothing about delivery.
"""
import os

ENV_ENABLED = 'RAFII_ONCALL_ENGINE_ENABLED'
ENV_AUTO_HOLD = 'RAFII_ONCALL_AUTO_HOLD_ENABLED'


def enabled(values=None, name=ENV_ENABLED):
    """Exact string 'true', like the Discord flags; anything else (unset, 'TRUE', '1') is off."""
    values = os.environ if values is None else values
    return values.get(name) == 'true'

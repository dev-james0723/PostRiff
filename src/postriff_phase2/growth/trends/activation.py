"""Reviewed, narrow Stage 2 Bluesky activation manifest. No I/O or dispatch."""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
import json

from .contracts import PERMISSIONS, ContractError, canonical, instant, iso, uuid
from .policy import SourcePolicy
from .providers.bluesky import CAPABILITY, HOST, PATH, PROTOCOL

PROVIDER = 'bluesky'
OPERATION = 'live_sample'
POLICY_VERSION = 'stage2-20260928-v1'
CONTRACT_FROM = '2026-09-28T00:00:00Z'
CONTRACT_UNTIL = '2026-10-05T00:00:00Z'
REVIEW_REF = 'docs/superpowers/specs/2026-09-28-rafii-trends-live-acquisition-stage2.md'
REVIEWED_PROTOCOL = 'jetstream-v2-json@3fa54fdbb0f47ad3aa43de78a6fbbd8dc362f81d'
REVIEWED_ENDPOINT = 'wss://jetstream.us-west.bsky.network/xrpc/network.bsky.jetstream.subscribeEvents'
ALLOWED = frozenset({'retrieve', 'store_raw', 'store_metrics', 'display_excerpt',
                     'display_link', 'derive_metrics', 'retain_derivatives'})


def candidate(workspace_id: str, start_at: str, expires_at: str, *, now: str):
    wid = uuid(workspace_id)
    start, end, current = instant(start_at), instant(expires_at), instant(now)
    if (start < current - timedelta(hours=4) or start > current + timedelta(minutes=30)
            or end <= current or end > start + timedelta(hours=4)
            or start < instant(CONTRACT_FROM) or end > instant(CONTRACT_UNTIL)):
        raise ContractError('activation_window_invalid')
    if (CAPABILITY.provider_id, CAPABILITY.operation, CAPABILITY.version,
            CAPABILITY.endpoint, CAPABILITY.billable_unit) != (
                PROVIDER, OPERATION, REVIEWED_PROTOCOL, REVIEWED_ENDPOINT,
                'unmetered_live_bytes_bounded'):
        raise ContractError('capability_contract_changed')
    scope = 'workspace:' + wid
    until = iso(end)
    rights = {name: {'state': 'allow' if name in ALLOWED else 'deny',
                     'policy_ref': REVIEW_REF, 'audience_scope': scope, 'expires_at': until}
              for name in PERMISSIONS}
    policy = SourcePolicy(id='bluesky-internal-live-sample', version=POLICY_VERSION,
                          provider_id=PROVIDER, operation=OPERATION, scope_key=scope,
                          rights=rights, reviewed_by='internal-beta-owner', review_ref=REVIEW_REF,
                          effective_at=iso(start), expires_at=until, retention_seconds=86400,
                          readiness='ready', approved_attempt_cap_microusd=0)
    keys = [f'trend:stage2:{dimension}:{wid}' for dimension in ('system', 'provider', 'workspace')]
    schedule = {'enabled': True, 'start_at': iso(start), 'interval_seconds': 120,
                'max_samples': 120, 'max_items': 100, 'seconds': 5,
                'budget_keys': sorted(keys), 'reservation_microusd': 0}
    contract = {'provider_id': PROVIDER, 'version': PROTOCOL,
                'operations': sorted(ALLOWED), 'valid_from': CONTRACT_FROM,
                'expires_at': CONTRACT_UNTIL,
                'manifest': {'operation': OPERATION, 'endpoint': 'wss://' + HOST + PATH,
                             'protocol': PROTOCOL, 'billable_unit': CAPABILITY.billable_unit,
                             'review_ref': REVIEW_REF}}
    manifest = json.loads(canonical({**asdict(policy), 'schedule': schedule,
                                     'frontier': {'enabled': False}}))
    return {'contract': contract, 'policy': manifest,
            'budgets': [{'budget_key': key, 'dimension': dimension, 'cap_micro_usd': 0,
                         'period_start': iso(start), 'period_end': until}
                        for dimension, key in zip(('system', 'provider', 'workspace'), keys)]}

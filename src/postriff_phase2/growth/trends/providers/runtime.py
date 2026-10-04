"""Disabled-by-default reviewed bindings; no source, flag or budget is configured.

Endpoint selection belongs to immutable source policy metadata, never a queued
job. The existing worker requires flags, allowlist, current rights and an atomic
reservation before invoking either adapter. No import initiates network access.
"""
from dataclasses import replace
import time
import urllib.request

from .... import research
from ....coworker.research_broker import ResearchBroker, WebSearchProvider
from ..contracts import ContractError
from ..store import row
from .. import credit_admission
from . import mastodon, web
from .base import safe_url, _NoRedirect


def workspace_state(store, policy):
    if not policy.scope_key.startswith('workspace:'):
        raise ContractError('workspace_research_consent_required')
    with store.transaction() as cur:
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (policy.scope_key[10:],))
        value = row(cur)
    state = value['state'] if value else None
    if (not isinstance(state, dict) or state.get('accountDeletion')
            or research.consent(state).get('web') is not True or not research.allowed(state)):
        raise ContractError('workspace_research_consent_required')
    return state


class BoundedExaSearch(research.ExaSearch):
    """Existing broker search: two MCP requests with a combined time/byte cap."""
    def __init__(self, endpoint, *, clock=time.monotonic, authorize=None):
        super().__init__(url=endpoint, timeout=10)
        self.clock = clock
        self.deadline = clock() + 20
        self.remaining = web.CAPABILITY.max_response_bytes
        self.calls = 0
        self.authorize = authorize

    def _post(self, headers, body):
        remaining_time = self.deadline - self.clock()
        if self.calls >= 2 or remaining_time <= 0 or self.remaining <= 0:
            raise ContractError('web_transport_budget_exhausted')
        self.calls += 1
        url = safe_url(self.url, allowed_hosts=frozenset({'mcp.exa.ai'}))
        request = urllib.request.Request(url, method='POST', data=body,
            headers={'User-Agent':research.USER_AGENT, **headers})
        if self.authorize is not None:
            self.authorize()
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=min(10, remaining_time)) as response:
            data = response.read(self.remaining + 1)
            self.remaining -= len(data)
            if self.remaining < 0:
                raise ContractError('web_response_limit')
            return response.status, dict(response.headers), data.decode('utf-8', 'replace')


def binding(store, manifest, contract_version):
    """Return an inert binding or None; source-policy review remains independent."""
    identity = (manifest.get('provider_id'), manifest.get('operation'), contract_version)
    if identity == ('mastodon', 'public_timeline', mastodon.VERSION):
        instance = manifest.get('instance_url', '')
        cap = mastodon.capability(instance)
        # Public timeline only. This adds no credential resolver or entitlement.
        def collect_mastodon(*, policy, cursor, now, payload, reservation_microusd):
            credit_admission.require_provider_dispatch(store, policy.scope_key, cap, reservation_microusd)
            return mastodon.collect(instance=instance, policy=policy, cursor=cursor or None,
                enabled=True, entitlement_current=True, received_at=now, available_at=now,
                coverage_epoch=payload['coverage_epoch'], limit=payload['max_items'],
                reservation_microusd=reservation_microusd)
        return cap, collect_mastodon
    if identity == ('web', 'corroborate', web.VERSION):
        endpoint = manifest.get('corroboration_endpoint')
        if manifest.get('broker_provider_id') != 'exa_search' or endpoint != research.DEFAULT_EXA_URL:
            raise ContractError('unreviewed_research_endpoint')
        def collect_web(*, policy, cursor, now, payload, reservation_microusd):
            credit_admission.require_dispatch(store, policy.scope_key[10:])
            state = workspace_state(store, policy)
            denied = []
            def authorize():
                try:
                    credit_admission.require_dispatch(store, policy.scope_key[10:])
                except Exception as exc:
                    denied.append(exc)
                    raise
            backend = BoundedExaSearch(endpoint, authorize=authorize)
            broker = ResearchBroker(providers=[WebSearchProvider(backend=backend)], state=state)
            result = web.collect(broker=broker, query=payload.get('query'), policy=policy,
                enabled=True, entitlement_current=True, received_at=now, available_at=now,
                coverage_epoch=payload['coverage_epoch'], reservation_microusd=reservation_microusd,
                workspace_consent=True, scope_context={'workspace_id':policy.scope_key[10:], 'limit':6})
            # The existing broker catches AlphaError. Preserve this funding denial
            # as the truthful unavailable code rather than a generic empty batch.
            if denied:
                raise denied[0]
            return replace(result, bytes_received=web.CAPABILITY.max_response_bytes-backend.remaining)
        return web.CAPABILITY, collect_web
    return None

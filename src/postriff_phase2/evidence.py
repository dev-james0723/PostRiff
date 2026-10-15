"""Read-only Evidence Mode projections. Callers supply already-authorized workspace data.

No retrieval, confidence score, collection window or success timestamp is synthesized.
The common envelope describes a stored reading or attributed claim, never its truth.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Literal, TypedDict


class EvidenceSource(TypedDict):
    platform: str | None
    provider: str | None
    entityType: str
    entityId: str | None
    connectionId: str | None
    document: str | None
    href: str | None


class CollectionPeriod(TypedDict):
    start: str | None
    end: str | None
    basis: Literal['provider_reading', 'source_retrieval']


class EvidenceDefinition(TypedDict):
    name: str | None
    version: str | None
    description: str
    unit: str | None


class EvidenceEnvelope(TypedDict):
    schema: Literal['rafii.evidence.v1']
    workspaceId: str
    classification: Literal['observed', 'inferred', 'recommended']
    availability: str
    source: EvidenceSource
    collectionPeriod: CollectionPeriod
    lastSuccessfulSync: str | None
    definition: EvidenceDefinition
    uncertainty: list[str]


def instant(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        try:
            return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace('+00:00', 'Z')
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z') if parsed.tzinfo else None
        except ValueError:
            pass
    return None


def _text(value, limit=200):
    return value[:limit] if isinstance(value, str) and value else None


def _scope(workspace_id, *records):
    if not workspace_id or any(r.get('workspaceId', workspace_id) != workspace_id or r.get('workspace_id', workspace_id) != workspace_id or r.get('scope', 'workspace') != 'workspace' for r in records):
        raise ValueError('Evidence must belong to the authorized workspace')


def metric(workspace_id, post, name, reading) -> EvidenceEnvelope:
    _scope(workspace_id, post, reading)
    available = reading.get('availability') == 'available' and reading.get('value') is not None
    return {
        'schema': 'rafii.evidence.v1', 'workspaceId': workspace_id, 'classification': 'observed',
        'availability': reading.get('availability') or 'not_read',
        'source': {'platform': _text(post.get('platform') or post.get('provider')), 'provider': _text(post.get('provider')),
                   'entityType': 'provider_post', 'entityId': _text(post.get('providerPostId')), 'connectionId': _text(post.get('connectionId')),
                   'document': None, 'href': None},
        'collectionPeriod': {'start': instant(reading.get('periodStart')) if available else None, 'end': instant(reading.get('observedAt')) if available else None,
                             'basis': 'provider_reading'},
        'lastSuccessfulSync': instant(reading.get('ingestedAt')) if available else None,
        'definition': {'name': name, 'version': _text(reading.get('definitionVersion')),
                       'description': 'Native provider metric; counts are not unique people across platforms.', 'unit': _text(reading.get('unit'))},
        'uncertainty': ['Collection start is not recorded.'] if not instant(reading.get('periodStart')) else [],
    }


def source(workspace_id, record, *, claim=None, definition_version=None) -> EvidenceEnvelope:
    _scope(workspace_id, record, claim or {})
    origin = record.get('origin') or record.get('provenance') or {}
    status = (claim or {}).get('status') or 'attributed'
    available = record.get('available', True) and not record.get('retracted') and record.get('active', True)
    if not available:
        status = 'unavailable'
    # fetched/retrieved marks collection, not a successful provider sync.
    retrieved = instant(origin.get('fetchedAt') or origin.get('retrievedAt'))
    uncertainty = ['Source statements are attributed, not independently verified.']
    if claim:
        uncertainty = [f'Claim status: {status}.']
        if claim.get('qualification'):
            uncertainty.append(str(claim['qualification'])[:400])
        if (claim.get('freshness') or {}).get('stale'):
            uncertainty.append('The stored claim is marked stale.')
    return {
        'schema': 'rafii.evidence.v1', 'workspaceId': workspace_id, 'classification': 'observed', 'availability': status,
        'source': {'platform': _text(origin.get('provider') or origin.get('host')), 'provider': _text(origin.get('provider')),
                   'entityType': 'source_document',
                   'entityId': _text(record.get('id')), 'connectionId': None,
                   'document': _text(record.get('title')), 'href': _text(origin.get('url'), 1000)},
        'collectionPeriod': {'start': None, 'end': retrieved, 'basis': 'source_retrieval'},
        'lastSuccessfulSync': None,
        'definition': {'name': (claim or {}).get('claimType') or 'Source attribution', 'version': definition_version,
                       'description': _text((claim or {}).get('text'), 400) or 'Stored source attribution; not an account measurement.', 'unit': None},
        'uncertainty': uncertainty,
    }


def fact_pack(workspace_id, pack, sources):
    """Project existing claims without modifying the FactPack/hash or promoting a snippet."""
    _scope(workspace_id, pack)
    by_id = {s['id']: s for s in sources if s.get('id')}
    out = []
    for claim in (pack.get('claims') or [])[:30]:
        for relation in (claim.get('evidence') or [])[:8]:
            record = by_id.get(relation.get('sourceId'))
            if record is not None:
                out.append({'claimId': claim.get('claimId'), 'relation': relation.get('relation'),
                            'evidence': source(workspace_id, record, claim=claim, definition_version=pack.get('schema'))})
    return out

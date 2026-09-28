"""Content-free poison-record receipts and bounded, reviewed replay recovery.

Receipts are durable operational metadata, not retained provider evidence. Their
indexes refer only to the received batch. Unknown reason strings collapse to a
fixed code. Recovery never invents an offset or moves past unverified deletion
events: an adapter-specific reconciled checkpoint is required for skip recovery.
"""
import re

from .contracts import ContractError, digest, uuid
from .jobs import TrendJobs, partition_key as cursor_partition
from .outbox import TrendOutbox
from .planner import integer
from .store import row


REASONS = frozenset({'invalid_record', 'jetstream_invalid_frame', 'jetstream_invalid_record',
    'jetstream_identity_required', 'jetstream_sequence_required', 'jetstream_unknown_event',
    'mastodon_identity_required', 'mastodon_canonical_identity_required', 'mastodon_nonpublic_status',
    'invalid_number', 'provider_invalid_json', 'invalid_payload', 'invalid_timestamp',
    'source_right_not_permitted', 'unsafe_url', 'unsupported_language_tag'})
SCHEMA = 'trend.quarantine.v1'
# At the maximum permitted code/index/64-bit counters, 500 entries remain
# comfortably below the frozen64KiB jsonb::text constraint, including spaces.
RECEIPT_ENTRIES = 500


def sanitize_receipt(payload):
    required = {'schema_version', 'job_id', 'lease_generation', 'partition_key', 'generation',
                'accepted_count', 'quarantined_count', 'entries', 'completeness'}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ContractError('invalid_quarantine_receipt')
    if payload['schema_version'] != SCHEMA or payload['completeness'] != 'gap':
        raise ContractError('invalid_quarantine_receipt')
    partition = payload['partition_key']
    if not isinstance(partition, str) or not re.fullmatch('[0-9a-f]{64}', partition):
        raise ContractError('invalid_quarantine_partition')
    entries = payload['entries']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 1000:
        raise ContractError('invalid_quarantine_entries')
    count = integer(payload['quarantined_count'], 1, 1000, 'invalid_quarantine_count')
    if count != len(entries):
        raise ContractError('invalid_quarantine_count')
    safe, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'index', 'reason_code'}:
            raise ContractError('invalid_quarantine_entry')
        index = integer(entry['index'], 0, 9999, 'invalid_quarantine_index')
        if index in seen:
            raise ContractError('duplicate_quarantine_index')
        seen.add(index)
        code = entry['reason_code']
        safe.append({'index': index, 'reason_code': code if isinstance(code, str) and code in REASONS else 'invalid_record'})
    return {'schema_version': SCHEMA, 'job_id': uuid(payload['job_id']),
            'lease_generation': integer(payload['lease_generation'], 1, 2**63 - 1),
            'partition_key': partition, 'generation': integer(payload['generation'], 1, 2**63 - 1),
            'accepted_count': integer(payload['accepted_count'], 0, 1000),
            'quarantined_count': count, 'entries': sorted(safe, key=lambda e: e['index']), 'completeness': 'gap'}


def record_batch(store, claim, *, partition_key, expected_generation, quarantined, accepted_count, cursor):
    """Call in the SAME transaction as complete_batch(coverage_state='gap').

    The required caller cursor prevents an orphan receipt from a separate commit.
    A fenced claim and a subsequent durable batch are checked again at recovery.
    """
    if cursor is None:
        raise ContractError('quarantine_batch_transaction_required')
    if not quarantined:
        return None
    integer(expected_generation, 0, 2**63 - 2)
    payload = sanitize_receipt({'schema_version': SCHEMA, 'job_id': claim['job_id'],
        'lease_generation': claim['lease_generation'], 'partition_key': partition_key,
        'generation': expected_generation + 1, 'accepted_count': accepted_count,
        'quarantined_count': len(quarantined), 'entries': list(quarantined), 'completeness': 'gap'})
    current = TrendJobs(store)._fence(cursor, claim)
    if current['state'] != 'running' or current['kind'] != 'trend.ingest':
        raise ContractError('quarantine_running_ingest_required')
    key = 'quarantine:' + digest([claim['job_id'], claim['lease_generation']])
    outbox, primary = TrendOutbox(store), None
    # Preserve every safe index/code. All chunks commit or roll back with the
    # batch; the primary event keeps the existing API/idempotency identity.
    for offset in range(0, len(payload['entries']), RECEIPT_ENTRIES):
        entries = payload['entries'][offset:offset + RECEIPT_ENTRIES]
        chunk = {**payload, 'entries': entries, 'quarantined_count': len(entries)}
        event = outbox.enqueue(claim['scope_key'], key if offset == 0 else key + ':' + str(offset),
                               'trend.quarantined', chunk, cursor=cursor)
        if primary is None:
            primary = event
    return primary


def replay(store, planner, scope_key, event_id, *, cursor=None):
    """Persist one bounded replay from a committed, unadvanced quarantine cursor.

    Opt-in manifest.quarantine_recovery = {enabled: true, max_replays: 1..3}.
    The cap is per policy version and cursor partition across ALL poison batches;
    replaying a replay cannot reset the counter. Retry admission/cost reservation
    remains the worker's responsibility. Unknown original exposure blocks replay.
    """
    event_id = uuid(event_id)
    jobs = TrendJobs(store)
    with store.transaction(cursor) as cur:
        cur.execute("SELECT * FROM public.pr_trend_outbox WHERE scope_key=%s AND event_id=%s AND event_type='trend.quarantined' FOR UPDATE",
                    (scope_key, event_id))
        event = row(cur)
        if not event:
            raise ContractError('quarantine_receipt_missing')
        receipt = sanitize_receipt(event['payload'])
        # Different receipt chunks are ONE original dispatch. Resolve the
        # primary before replay deduplication so chunk IDs cannot multiply
        # recovery attempts or reset the reviewed partition-wide replay cap.
        primary_key = 'quarantine:' + digest([receipt['job_id'], receipt['lease_generation']])
        cur.execute("SELECT * FROM public.pr_trend_outbox WHERE scope_key=%s AND event_key=%s AND event_type='trend.quarantined'",
                    (scope_key, primary_key))
        primary = row(cur)
        if not primary:
            raise ContractError('quarantine_primary_missing')
        original = sanitize_receipt(primary['payload'])
        if any(original[k] != receipt[k] for k in ('job_id', 'lease_generation', 'partition_key', 'generation', 'accepted_count')):
            raise ContractError('quarantine_chunk_mismatch')
        event_id, receipt = primary['event_id'], original
        cur.execute('SELECT * FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s FOR SHARE',
                    (scope_key, receipt['job_id']))
        origin = row(cur)
        if not origin or origin['kind'] != 'trend.ingest' or origin['state'] != 'succeeded':
            raise ContractError('quarantine_batch_not_committed')
        policy, cap, controls, manifest = planner.admitted(cur, scope_key, origin['provider_id'],
                                                         origin['source_policy_version'], at=planner.clock())
        recovery = manifest.get('quarantine_recovery')
        if (not isinstance(recovery, dict) or set(recovery) != {'enabled', 'max_replays'}
                or recovery['enabled'] is not True):
            raise ContractError('quarantine_recovery_not_reviewed')
        maximum = integer(recovery['max_replays'], 1, 3, 'quarantine_replay_bound')
        expected_partition = cursor_partition(instance_id=cap.endpoint, protocol_version=cap.version,
            filter_digest=digest({'operation': policy.operation, 'scope': policy.scope_key, 'filter': {}}))
        if expected_partition != receipt['partition_key']:
            raise ContractError('quarantine_partition_mismatch')
        domain = digest([scope_key, origin['provider_id'], origin['source_policy_version'], receipt['partition_key']])
        prefix = 'quarantine-replay:' + domain + ':'
        key = prefix + event_id
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (prefix,))
        cur.execute('SELECT * FROM public.pr_trend_jobs WHERE scope_key=%s AND idempotency_key=%s', (scope_key, key))
        existing = row(cur)
        if existing:
            return existing
        cur.execute("""SELECT count(*) AS n FROM public.pr_trend_ingestion_batches
            WHERE scope_key=%s AND job_id=%s AND fence=%s AND partition_key=%s AND next_generation=%s""",
            (scope_key, origin['job_id'], receipt['lease_generation'], receipt['partition_key'], receipt['generation']))
        if row(cur)['n'] != 1:
            raise ContractError('quarantine_batch_not_committed')
        if origin.get('reservation_id'):
            cur.execute('SELECT state FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s FOR SHARE',
                        (scope_key, origin['reservation_id']))
            reservation = row(cur)
            if not reservation or reservation['state'] not in ('settled', 'released'):
                raise ContractError('quarantine_unknown_exposure')
        cur.execute('''SELECT * FROM public.pr_trend_provider_cursors
            WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE''',
            (scope_key, origin['provider_id'], receipt['partition_key']))
        checkpoint = row(cur)
        if not checkpoint or checkpoint['generation'] != receipt['generation'] or checkpoint['coverage_state'] != 'gap':
            raise ContractError('quarantine_cursor_changed')
        cur.execute("SELECT count(*) AS n FROM public.pr_trend_jobs WHERE scope_key=%s AND idempotency_key LIKE %s",
                    (scope_key, prefix + '%'))
        if row(cur)['n'] >= maximum:
            raise ContractError('quarantine_replay_exhausted')
        payload = planner.payload(policy, controls, 'recovery:' + digest([domain, event_id]))
        payload['quarantine_event_id'] = event_id
        # No cursor mutation: untrusted sequence values cannot skip deletion or
        # account events. A new epoch keeps replay coverage explicitly separate.
        return jobs.enqueue(scope_key, 'trend.ingest', payload, idempotency_key=key,
            provider_id=policy.provider_id, source_policy_version=policy.version,
            due_at=planner.clock(), max_attempts=cap.max_attempts, cursor=cur)

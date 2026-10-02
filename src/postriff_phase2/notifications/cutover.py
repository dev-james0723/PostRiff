"""Admission before real egress: immutable approval, new events and durable dedupe.

The dispatch marker commits before sending. Retrying the exact payload within
the provider window is safe; after 24h or a changed payload, retain uncertainty
for reconciliation. Neither flags nor provider keys create an approval record.
"""
import hashlib
import json

WINDOW = 24 * 3600
# PostgreSQL stores timestamp values to microseconds. Refuse at the boundary
# conservatively even when rounding the committed dispatch time up by 0.5 us.
TIMESTAMP_MARGIN = 0.000001


def admit(factory, rows, contexts, message, *, now, channel='email', reserve=None, linked_delivery_id='row'):
    if channel not in ('email', 'push'):
        return {'state': 'config', 'detail': 'delivery_cutover_channel_invalid'}
    if not rows or len(rows) != len(contexts):
        return {'state': 'config', 'detail': 'delivery_cutover_context_missing'}
    audiences = {'founder' if ctx['type'].startswith('founder.') else 'customer' for ctx in contexts}
    if len(audiences) != 1:
        return {'state': 'config', 'detail': 'delivery_cutover_mixed_audience'}
    audience = next(iter(audiences))
    key = message['idempotencyKey']
    provider = 'resend_dispatch' if channel == 'email' else 'webpush_dispatch'
    digest = hashlib.sha256(json.dumps(message, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    try:
        with factory() as db, db.cursor() as cur:
            cur.execute("SELECT revision,mode,extract(epoch from not_before),recipient_user_ids,max_messages,template_version,approval_ref "
                        "FROM public.pr_delivery_cutovers WHERE audience=%s AND channel=%s ORDER BY revision DESC LIMIT 1", (audience, channel))
            policy = cur.fetchone()
            if not policy or policy[1] == 'disabled':
                return {'state': 'config', 'detail': 'delivery_cutover_not_approved'}
            revision, mode, not_before, recipients, cap, version, ref = policy
            if version != str(message.get('templateVersion')):
                return {'state': 'config', 'detail': 'delivery_cutover_template_mismatch'}
            if now < float(not_before) or any(ctx.get('occurredAt') is None or ctx['occurredAt'] < float(not_before) for ctx in contexts):
                return {'state': 'config', 'detail': 'delivery_before_cutover'}
            if mode == 'canary_only' and any(row['userId'] not in {str(user) for user in recipients} for row in rows):
                return {'state': 'config', 'detail': 'delivery_outside_canary_scope'}
            # Serialize quota admission; retry of the same key consumes no quota.
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (channel + '_cutover:' + audience + ':' + ref,))
            cur.execute("SELECT extract(epoch from event_at),payload_digest FROM public.pr_notification_provider_events "
                        "WHERE provider=%s AND event_id=%s", (provider, key))
            old = cur.fetchone()
            if old:
                if channel == 'push' or now - float(old[0]) >= WINDOW - TIMESTAMP_MARGIN or old[1] != digest:
                    return {'state': 'uncertain', 'detail': channel + '_reconciliation_required'}
            else:
                cur.execute("SELECT count(*) FROM public.pr_notification_provider_events WHERE provider=%s AND kind=%s", (provider, audience + ':' + ref))
                if cur.fetchone()[0] >= cap:
                    return {'state': 'config', 'detail': 'delivery_cutover_cap_reached'}
                cur.execute("INSERT INTO public.pr_notification_provider_events(provider,event_id,delivery_id,kind,event_at,payload_digest,outcome) "
                            "VALUES(%s,%s,%s,%s,to_timestamp(%s),%s,'applied') ON CONFLICT DO NOTHING",
                            (provider, key, rows[0]['id'] if linked_delivery_id == 'row' else linked_delivery_id, audience + ':' + ref, now, digest))
            if reserve:
                reserve(cur)
            db.commit()
        return None
    except Exception:
        return {'state': 'config', 'detail': 'delivery_cutover_source_unavailable'}

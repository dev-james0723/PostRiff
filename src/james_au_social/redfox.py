"""Read-only signal acceptance, separate from any credential-bearing connector."""
from datetime import timedelta
from .execution import instant, payload_hash

READ_OPERATIONS = {'search','trend','detail','audience_questions','public_comments'}
PLATFORMS = {'xiaohongshu','douyin','wechat','bilibili','kuaishou'}

def accept_signal(policy, signal, *, now):
    fields={'operation','platform','query','provider_version','retrieved_at','window_start','window_end',
            'cost_minor','quota_remaining','source_refs'}
    if set(signal)!=fields:
        raise ValueError('signal_metadata_or_secret_field')
    if signal['operation'] not in READ_OPERATIONS or signal['operation'] not in policy['allowed_operations']:
        raise ValueError('read_operation_not_approved')
    if signal['platform'] not in PLATFORMS or signal['platform'] not in policy['platforms'] or signal['provider_version']!=policy['version']:
        raise ValueError('provider_scope_drift')
    if type(signal['cost_minor']) is not int or signal['cost_minor']!=0:
        raise ValueError('separate_paid_connector_authorization_required')
    if type(signal['quota_remaining']) is not int or signal['quota_remaining']<0 or not signal['source_refs']:
        raise ValueError('quota_or_provenance_missing')
    start,end,retrieved,current=map(instant,(signal['window_start'],signal['window_end'],signal['retrieved_at'],now))
    if not start<=end<=retrieved<=current:
        raise ValueError('invalid_signal_time_window')
    return {'signal':signal,'signal_hash':payload_hash(signal),'source_tier':'discovery_only',
            'establishes_facts':False,'establishes_james_view':False,
            'state':'stale' if current-retrieved>timedelta(hours=24) else 'discovery_ready',
            'external_operations':[]}

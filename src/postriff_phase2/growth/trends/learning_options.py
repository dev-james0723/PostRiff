"""Current server-derived metric-choice controls for the existing Performance UI."""
from copy import deepcopy
from . import contracts, learning, opportunities
from ...insights import INSIGHT_METRICS, DEFINITION_VERSION
from postriff_alpha.domain import AlphaError


def choices(store, cur, workspace_id, actor_id, state, now):
    channels = {c['id']:c for c in state.get('phase2',{}).get('channels',[]) if not c.get('revoked')}
    saved = state.get('coworker',{}).get('trendLearning',{}).get('metricChoices',[])[-100:]
    selected=[];seen=set()
    for source in state.get('sources',[])[-100:]:
        binding=source.get('origin',{}).get('trendLineage',{})
        channel=channels.get(binding.get('channel_id'))
        provider=str(channel.get('platform','')).lower() if channel else ''
        if (not source.get('active') or not binding.get('selection_digest') or provider not in INSIGHT_METRICS
                or binding['selection_digest'] in seen):
            continue
        try:
            opportunities.validate_lineage(state,opportunities.lineage(state,[source['id']]),now)
            op=store.get_projection(workspace_id,actor_id,'opportunity',binding['opportunity_id'],revision=binding['opportunity_revision'],cursor=cur)
            receipt=store.get_projection(workspace_id,actor_id,'receipt',binding['trust_receipt_id'],cursor=cur)
            if (not learning._valid(op,now) or not learning._valid(receipt,now)
                    or receipt.get('verification_state')!='verified' or op['scope_key']!='workspace:'+workspace_id
                    or op['payload'].get('trust_receipt_id')!=binding['trust_receipt_id']):
                continue
        except (contracts.ContractError,AlphaError,KeyError,ValueError,TypeError):
            continue
        prior=[c for c in saved if c.get('selection_digest')==binding['selection_digest'] and c.get('channel_id')==channel['id']
               and c.get('provider')==provider and c.get('definition_version')==DEFINITION_VERSION and c.get('confirmed') is True
               and c.get('metric') in INSIGHT_METRICS[provider] and c.get('window') in learning.WINDOWS
               and c.get('objective') in learning.OBJECTIVES and c.get('denominator_metric') in (None,*INSIGHT_METRICS[provider])]
        previous=deepcopy(prior[-1]) if prior else None
        if previous is not None and previous.get('denominator_metric') is None:
            previous.pop('denominator_metric',None)
        selected.append({'selection_digest':binding['selection_digest'],'source_id':source['id'],'source_label':'Saved trend idea',
            'channel_id':channel['id'],'channel_label':str(channel.get('name') or channel.get('label') or channel['platform'])[:200],
            'provider':provider,'metrics':list(INSIGHT_METRICS[provider]),'definition_version':DEFINITION_VERSION,
            'windows':list(learning.WINDOWS),'objectives':sorted(learning.OBJECTIVES),
            'saved_choice':previous})
        seen.add(binding['selection_digest'])
        if len(selected)>=20:break
    return selected


def require_choice(options,payload):
    if (not isinstance(payload,dict) or 'denominator_metric' in payload and payload['denominator_metric'] is None
            or not any(all(payload.get(k)==o[k] for k in
            ('selection_digest','channel_id','provider','definition_version'))
            and payload.get('metric') in o['metrics'] and payload.get('denominator_metric') in (None,*o['metrics'])
            and payload.get('window') in o['windows'] and payload.get('objective') in o['objectives'] for o in options)):
        raise ValueError('current_metric_choice_required')

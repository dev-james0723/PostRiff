"""Founder-only preview services over the EXISTING actor-isolated Demo JSONB row.

The caller owns authentication, CSRF, locked revision/replay checks, persistence
and audit. These reducers perform no I/O. A result becomes durable only when the
caller's transaction commits. There is no scheduler, model, phone or mail dispatch.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_phase2.agent_runtime_v2.contracts import empty_result, new_trace_id
from .auth import ControlError
from .intelligence import QueryService, canonical

ACTIONS = frozenset({'founder_turn', 'founder_reminder', 'founder_report_schedule',
                     'founder_delivery', 'founder_follow_up', 'founder_voice', 'founder_summary',
                     'founder_follow_up_update', 'founder_schedule_tick', 'set_scenario'})
CHARTS = {'plan-distribution':'planDistribution', 'revenue-trend':'revenueTrend',
          'usage-distribution':'usageDistribution', 'support-distribution':'supportDistribution'}
TIME_ZONE = 'America/Indiana/Indianapolis'


def _id(value):
    try: return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError): raise ControlError('VALIDATION_FAILED',400) from None


def _text(value, limit=1600):
    if not isinstance(value,str) or not 1 <= len(value.strip()) <= limit or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise ControlError('VALIDATION_FAILED',400)
    return value.strip()


def _fields(payload, required, optional=()):
    if not isinstance(payload,dict) or not set(required) <= set(payload) or set(payload)-set(required)-set(optional):
        raise ControlError('VALIDATION_FAILED',400)


def _require(data, principal):
    QueryService.require(principal,'control.read')
    QueryService.require(principal,'copilot.use')
    QueryService.require(principal,'metrics.query')
    operator, session = principal.get('operator',{}),principal.get('session',{})
    if operator.get('role')!='founder' or operator.get('status')!='active': raise ControlError('FOUNDER_REQUIRED')
    if session.get('assurance')!='aal2': raise ControlError('STEP_UP_REQUIRED')
    actor = _id(operator.get('user_id'))
    if (session.get('revoked_at') is not None or session.get('expires_at',0)<=time.time() or
        session.get('environment')!=operator.get('environment') or
        session.get('auth_epoch')!=operator.get('auth_epoch')): raise ControlError('AUTH_REQUIRED',401)
    if data.get('mode')!='demo': raise ControlError('SCOPE_DENIED')
    stored=data.get('founderIntelligence')
    if stored and (stored.get('operatorId')!=actor or stored.get('environment')!=session['environment']):
        raise ControlError('SCOPE_DENIED')
    # Derived messages/reports/summaries and cached action responses retain
    # customer context. Recheck its CURRENT grant before any read or mutation.
    for conversation in (stored or {}).get('conversations',[]):
        for turn in conversation.get('turns',[]):
            selection=turn.get('chartContext',{}).get('selectedEntity')
            if selection:
                QueryService.require(principal,'workspaces.read' if selection['collection']=='workspaces' else 'customers.read')
    return actor,session['environment']


def _empty(actor, environment):
    return dict(version=1,mode='demo',operatorId=actor,environment=environment,timeZone=TIME_ZONE,
                conversations=[],reports=[],schedules=[],followUps=[],contactAttempts=[],summaries=[])


def _receipt(data):
    # The dataset owner is the only receipt/metric definition owner.
    from .demo_dataset import receipt
    return copy.deepcopy(receipt(data))


def _entity(data, selection, principal):
    _fields(selection,('collection','id'))
    collection,ref=selection['collection'],selection['id']
    if collection not in ('customers','workspaces','invoices') or not isinstance(ref,str) or not re.fullmatch('[A-Za-z0-9-]{1,80}',ref):
        raise ControlError('VALIDATION_FAILED',400)
    QueryService.require(principal,'workspaces.read' if collection=='workspaces' else 'customers.read')
    row=next((r for r in data.get(collection,[]) if r['id']==ref),None)
    if row is None: raise ControlError('SCOPE_DENIED')
    fields=('id','name','company','plan','billingCycle','status','workspaceIds','workspaceId',
            'memberCount','creditsQuota','creditsUsed','creditsRemaining','amountMinor','currency','period')
    return {key:copy.deepcopy(row[key]) for key in fields if key in row}


def _context(data, payload, environment, principal):
    _fields(payload,('chartId','viewVersion','queryReceiptId','mode','environment'),('selectedSeries','selectedEntity'))
    if (not isinstance(payload['chartId'],str) or payload['chartId'] not in CHARTS or type(payload['viewVersion']) is not int or payload['viewVersion']!=1 or
        payload['mode']!='demo' or payload['environment']!=environment): raise ControlError('SCOPE_DENIED')
    if payload['queryReceiptId']!=_receipt(data)['id']: raise ControlError('STALE_PREVIEW',409)
    series=payload.get('selectedSeries',[])
    if not isinstance(series,list) or len(series)>10 or any(not isinstance(s,str) or len(s)>80 for s in series):
        raise ControlError('VALIDATION_FAILED',400)
    rows=copy.deepcopy(data.get('analytics',{}).get(CHARTS[payload['chartId']],[]))
    if not isinstance(rows,list) or len(rows)>1000: raise ControlError('BUDGET_EXCEEDED',400)
    entity=_entity(data,payload['selectedEntity'],principal) if 'selectedEntity' in payload else None
    return copy.deepcopy(payload),rows,entity


def _find(state, collection, ref):
    row=next((r for r in state.get(collection,[]) if r['id']==ref),None)
    if row is None: raise ControlError('SCOPE_DENIED')
    return row


def _incidents(data):
    # Only safe server-owned scenario observations enter conversation/email context.
    allowed=('id','title','severity','state','affectedCount','affectedWorkspaceIds','affectedSourceIds',
             'affectedRecords','observedAt','known','unknown','episodeId','timeline','acknowledged','notificationState')
    out=[]
    for incident in data.get('incidents',[])[:20]:
        safe={key:copy.deepcopy(incident[key]) for key in allowed if key in incident}
        if safe.get('id'): out.append(safe)
    return out


def _explain(data, message, rows, chart):
    text=message.casefold()
    stale=data.get('scenario')=='stale_data' or data.get('dataState') in ('stale','unavailable','partial')
    if stale:
        return ('Demo simulation. Source data is stale or incomplete. The last-good snapshot is '+str(data.get('asOf'))+
                '; current business performance is unavailable. Review Connections before interpreting changes.'),True,[]
    if any(s in text for s in ('plan','subscriber','訂閱','人數','最多','explain this chart','explain chart')):
        descriptions=[]
        for row in rows:
            if 'subscribers' in row:
                descriptions.append(f"{row.get('plan',row.get('label','Selected series'))}: {row['subscribers']:,} subscribers")
            elif 'revenueMinor' in row:
                descriptions.append(f"{row['period']}: invoiced amount {row['revenueMinor']} minor units; cash {row['cashMinor']} minor units ({row['currency']})")
            elif 'count' in row: descriptions.append(f"{row.get('status','Selected series')}: {row['count']:,}")
        if descriptions:
            return 'Demo simulation; fictional data, not live AI. '+ '; '.join(descriptions)+'. Values use the selected chart receipt.',True,[]
    if any(s in text for s in ('payment','invoice','付款','發票')):
        failed=[r for r in data.get('invoices',[]) if r.get('status') in ('failed','past_due','open')][:10]
        links=[dict(kind='invoice',id=r['id'],workspaceId=r.get('workspaceId')) for r in failed]
        return ('Demo simulation. '+str(len(failed))+' displayed invoice exceptions; total failed payments '+
                str(data.get('summary',{}).get('failedPayments','unavailable'))+'. No charge or reminder was sent.'),True,links
    if any(s in text for s in ('bug','outage','incident','影響','故障','known','未知','email','電郵')):
        incidents=_incidents(data)
        if incidents:
            descriptions=[f"{r.get('title','Incident')}: {r.get('state','open')}; affected count {r.get('affectedCount','unavailable')}. Root cause remains unverified." for r in incidents]
            return 'Demo simulation. '+' '.join(descriptions),True,[dict(kind='incident',id=r['id']) for r in incidents]
        return 'Demo simulation. No qualified incident observation is present in this scenario. Impact and root cause are unavailable.',True,[]
    if any(s in text for s in ('remind','follow-up','follow up','提醒','跟進')):
        return 'Demo simulation. Prepare an exact reminder date, time and timezone, then confirm it in the sandbox. No real notification will be sent.',True,[]
    return ('Demo simulation; live model access has not been verified. This free-text question is unsupported by the deterministic preview. '
            'Ask about a selected chart, invoice exceptions, incident evidence or a sandbox reminder. No action was performed.'),False,[]


def _turn(data, state, payload, request_id, now, principal, *, evidence=None):
    _fields(payload,('message','conversationId','chartContext'),('modality',))
    message=_text(payload['message'])
    modality=payload.get('modality','text')
    if modality not in ('text','voice'): raise ControlError('VALIDATION_FAILED',400)
    if evidence:
        context,rows,receipt=evidence['chartContext'],copy.deepcopy(evidence['evidenceRows']),copy.deepcopy(evidence['receipt'])
        if 'selectedEntity' in context:
            QueryService.require(principal,'workspaces.read' if context['selectedEntity']['collection']=='workspaces' else 'customers.read')
        entity=copy.deepcopy(evidence.get('selectedEntityFacts'))
    else:
        context,rows,entity=_context(data,payload['chartContext'],state['environment'],principal)
        receipt=_receipt(data)
    conversation_id=payload['conversationId']
    if conversation_id is None:
        if len(state['conversations'])>=20: raise ControlError('BUDGET_EXCEEDED',400)
        conversation=dict(id=str(uuid.uuid4()),createdAt=now,turns=[],voice=dict(state='text',generationId=0))
        state['conversations'].append(conversation)
    else: conversation=_find(state,'conversations',_id(conversation_id))
    if len(conversation['turns'])>=50: raise ControlError('BUDGET_EXCEEDED',400)
    historical=receipt['id']!=_receipt(data)['id']
    read_data=data if not evidence else dict(scenario=receipt.get('scenario','normal'),asOf=receipt.get('asOf'),dataState=receipt.get('dataState'),
                                             summary={},incidents=[],analytics={})
    answer,supported,links=_explain(read_data,message,rows,context['chartId'])
    stale=read_data.get('scenario')=='stale_data' or read_data.get('dataState') in ('stale','unavailable','partial') or receipt.get('dataState') in ('stale','unavailable','partial')
    if entity and stale:
        answer+=' The selected fictional entity reflects that last-good snapshot; its current status and balance are unavailable.'
    elif entity and any(s in message.casefold() for s in ('customer','workspace','invoice','maya','客戶','工作區','發票')):
        description='; '.join(f'{key}: {value}' for key,value in entity.items() if key not in ('workspaceIds',))
        answer='Demo simulation; selected fictional '+context['selectedEntity']['collection']+' evidence. '+description+'. No account or financial change was performed.'
        supported=True
        links=[dict(kind={'customers':'customer','workspaces':'workspace','invoices':'invoice'}[context['selectedEntity']['collection']],id=entity['id'])]
    if historical: answer='Historical Demo snapshot as of '+str(receipt.get('asOf'))+'. '+answer
    result=empty_result(new_trace_id(),modality)
    result.update(runId=request_id,conversationId=conversation['id'],namespace='founder',mode='demo_simulation',
                  state='completed' if supported else 'blocked',answerText=answer,speakableSummary=answer,
                  evidenceRows=rows,selectedEntityFacts=entity,queryReceiptIds=[receipt['id']],chartContext=context,receipt=receipt,
                  scenario=receipt.get('scenario','normal'),historicalContext=historical,createdAt=now,links=links,externalDelivery=False,
                  usage=dict(providerCalls=0,costState='not_applicable',costCenter='founder_operations'),
                  warnings=[dict(code='DEMO_SIMULATION',message='Deterministic simulation; no live model or voice connected.')])
    conversation['turns'].append({**copy.deepcopy(result),'question':message})
    return result


def resolve_local_time(value, zone):
    """First fold; a DST gap advances to its first valid minute. No invented time."""
    try:
        tz=ZoneInfo(zone)
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00',value): raise ValueError()
        local=datetime.fromisoformat(value)
        for _ in range(181):
            aware=local.replace(tzinfo=tz,fold=0)
            utc=aware.astimezone(timezone.utc)
            if utc.astimezone(tz).replace(tzinfo=None)==local: return utc.isoformat()
            local+=timedelta(minutes=1)
    except (ValueError,TypeError,ZoneInfoNotFoundError): pass
    raise ControlError('VALIDATION_FAILED',400)


def _schedule(data,state,payload,now,report=False):
    required=('conversationId','dueLocal','timeZone','confirmed')+ (('kind',) if report else ('intent',))
    _fields(payload,required)
    conversation=_find(state,'conversations',_id(payload['conversationId']))
    if not conversation['turns']: raise ControlError('SCOPE_DENIED')
    if type(payload['confirmed']) is not bool: raise ControlError('VALIDATION_FAILED',400)
    try: ZoneInfo(payload['timeZone'])
    except (ValueError,TypeError,ZoneInfoNotFoundError): raise ControlError('VALIDATION_FAILED',400) from None
    due=resolve_local_time(payload['dueLocal'],payload['timeZone']) if payload['dueLocal'] else None
    if payload['confirmed'] and due is None: raise ControlError('TIME_NOT_SELECTED',400)
    if due and datetime.fromisoformat(due)<=datetime.fromisoformat(now.replace('Z','+00:00')):
        raise ControlError('STALE_PREVIEW',409)
    if report and payload['kind'] not in ('daily','weekly'): raise ControlError('VALIDATION_FAILED',400)
    intent=payload['kind']+' report' if report else _text(payload['intent'],300)
    digest=hashlib.sha256(canonical(payload).encode()).hexdigest()
    collection='schedules' if report else 'followUps'
    previous=next((r for r in state[collection] if r['sourceDigest']==digest),None)
    if previous: return copy.deepcopy(previous)
    if len(state[collection])>=50: raise ControlError('BUDGET_EXCEEDED',400)
    last=conversation['turns'][-1]
    row=dict(id=str(uuid.uuid4()),conversationId=conversation['id'],sourceDigest=digest,
             sourceIdentity='conversation:'+conversation['id'],intent=intent,dueLocal=payload['dueLocal'],
             timeZone=payload['timeZone'],dueAt=due,state='scheduled' if payload['confirmed'] else 'draft',
             queryReceiptIds=list(last['queryReceiptIds']),createdAt=now,simulation=True,externalDelivery=False,
             schedulerActivated=False,deliveryMode='sandbox',revision=1)
    state[collection].append(row)
    if report:
        row['kind']=payload['kind']
        briefing=dict(id=str(uuid.uuid4()),scheduleId=row['id'],conversationId=conversation['id'],
                      kind=payload['kind'],state='ready',createdAt=now,queryReceiptIds=list(last['queryReceiptIds']),
                      receipt=copy.deepcopy(last['receipt']),chartContext=copy.deepcopy(last['chartContext']),
                      evidenceRows=copy.deepcopy(last['evidenceRows']),text=last['answerText'],
                      selectedEntityFacts=copy.deepcopy(last.get('selectedEntityFacts')),
                      simulation=True,externalDelivery=False,deliveryMode='sandbox',version=1)
        state['reports'].append(briefing)
        row['reportId']=briefing['id']
    return copy.deepcopy(row)


def _summary(state,payload,now):
    _fields(payload,('conversationId',))
    conversation=_find(state,'conversations',_id(payload['conversationId']))
    if not conversation['turns']: raise ControlError('SCOPE_DENIED')
    last=conversation['turns'][-1]
    existing=next((r for r in state['summaries'] if r['lastRunId']==last['runId']),None)
    if existing: return copy.deepcopy(existing)
    if len(state['summaries'])>=50: raise ControlError('BUDGET_EXCEEDED',400)
    receipts=list(dict.fromkeys(ref for turn in conversation['turns'] for ref in turn['queryReceiptIds']))
    row=dict(id=str(uuid.uuid4()),conversationId=conversation['id'],lastRunId=last['runId'],createdAt=now,
             queryReceiptIds=receipts,text=last['answerText'],turnCount=len(conversation['turns']),
             followUpIds=[r['id'] for r in state['followUps'] if r['conversationId']==conversation['id']],
             humanAcknowledged=False,simulation=True,externalDelivery=False)
    state['summaries'].append(row)
    return copy.deepcopy(row)


def _apply(data,state,action,payload,now,principal):
    kind,request_id=action['action'],action['requestId']
    if kind=='founder_turn': return _turn(data,state,payload,request_id,now,principal)
    if kind in ('founder_reminder','founder_report_schedule'):
        return _schedule(data,state,payload,now,kind=='founder_report_schedule')
    if kind=='founder_summary': return _summary(state,payload,now)
    if kind=='founder_delivery':
        from .founder_preview_delivery import delivery_action
        source=payload.get('sourceId')
        if not any(r['id']==source for name in ('reports','followUps') for r in state[name]) and not any(r['id']==source for r in _incidents(data)+data.get('notificationEvents',[])):
            raise ControlError('SCOPE_DENIED')
        result=delivery_action(state,payload,request_id=request_id,now=now)
        return result['attempt']
    if kind=='founder_follow_up':
        _fields(payload,('attemptId','message'))
        attempt=_find(state,'contactAttempts',payload['attemptId'])
        if attempt['channel']!='call' or attempt['state']!='live': raise ControlError('SCOPE_DENIED')
        report=_find(state,'reports',attempt['sourceId'])
        conversation=_find(state,'conversations',report['conversationId'])
        return _turn(data,state,dict(message=payload['message'],conversationId=conversation['id'],
                     chartContext=report['chartContext'],modality='voice'),request_id,now,principal,evidence=report)
    if kind=='founder_voice':
        _fields(payload,('conversationId','operation'),('generationId',))
        conversation=_find(state,'conversations',_id(payload['conversationId']))
        states={'start':'listening','stop':'stopped','interrupt':'interrupted','repeat':'playing','text':'text'}
        operation=payload['operation']
        if not isinstance(operation,str) or operation not in states: raise ControlError('VALIDATION_FAILED',400)
        voice=conversation['voice']
        if 'generationId' in payload and payload['generationId']!=voice['generationId']: raise ControlError('STALE_PREVIEW',409)
        voice.update(state=states[operation],generationId=voice['generationId']+1,liveVoiceConnected=False,
                     simulation=True,externalDelivery=False,recording=False)
        if operation=='repeat': voice['speakableSummary']=conversation['turns'][-1]['speakableSummary'] if conversation['turns'] else ''
        else: voice.pop('speakableSummary',None)
        return copy.deepcopy(voice)
    if kind=='founder_follow_up_update':
        _fields(payload,('id','state','revision'))
        row=_find(state,'followUps',payload['id'])
        if type(payload['revision']) is not int or payload['revision']!=row['revision']: raise ControlError('STALE_PREVIEW',409)
        if payload['state'] not in ('completed','cancelled') or row['state'] in ('completed','cancelled'):
            raise ControlError('VALIDATION_FAILED',400)
        row.update(state=payload['state'],revision=row['revision']+1,updatedAt=now)
        return copy.deepcopy(row)
    if kind=='founder_schedule_tick':
        _fields(payload,())
        current=datetime.fromisoformat(now.replace('Z','+00:00'))
        due=[]
        for schedule in state['schedules']+state['followUps']:
            if schedule['state']!='scheduled' or datetime.fromisoformat(schedule['dueAt'])>current: continue
            elapsed=(current-datetime.fromisoformat(schedule['dueAt'])).total_seconds()
            schedule.update(state='missed' if elapsed>900 else 'due',revision=schedule['revision']+1)
            due.append(schedule['id'])
        return dict(state='sandbox_tick',dueIds=due,simulation=True,externalDelivery=False,schedulerActivated=False)
    raise ControlError('SCOPE_DENIED')


def reduce_action(data, action, principal, *, now=None):
    """Called only within WorkspaceService's existing locked Demo transaction."""
    actor,environment=_require(data,principal)
    _fields(action,('action','targetId','value','revision','requestId'))
    if not isinstance(action['action'],str) or action['action'] not in ACTIONS: raise ControlError('SCOPE_DENIED')
    if type(action['revision']) is not int or action['revision']!=data.get('revision'): raise ControlError('STALE_PREVIEW',409)
    if not isinstance(action['targetId'],str) or not re.fullmatch('[A-Za-z0-9-]{1,80}',action['targetId']): raise ControlError('VALIDATION_FAILED',400)
    request_id=_id(action['requestId'])
    if not isinstance(action['value'],str) or len(action['value'].encode())>4000: raise ControlError('BUDGET_EXCEEDED',400)
    if action['action']=='set_scenario':
        from .founder_preview_scenarios import apply_scenario
        if action['targetId']!='scenario': raise ControlError('VALIDATION_FAILED',400)
        # The scenario service validates linked sources before mutation. Outer
        # WorkspaceService holds the actor/environment row and owns its commit.
        result=apply_scenario(data,action['value'],now=now or datetime.now(timezone.utc).isoformat())
        if 'founderIntelligence' not in data: data['founderIntelligence']=_empty(actor,environment)
        data['founderIntelligence']['lastActionResult']=copy.deepcopy(result)
        return result
    try: payload=json.loads(action['value'])
    except (ValueError,TypeError): raise ControlError('VALIDATION_FAILED',400) from None
    if not isinstance(payload,dict): raise ControlError('VALIDATION_FAILED',400)
    state=copy.deepcopy(data.get('founderIntelligence') or _empty(actor,environment))
    # Transactional copy: an invalid action never leaves partial state in caller memory.
    result=_apply(data,state,{**action,'requestId':request_id},payload,now or datetime.now(timezone.utc).isoformat(),principal)
    data['founderIntelligence']=state
    return result


def preview_state(data, principal):
    """Bounded presentation; retrieval still requires the current Founder grant."""
    actor,environment=_require(data,principal)
    state=copy.deepcopy(data.get('founderIntelligence') or _empty(actor,environment))
    full_count=sum(len(c['turns']) for c in state['conversations'])
    state['conversations']=state['conversations'][-3:]
    for conversation in state['conversations']: conversation['turns']=conversation['turns'][-4:]
    state['historyTruncated']=full_count>sum(len(c['turns']) for c in state['conversations'])
    state['totalTurnCount']=full_count
    for collection,limit in (('reports',5),('schedules',10),('followUps',10),('summaries',10),('contactAttempts',10)):
        state[collection]=state[collection][-limit:]
    for attempt in state['contactAttempts']: attempt.pop('operationRequests',None)
    if isinstance(state.get('lastActionResult'),dict):state['lastActionResult'].pop('operationRequests',None)
    current_receipt=_receipt(data)['id']
    for conversation in state['conversations']:
        for turn in conversation['turns']:
            turn['historicalContext']=turn['receipt']['id']!=current_receipt
    # One presentation adapter for the coordinator's panel; these are projections
    # of persisted turns, not another conversation store.
    messages=[]
    for conversation in state['conversations'][-5:]:
        for turn in conversation['turns'][-10:]:
            common=dict(scenario=turn['scenario'],receiptId=turn['queryReceiptIds'][0],
                        conversationId=conversation['id'],historicalContext=turn['historicalContext'])
            messages.extend([dict(id=turn['runId']+'-question',role='user',text=turn['question'],**common),
                             dict(id=turn['runId'],role='assistant',text=turn['answerText'],**common)])
    state['messages']=messages[-16:]
    incidents=_incidents(data)
    state['incident']=incidents[-1] if incidents else None
    state['notifications']=[]
    if incidents:
        from .founder_preview_delivery import email_preview
        for event in data.get('notificationEvents',[])[-3:]:
            incident=next((r for r in incidents if r['id']==event['incidentId']),None)
            if not incident: continue
            # Recovery preview is pinned to the resolved event; the earlier
            # outage notice remains an immutable historical notification.
            observed={**incident,'state':'resolved' if event['kind']=='recovery' else 'open'}
            rendered=email_preview(observed)
            latest=next((a for a in reversed(state['contactAttempts']) if a['sourceId'] in (event['id'],incident['id']) and a['channel']=='email'),None)
            state['notifications'].append(dict(**rendered,id=event['id'],incidentId=incident['id'],kind=event['kind'],
                       state=latest['state'] if latest else event['state'],attemptId=latest['id'] if latest else None,
                       sourceId=event['id'],acknowledged=latest['acknowledged'] if latest else False,
                       recipientLabel='Founder sandbox; no destination selected',receiptId=_receipt(data)['id']))
    for collection in ('reports','followUps'):
        for item in state[collection]:
            item['title']=item.get('intent',item.get('kind','Report').title()+' briefing')
            item['summary']=item.get('text','Saved in the sandbox. No real delivery is enabled.')
    state.update(simulation=True,externalDelivery=False,
                 modelReadiness=dict(live=False,mode='demo_simulation',code='MODEL_PERMISSION_UNVERIFIED'),
                 voiceReadiness=dict(live=False,mode='demo_simulation',recording=False,
                                     code='FOUNDER_VOICE_NOT_QUALIFIED',supportedControls=['start','interrupt','stop','repeat','text']),
                 operationsCost=dict(costCenter='founder_operations',costState='not_applicable',providerCalls=0,
                                     customerDebited=False),schedulerActivated=False)
    state.pop('operatorId',None)
    return state


def demo_snapshot(data, principal):
    try: return {'intelligence':preview_state(data,principal)}
    except ControlError as error:
        # Optional conversation access must not broaden ordinary workspace read
        # authority or break its existing read-only dashboard.
        return {'intelligence':dict(code=error.code,simulation=True,externalDelivery=False,
                                    modelReadiness=dict(live=False),voiceReadiness=dict(live=False))}


def authorize_demo_action(data, action, principal):
    """Call BEFORE returning an action replay from the enclosing Demo store."""
    if not isinstance(action,dict) or not isinstance(action.get('action'),str): raise ControlError('VALIDATION_FAILED',400)
    if action.get('action') not in ACTIONS: return False
    _require(data,principal)
    return True


def apply_demo_action(data, action, principal):
    """Existing WorkspaceService extension hook; no new route or persistence."""
    if not isinstance(action,dict) or not isinstance(action.get('action'),str): raise ControlError('VALIDATION_FAILED',400)
    if action.get('action') not in ACTIONS: return False
    result=reduce_action(data,action,principal)
    data['founderIntelligence']['lastActionResult']=copy.deepcopy(result)
    return True

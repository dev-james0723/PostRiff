"""Agent access to X metadata and exact proposals. No provider calls or approvals."""
import re
from postriff_alpha.domain import AlphaError
from . import contracts


def _engine(ctx,connection):
    if ctx.cur is None or not isinstance(connection,str) or not re.fullmatch(r'[0-9a-f]{32}',connection):
        raise AlphaError('Choose a connected X account.',404)
    engine=getattr(ctx.service,'x_direct',None)
    if engine is None:
        raise AlphaError('X Direct management is unavailable.',503,code='x_direct_unavailable')
    return engine,engine._credential(ctx.cur,ctx.workspace_id,connection)


def capabilities(ctx,connectionId,operation=None,offset=0):
    from ..x_direct_contract import list_capabilities
    from ..x_direct_executor import plain
    if type(offset) is not int or not 0<=offset<=200:
        raise AlphaError('Invalid X catalogue offset.',400,code='tool_input')
    engine,credential=_engine(ctx,connectionId)
    catalogue=list(list_capabilities(engine._context(ctx.workspace_id,connectionId,credential)))
    if operation:
        selected=next((d for d in catalogue if d.capability.id==operation),None)
        if selected is None:
            raise AlphaError('Unknown X capability.',404)
        data=plain(selected)
        data['capability']['input_path_params']=list(selected.capability.input_path_params)
        data['capability']['mutates']=selected.capability.mutates
    else:
        data={'total':len(catalogue),'nextOffset':offset+30 if offset+30<len(catalogue) else None,
            'capabilities':[{'operation':d.capability.id,'title':d.capability.title,
                'status':d.status,'reasonCode':d.reason_code,'reason':d.reason,
                'canPrepare':d.ready_for_preview} for d in catalogue[offset:offset+30]]}
    return contracts.result({'connectionId':connectionId,'directOnly':True,'providerExecuted':False,
        'availability':data,'href':'/app/x?channel='+connectionId},now=ctx.now)


def operations(ctx,connectionId):
    from .. import x_direct_journal as journal
    _engine(ctx,connectionId)
    journal.require_schema(ctx.cur)
    ctx.cur.execute('SELECT '+journal.SELECT+""" FROM public.pr_x_direct_operations
        WHERE workspace_id=%s AND connection_id=%s ORDER BY created_at DESC LIMIT 30""",
        (ctx.workspace_id,connectionId))
    rows=[journal.row_value(v) for v in ctx.cur.fetchall()]
    data=[{'operationId':r['id'],'operation':r['operation_id'],'state':r['state'],
        'scheduledAt':r['next_at'],'cancelRequested':r['cancel_requested'],
        'receiptCount':len(r['receipts']),
        'verifiedPostIds':[v['resourceId'] for v in r['receipts'] if v.get('readbackVerified') is True
                           and isinstance(v.get('resourceId'),str)]} for r in rows]
    return contracts.result({'connectionId':connectionId,'operations':data,
        'providerExecuted':False,'href':'/app/x?channel='+connectionId},now=ctx.now)


def propose(ctx,connectionId,request):
    if not ctx.membership.allows('edit'):
        raise AlphaError('Your role cannot prepare X operations.',403,code='tool_forbidden')
    engine,_=_engine(ctx,connectionId)
    if not isinstance(request,dict):
        raise AlphaError('Use a structured X operation.',400,code='tool_input')
    result=engine.preview_in_transaction(ctx.cur,ctx.workspace_id,ctx.principal,connectionId,request)
    # Models receive proposal identity/status, not private stored provider content.
    return contracts.result({'operationId':result['id'],'operation':result['operation'],
        'state':result['state'],'digest':result['digest'],'providerExecuted':False,
        'approvalRequired':True,'href':'/app/x?channel='+connectionId,
        'message':'Prepared for customer review. Open Manage X to approve the exact action.'},now=ctx.now)

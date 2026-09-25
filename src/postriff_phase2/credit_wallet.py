"""Credit accounting projected from the existing immutable usage ledger.

Disabled unless explicitly enabled AND the workspace has active versioned credit
terms. This module does not contact payment providers or activate plan terms.
"""
import json
import time
from postriff_alpha.domain import AlphaError
from .contracts import digest
from .credit_meter import POLICY_VERSION, millicredits


def amount(value):
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError('Credit amounts must be bounded nonnegative integers.')
    return value


def project_credit_wallet(rows, now):
    grants = {}
    for row in rows:
        c = row['credits']
        if c['op'] == 'grant':
            if row['id'] in grants: raise ValueError('Duplicate credit grant.')
            grants[row['id']] = {'grantId':row['id'], 'milli':amount(c['milli']),
                'expiresAt':c.get('expiresAt'), 'used':0, 'held':0, 'reversed':0}
    terminal = {r['reservationId'] for r in rows if r['credits']['op'] == 'settle'}
    used = held = 0
    for row in rows:
        c = row['credits']; op = c['op']
        if op in ('reverse','restore'):
            grant = grants.get(c['grantId'])
            if grant is None: raise ValueError('Unknown credit grant.')
            grant['reversed'] += amount(c['milli']) * (1 if op == 'reverse' else -1)
        elif op == 'settle' or op == 'reserve' and row['id'] not in terminal:
            for allocation in c['allocations']:
                grant = grants.get(allocation['grantId'])
                if grant is None: raise ValueError('Unknown allocated grant.')
                value = amount(allocation['milli'])
                grant['used' if op == 'settle' else 'held'] += value
                if op == 'settle': used += value
                else: held += value
    lots = sorted(grants.values(), key=lambda g:(g['expiresAt'] if g['expiresAt'] is not None else float('inf'),g['grantId']))
    debt = 0
    remaining = {}
    for g in lots:
        if not 0 <= g['reversed'] <= g['milli']: raise ValueError('Invalid net credit reversal.')
        remaining[g['grantId']] = g['milli'] - g['reversed'] - g['used'] - g['held']
        debt += max(0, -remaining[g['grantId']])
    # Debt left when paid credits are taken back after they were spent (refund, dispute) is repaid
    # first from credits that are still usable, earliest expiry first; only unpaid debt blocks spending.
    available = 0
    for g in lots:
        usable = max(0, remaining[g['grantId']]) if g['expiresAt'] is None or g['expiresAt'] > now else 0
        repaid = min(debt, usable)
        debt -= repaid
        g['available'] = usable - repaid
        available += g['available']
    return {'availableMilliCredits':available, 'heldMilliCredits':held,
            'usedMilliCredits':used, 'debtMilliCredits':debt, 'lots':lots}


class CreditBook:
    def __init__(self, clock=time.time):
        self.clock = clock

    def policy(self, cur, workspace_id):
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
        if cur.fetchone() is None: raise AlphaError('Workspace unavailable.',404)
        cur.execute("SELECT p.entitlements->>'creditPolicy',p.status FROM public.pr_entitlements e JOIN public.pr_plan_terms p ON p.id=e.plan_terms_id WHERE e.workspace_id=%s", (workspace_id,))
        row = cur.fetchone()
        if not row or not row[0]: return None
        if row[0] != POLICY_VERSION or row[1] != 'active':
            raise AlphaError('This credit policy is not active. No charge was made.',409)
        return row[0]

    def rows(self, cur, workspace_id):
        cur.execute("SELECT id::text,reservation_id::text,meta->'credits' FROM public.pr_usage_ledger WHERE workspace_id=%s AND meta ? 'credits' ORDER BY at,id LIMIT 10001",(workspace_id,))
        rows=cur.fetchall()
        if len(rows)>10000: raise AlphaError('Credit history needs archival review before more spending.',503)
        return [{'id':r[0],'reservationId':r[1],'credits':r[2]} for r in rows]

    def view(self, cur, workspace_id):
        return project_credit_wallet(self.rows(cur,workspace_id),self.clock())

    def _adjust(self, cur, workspace_id, actor, key, credit):
        fingerprint=digest(credit)
        cur.execute('SELECT id::text,meta FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s',(workspace_id,key))
        prior=cur.fetchone()
        if prior:
            if prior[1].get('creditFingerprint')!=fingerprint: raise AlphaError('Credit event conflicts with its earlier version.',409)
            return {'entryId':prior[0],'duplicate':True}
        cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,kind,dimension,unit,cost_state,idempotency_key,meta) VALUES(%s,%s,'adjust','action','credit','actual',%s,%s::jsonb) RETURNING id::text",(workspace_id,actor,key,json.dumps({'credits':credit,'creditFingerprint':fingerprint})))
        return {'entryId':cur.fetchone()[0],'duplicate':False}

    def grant(self, cur, workspace_id, actor, key, milli, expires_at=None, source='test'):
        import math
        policy=self.policy(cur,workspace_id)
        if policy is None: raise AlphaError('This workspace uses its existing allowance plan.',409)
        amount(milli)
        if not isinstance(key,str) or not key or len(key)>100: raise AlphaError('Invalid credit event key.',400)
        if expires_at is not None and (type(expires_at) not in (float,int) or not math.isfinite(expires_at)):
            raise AlphaError('Invalid credit expiry.',400)
        return self._adjust(cur,workspace_id,actor,key,{'op':'grant','milli':milli,'expiresAt':expires_at,'policy':policy,'source':source})

    def reverse(self, cur, workspace_id, actor, key, grant_id, milli):
        self.policy(cur,workspace_id); amount(milli)
        credit={'op':'reverse','grantId':grant_id,'milli':milli}
        cur.execute('SELECT meta FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s',(workspace_id,key))
        prior=cur.fetchone()
        if not prior:
            rows=self.rows(cur,workspace_id)
            project_credit_wallet(rows+[{'id':'proposed','reservationId':None,'credits':credit}],self.clock())
        return self._adjust(cur,workspace_id,actor,key,credit)

    def issue(self, cur, workspace_id, actor, revision, request_digest, model, provider, maximum):
        policy=self.policy(cur,workspace_id)
        if not policy: raise AlphaError('Credit billing is not active for this workspace.',409)
        amount(maximum)
        if maximum>100000000: raise AlphaError('Task credit limit is too large.',400)
        if self.view(cur,workspace_id)['availableMilliCredits']<maximum: raise AlphaError('Not enough available credits for this limit.',402)
        cur.execute('INSERT INTO public.pr_credit_quotes(workspace_id,actor,policy_id,request_digest,workspace_revision,model,provider,max_millicredits,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) RETURNING id::text',(workspace_id,actor,policy,request_digest,revision,model,provider,maximum,self.clock()+600))
        return {'quoteId':cur.fetchone()[0],'maxMilliCredits':maximum,'policy':policy,'expiresAt':self.clock()+600,'kind':'spending_limit','estimatedCredits':None}

    def quote(self, cur, workspace_id, actor, quote_id):
        import uuid
        try: uuid.UUID(str(quote_id))
        except (ValueError,TypeError): raise AlphaError('Confirm a valid task credit limit first.',402)
        cur.execute('SELECT policy_id,request_digest,workspace_revision,model,provider,max_millicredits,extract(epoch from expires_at),reservation_id::text FROM public.pr_credit_quotes WHERE workspace_id=%s AND actor=%s AND id::text=%s FOR UPDATE',(workspace_id,actor,str(quote_id)))
        row=cur.fetchone()
        if not row: raise AlphaError('Credit approval unavailable.',403)
        if row[7] or float(row[6])<=self.clock(): raise AlphaError('Credit approval is used or expired. Review it again.',409)
        return dict(zip(('policy','digest','revision','model','provider','maximum','expiry','reservationId'),row))

    def authorize(self, cur, workspace_id, actor, revision, request_digest, quote_id):
        if not self.policy(cur,workspace_id): return None
        quote=self.quote(cur,workspace_id,actor,quote_id)
        if quote['revision']!=revision or quote['digest']!=request_digest:
            raise AlphaError('The draft request changed. Review its credit limit again.',409)
        return {'quoteId':str(quote_id),'requestDigest':request_digest}

    def prepare(self, cur, workspace_id, actor, estimate, model, provider, authority):
        policy=self.policy(cur,workspace_id)
        if not policy: return None
        if not isinstance(authority,dict): raise AlphaError('Confirm this task credit limit before generating.',402)
        quote=self.quote(cur,workspace_id,actor,authority.get('quoteId'))
        if quote['policy']!=policy or quote['digest']!=authority.get('requestDigest') or quote['model']!=model or quote['provider']!=provider:
            raise AlphaError('The model or credit policy changed. Review again.',409)
        if millicredits(estimate)>quote['maximum']: raise AlphaError('This task exceeds your credit limit. Increase it or reduce the task.',402)
        view=self.view(cur,workspace_id)
        if view['debtMilliCredits'] or view['availableMilliCredits']<quote['maximum']:
            raise AlphaError('Insufficient available credits; no model request was sent.',402)
        remaining=quote['maximum']; allocations=[]
        for lot in view['lots']:
            take=min(remaining,lot['available'])
            if take: allocations.append({'grantId':lot['grantId'],'milli':take});remaining-=take
            if not remaining: break
        if remaining: raise AlphaError('Credit allocation is incomplete.',409)
        return {'op':'reserve','quoteId':authority['quoteId'],'policy':policy,'maximum':quote['maximum'],'allocations':allocations}

    def claim(self, cur, workspace_id, reservation_id, credit):
        cur.execute('UPDATE public.pr_credit_quotes SET reservation_id=%s WHERE workspace_id=%s AND id::text=%s AND reservation_id IS NULL RETURNING id',(reservation_id,workspace_id,credit['quoteId']))
        if not cur.fetchone(): raise AlphaError('This credit approval was already claimed.',409)

    def settlement(self, cur, workspace_id, reservation_id, outcome, actual):
        cur.execute("SELECT meta->'credits' FROM public.pr_usage_ledger WHERE workspace_id=%s AND id::text=%s AND kind='reserve'",(workspace_id,reservation_id))
        row=cur.fetchone();credit=row[0] if row else None
        if not credit or outcome=='unknown': return None
        used=min(credit['maximum'],millicredits(actual)) if outcome=='completed' else 0
        remaining=used;allocations=[]
        for lot in credit['allocations']:
            take=min(remaining,lot['milli'])
            if take: allocations.append({'grantId':lot['grantId'],'milli':take});remaining-=take
        if remaining: raise AlphaError('Settlement exceeds its reserved credits.',409)
        return {'op':'settle','policy':credit['policy'],'used':used,'allocations':allocations,
                'released':credit['maximum']-used,'absorbed':max(0,millicredits(actual)-used) if outcome=='completed' else 0}


def request_digest(operation, payload, conversation_id=None):
    if operation not in ('quick-start','turn') or not isinstance(payload,dict):
        raise ValueError('Unknown credit operation.')
    if any(not isinstance(key,str) or key.startswith('_') for key in payload):
        raise ValueError('Private execution fields are not accepted.')
    binding={key:value for key,value in payload.items() if key not in ('creditQuoteId','expectedRevision','idempotencyKey')}
    encoded=json.dumps(binding,ensure_ascii=False,allow_nan=False)
    if len(encoded.encode())>200000: raise ValueError('Draft request too large.')
    return digest({'operation':operation,'conversationId':conversation_id,'request':binding})

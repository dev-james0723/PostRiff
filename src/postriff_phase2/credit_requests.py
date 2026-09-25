"""Authenticated credit limits for the existing drafting pipeline, opt-in only."""
from postriff_alpha.domain import AlphaError
from .api_tokens import is_api_token
from .permissions import require
from .credit_wallet import request_digest, amount
from .credit_meter import POLICY_VERSION, millicredits


class CreditRequests:
    def __init__(self, ideas):
        self.ideas=ideas

    def _book(self):
        book=getattr(self.ideas.ledger,'credits',None)
        if book is None: raise AlphaError('Credit billing is not enabled.',503)
        return book

    def _validate(self, payload):
        if not isinstance(payload,dict): raise AlphaError('Supply a draft request.',400)
        if payload.get('research') is not False:
            raise AlphaError('This credit route supports writing only. Turn off web research for this task.',409)
        if self.ideas._wants_image(payload):
            raise AlphaError('Images need a separate credit approval; use the existing media plan.',409)
        runtime=self.ideas._select_runtime(payload.get('model'))
        if runtime.cost_class!='paid': raise AlphaError('This writer does not use cloud credits.',409)
        return runtime, payload.get('model') or runtime.model

    def _ceiling(self, runtime, model, request):
        import math
        return millicredits(math.ceil(runtime.price_quote(request, model) * 1_000_000))

    def estimate(self, workspace_id, token, body):
        """A labelled usual cost and the ceiling that will be held, from the request the writer would receive."""
        if is_api_token(token): raise AlphaError('Sign in to review a credit estimate.',403)
        book=self._book(); payload=body.get('request'); runtime,model=self._validate(payload)
        operation=body.get('operation','quick-start')
        if operation not in ('quick-start','turn'): raise AlphaError('Choose quick-start or turn.',400)
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,actor):
            require(self.ideas._member(row),'edit')
            policy=book.policy(cur,workspace_id)
            if not policy: raise AlphaError('Credit billing is not active for this workspace.',409)
            if operation=='turn': self.ideas._conversation(cur,workspace_id,body.get('conversationId'))
            available=book.view(cur,workspace_id)['availableMilliCredits']
            runtime,model,request=self.ideas.estimate_request(self.ideas._state(row),payload,operation,actor)
        import math
        ceiling=self._ceiling(runtime,model,request)
        usual=min(ceiling,millicredits(math.ceil(runtime.typical_quote(request,model)*1_000_000)))
        return {'estimateMilliCredits':usual,'ceilingMilliCredits':ceiling,'availableMilliCredits':available,'basis':runtime.ESTIMATE_BASIS,
                'model':model,'provider':runtime.provider,'policy':policy,'reasoning':request.get('reasoning')}

    def issue(self, workspace_id, token, body):
        if is_api_token(token): raise AlphaError('Sign in to approve a credit limit.',403)
        book=self._book(); payload=body.get('request');runtime,model=self._validate(payload)
        operation=body.get('operation','quick-start');conversation=body.get('conversationId')
        try:
            maximum=amount(body.get('maxMilliCredits'))
            binding=request_digest(operation,payload,conversation)
        except (ValueError,TypeError): raise AlphaError('Invalid credit request or limit.',400)
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,actor):
            require(self.ideas._member(row),'edit')
            if body.get('expectedRevision')!=row[0]: raise AlphaError('Workspace changed. Review this request again.',409)
            if operation=='turn': self.ideas._conversation(cur,workspace_id,conversation)
            elif conversation is not None: raise AlphaError('A new draft cannot name another conversation.',400)
            # The limit must cover the most this exact request can cost, so approval never ends in a later 402.
            _,_,request=self.ideas.estimate_request(self.ideas._state(row),payload,operation,actor)
            ceiling=self._ceiling(runtime,model,request)
            if maximum<ceiling: raise AlphaError(f'This task can use up to {ceiling/1000:.1f} credits. Set the limit to at least {ceiling/1000:.1f}.',402)
            return book.issue(cur,workspace_id,actor,row[0],binding,model,runtime.provider,maximum)

    def authorize(self, workspace_id, token, revision, payload, operation, conversation=None):
        book=getattr(self.ideas.ledger,'credits',None)
        if book is None: return None
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,actor):
            require(self.ideas._member(row),'edit')
            if not book.policy(cur,workspace_id): return None
            runtime=self.ideas._select_runtime(payload.get('model'))
            if runtime.cost_class!='paid' and not self.ideas._wants_image(payload): return None
            self._validate(payload)
            if operation=='turn': self.ideas._conversation(cur,workspace_id,conversation)
            current=row[0] if revision is None else revision
            if current!=row[0]: raise AlphaError('Workspace changed. Review the credit limit again.',409)
            try: binding=request_digest(operation,payload,conversation)
            except (ValueError,TypeError): raise AlphaError('Invalid draft request.',400)
            return book.authorize(cur,workspace_id,actor,current,binding,payload.get('creditQuoteId'))

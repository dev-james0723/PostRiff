"""Authenticated credit limits for the existing drafting pipeline, opt-in only."""
from postriff_alpha.domain import AlphaError
from .api_tokens import is_api_token
from .permissions import require
from .credit_wallet import request_digest, amount
from .credit_meter import POLICY_VERSION, millicredits
from .developer_usage import ai_usage_exempt


class CreditRequests:
    def __init__(self, ideas):
        self.ideas=ideas

    def _book(self):
        book=getattr(self.ideas.ledger,'credits',None)
        if book is None: raise AlphaError('Credit billing is not enabled.',503)
        return book

    def _growth_rewrite(self, workspace_id, token, body, *, issue=False):
        growth=getattr(self,'growth',None)
        if growth is None:
            raise AlphaError('This Growth route needs a qualified credit bridge before AI use.',503,code='growth_credit_bridge_unavailable')
        return growth.rewrite_credit_request(workspace_id,token,body,issue=issue)

    def _validate(self, payload):
        if not isinstance(payload,dict): raise AlphaError('Supply a draft request.',400)
        if payload.get('research') is not False:
            raise AlphaError('This credit route does not include web research. Turn it off for this task.',409)
        if self.ideas._wants_image(payload):
            runtime = getattr(self.ideas, 'image_runtime', None)
            if runtime is None or not runtime.credit_basis():
                raise AlphaError('Image credit pricing is not qualified yet. No provider request was made.',503,code='image_credit_unavailable')
            request = payload['imageGeneration']
            if request is not True and (set(request) - {'enabled', 'count'} or type(request.get('count', 1)) is not int or request.get('count', 1) != 1):
                raise AlphaError('Choose one supported image candidate.',400)
            return runtime, runtime.model
        runtime=self.ideas._select_runtime(payload.get('model'))
        if runtime.cost_class!='paid': raise AlphaError('This writer does not use cloud credits.',409)
        # The model an Auto request writes with depends on workspace state: estimate and issue take it from estimate_request.
        return runtime, payload.get('model') or runtime.model

    def _notes(self, cur, workspace_id, state, payload):
        """What a `media-notes` read of this asset would cost now, checked the way the read checks it (SPEC §8.2)."""
        from . import asset_kinds, media_consent, media_notes as notes_module, turn_references
        if not isinstance(payload,dict) or set(payload)!={'assetId'} or not isinstance(payload.get('assetId'),str) or not notes_module.ASSET_ID.match(payload['assetId']):
            raise AlphaError('Invalid media notes request.',400)
        notes=getattr(self.ideas,'media_notes',None)
        if notes is None or not notes.reader.available:
            raise AlphaError(turn_references.REASONS['reader_unavailable'],409,code='reader_unavailable')
        asset=next((a for a in (state.get('phase2') or {}).get('assets',[]) if isinstance(a,dict) and a.get('id')==payload['assetId'] and not a.get('deleted') and not a.get('deletionPending')),None)
        if asset is None or asset_kinds.kind_of(asset) is None: raise AlphaError("This photo or video isn't in this workspace.",404)
        if not asset_kinds.is_ready(asset): raise AlphaError(turn_references.REASONS['media_not_ready'],409,code='media_not_ready')
        kind,frames=notes_module.kind_for(asset),notes_module.frame_count(asset)
        if kind=='video_frames' and not frames: raise AlphaError(turn_references.REASONS['no_frames'],409,code='no_frames')
        processor=notes.reader.processor()
        if not media_consent.allowed(state,processor): raise AlphaError(turn_references.REASONS['consent_required'],409,code='consent_required')
        existing=notes_module._row(cur,workspace_id,asset['id'],str(asset.get('hash') or ''))
        cached=bool(existing and existing['status']=='ready' and (existing.get('processor') or {}).get('id')==processor['id'])
        estimate=notes.reader.estimate(kind,frames)
        if estimate['ceilingUsdMicro'] is None: raise AlphaError(turn_references.REASONS['reader_unavailable'],409,code='reader_unavailable')
        return {'estimate':estimate,'kind':kind,'frames':frames,'cached':cached}

    def _notes_estimate(self, workspace_id, token, body):
        book=self._book()
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,_actor):
            require(self.ideas._member(row),'edit')
            self.ideas.ledger.ensure_entitlement(cur,workspace_id,None)
            policy=book.policy(cur,workspace_id)
            if not policy: raise AlphaError('Credit billing is not active for this workspace.',409)
            available=book.view(cur,workspace_id)['availableMilliCredits']
            info=self._notes(cur,workspace_id,self.ideas._state(row),body.get('request'))
        cost=info['estimate']
        # A cached note costs nothing and needs no quote.
        typical,ceiling=(0,0) if info['cached'] else (millicredits(cost['typicalUsdMicro']),millicredits(cost['ceilingUsdMicro']))
        return {'estimateMilliCredits':min(typical,ceiling),'ceilingMilliCredits':ceiling,'availableMilliCredits':available,'basis':'media_notes',
                'model':cost['model'],'provider':cost['provider'],'policy':policy,'stateRevision':row[0],'kind':info['kind'],'frames':info['frames'],'cached':info['cached']}

    def _ceiling(self, runtime, model, request):
        if self.ideas._wants_image(request):
            basis = runtime.credit_basis()
            if not basis:
                raise AlphaError('Image credit pricing is not qualified yet.',503,code='image_credit_unavailable')
            return millicredits(basis['ceilingUsdMicro'])
        import math
        return millicredits(math.ceil(runtime.price_quote(request, model) * 1_000_000))

    def _priced_request(self, state, payload, operation, actor):
        if self.ideas._wants_image(payload):
            runtime, model = self._validate(payload)
            return runtime, model, payload
        return self.ideas.estimate_request(state,payload,operation,actor)

    def estimate(self, workspace_id, token, body):
        """A labelled usual cost and the ceiling that will be held, from the request the writer would receive."""
        if is_api_token(token): raise AlphaError('Sign in to review a credit estimate.',403)
        if isinstance(body,dict) and body.get('operation')=='post-doctor-rewrite': return self._growth_rewrite(workspace_id,token,body)
        if isinstance(body,dict) and body.get('operation')=='media-notes': return self._notes_estimate(workspace_id,token,body)
        book=self._book(); payload=body.get('request'); runtime,model=self._validate(payload)
        operation=body.get('operation','quick-start')
        if operation not in ('quick-start','turn'): raise AlphaError('Choose quick-start or turn.',400)
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,actor):
            require(self.ideas._member(row),'edit')
            self.ideas.ledger.ensure_entitlement(cur,workspace_id,None)
            policy=book.policy(cur,workspace_id)
            if not policy: raise AlphaError('Credit billing is not active for this workspace.',409)
            if operation=='turn': self.ideas._conversation(cur,workspace_id,body.get('conversationId'))
            available=book.view(cur,workspace_id)['availableMilliCredits']
            runtime,model,request=self._priced_request(self.ideas._state(row),payload,operation,actor)
        import math
        ceiling=self._ceiling(runtime,model,request)
        usual=ceiling if self.ideas._wants_image(payload) else min(ceiling,millicredits(math.ceil(runtime.typical_quote(request,model)*1_000_000)))
        return {'estimateMilliCredits':usual,'ceilingMilliCredits':ceiling,'availableMilliCredits':available,'basis':runtime.ESTIMATE_BASIS,
                'model':model,'provider':runtime.provider,'policy':policy,'reasoning':request.get('reasoning'),'stateRevision':row[0],
                **({'warnings':[request['writerNote']]} if request.get('writerNote') else {})}

    def _notes_issue(self, workspace_id, token, body):
        book=self._book(); payload=body.get('request')
        try:
            maximum=amount(body.get('maxMilliCredits'))
            binding=request_digest('media-notes',payload,body.get('conversationId'))
        except (ValueError,TypeError): raise AlphaError('Invalid credit request or limit.',400)
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,actor):
            require(self.ideas._member(row),'edit')
            self.ideas.ledger.ensure_entitlement(cur,workspace_id,None)
            if body.get('expectedRevision')!=row[0]: raise AlphaError('Workspace changed. Review this request again.',409)
            info=self._notes(cur,workspace_id,self.ideas._state(row),payload)
            if info['cached']: raise AlphaError('Rafii already read this; no credits are needed.',409,code='notes_cached')
            cost=info['estimate']; ceiling=millicredits(cost['ceilingUsdMicro'])
            if maximum<ceiling: raise AlphaError(f'This task can use up to {ceiling/1000:.1f} credits. Set the limit to at least {ceiling/1000:.1f}.',402)
            # The quote names the vision model and provider, so the read's reservation (CreditBook.prepare) matches it.
            return book.issue(cur,workspace_id,actor,row[0],binding,cost['model'],cost['provider'],maximum)

    def issue(self, workspace_id, token, body):
        if is_api_token(token): raise AlphaError('Sign in to approve a credit limit.',403)
        if isinstance(body,dict) and body.get('operation')=='post-doctor-rewrite': return self._growth_rewrite(workspace_id,token,body,issue=True)
        if isinstance(body,dict) and body.get('operation')=='media-notes': return self._notes_issue(workspace_id,token,body)
        book=self._book(); payload=body.get('request');runtime,model=self._validate(payload)
        operation=body.get('operation','quick-start');conversation=body.get('conversationId')
        try:
            maximum=amount(body.get('maxMilliCredits'))
            binding=request_digest(operation,payload,conversation)
        except (ValueError,TypeError): raise AlphaError('Invalid credit request or limit.',400)
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,actor):
            require(self.ideas._member(row),'edit')
            self.ideas.ledger.ensure_entitlement(cur,workspace_id,None)
            if body.get('expectedRevision')!=row[0]: raise AlphaError('Workspace changed. Review this request again.',409)
            if operation=='turn': self.ideas._conversation(cur,workspace_id,conversation)
            elif conversation is not None: raise AlphaError('A new draft cannot name another conversation.',400)
            # The limit must cover the most this exact request can cost, so approval never ends in a later 402. The writer
            # is the one the turn will use: Auto resolves against this workspace's default, as the turn does.
            runtime,model,request=self._priced_request(self.ideas._state(row),payload,operation,actor)
            ceiling=self._ceiling(runtime,model,request)
            if maximum<ceiling: raise AlphaError(f'This task can use up to {ceiling/1000:.1f} credits. Set the limit to at least {ceiling/1000:.1f}.',402)
            return book.issue(cur,workspace_id,actor,row[0],binding,model,runtime.provider,maximum)

    def authorize(self, workspace_id, token, revision, payload, operation, conversation=None):
        book=getattr(self.ideas.ledger,'credits',None)
        if book is None: return None
        with self.ideas.repository.transaction(token,workspace_id) as (cur,row,actor):
            require(self.ideas._member(row),'edit')
            self.ideas.ledger.ensure_entitlement(cur,workspace_id,None)
            if ai_usage_exempt(actor): return None
            if not book.policy(cur,workspace_id): return None
            if operation=='media-notes':
                return self._notes_authority(cur,workspace_id,row,actor,revision,payload,book)
            if not self.ideas._wants_image(payload):
                runtime=self.ideas._select_runtime(payload.get('model'))
                if runtime.cost_class!='paid': return None
            self._validate(payload)
            if operation=='turn': self.ideas._conversation(cur,workspace_id,conversation)
            current=row[0] if revision is None else revision
            if current!=row[0]: raise AlphaError('Workspace changed. Review the credit limit again.',409)
            try: binding=request_digest(operation,payload,conversation)
            except (ValueError,TypeError): raise AlphaError('Invalid draft request.',400)
            return book.authorize(cur,workspace_id,actor,current,binding,payload.get('creditQuoteId'))

    def _notes_authority(self, cur, workspace_id, row, actor, revision, payload, book):
        """The quote a `media-notes` read reserves against, or None when it needs none: a cached note, or a read that will
        answer `unavailable` before reserving anything (the read itself reports why)."""
        body={'assetId':payload.get('assetId')}
        try:
            info=self._notes(cur,workspace_id,self.ideas._state(row),body)
        except AlphaError:
            return None
        if info['cached']: return None
        current=row[0] if revision is None else revision
        if current!=row[0]: raise AlphaError('Workspace changed. Review the credit limit again.',409)
        try: binding=request_digest('media-notes',body)
        except (ValueError,TypeError): raise AlphaError('Invalid media notes request.',400)
        return book.authorize(cur,workspace_id,actor,current,binding,payload.get('creditQuoteId'))

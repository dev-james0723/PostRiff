"""Disposable local browser fixture: synthetic Live/Manager input, actual phone controller and draft command.

This helper never opens a provider or model connection. It refuses a non-fake call and only seeds an empty test workspace.
"""
import json
import os
import sys
import uuid

os.environ['OPENAI_AGENTS_DISABLE_TRACING'] = '1'
import psycopg
from agents.testing import ScriptedModel, assistant_message, function_call
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.agent_runtime_v2.config import RuntimeConfig
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.phone import contracts, store, webhooks
from postriff_phase2.phone.providers.fake import FakeTelephonyProvider
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.phone.session import PhoneSessionController

action, port, principal, workspace_id, *rest = sys.argv[1:]
assert port.isdigit() and 1024 <= int(port) <= 65535
principal, workspace_id = str(uuid.UUID(principal)), str(uuid.UUID(workspace_id))
connection = lambda: psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres')
service = HostedWorkspaceService(connection, lambda token: principal if token == principal else None,
                                vault=CredentialVault(CredentialVault.generate_key()))
edited = 'Small steps make piano practice feel possible. Come try one with us.'
if action == 'seed':
    snapshot = service.get(workspace_id, principal)
    assert not snapshot['state'].get('variants'), 'Only seed an empty synthetic workspace'
    first, second = uuid.uuid4().hex, uuid.uuid4().hex
    def seed(state, _actor):
        state['variants'] = [
            {'id':draft_id,'platform':'LinkedIn','language':'English','text':text,'revision':1,'needsReview':True,
             'revisions':[],'localPreferences':{},'openings':[],'unknowns':[],'warnings':[],'sourceIds':[],
             'voiceRevision':None,'blockedByRetraction':False,'createdAt':index}
            for index,(draft_id,text) in enumerate(((first,'First LinkedIn draft'),
                (second,'We have spent many evenings reflecting on small steps that make piano practice feel possible. Join us for a gentle, friendly start.')))]
        return state
    service.repository.command(workspace_id, principal, snapshot['revision'], seed)
    print(json.dumps({'draftId':second,'editedText':edited}))
elif action == 'delegate':
    call_id, draft_id = rest
    call_id = str(uuid.UUID(call_id))
    model = ScriptedModel([
        [function_call('workspace_summary',{},call_id='workspace')],
        [function_call('draft_get',{'draftId':draft_id},call_id='read')],
        [function_call('draft_edit',{'draftId':draft_id,'revision':1,'text':edited},call_id='edit')],
        [assistant_message(json.dumps({'answer':'I shortened and warmed the second LinkedIn draft. It is saved and needs publishing review.',
                                      'speakable':'I shortened and warmed the second LinkedIn draft. It is saved and needs publishing review.',
                                      'language':'en','follow_ups':[]}))]])
    cfg = RuntimeConfig.from_environment({'OPENAI_API_KEY':'fake-phone-browser-test','RAFII_AGENT_V2_ENABLED':'1','RAFII_SPECIALISTS_ENABLED':'1'})
    runtime = AgentRuntimeService(service,cfg,model_factory=lambda *_args:model)
    provider = FakeTelephonyProvider()
    phone = PhoneService(service,{flag:'1' for flag in contracts.FLAGS},provider=provider,runtime=runtime)
    with connection() as db:
        value = store.call(db.cursor(),call_id)
    assert value and value['provider']=='fake' and value['user_id']==principal and value['workspace_id']==workspace_id
    assert value['state']=='ringing', 'Only answer this explicit synthetic call once'
    event={'callRef':value['provider_call_ref'],'eventId':'browser-answer:'+call_id,'state':'answered'}
    url='/api/phone/webhooks/'+call_id
    webhooks.apply(phone,call_id,url,event,provider.sign(url,event))
    controller=PhoneSessionController(phone,call_id)
    controller.started('synthetic-browser-phone-live')
    controller.transcript({'type':'session.input_transcript.delta','delta':'Open the second LinkedIn draft and cut the opening in half. Make it warmer.'})
    result=controller.delegate({'delegation':{'id':'browser-edit-second','target':'client'}})
    model.assert_complete()
    state=service.get(workspace_id,principal)['state']
    assert state['variants'][0]['text']=='First LinkedIn draft'
    assert state['variants'][1]['text']==edited and state['variants'][1]['revision']==2 and state['variants'][1]['needsReview']
    controller.transcript({'type':'session.input_transcript.delta','delta':'Publish it.'})
    approval=controller.delegate({'delegation':{'id':'browser-publish','target':'client'}})
    assert not service.get(workspace_id,principal)['state']['phase2']['jobs'], 'Phone must not bypass publication approval'
    assert any(word in approval['content'].lower() for word in ('review','approval','approve','publish'))
    print(json.dumps({'execution':'synthetic Live and Manager + actual PhoneSessionController/AgentRuntime/draft command',
                      'conversationId':value['conversation_id'],'editedText':edited,'spoken':result['content'],'approval':approval['content']}))
else:
    raise ValueError('Unknown local fixture action')

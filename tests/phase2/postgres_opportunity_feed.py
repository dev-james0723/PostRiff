"""Real source stores and native decisions; synthetic identities/metrics, no egress."""
import json
import os
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2 import suggestions
from postriff_phase2.coworker import flags, performance
from postriff_phase2.agent_runtime_v2 import creator_pipeline, opportunity_feed as feed

ROOT = Path(__file__).resolve().parents[2]
def admin(): return psycopg.connect(os.environ['POSTRIFF_TEST_DSN'], client_encoding='utf8')
def connect():
    db = admin(); db.execute('SET ROLE service_role'); return db


class OpportunityPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with admin() as db: db.execute((ROOT / 'migrations/postriff/108_agent_tasks.sql').read_text())

    def setUp(self):
        self.now = time.time(); self.owner, self.editor, self.other = [str(uuid.uuid4()) for _ in range(3)]
        self.tokens = {'owner':self.owner,'editor':self.editor,'other':self.other}
        with admin() as db:
            for uid in self.tokens.values(): db.execute('INSERT INTO auth.users(id) VALUES(%s)', (uid,))
        self.service = HostedWorkspaceService(connect, lambda token:self.tokens[token], clock=lambda:self.now)
        self.wid = self.service.bootstrap('owner','studio')['workspaceId']; self.other_wid = self.service.bootstrap('other','studio')['workspaceId']; self.service.bootstrap('editor','studio')
        with connect() as db: db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (self.wid,self.editor))
        self.runtime = SimpleNamespace(service=self.service, clock=lambda:self.now, cfg=SimpleNamespace(task_engine_for=lambda wid:'on',permissions_for=lambda wid:'off'))
        before = flags._values
        flags.attach({'RAFII_NOTIFICATIONS_V2_ENABLED':'1','RAFII_PERFORMANCE_LEARNING_ENABLED':'1','RAFII_LISTENING_ENABLED':'1'})
        self.addCleanup(flags.attach, before)
        env = patch.dict(os.environ, {'POSTRIFF_RESEARCH':'1', 'POSTRIFF_HOSTED':'1'})
        env.start(); self.addCleanup(env.stop)
        state = self.service.get(self.wid,'owner')['state']
        state.setdefault('raffi', {})['campaignPlanning'] = {'campaigns':[{'id':'campaign-a','version':1,'goal':'Recital','audience':'Neighbours','facts':{'venue':'Studio'},'status':'draft','items':[]}]}
        state['raffi']['suggestions'] = []; self.suggestion = suggestions.refresh(state,self.now)[0]
        state['researchEgress'] = {'web':True}
        state.setdefault('coworker',{})['listening'] = {'watchlists':[], 'opportunities':[{'id':'lead','title':'A sourced opportunity','why':'Matches selected topic','status':'open','createdAt':self.now-10,'expiresAt':self.now+3600,'evidence':[]}]}
        self.save(state)

    def save(self, state):
        with connect() as db: db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state),self.wid))
    def items(self, token='owner'):
        return feed.listing(self.runtime,self.wid,token)['items']
    def decide(self, item, decision='dismiss', token='owner'):
        return feed.decide(self.runtime,self.wid,token,{'id':item['id'],'digest':item['digest'],'decision':decision})
    def family(self, name, token='owner'): return [i for i in self.items(token) if i['family']==name]

    def test_suggestion_dismissal_persists_and_cooldown_survives_refresh(self):
        item = self.family('suggestion')[0]
        self.assertTrue(self.decide(item)['verified'])
        feed.refresh(self.runtime,self.wid,'owner')
        self.assertEqual(self.family('suggestion'), [])
        with self.assertRaises(AlphaError): self.decide(item)

    def test_task_receipt_link_is_creator_private_and_replaces_duplicate_action(self):
        item = self.family('suggestion')[0]
        body = {'suggestionId':item['sourceId'],'platforms':['Threads'],'budgetCeilingUsdMicro':0}
        preview = creator_pipeline.preview(self.runtime,self.wid,'owner',body)
        task = creator_pipeline.create(self.runtime,self.wid,'owner',{**body,'digest':preview['digest'],'idempotencyKey':'opportunity-'+uuid.uuid4().hex})
        own = self.family('suggestion')[0]
        self.assertEqual(own['action']['href'], task['href']); self.assertEqual(own['task']['state'],'awaiting_approval')
        self.assertIsNone(self.family('suggestion','editor')[0]['task'])

    def test_source_change_role_demotion_and_foreign_workspace_fail_closed(self):
        item = self.family('suggestion')[0]
        state = self.service.get(self.wid,'owner')['state']; state['raffi']['campaignPlanning']['campaigns'][0]['version']+=1; self.save(state)
        with self.assertRaises(AlphaError): self.decide(item)
        with connect() as db: db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (self.wid,self.editor))
        for token in ('editor','other'):
            with self.assertRaises(AlphaError) as caught: self.items(token)
            self.assertEqual(caught.exception.status,403)

    def test_listening_consent_expiry_and_existing_dismissal(self):
        item = self.family('listening')[0]
        self.assertEqual(item['action']['kind'],'open')
        self.decide(item); self.assertEqual(self.family('listening'),[])
        state = self.service.get(self.wid,'owner')['state']; state['coworker']['listening']['opportunities'][0]['status']='open'; state['researchEgress']['web']=False; self.save(state)
        self.assertEqual(self.family('listening'),[])
        state['researchEgress']['web']=True; state['coworker']['listening']['opportunities'][0]['expiresAt']=self.now-1; self.save(state)
        self.assertEqual(self.family('listening'),[])

    def attention(self):
        state = self.service.get(self.wid,'owner')['state']
        state.setdefault('phase2',{})['jobs']=[{'id':'failed-job','state':'failed','attempts':[],'events':[],'manifest':{'platform':'Threads'}}]
        self.save(state)
        with connect() as db:
            event=db.execute("INSERT INTO public.pr_notification_events(workspace_id,scope_key,event_type,category,severity,entity_type,entity_id,payload,dedupe_key) VALUES(%s,%s,'publish.failed','publishing','warning','job','failed-job','{}','publish.failed:failed-job:0') RETURNING id",(self.wid,self.wid)).fetchone()[0]
            for user in (self.owner,self.editor):
                db.execute("INSERT INTO public.pr_notification_deliveries(event_id,workspace_id,user_id,channel,mode,status,idempotency_key) VALUES(%s,%s,%s,'in_app','in_app','delivered',%s)",(event,self.wid,user,uuid.uuid4().hex))

    def test_attention_is_current_personal_and_dismisses_only_own_delivery(self):
        self.attention(); mine=self.family('attention')[0]
        self.assertEqual(mine['dismissalScope'],'person')
        with self.assertRaises(AlphaError):self.decide(mine,token='editor')
        self.decide(mine); self.assertEqual(self.family('attention'),[])
        with connect() as db:
            self.assertEqual(db.execute("SELECT status FROM public.pr_notification_deliveries WHERE workspace_id=%s AND user_id=%s",(self.wid,self.editor)).fetchone()[0],'delivered')
        state=self.service.get(self.wid,'owner')['state'];state['phase2']['jobs'][0]['state']='verified';self.save(state)
        self.assertEqual(self.family('attention','editor'),[])

    def seed_performance(self, account="account-a", label="Studio A"):
        state=self.service.get(self.wid,'owner')['state'];phase=state.setdefault('phase2',{})
        phase.setdefault('channels',[]).append({'id':account,'account':label,'platform':'Threads','revoked':False,'configured':True,'expiresAt':self.now+86400,'identityVerified':True,'capabilityVerified':True,'verifiedAt':self.now});phase.setdefault('jobs',[])
        for n in range(12):
            phase['jobs'].append({'id':f'{account}-job-{n}','state':'verified','providerReference':f'{account}-post-{n}','verification':{'at':self.now-86400*(n+1)},
                'manifest':{'channelId':account,'platform':'Threads','payload':{'text':'A question?' if n%2 else 'A statement.','language':'en'},'timing':{'timestamp':self.now-86400*(n+1)}}})
        self.save(state)
        with connect() as db:
            db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')",(self.wid,account))
            for n in range(12):
                db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,read_offset) VALUES(%s,%s,'threads',%s,%s,'views','native-v1',%s,'count','available',to_timestamp(%s),'24h')",(self.wid,account,f'{account}-post-{n}',f'{account}-job-{n}',900+n if n%2 else 400+n,self.now-n))
            performance.refresh(db.cursor(),self.wid,state,self.now)

    def test_current_native_hypothesis_defines_existing_experiment_without_task_or_paid_work(self):
        self.seed_performance();item=next(i for i in self.family('performance') if 'question' in i['title'])
        self.assertEqual(item['measurement']['window'],'24h');self.assertFalse(item['measurement']['causal'])
        editor=next(i for i in self.family('performance','editor') if i['id']==item['id'])
        self.assertEqual(editor['action']['kind'],'open');self.assertFalse(editor['canDismiss'])
        with self.assertRaises(AlphaError):self.decide(editor,'experiment','editor')
        result=self.decide(item,'experiment');self.assertEqual(result['state'],'experiment')
        updated=next(i for i in self.family('performance') if i['id']==item['id'])
        self.assertEqual(updated['experiment']['outcome'],'unmeasured');self.assertEqual(updated['experiment']['measurementWindow'],'24h')
        with self.assertRaises(AlphaError):self.decide(item,'experiment')
        with connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_agent_tasks WHERE workspace_id=%s',(self.wid,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s',(self.wid,)).fetchone()[0],0)

    def test_two_account_comparison_identity_and_arms_are_captured(self):
        self.seed_performance();self.seed_performance('account-b','Studio B')
        items=[i for i in self.family('performance') if i['measurement']['comparison']['dimension']=='opening']
        self.assertEqual(len(items),2)
        self.assertEqual({i['measurement']['comparison']['accountLabel'] for i in items},{'Studio A','Studio B'})
        self.assertEqual(len({i['digest'] for i in items}),2)
        selected=next(i for i in items if i['measurement']['comparison']['accountId']=='account-b')
        self.assertEqual((selected['measurement']['comparison']['armA'],selected['measurement']['comparison']['armB']),('question','statement'))
        self.decide(selected,'experiment')
        with connect() as db:
            stored=db.execute('SELECT experiment FROM public.pr_strategy_hypotheses WHERE workspace_id=%s AND id=%s',(self.wid,selected['sourceId'])).fetchone()[0]
            self.assertEqual(stored['comparison'],selected['measurement']['comparison'])
            db.execute("UPDATE public.pr_strategy_hypotheses SET arm_a='unreviewed' WHERE workspace_id=%s AND id=%s",(self.wid,selected['sourceId']))
        self.assertFalse(any(i['id']==selected['id'] for i in self.family('performance')))

    def test_revoked_account_analytics_and_unknown_metric_window_withhold_hypotheses(self):
        self.seed_performance();self.assertTrue(self.family('performance'))
        state=self.service.get(self.wid,'owner')['state'];state['phase2']['channels'][0]['revoked']=True;self.save(state)
        self.assertEqual(self.family('performance'),[])
        state['phase2']['channels'][0]['revoked']=False;self.save(state)
        with connect() as db:db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s",(self.wid,))
        self.assertEqual(self.family('performance'),[])
        with connect() as db:
            db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s",(self.wid,))
            db.execute('UPDATE public.pr_metric_observations SET read_offset=NULL WHERE workspace_id=%s',(self.wid,))
        self.assertEqual(self.family('performance'),[])


if __name__ == '__main__': unittest.main()

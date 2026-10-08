"""Zero-network Phase 2 adapters. Private test data only, never a production model."""
import json
from growth_phase1_fixtures import ENV as PHASE1_ENV, Models as BaseModels, Writer, MODEL
from postriff_phase2.growth import jev

ENV={**PHASE1_ENV,'POSTRIFF_POSTMORTEM':'1','POSTRIFF_AUDIENCE_MINER':'1',
     'POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP':'10'}


class Models(BaseModels):
    def evaluate(self,state,questions,*,timeout_s):
        if 'category' not in questions:return super().evaluate(state,questions,timeout_s=timeout_s)
        self.calls.append(('evaluate',state))
        if self.before:
            before,self.before=self.before,None;before()
        text=str(state).lower()
        category='request' if 'resource' in text else 'objection' if 'disagree' in text else 'follow_up' if 'sequel' in text else 'question'
        raw={}
        for name,q in questions.items():
            if q['type']=='boolean':raw[name]={'type':'boolean','probability':.01 if name=='sensitive' and 'private medical' not in text else .95}
            else:
                options=q.get('choices',q.get('criteria',q.get('options',{})))
                options=[o['name'] if isinstance(o,dict) else o for o in options]
                raw[name]={'type':'choice','choice':category,'probabilities':{o:float(o==category) for o in options}}
        return jev.RawEvaluation('typesafe-ai/jev',raw,100,0,None,'unknown','fixture-eval','fixture',1)

    def chat(self,messages,model,max_tokens,timeout_s):
        data=json.loads(messages[-1]['content'])
        if 'original' in data:return super().chat(messages,model,max_tokens,timeout_s)
        self.calls.append(('chat',model))
        if self.before_chat:
            before,self.before_chat=self.before_chat,None;before()
        if 'groups' in data:
            titles={'question':('Making practice feel possible','How can a beginner build a practice routine that lasts?'),
                    'request':('A resource worth keeping','What simple resources help you find the next practice step?'),
                    'objection':('Make room for another perspective','When might a different practice approach work better?'),
                    'follow_up':('The next chapter','What should we explore more deeply next?')}
            return json.dumps({'suggestions':[{'group':g['group'],'title':titles.get(g['category'],('A fresh perspective','What could we explore?'))[0],
                                              'question':titles.get(g['category'],('A fresh perspective','What could we explore?'))[1]} for g in data['groups']]}),{}
        return json.dumps({'nextStep':'repeat_with_control'}),{}


def seed(host,wid,token,*,calibration=False):
    """Explicit synthetic verified posts and official-shaped observations, disposable DB only."""
    import time,uuid
    from postriff_phase2.contracts import digest
    from postriff_phase2.growth import performance
    now=time.time();conn='phase2-fixture-account';n=60 if calibration else 6
    titles=['The quiet power of showing up to practise.','A better question before the first note.','What slow practice actually teaches you.','Make space for a small beginning.','Learning to listen to your own playing.','A practice routine that feels like yours.']
    def command(state,actor):
        state['phase2']['channels']=[{'id':conn,'platform':'Threads','account':'Practice Studio · fixture','accountType':'profile','scopes':['threads_basic','threads_manage_insights','threads_read_replies'],'verifiedAt':now,'expiresAt':now+86400,'capabilityVersion':1,'configured':True,'evidenceSource':'synthetic','revoked':False,'identityVerified':True,'capabilityVerified':True}]
        jobs=[]
        for i in range(n):
            text=titles[i%len(titles)];score=(i%20)/20
            m={'channelId':conn,'platform':'Threads','account':'Practice Studio · fixture','contentRevision':1,'payload':{'text':text,'language':'en'},'payloadDigest':digest(text),'contentType':{'formatId':'text'},'timing':{'timestamp':now-(n-i)*86400,'timeZone':'UTC'},'execution':'synthetic','idempotencyKey':digest(str(i))}
            if calibration or i==n-1:
                m['postDoctor']={'revision':1,'levels':[{'id':'audience','label':'Audience relevance','level':3,'levelName':'Very strong'}], 'scores':{'shareability':score,'specificity':score,'novelty':score},'evaluation':{'model':'typesafe-ai/jev','rubricDigest':'fixture-rubric'},'questionSet':'postdoctor.v1'}
            jobs.append({'id':str(uuid.uuid4()),'state':'verified','stateReason':'Synthetic verification','providerReference':'p2-fixture-'+str(i),'verification':{'at':now-(n-i)*86400,'method':'fixture_lookup'},'manifest':m,'events':[],'attempts':[]})
        state['phase2']['jobs']=jobs
        return state
    result=host.repository.command(wid,token,host.repository.get(wid,token)['revision'],command)
    with host.connection_factory() as db,db.cursor() as cur:
        for cap in ('analytics','comments_read'):
            cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,%s,'Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'",(wid,conn,cap))
        for i,job in enumerate(result['state']['phase2']['jobs']):
            performance.on_verified(cur,wid,job)
            for metric,value in [('likes',[8,12,19,25,30,96][i%6]),('shares',(i%20)*5)]:
                cur.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,read_offset,period_start) VALUES(%s,%s,'threads',%s,%s,%s,'fixture-native-v1',%s,'count','available',to_timestamp(%s),'24h',to_timestamp(%s))",(wid,conn,job['providerReference'],job['id'],metric,value,job['verification']['at']+86400,job['verification']['at']))
        for i,text in enumerate(['How do I keep practising on a busy day?','Which resource would help a beginner?','I disagree about repeating without listening.','Could you make a sequel about preparing for lessons?','My email is alice@example.com @alice, how can I begin?','private medical information should be withheld']):
            cur.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text) VALUES(%s,%s,'threads',%s,%s,'private_handle',%s) ON CONFLICT(workspace_id,provider,provider_comment_id) DO UPDATE SET text=excluded.text",(wid,conn,'p2-fixture-'+str(n-1),'p2-comment-'+str(i),text))
    return {'jobId':result['state']['phase2']['jobs'][-1]['id']}

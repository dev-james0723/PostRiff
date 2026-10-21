"""Synthetic executor/adversarial provider tests. No network or live acceptance."""
import hashlib,json,unittest
from dataclasses import replace
from copy import deepcopy
from postriff_alpha.domain import AlphaError
from postriff_phase2.x_direct_contract import normalize_operation
from postriff_phase2.x_direct_executor import execute,reconcile_post,plain

W='00000000-0000-0000-0000-000000000001'; C='a'*32; U='123'; P='1234567890123456789'; NOW=1800000000
GRANT={'workspaceId':W,'connectionId':C,'providerAccountId':U,'accessToken':'fixture-access','authorizationGeneration':'fixture-generation'}
def op(name='posts.create',body=None,path=None,query=None,units=1,actor=U):
    return normalize_operation(name,workspace_id=W,account_id=C,actor_user_id=actor,path_params=path,body=body,query=query,max_billable_resources=units)
def response(status=200,data=None,errors=None,headers=None,**extra):
    body={'data':data,**extra}
    if errors is not None:body['errors']=errors
    return {'status':status,'body':body,'headers':headers or {}}
class FakeX:
    id='x'
    def __init__(self,*answers):self.answers=list(answers);self.calls=[]
    def api(self,access,method,path,**options):
        self.calls.append({'access':access,'method':method,'path':path,**plain(options)})
        if not self.answers:raise AssertionError('Unexpected transport or hidden retry')
        answer=self.answers.pop(0)
        if isinstance(answer,BaseException):raise answer
        return deepcopy(answer)
class Boundary(unittest.TestCase):
    def denied(self,request,grant=GRANT):
        provider=FakeX(response(201,{'id':P}))
        with self.assertRaises((AlphaError,ValueError)):execute(request,provider,grant,now=NOW)
        self.assertEqual(provider.calls,[])
    def test_noncanonical_actor_ids(self):
        for actor in (None,True,123,'','0','0123',' 123','123/456','1'*20):
            with self.subTest(actor=actor),self.assertRaises((AlphaError,ValueError)):op(body={'text':'Approved'},actor=actor)
    def test_all_wire_fields_and_fingerprint_revalidated(self):
        request=op(body={'text':'Approved'})
        for changes in ({'method':'DELETE'},{'method':'post'},{'path':'/2/tweets/456'},
                {'path':'https://api.x.com/2/tweets'},{'path':'/2/tweets?ids=456'},
                {'body':{'text':'Changed'}},{'query':{'expansions':'author_id'}},
                {'query':{'unknown':'1'}},{'max_billable_resources':True},{'max_billable_resources':2},
                {'estimated_cost_micros':-1},{'operation_id':'posts.reply'},{'fingerprint':'0'*64}):
            with self.subTest(changes=changes):self.denied(replace(request,**changes))
    def test_tenant_connection_and_actor_bound(self):
        request=op(body={'text':'Approved'})
        for key,values in [('workspaceId',[W[:-1]+'2',None]),('connectionId',['b'*32,None]),
                           ('providerAccountId',['456',123,True,'0123',None])]:
            for value in values:
                with self.subTest(key=key,value=value):self.denied(request,{**GRANT,key:value})
        self.denied(replace(op('likes.create',body={'tweet_id':'456'}),path='/2/users/456/likes'))
    def test_actual_request_receipt_and_secret_redaction(self):
        request=op(body={'text':'Approved'});answer=response(201,{'id':P},headers={'authorization':'SECRET','set-cookie':'COOKIE'})
        provider=FakeX(answer);result=execute(request,provider,GRANT,now=NOW);receipt=result['receipt']
        self.assertEqual(result['state'],'accepted')
        self.assertEqual((receipt['source'],receipt['operation'],receipt['method'],receipt['path'],receipt['httpStatus']),('X API','posts.create','POST','/2/tweets',201))
        self.assertEqual(receipt['requestFingerprint'],request.fingerprint)
        self.assertEqual(receipt['resourceId'],P)
        self.assertEqual(receipt['responseSha256'],hashlib.sha256(json.dumps(answer['body'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        self.assertEqual(provider.calls,[{'access':'fixture-access','method':'POST','path':'/2/tweets','max_resources':1,'json_body':{'text':'Approved'}}])
        for secret in ('fixture-access','SECRET','COOKIE'):self.assertNotIn(secret,json.dumps(result))
    def test_partial_post_id_retained_for_readback(self):
        result=execute(op(body={'text':'Approved'}),FakeX(response(201,{'id':P},errors=[{'detail':'partial'}])),GRANT,now=NOW)
        self.assertEqual(result['state'],'accepted');self.assertTrue(result['receipt']['partial'])
    def test_ids_and_status_are_strict(self):
        for resource in (None,True,int(P),0,'','0','01','-1','1'*20,'123/456'):
            self.assertEqual(execute(op(body={'text':'A'}),FakeX(response(201,{'id':resource})),GRANT,now=NOW)['state'],'uncertain')
        for status in (True,'201',201.0,None):
            self.assertEqual(execute(op(body={'text':'A'}),FakeX(response(status,{'id':P})),GRANT,now=NOW)['state'],'uncertain')
    def test_boolean_confirmation_not_truthiness(self):
        request=op('likes.create',body={'tweet_id':'456'})
        for value in (1,'true','false',None,False,[],{}):
            self.assertEqual(execute(request,FakeX(response(data={'liked':value})),GRANT,now=NOW)['state'],'uncertain')
        self.assertEqual(execute(request,FakeX(response(data={'liked':True})),GRANT,now=NOW)['state'],'verified')
    def test_exact_read_ids_cardinality_and_empty_evidence(self):
        request=op('posts.get',path={'id':P})
        for resource in ('456',int(P),True,'0'):
            self.assertEqual(execute(request,FakeX(response(data={'id':resource})),GRANT,now=NOW)['state'],'failed')
        request=op('posts.lookup',query={'ids':P+',456'},units=2)
        for ids in ((P,P),(P,'789'),(P,'456','789')):
            self.assertEqual(execute(request,FakeX(response(data=[{'id':v} for v in ids])),GRANT,now=NOW)['state'],'failed')
        for count in (False,'0',0.0,None,1):
            self.assertEqual(execute(request,FakeX(response(meta={'result_count':count})),GRANT,now=NOW)['state'],'failed')
        self.assertEqual(execute(request,FakeX(response(meta={'result_count':0})),GRANT,now=NOW)['state'],'verified')
        self.assertEqual(execute(request,FakeX(response(meta={'result_count':0},errors=[{}])),GRANT,now=NOW)['state'],'failed')
    def test_metrics_missing_or_conflicting_never_invented(self):
        request=op('analytics.public',path={'id':P})
        self.assertEqual(execute(request,FakeX(response(data={'id':P})),GRANT,now=NOW)['state'],'failed')
        request=op('posts.get',path={'id':P})
        result=execute(request,FakeX(response(data={'id':P})),GRANT,now=NOW)
        self.assertEqual(result['state'],'verified');self.assertNotIn('like_count',json.dumps(result))
        for metrics in ({'like_count':True},{'like_count':-1},{'like_count':'0'},{'like_count':0.0},{'retweet_count':2,'repost_count':3}):
            self.assertEqual(execute(request,FakeX(response(data={'id':P,'public_metrics':metrics})),GRANT,now=NOW)['state'],'failed')
    def test_no_internal_retry_and_bounded_rate_limit(self):
        for status,state in ((429,'queued'),(402,'held'),(403,'held'),(400,'failed'),(502,'uncertain')):
            provider=FakeX(response(status,errors=[{}],headers={'Retry-After':'99999999999'}),response(201,{'id':P}))
            result=execute(op(body={'text':'A'}),provider,GRANT,now=NOW)
            self.assertEqual(result['state'],state);self.assertEqual(len(provider.calls),1);self.assertEqual(len(provider.answers),1)
            if status==429:self.assertTrue(NOW+15<=result['nextAt']<=NOW+86400)
        provider=FakeX(TimeoutError('response lost'),response(201,{'id':P}))
        self.assertEqual(execute(op(body={'text':'A'}),provider,GRANT,now=NOW)['state'],'uncertain');self.assertEqual(len(provider.calls),1)

class Readback(unittest.TestCase):
    def receipt(self,request,partial=False):
        return execute(request,FakeX(response(201,{'id':P},errors=[{}] if partial else None)),GRANT,now=NOW)['receipt']
    def data(self,text,**extra):return {'id':P,'author_id':U,'text':text,**extra}
    def check(self,request,data,**kw):
        provider=FakeX(response(data=data,**kw))
        result=reconcile_post(request,provider,GRANT,self.receipt(request),now=NOW)
        self.assertEqual(len(provider.calls),1);self.assertEqual(provider.calls[0]['method'],'GET');self.assertEqual(provider.calls[0]['max_resources'],1)
        return result
    def test_receipt_integrity_before_lookup(self):
        request=op(body={'text':'A'});original=self.receipt(request)
        for changes in ({'source':'browser'},{'operation':'posts.reply'},{'method':'GET'},{'path':'/2/tweets/456'},
                {'requestFingerprint':'0'*64},{'responseSha256':'bad'},{'httpStatus':True},{'httpStatus':'201'},
                {'httpStatus':201.0},{'httpStatus':500},{'resourceId':int(P)},{'resourceId':'0'}):
            provider=FakeX(response(data=self.data('A')))
            result=reconcile_post(request,provider,GRANT,{**original,**changes},now=NOW)
            self.assertEqual(result['state'],'uncertain');self.assertEqual(provider.calls,[])
        for field in ('source','method','path','operation','requestFingerprint','responseSha256','httpStatus'):
            provider=FakeX(response(data=self.data('A')))
            result=reconcile_post(request,provider,GRANT,{k:v for k,v in original.items() if k!=field},now=NOW)
            self.assertEqual(result['state'],'uncertain');self.assertEqual(provider.calls,[])
    def test_current_contract_checked_before_lookup(self):
        request=op(body={'text':'A'});receipt=self.receipt(request)
        for changed,grant in ((replace(request,body={'text':'B'}),GRANT),(request,{**GRANT,'providerAccountId':'456'})):
            provider=FakeX(response(data=self.data('B')))
            with self.assertRaises((AlphaError,ValueError)):reconcile_post(changed,provider,grant,receipt,now=NOW)
            self.assertEqual(provider.calls,[])
    def test_partial_post_and_complete_lookup_have_separate_receipts(self):
        request=op(body={'text':'A'});first=self.receipt(request,True);answer=response(data=self.data('A'))
        result=reconcile_post(request,FakeX(answer),GRANT,first,now=NOW)
        self.assertEqual(result['state'],'verified');self.assertEqual(first['method'],'POST');self.assertTrue(first['partial'])
        self.assertEqual(result['receipt']['method'],'GET');self.assertFalse(result['receipt']['partial']);self.assertTrue(result['receipt']['readbackVerified'])
        self.assertNotEqual(first['responseSha256'],result['receipt']['responseSha256'])
    def test_literal_html_entities_and_whitespace_not_collapsed(self):
        for approved,other in (('A &amp; B','A & B'),('Cost &#36;5','Cost $5'),('Literal &lt;tag&gt;','Literal <tag>'),('A','A ')):
            request=op(body={'text':approved})
            self.assertEqual(self.check(request,self.data(other))['state'],'uncertain')
            self.assertEqual(self.check(request,self.data(approved))['state'],'verified')
        request=op(body={'text':'Café\nsecond'})
        self.assertEqual(self.check(request,self.data('Cafe\u0301\r\nsecond'))['state'],'verified')
    @staticmethod
    def entity(text,short,expanded,utf16=False):
        start=text.rindex(short);end=start+len(short)
        if utf16:start,end=len(text[:start].encode('utf-16-le'))//2,len(text[:end].encode('utf-16-le'))//2
        return {'start':start,'end':end,'url':short,'expanded_url':expanded}
    def test_tco_expansion_requires_exact_span(self):
        short='https://t.co/Exact';expanded='https://example.com/approved'
        for prefix,utf16 in (('Read ',False),('🙂 Read ',True)):
            text=prefix+short;request=op(body={'text':prefix+expanded})
            data=self.data(text,entities={'urls':[self.entity(text,short,expanded,utf16)]})
            self.assertEqual(self.check(request,data)['state'],'verified')
        entity=self.entity(short,short,expanded);request=op(body={'text':expanded})
        for urls in ([{**entity,'start':False}],[entity,{**entity,'expanded_url':'https://example.com/other'}]):
            self.assertEqual(self.check(request,self.data(short,entities={'urls':urls}))['state'],'uncertain')
        request=op(body={'text':'Literal '+short})
        self.assertEqual(self.check(request,self.data('Literal '+short))['state'],'verified')
        request=op(body={'text':'A'});self.assertEqual(self.check(request,self.data('A '+short))['state'],'uncertain')
    def test_actor_id_refs_attachments_and_aliases(self):
        request=op(body={'text':'A'})
        for extra in ({'id':'456'},{'author_id':'456'},{'id':int(P)},{'author_id':123},
                {'referenced_tweets':[{'type':'replied_to','id':'456'}]},
                {'attachments':{'media_keys':['3_456']}},{'attachments':{'poll_ids':['456']}},
                {'edit_history_tweet_ids':[P],'edit_history_post_ids':['456']}):
            self.assertEqual(self.check(request,self.data('A',**extra))['state'],'uncertain')
        request=op('posts.reply',body={'text':'A','reply':{'in_reply_to_tweet_id':'456'}})
        refs=[{'type':'replied_to','id':'456'}]
        self.assertEqual(self.check(request,self.data('A',referenced_posts=refs))['state'],'verified')
        self.assertEqual(self.check(request,self.data('A',referenced_tweets=refs,referenced_posts=[{'type':'replied_to','id':'789'}]))['state'],'uncertain')
    def test_quote_suffix_only_exact_target_and_reference(self):
        request=op('posts.quote',body={'text':'Approved quote','quote_tweet_id':'456'})
        short='https://t.co/AutoQuote';text='Approved quote '+short;refs=[{'type':'quoted','id':'456'}]
        for expanded,expected in (('https://x.com/i/web/status/456','verified'),('https://twitter.com/account/status/456','verified'),
                ('https://x.com/i/web/status/789','uncertain'),('https://example.com/status/456','uncertain'),
                ('https://x.com/i/web/status/456/likes','uncertain')):
            data=self.data(text,referenced_tweets=refs,entities={'urls':[self.entity(text,short,expanded)]})
            self.assertEqual(self.check(request,data)['state'],expected)
        data=self.data(text,entities={'urls':[self.entity(text,short,'https://x.com/i/web/status/456')]})
        self.assertEqual(self.check(request,data)['state'],'uncertain')
    def test_incomplete_lookup_pending_and_never_repeats_write(self):
        request=op(body={'text':'A'})
        self.assertEqual(self.check(request,{'id':P,'text':'A'})['state'],'accepted')
        self.assertEqual(self.check(request,self.data('A'),errors=[{}])['state'],'accepted')
        for failure in (TimeoutError('lost'),response(429,errors=[{}],headers={'Retry-After':'999999999999'})):
            provider=FakeX(failure,response(data=self.data('A')))
            result=reconcile_post(request,provider,GRANT,self.receipt(request),now=NOW)
            self.assertEqual(result['state'],'accepted');self.assertEqual(len(provider.calls),1)
            self.assertEqual(provider.calls[0]['method'],'GET')
            if result.get('reasonCode')=='x_rate_limited':self.assertTrue(NOW+15<=result['nextAt']<=NOW+86400)
if __name__=='__main__':unittest.main()

"""Offline contract/security tests. These never qualify a real Telegram destination."""
import copy
import asyncio
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src')]
from postriff_alpha.domain import AlphaError
from postriff_phase2.telegram.capabilities import CATALOG, compute, destination_type
from postriff_phase2.telegram.content import normalize, formatted, entities, poll, keyboard
from postriff_phase2.telegram.publishing import payload, receipt, submit
from postriff_phase2.api_tokens import route_scope

CHAT={'id':-100123,'type':'channel','username':'rafii_test'}
ADMIN={'status':'administrator','can_post_messages':True,'can_edit_messages':False,'can_delete_messages':False,'can_pin_messages':False}

def manifest(t=None, text='hello', media=None):
    return {'workspaceId':'workspace','channelId':'channel-id','platform':'Telegram','payload':{'text':text},'media':media or [],'publishOptions':{'telegram':t or {}}}
def file(kind,n=1): return {'kind':kind,'fileId':'telegram_file_'+str(n),'recordId':'record-'+str(n)}
def success(messages):return {'status':200,'body':{'ok':True,'result':messages}}
def msg(mid=1,**kw):return {'message_id':mid,'chat':CHAT,'date':1791000000,**kw}

class Capabilities(unittest.TestCase):
    def release_evidence(self):
        from postriff_phase2.telegram.qualification import RELEASE_VERSION, DESTINATION_VERSION
        return {'source':'telegram_real_e2e','releaseVersion':RELEASE_VERSION,
                'qualificationVersion':DESTINATION_VERSION,'reviewed':True,
                'flows':{f:{'passed':True,'timestamp':1791000000,'evidenceRef':'synthetic-test-of-validation-only'} for f in 'ABCD'},
                'cases':[{'passed':True,'timestamp':1791000000,'evidenceRef':'synthetic-test-of-validation-only',
                          'connectionType':'bot','capability':'publish','botId':999,'chatId':-100123,'messageId':9}]}

    def test_public_release_does_not_require_operator_enrollment_for_new_destination(self):
        from postriff_phase2.social_connectors import TelegramConnector
        adapter=TelegramConnector('synthetic','synthetic','https://synthetic.example');adapter._me={'id':444}
        adapter.acceptance={'_release':self.release_evidence()}
        self.assertEqual(adapter.qualified('-100999'),{'publish'})
        self.assertEqual(adapter.qualified('new-business','business','new-connection'),set())
        self.assertFalse(compute(CHAT,{'status':'left'},qualified=adapter.qualified('-100999'))['publish']['enabled'])

    def test_public_release_requires_real_reviewed_complete_current_evidence(self):
        from postriff_phase2.telegram.qualification import release_capabilities
        for patch in ({'source':'synthetic'},{'reviewed':False},{'releaseVersion':'stale'},{'flows':{}},{'cases':None}):
            self.assertEqual(release_capabilities({**self.release_evidence(),**patch},'bot'),set())
        evidence=self.release_evidence();evidence['flows']['D']['timestamp']=float('nan')
        self.assertEqual(release_capabilities(evidence,'bot'),set())
        evidence=self.release_evidence();evidence['cases'][0]['botId']=True
        self.assertEqual(release_capabilities(evidence,'bot'),set())

    def test_connected_does_not_enable_publishing(self):
        c=compute(CHAT,ADMIN)
        self.assertTrue(c['identity']['enabled']);self.assertEqual(c['publish']['state'],'requires_e2e')
        self.assertFalse(c['story_publish']['enabled']);self.assertFalse(c['paid_media']['enabled'])

    def test_private_candidate_execution_does_not_fabricate_acceptance_or_rights(self):
        c=compute(CHAT,ADMIN,candidate={'publish','text','schedule','story_publish'})
        self.assertTrue(c['publish']['enabled']);self.assertTrue(c['publish']['candidateExecution'])
        self.assertFalse(c['publish']['e2eTested']);self.assertEqual(c['photo']['state'],'requires_e2e')
        self.assertFalse(c['story_publish']['enabled'])
        denied=compute(CHAT,{'status':'left'},candidate={'publish','text'})
        self.assertFalse(denied['publish']['enabled'])

    def test_canary_grant_is_default_off_exact_owner_workspace_and_production_binding(self):
        import time
        from postriff_phase2.social_connectors import TelegramConnector
        from postriff_phase2.social_release import PRODUCTION_PROJECT, PRODUCTION_REF, PRODUCTION_URL
        workspace='11111111-1111-4111-8111-111111111111';actor='22222222-2222-4222-8222-222222222222'
        owner={'workspace_id':workspace,'actor_id':actor}
        scope={'workspaceId':workspace,'actorId':actor,'botId':999,'expiresAt':time.time()+600,'destinations':[{'chatId':-100123,'mode':'bot','capabilities':['publish','text']}]}
        values={'POSTRIFF_TELEGRAM_BOT_TOKEN':'123456:'+'x'*35,'POSTRIFF_TELEGRAM_WEBHOOK_SECRET':'x'*32,
                'POSTRIFF_PUBLIC_BASE_URL':'https://rafii.io','VERCEL_ENV':'production','VERCEL_PROJECT_ID':PRODUCTION_PROJECT,
                'POSTRIFF_SUPABASE_URL':PRODUCTION_URL,'NEXT_PUBLIC_SUPABASE_URL':PRODUCTION_URL,
                'POSTRIFF_DATABASE_URL':f'postgresql://postgres.{PRODUCTION_REF}:synthetic@aws-0-us-east-1.pooler.supabase.com/postgres?sslmode=require',
                'POSTRIFF_TELEGRAM_CANARY_ENABLED':'true','POSTRIFF_TELEGRAM_CANARY_SCOPE':json.dumps(scope)}
        bot,_=TelegramConnector.mount(values);bot._me={'id':999}
        self.assertEqual(bot.candidate_capabilities(-100123,**owner),{'publish','text'})
        self.assertEqual(bot.qualified(-100123),set())
        self.assertEqual(bot.candidate_capabilities(-100124,**owner),set())
        self.assertEqual(bot.candidate_capabilities(-100123,'business','another',**owner),set())
        for context in ({},{'workspace_id':'other','actor_id':actor},{'workspace_id':workspace,'actor_id':'other'}):
            self.assertEqual(bot.candidate_capabilities(-100123,**context),set())
        for patch in ({'VERCEL_ENV':'preview'},{'POSTRIFF_TELEGRAM_CANARY_ENABLED':''},
                      {'POSTRIFF_SUPABASE_URL':'https://other.supabase.co'},
                      {'VERCEL_PROJECT_ID':'prj_4bfvSc0AC6am9FdknFWcwNYgmcnN'},
                      {'POSTRIFF_TELEGRAM_CANARY_SCOPE':json.dumps({**scope,'expiresAt':time.time()+90000})}):
            other,_=TelegramConnector.mount({**values,**patch});other._me={'id':999}
            self.assertEqual(other.candidate_capabilities(-100123,**owner),set())
        bot._me={'id':111};self.assertEqual(bot.candidate_capabilities(-100123,**owner),set())
        bot._me={'id':999};bot.candidate_scope['expiresAt']=time.time()-1
        self.assertEqual(bot.candidate_capabilities(-100123,**owner),set())
        # The retired QA variables never restore a staging execution grant.
        old={k:v for k,v in values.items() if not k.startswith('POSTRIFF_TELEGRAM_CANARY_')}
        old.update(POSTRIFF_TELEGRAM_QA_SCOPE=json.dumps(scope),POSTRIFF_TELEGRAM_QA_SUPABASE_URL=PRODUCTION_URL)
        retired,_=TelegramConnector.mount(old);retired._me={'id':999}
        self.assertEqual(retired.candidate_capabilities(-100123,**owner),set())
    def test_minimal_rights_do_not_imply_pin(self):
        c=compute(CHAT,ADMIN,qualified=CATALOG)
        self.assertTrue(c['publish']['enabled']);self.assertTrue(c['edit_own']['enabled']);self.assertTrue(c['delete_own']['enabled'])
        self.assertFalse(c['pin']['enabled']);self.assertFalse(c['topics']['enabled'])
    def test_permission_loss_overrules_qualification(self):
        c=compute(CHAT,{'status':'administrator','can_post_messages':False},qualified=CATALOG)
        self.assertEqual(c['text']['state'],'permission_required')
    def test_restricted_group_formats(self):
        chat={'id':-44,'type':'group','permissions':{'can_send_messages':True,'can_send_photos':True}}
        c=compute(chat,{'status':'member'},qualified=CATALOG)
        self.assertTrue(c['text']['enabled']);self.assertTrue(c['photo']['enabled']);self.assertFalse(c['video']['enabled'])
        self.assertTrue(c['reaction_set']['enabled']);self.assertFalse(c['reactions']['enabled'])
        self.assertTrue(c['photo_album']['enabled']);self.assertFalse(c['mixed_album']['enabled'])
    def test_business_requires_active_connection_right_and_recent_incoming(self):
        chat={'id':5,'type':'private'};business={'is_enabled':True,'rights':{'can_reply':True,'can_manage_stories':True}}
        c=compute(chat,{'status':'member'},mode='business',business=business,incoming_at=100,now=86500,qualified=CATALOG)
        self.assertFalse(c['publish']['enabled']);self.assertFalse(c['business_messaging']['enabled'])
        c=compute(chat,{'status':'member'},mode='business',business=business,incoming_at=100,now=101,qualified=CATALOG)
        self.assertTrue(c['business_messaging']['enabled']);self.assertFalse(c['pin']['enabled']);self.assertFalse(c['business_stories']['enabled'])
    def test_channel_dm_is_separate_and_cannot_receive_poll(self):
        chat={'id':-777,'type':'supergroup','is_direct_messages':True}
        c=compute(chat,dict(ADMIN,can_manage_direct_messages=True),qualified=CATALOG)
        self.assertTrue(c['channel_dm']['enabled']);self.assertFalse(c['poll']['enabled'])
        c=compute(chat,dict(ADMIN,can_post_messages=False,can_manage_direct_messages=True),qualified=CATALOG)
        self.assertFalse(c['approve_suggested_post']['enabled']);self.assertTrue(c['decline_suggested_post']['enabled'])
    def test_destination_types(self):
        values=[({'type':'channel'},'private_channel'),({'type':'channel','username':'a'},'public_channel'),({'type':'group'},'basic_group'),({'type':'supergroup'},'supergroup'),({'type':'supergroup','is_forum':True},'forum_supergroup'),({'type':'private'},'user_dm')]
        for chat,kind in values:self.assertEqual(destination_type(chat),kind)
    def test_api_tokens_have_no_telegram_authority(self):
        for method in ('GET','POST','DELETE'):
            self.assertIsNone(route_scope(method,['api','workspaces','w','telegram','connections','c','execute']))
    def test_group_connection_requires_administrator_proof(self):
        from postriff_phase2.social_connectors import TelegramConnector
        bot=TelegramConnector('synthetic','synthetic','https://synthetic.example');bot._me={'id':999}
        bot.call=lambda method,args: {'id':-44,'type':'group'} if method=='getChat' else {'status':'member'}
        with self.assertRaises(AlphaError):bot.grant_from_context({'chat':{'id':-44,'userId':5}})
        bot.call=lambda method,args: {'id':-44,'type':'group'} if method=='getChat' else {'status':'administrator'}
        grant=bot.grant_from_context({'chat':{'id':-44,'userId':5}})
        self.assertEqual(json.loads(grant['accessToken'])['chat'],-44)
        bot.call=lambda method,args: {'id':-44,'type':'group'} if method=='getChat' else {'status':'member'}
        self.assertEqual(json.loads(bot.grant_from_context({'chat':{'id':-44,'senderChatId':-44}})['accessToken'])['chat'],-44)

class Content(unittest.TestCase):
    def test_utf16_entities_and_no_surrogate_splitting(self):
        self.assertEqual(entities('🎹abc',[{'type':'bold','offset':2,'length':3}])[0]['offset'],2)
        with self.assertRaises(AlphaError):entities('🎹abc',[{'type':'bold','offset':1,'length':3}])
    def test_structured_html_nested_spoilers_quote_code(self):
        text,es=formatted('<b>A &amp; <i>B</i></b> <tg-spoiler>secret</tg-spoiler>\n<blockquote expandable>quote</blockquote>\n<pre><code class="language-python">x=1</code></pre>','HTML')
        self.assertEqual(text,'A & B secret\nquote\nx=1')
        self.assertEqual({e['type'] for e in es},{'bold','italic','spoiler','expandable_blockquote','pre'})
        self.assertEqual(es[-1]['language'],'python')
    def test_injection_unknown_overlap_and_malformed_html_rejected(self):
        for text in ('<script>alert(1)</script>','<b>x</i>','<a href="javascript:run()">x</a>'):
            with self.assertRaises(AlphaError):formatted(text,'HTML')
        with self.assertRaises(AlphaError):entities('abc',[{'type':'code','offset':0,'length':3},{'type':'bold','offset':1,'length':1}])
    def test_canonical_revision_is_stable_and_tampering_rejected(self):
        o=normalize({'telegram':{'parseMode':'HTML'}},[],'<b>hello</b>')
        self.assertEqual(normalize(o,[],'<b>hello</b>'),o)
        o['telegram']['text']='other'
        with self.assertRaises(AlphaError):normalize(o,[],'<b>hello</b>')
    def test_markup_length_after_parsing(self):
        self.assertEqual(len(normalize({'telegram':{'parseMode':'HTML'}},[],'<b>'+('x'*4096)+'</b>')['telegram']['text']),4096)
        with self.assertRaises(AlphaError):normalize({},[],'x'*4097)
    def test_markdown_v2_escape_and_unsupported_links_are_explicit(self):
        self.assertEqual(formatted('*hi* \\#tag','MarkdownV2')[0],'hi #tag')
        with self.assertRaises(AlphaError):formatted('[hello](https://example.com)','MarkdownV2')
    def test_video_note_omission_must_be_explicit(self):
        opts={'telegram':{'format':'video_note','fileIds':[file('video_note')]}}
        with self.assertRaises(AlphaError):normalize(opts,[],'source text')
        opts['telegram']['omitCaption']=True;o=normalize(opts,[],'source text')
        self.assertEqual(o['telegram']['text'],'');self.assertEqual(normalize(o,[],'source text'),o)
    def test_poll_remains_native_and_has_no_silent_adaptation(self):
        p=poll({'question':'pick','options':[{'text':'A'},{'text':'B'}],'type':'quiz','correct_option_ids':[0,1],'allows_multiple_answers':True,'allows_revoting':True,'shuffle_options':True})
        self.assertEqual(p['correct_option_ids'],[0,1])
        with self.assertRaises(AlphaError):normalize({'telegram':{'format':'poll','poll':p}},[],'different')
        with self.assertRaises(AlphaError):poll({'question':'pick','options':[{'text':'A'}],'is_anonymous':True,'allow_adding_options':True})
    def test_paid_callback_and_business_mini_app_buttons_disabled(self):
        for button in ({'text':'Buy','pay':True},{'text':'Go','callback_data':'danger'}):
            with self.assertRaises(AlphaError):keyboard([[button]])
        with self.assertRaises(AlphaError):keyboard([[{'text':'App','web_app':{'url':'https://example.com'}}]],destination='user_dm',business=True)
    def test_album_keyboard_rejected(self):
        with self.assertRaises(AlphaError):normalize({'telegram':{'format':'album','fileIds':[file('photo',1),file('photo',2)],'buttons':[[{'text':'go','url':'https://example.com'}]]}},[],'caption')
    def test_unknown_options_are_not_silently_discarded(self):
        with self.assertRaises(AlphaError):normalize({'telegram':{'newUnsupportedFormat':True}},[],'hello')
    def test_text_and_poll_do_not_discard_files_or_question_formatting(self):
        with self.assertRaises(AlphaError):normalize({'telegram':{'format':'text','fileIds':[file('photo')]}},[],'hello')
        p={'question':'hello','options':[{'text':'A'}]}
        with self.assertRaises(AlphaError):normalize({'telegram':{'format':'poll','poll':p,'fileIds':[file('photo')]}},[],'hello')
        with self.assertRaises(AlphaError):normalize({'telegram':{'format':'poll','poll':p,'parseMode':'HTML'}},[],'<b>hello</b>')

class Publishing(unittest.TestCase):
    def build(self,t,chat=CHAT):return payload(manifest(t),{'chat':chat['id']},chat,SimpleNamespace(assets=None),file_check=lambda *a:True)
    def test_native_method_per_format(self):
        for kind,method in [('photo','sendPhoto'),('video','sendVideo'),('animation','sendAnimation'),('audio','sendAudio'),('voice','sendVoice'),('document','sendDocument')]:
            got,body,files,_=self.build({'format':kind,'fileIds':[file(kind)]})
            self.assertEqual(got,method);self.assertEqual(body[kind],file(kind)['fileId']);self.assertEqual(files,[])
    def test_workspace_file_reuse_checked(self):
        with self.assertRaises(AlphaError):payload(manifest({'format':'photo','fileIds':[file('photo')]}),{'chat':CHAT['id']},CHAT,SimpleNamespace(),file_check=lambda *a:False)
    def test_forum_never_falls_into_general_feed(self):
        chat={'id':-88,'type':'supergroup','is_forum':True}
        with self.assertRaises(AlphaError):self.build({},chat)
        _,body,_,_=self.build({'messageThreadId':19},chat);self.assertEqual(body['message_thread_id'],19)
    def test_dm_topic_required(self):
        chat={'id':-88,'type':'supergroup','is_direct_messages':True}
        with self.assertRaises(AlphaError):self.build({},chat)
        _,body,_,_=self.build({'directMessagesTopicId':12},chat);self.assertEqual(body['direct_messages_topic_id'],12)
    def test_album_homogeneous_audio_and_paired_live_photo(self):
        opts={'format':'album','fileIds':[file('audio',1),file('audio',2)]}
        _,body,_,_=self.build(opts);self.assertEqual([x['type'] for x in body['media']],['audio','audio'])
        opts={'format':'album','fileIds':[file('video',1),file('photo',2),file('photo',3)],'mediaOptions':{'albumItems':[{'type':'live_photo','sourceIndex':0,'photoIndex':1},{'type':'photo','sourceIndex':2}]}}
        _,body,_,_=self.build(opts);self.assertEqual(body['media'][0]['photo'],file('photo',2)['fileId']);self.assertEqual(len(body['media']),2)
        opts['mediaOptions']['albumItems'][1]['sourceIndex']=1
        with self.assertRaises(AlphaError):self.build(opts)
    def test_partial_album_receipt_never_verified_or_split(self):
        expected={'text':'hello'};body={'media':[{},{}]}
        r=receipt(success([msg(media_group_id='a',caption='hello')]),CHAT['id'],'sendMediaGroup',expected,body)
        self.assertEqual(r['state'],'uncertain')
        r=receipt(success([msg(1,media_group_id='a',caption='hello'),msg(2,media_group_id='b')]),CHAT['id'],'sendMediaGroup',expected,body)
        self.assertEqual(r['state'],'uncertain')
    def test_live_photo_upload_limits_are_checked_before_reading_storage(self):
        assets=[{'id':'video','mime':'video/mp4','duration':11,'bytes':100,'width':200,'height':200},{'id':'still','mime':'image/jpeg','bytes':100,'width':200,'height':200}]
        with self.assertRaises(AlphaError) as error:payload(manifest({'format':'live_photo'},media=assets),{'chat':CHAT['id']},CHAT,SimpleNamespace(assets=None))
        self.assertIn('10 seconds',str(error.exception))
    def test_plain_text_and_photo_album_evidence_cannot_unlock_other_formats(self):
        class Bot:
            def session(self,_):return {'workspace':'workspace','chat':CHAT['id']}
            def for_session(self,_):return self
            def call(self,method,args):return CHAT if method=='getChat' else ADMIN
            def me(self):return {'id':999}
            def qualified(self,*args):return {'publish','text','album','photo_album'}
            def request(self,*args):raise AssertionError('Unqualified format must make no send request')
        bot=Bot();host=SimpleNamespace(assets=None)
        result=submit(manifest({'format':'album','fileIds':[file('video',1),file('video',2)]}),bot,'synthetic',host)
        self.assertEqual(result['state'],'held');self.assertIn('video_album: requires_e2e',result['confirmed'])
        result=submit(manifest({'parseMode':'HTML'},text='<b>formatted</b>'),bot,'synthetic',host)
        self.assertEqual(result['state'],'held');self.assertIn('text_formatting: requires_e2e',result['confirmed'])
    def test_exact_message_receipt_and_thread_verification(self):
        expected={'text':'hello'};body={'text':'hello','message_thread_id':2}
        r=receipt(success(msg(text='hello',message_thread_id=2)),CHAT['id'],'sendMessage',expected,body)
        self.assertEqual(r['state'],'verified');self.assertEqual(r['telegram']['messages'][0]['date'],1791000000)
        r=receipt(success(msg(text='edited',message_thread_id=2)),CHAT['id'],'sendMessage',expected,body)
        self.assertEqual(r['state'],'published')
        r=receipt(success(msg(text='hello',message_thread_id=3)),CHAT['id'],'sendMessage',expected,body)
        self.assertEqual(r['state'],'published')
    def test_definitive_rate_limit_vs_ambiguous_transport(self):
        r=receipt({'status':429,'body':{'ok':False,'error_code':429,'parameters':{'retry_after':9}}},CHAT['id'],'sendMessage',{'text':'x'},{})
        self.assertEqual((r['state'],r['retryAfter']),('scheduled',9))
        self.assertEqual(receipt({'status':502},CHAT['id'],'sendMessage',{'text':'x'},{})['state'],'uncertain')
    def test_receipt_sanitizer_rejects_secret_and_mismatched_reference(self):
        from postriff_phase2.outcomes import normalize_result
        r=receipt(success(msg(text='hello')),CHAT['id'],'sendMessage',{'text':'hello'},{'chat_id':CHAT['id'],'text':'hello'})
        good=normalize_result(r,{'manifest':{'platform':'Telegram'}})
        self.assertIn('telegram',good)
        r['telegram']['payload']['token']='secret'
        bad=normalize_result(r,{'manifest':{'platform':'Telegram'}})
        self.assertNotIn('telegram',bad)

if __name__=='__main__':unittest.main()

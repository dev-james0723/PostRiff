"""Inert harness bookkeeping regressions; no real SQL or provider calls."""
import copy
import hashlib
import threading
import time
import unittest
from collections import Counter
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from phase2.postgres_discord_capacity import Runtime, APP, BOT, fingerprint


class ApprovalReceiptControls(unittest.TestCase):
    def fixture(self, *, wrong_channel=False, wrong_receipt=False):
        r=Runtime.__new__(Runtime);r.lock=threading.RLock();r.nonces={};r.guard=lambda:None
        counters=Counter();events=[]
        r.m=SimpleNamespace(records={},timing=lambda *a:None,running=lambda *a:nullcontext(),
            count=lambda key,*a:counters.update([key]),event=lambda kind,**values:events.append((kind,values)))
        f={'workspace':'workspace','user':'approver','token':'synthetic','index':0,'lock':threading.RLock(),
           'destinations':[('connection','guild','channel')],
           'service':SimpleNamespace(repository=SimpleNamespace(get=lambda *a:{'revision':0}))}
        manifest={'workspaceId':'workspace','actor':'approver','channelId':'connection',
            'idempotencyKey':'synthetic-publication','payloadDigest':'p'*64,'payload':{'text':'exact text'},
            'discord':{'publicationId':'publication','target':{'channelId':'channel','guildId':'guild','applicationId':APP,
                'botUserId':BOT,'linkedUserId':'linked-user'}}}
        authorization={'digest':'e'*64}
        job={'id':'publication','manifest':copy.deepcopy(manifest),'discordAuthorization':authorization,
             'approvedBy':'approver','approvedAt':time.time(),'approvalDigest':'d'*64,
             'leaseOwner':'worker','leaseId':'lease','leaseUntil':time.time()+60,
             'discordDispatchIntents':[{'id':'intent','rateAdmissionId':'00000000-0000-4000-8000-000000000001'}]}
        review={'id':'review','digest':'d'*64,'manifest':copy.deepcopy(manifest)}
        state={'variants':[],'phase2':{'reviews':[copy.deepcopy(review)],'jobs':[]}}
        r.state=lambda fixture:state;r.change=lambda fixture,update:update(state)
        r.discord_users={0:('linked-user',)}
        r.auth=SimpleNamespace(destination_id=lambda *a:'destination',approval=lambda j:copy.deepcopy(authorization),
            wire_content=lambda m:{'content':m['payload']['text']})
        digest=lambda value:hashlib.sha256(str(value).encode()).hexdigest()
        consumed=(fingerprint(manifest),authorization['digest'],job['approvalDigest'],
            digest(job['leaseOwner']),digest(job['leaseId']),digest('channel'),'sent')
        @contextmanager
        def connection():
            db=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:consumed))
            yield db
        r.connection=connection;observed=[]
        def command(fixture,revision,action,payload):
            if action=='p2_review':return {'revision':1,'state':copy.deepcopy(state)}
            self.assertEqual(action,'p2_approve');self.assertEqual(payload['reviewId'],'review')
            state['phase2']['jobs']=[copy.deepcopy(job)]
            state['phase2']['reviews'][0]['jobId']='other' if wrong_receipt else 'publication'
            if not wrong_receipt:
                payload={'nonce':hashlib.sha256(manifest['idempotencyKey'].encode()).hexdigest()[:25],
                    'content':'exact text','allowed_mentions':{'parse':[]}}
                # A real worker can see the committed approval before the
                # caller has received the fresh approval response.
                observed.append(r.create_oracle('other' if wrong_channel else 'channel',payload,time.time()))
            return {'revision':2,'state':copy.deepcopy(state)}
        r.command=command
        return r,f,review,observed,counters

    def test_committed_delivery_before_fresh_response_keeps_exact_receipt(self):
        r,f,old,observed,counters=self.fixture()
        record=r.approve(f,'request',time.time(),'control')
        self.assertNotIn('jobId',old)
        self.assertEqual(record['jobId'],'publication')
        self.assertEqual(observed[0]['alias'],'request')
        self.assertTrue(observed[0]['safe'])
        self.assertEqual(counters['unsafeCreateAttempts'],0)
        self.assertNotIn('error',record)

    def test_pre_registration_cannot_authorize_another_destination(self):
        r,f,old,observed,counters=self.fixture(wrong_channel=True)
        r.approve(f,'request',time.time(),'control')
        self.assertFalse(observed[0]['safe'])
        self.assertEqual(counters['unsafeCreateAttempts'],1)

    def test_fresh_receipt_must_link_the_exact_reviewed_publication(self):
        r,f,old,observed,counters=self.fixture(wrong_receipt=True)
        record=r.approve(f,'request',time.time(),'control')
        self.assertIsNone(record['jobId'])
        self.assertEqual(record['error'],'Incomplete')
        self.assertFalse(observed)

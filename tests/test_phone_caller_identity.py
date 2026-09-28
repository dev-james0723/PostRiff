"""Offline admission assets, JWT method semantics and Supabase adapter boundary."""
import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_identity import SupabaseIdentityAdmin, verified_passkey_time, verified_webauthn_time
from postriff_phase2.phone import prompt_assets
from postriff_phase2.notifications.store import _clean_payload
from postriff_phase2.hosted_identity import _NoAuthRedirect

class CallerIdentityTests(unittest.TestCase):
    def test_only_exact_challenge_deep_link_bypasses_phone_number_redaction(self):
        href='/app/phone/verify-call?challenge=12345678-1234-1234-1234-123456789012'
        self.assertEqual(_clean_payload({'href':href}), {'href':href})
        for text in ('/app?code=123456789012','/app?phone=+12025550123'):
            self.assertNotEqual(_clean_payload({'href':text})['href'],text)
        self.assertIsNone(_NoAuthRedirect().redirect_request(None,None,302,'',{},'https://evil.test'))

    def test_prompt_contract_hash_and_copy_must_agree(self):
        for name in ('dial-acceptance','dial-inbound','dial-inbound-retry','dial-repeat'):
            self.assertGreaterEqual(len(prompt_assets.read(name)),8000)
        text=json.loads((prompt_assets.ASSETS/'prompts.json').read_text())['prompts']['dial-inbound']
        self.assertEqual(text,'Please enter or say your 12-digit agent pairing code. If you enter it on your keypad, press star when you’re done.')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('prompts.json','installed-prompts.json','dial-inbound.mulaw'):
                (root/name).write_bytes((prompt_assets.ASSETS/name).read_bytes())
            spec=json.loads((root/'prompts.json').read_text());spec['prompts']['dial-inbound']='Changed without approval'
            (root/'prompts.json').write_text(json.dumps(spec))
            with patch.object(prompt_assets,'ASSETS',root),self.assertRaises(ValueError): prompt_assets.read('dial-inbound')

    def test_jwt_distinguishes_passkey_sign_in_from_webauthn_mfa(self):
        def token(amr): return 'x.'+base64.urlsafe_b64encode(json.dumps({'sub':'user','iat':9999,'amr':amr}).encode()).decode().rstrip('=')+'.x'
        for methods in ([],[{'method':'passkey','timestamp':9999}],[{'method':'webauthn','timestamp':9999}],[{'method':'mfa/webauthn','timestamp':'9999'}],['mfa/webauthn']):
            self.assertEqual(verified_webauthn_time(token(methods),'user'),0)
        self.assertEqual(verified_webauthn_time(token([{'method':'mfa/webauthn','timestamp':5}]),'user'),5)
        for methods in ([],[{'method':'mfa/webauthn','timestamp':9999}],[{'method':'webauthn','timestamp':9999}],[{'method':'passkey','timestamp':'9999'}],['passkey']):
            self.assertEqual(verified_passkey_time(token(methods),'user'),0)
        self.assertEqual(verified_passkey_time(token([{'method':'passkey','timestamp':7}]),'user'),7)
        with self.assertRaises(AlphaError): verified_passkey_time(token([]),'wrong-user')

    def test_admin_passkey_list_is_server_only_and_content_bounded(self):
        user='00000000-0000-0000-0000-000000000001'
        passkey='00000000-0000-0000-0000-000000000002'
        calls=[]
        def fetch(method,url,headers):
            calls.append((method,url,headers))
            return 200,[{'id':passkey,'friendly_name':'Phone','last_used_at':'2026-09-28T12:00:00Z'},
                        {'id':'not-a-uuid','friendly_name':'ignored'}]
        identity=SupabaseIdentityAdmin('https://auth.test','publishable','server-only',fetch=fetch)
        self.assertEqual(identity.registered_passkeys(user),[{'id':passkey,'name':'Phone','last_used_at':'2026-09-28T12:00:00Z'}])
        self.assertEqual(calls[0][0:2],('GET','https://auth.test/auth/v1/admin/users/'+user+'/passkeys'))
        self.assertEqual(calls[0][2]['Authorization'],'Bearer server-only')

    def test_adapter_uses_server_bound_nonce_factor_origin_and_requires_uv(self):
        identity=SupabaseIdentityAdmin('https://auth.test','publishable','server-only')
        factor='00000000-0000-0000-0000-000000000001';nonce='00000000-0000-0000-0000-000000000002'
        credential={'response':{'authenticatorData':base64.urlsafe_b64encode(bytes(32)+bytes([5])+bytes(4)).decode()}}
        with patch.object(identity,'_phone_mfa_post',return_value={'access_token':'synthetic'}) as post:
            identity.phone_mfa_challenge('session',factor,'rafii.test','https://rafii.test')
            self.assertEqual(post.call_args.args,('session',factor,'challenge',{'webauthn':{'rpId':'rafii.test','rpOrigins':['https://rafii.test']}}))
            identity.phone_mfa_verify('session',factor,nonce,'rafii.test','https://rafii.test',credential)
            self.assertEqual(post.call_args.args[3]['challenge_id'],nonce)
            self.assertEqual(post.call_args.args[3]['webauthn']['credential_response'],credential)
            for flags in (0,1,4):
                bad=copy.deepcopy(credential);bad['response']['authenticatorData']=base64.urlsafe_b64encode(bytes(32)+bytes([flags])+bytes(4)).decode()
                with self.assertRaises(AlphaError): identity.phone_mfa_verify('session',factor,nonce,'rafii.test','https://rafii.test',bad)

if __name__=='__main__':unittest.main()

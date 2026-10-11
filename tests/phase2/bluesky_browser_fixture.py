"""Cloud-only UI fixture: synthetic identity, OAuth and images; no real Bluesky."""
import base64
import io
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

if sys.platform != 'linux' or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Use cloud Linux CI; this fixture cannot run on the Mac.')

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
# Reuse the existing disposable PostgreSQL/browser bootstrap and its safe OS user.
import youtube_browser_fixture as bootstrap
from PIL import Image
from postriff_phase2.atproto_oauth import BlueskyProvider, generate_jwk
from postriff_alpha.generation import FixtureAdapter

DID = 'did:plc:' + 'a' * 24


class SyntheticBluesky(BlueskyProvider):
    def __init__(self):
        super().__init__(generate_jwk(kid='synthetic-ui'), 'https://dev.postriff.invalid',
                         transport=self.no_egress, production_reviewed=True)

    @staticmethod
    def no_egress(*args, **kwargs):
        raise AssertionError('Synthetic UI fixture must not call any provider.')

    def begin(self, redirect, state, verifier, challenge, scopes, value):
        context = {'did': DID, 'issuer': 'https://oauth.synthetic.invalid', 'pds': 'https://pds.synthetic.invalid',
                   'tokenEndpoint': 'https://oauth.synthetic.invalid/token', 'dpopJwk': generate_jwk(),
                   'clientId': self.client_id, 'clientKeyId': self.client_jwk['kid'],
                   'clientKeyThumbprint': self._client_thumbprint(), 'scopes': scopes}
        return {'context': context, 'authorizeUrl': 'https://oauth.synthetic.invalid/?' + urlencode({'state': state})}

    def exchange(self, code, verifier, redirect, iss=None):
        context = json.loads(verifier)
        self._assert_binding(context)
        return self._session({'access_token': 'synthetic-AT', 'refresh_token': 'synthetic-RT', 'token_type': 'DPoP',
                              'scope': ' '.join(context['scopes']), 'sub': DID, 'expires_in': 900}, context, None)

    def identity(self, access_token):
        return {'providerAccountId': DID, 'handle': '@synthetic.bsky.invalid', 'accountType': 'profile'}

    def inspect_scopes(self, access_token, provider_account_id=None):
        return json.loads(access_token)['scope']


original = bootstrap.harness.HostedWorkspaceService
def local_service(*args, **kwargs):
    kwargs['providers']['bluesky'] = SyntheticBluesky()
    service = original(*args, **kwargs)
    upsert = service.commands.upsert_verified_channel
    def with_images(state, *arguments, **options):
        result = upsert(state, *arguments, **options)
        if arguments[1]['platform'] != 'Bluesky' or state['variants']:
            return result
        commands = service.commands
        commands(state, arguments[0], 'mode', {'mode': 'personal'})
        commands(state, arguments[0], 'context', {'purpose': 'Synthetic image test', 'audience': 'Testers', 'subject': 'Images', 'speaker': 'My voice', 'layers': []})
        commands(state, arguments[0], 'idea', {'idea': 'A synthetic image test.'})
        commands(state, arguments[0], 'source_done', {})
        commands(state, arguments[0], 'profile_propose', {'writing': 'A small step is useful.', 'tone': 'warm'})
        commands(state, arguments[0], 'profile_decide', {'decision': 'approve'})
        commands(state, arguments[0], 'runtime', {'selected': FixtureAdapter.id})
        commands(state, arguments[0], 'generate', {'platform': 'LinkedIn', 'language': 'English'})
        variant = state['variants'][0]
        variant.update(platform='Bluesky', channelId=arguments[1]['id'], text='CLOUD SYNTHETIC image approval test.',
                       needsReview=False, unknowns=[], warnings=[], voiceRevision=state['speaker']['activeRevision'])
        for index, color in enumerate(('red', 'blue', 'green', 'yellow')):
            output = io.BytesIO()
            Image.new('RGB', (640, 640), color).save(output, format='JPEG')
            asset = service.assets.stage_upload(state['workspace']['id'], {'data': base64.b64encode(output.getvalue()).decode()})
            asset['displayTitle'] = f'SYNTHETIC image {index + 1}'
            state['phase2']['assets'].append(asset)
        return result
    service.commands.upsert_verified_channel = with_images
    return service

bootstrap.harness.HostedWorkspaceService = local_service
if __name__ == '__main__':
    print('CLOUD SYNTHETIC BLUESKY UI: no real accounts, OAuth or publishing', flush=True)
    bootstrap.harness.main()

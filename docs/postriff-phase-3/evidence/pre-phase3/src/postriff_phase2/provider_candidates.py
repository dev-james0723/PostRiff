"""Reviewable server-side provider request adapters, NOT mounted in the local app.

Transport is dependency-injected. No requests or credential discovery occur on import.
Each send requires an exact, server-held request authorization. A browser flag cannot
enable this module. Current provider access and real responses remain unqualified.
"""
import base64
import json
import re
from urllib.parse import quote, urlparse
from postriff_alpha.domain import AlphaError
from .contracts import digest


class AuthorizedTransport:
    def __init__(self, send, authorization_lookup):
        self.send, self.authorization_lookup = send, authorization_lookup

    def request(self, descriptor, approval_id):
        approval = self.authorization_lookup(approval_id)
        if not approval or approval.get("requestDigest") != digest(descriptor) or approval.get("state") != "approved":
            raise AlphaError("An exact server-held authorization is required for this provider request.", 403)
        # send must atomically record dispatch/consumption and reconcile uncertain transport
        # outcomes before retry. Provider credentials are supplied inside send, never in descriptor.
        return self.send(descriptor, approval)


class LinkedInCandidate:
    def __init__(self, transport, version):
        if not re.fullmatch(r"\d{6}", version):
            raise ValueError("A currently supported documented API version is required")
        self.transport,self.version=transport,version

    def prepare(self, manifest, member_urn, media_urn=None):
        if manifest["platform"] != "LinkedIn" or manifest["operation"] != "member_post" or not re.fullmatch(r"urn:li:person:[A-Za-z0-9_-]+",member_urn):
            raise AlphaError("A verified exact LinkedIn member identity is required.")
        body={"author":member_urn,"commentary":manifest["payload"]["text"],"visibility":"PUBLIC","distribution":{"feedDistribution":"MAIN_FEED","targetEntities":[],"thirdPartyDistributionChannels":[]},"lifecycleState":"PUBLISHED","isReshareDisabledByAuthor":False}
        if manifest["media"]:
            if not media_urn or not media_urn.startswith('urn:li:image:'):
                raise AlphaError("Upload and verify the immutable image rendition before preparing this post.")
            body["content"]={"media":{"id":media_urn,"altText":manifest["media"][0]["alt"]}}
        return {"method":"POST","url":"https://api.linkedin.com/rest/posts","headers":{"Linkedin-Version":self.version,"X-Restli-Protocol-Version":"2.0.0"},"body":body,"manifestDigest":digest(manifest)}

    def submit(self, descriptor, authorization_id):
        result=self.transport.request(descriptor,authorization_id)
        status=result.get('status',0)
        if status in (401,403):return {"state":"held","confirmed":"Permission or session rejected"}
        if status==429:return {"state":"scheduled","confirmed":"Rate limited before acceptance"}
        reference=result.get('headers',{}).get('x-restli-id')
        if status==201 and isinstance(reference,str) and re.fullmatch(r'urn:li:(?:share|ugcPost):[A-Za-z0-9_-]+',reference):
            return {"state":"provider_accepted","reference":reference,"confirmed":"LinkedIn accepted the create request; separate publication verification required"}
        return {"state":"uncertain","confirmed":"No conclusive LinkedIn acceptance evidence; do not resubmit"}

    def reconciliation_request(self, reference, scopes):
        if 'r_member_social' not in scopes:
            return {"state":"uncertain","nextAction":"Restricted read permission unavailable. Review the intended account manually; never infer publication from a request ID."}
        if not re.fullmatch(r'urn:li:(?:share|ugcPost):[A-Za-z0-9_-]+',reference):
            raise AlphaError("A validated provider correlation ID is required.")
        return {"method":"GET","url":"https://api.linkedin.com/rest/posts/"+quote(reference,safe=''),"headers":{"Linkedin-Version":self.version,"X-Restli-Protocol-Version":"2.0.0"},"body":None}


class InstagramCandidate:
    """Two-stage container workflow. Persist container ID before the publish step."""
    def __init__(self, version):
        if not re.fullmatch(r'v\d+\.\d+',version):raise ValueError('A supported Graph version is required')
        self.base='https://graph.instagram.com/'+version

    def container_request(self, manifest, professional_id, rendition_url):
        if manifest['platform']!='Instagram' or manifest['operation']!='professional_image' or len(manifest['media'])!=1 or not re.fullmatch(r'\d+',professional_id):
            raise AlphaError('A verified professional identity and one decoded image are required.')
        u=urlparse(rendition_url)
        if u.scheme!='https' or not u.hostname or u.username or u.password:
            raise AlphaError('A reviewed, short-lived HTTPS image delivery URL is required.')
        return {'method':'POST','url':self.base+'/'+professional_id+'/media','headers':{},'body':{'image_url':rendition_url,'caption':manifest['payload']['text'],'alt_text':manifest['media'][0]['alt']},'manifestDigest':digest(manifest)}

    def status_request(self, container_id):
        if not re.fullmatch(r'\d+',container_id):raise AlphaError('Invalid container reference.')
        return {'method':'GET','url':self.base+'/'+container_id+'?fields=status_code,status','headers':{},'body':None}

    def publish_request(self, professional_id, container_id, saved_status):
        if not re.fullmatch(r'\d+',professional_id) or not re.fullmatch(r'\d+',container_id) or saved_status!='FINISHED':
            raise AlphaError('The exact persisted container must report FINISHED before publishing.')
        return {'method':'POST','url':self.base+'/'+professional_id+'/media_publish','headers':{},'body':{'creation_id':container_id}}

    def classify_container(self, response):
        status=response.get('status_code')
        return {'state':{'IN_PROGRESS':'provider_accepted','FINISHED':'provider_accepted','PUBLISHED':'published','ERROR':'failed','EXPIRED':'failed'}.get(status,'uncertain'),'readyToPublish':status=='FINISHED','confirmed':status if status in ('IN_PROGRESS','FINISHED','PUBLISHED','ERROR','EXPIRED') else 'No conclusive container state'}


class OpenAIImageCandidate:
    def __init__(self, transport, model):
        self.transport,self.model=transport,model

    def prepare(self, brief, count):
        allowed={'themes','energy','visualRhythm','motifs','palette','light','avoid','promptVersion'}
        if set(brief)!=allowed or type(count) is not int or not 1<=count<=3:
            raise AlphaError('Use the exact reviewed abstract ArtBrief and one to three previews.')
        # Recheck values, not only keys, against the constant allowlist before provider use.
        from postriff_alpha.visuals import SAFE_THEMES
        constants={'energy':'quiet momentum','visualRhythm':'layered but spacious','motifs':['open horizon','soft ripples'],'palette':['paper cream','moss green','muted rust','ink blue'],'light':'soft morning light','avoid':['portraits','text','identifiable places','personality symbols'],'promptVersion':'abstract-allowlist-v1'}
        if any(brief[k]!=v for k,v in constants.items()) or not isinstance(brief['themes'],list) or not 2<=len(brief['themes'])<=4 or any(t not in set(SAFE_THEMES.values()) for t in brief['themes']):
            raise AlphaError('The ArtBrief contains unapproved provider-bound values.')
        return {'method':'POST','url':'https://api.openai.com/v1/images/generations','headers':{},'body':{'model':self.model,'prompt':json.dumps(brief,sort_keys=True),'n':count,'quality':'low','size':'1536x1024','output_format':'png'}}

    def previews(self, descriptor, authorization_id):
        result=self.transport.request(descriptor,authorization_id)
        data=result.get('body',{}).get('data',[])
        if result.get('status')!=200 or not isinstance(data,list) or not 1<=len(data)<=descriptor['body']['n']:
            raise AlphaError('No verified image result; preserve the local fallback and reconcile usage before retry.')
        try:
            assets=[base64.b64decode(item['b64_json'],validate=True) for item in data]
            if any(not b.startswith(b'\x89PNG\r\n\x1a\n') or len(b)>8*1024*1024 for b in assets):raise ValueError()
            return assets  # Must pass decode_upload and private storage before display/selection.
        except (ValueError,KeyError,TypeError) as e:
            raise AlphaError('Malformed image response; no replacement selection was made.') from e


class SupabaseSessionCandidate:
    """Server-side getUser boundary. The transport authenticates to the exact project."""
    def __init__(self, project_url, get_user):
        url=urlparse(project_url)
        if url.scheme!='https' or not url.hostname or not url.hostname.endswith('.supabase.co') or url.path not in ('','/'):
            raise ValueError('An exact approved Supabase project URL is required')
        self.project_url,self.get_user=project_url.rstrip('/'),get_user

    def verify(self, access_token):
        # get_user is a server transport; do not log this argument or return it to the UI.
        response=self.get_user(self.project_url+'/auth/v1/user',access_token)
        user=response.get('body',{})
        if response.get('status')!=200 or not re.fullmatch(r'[0-9a-fA-F-]{36}',str(user.get('id',''))) or not (user.get('email_confirmed_at') or user.get('phone_confirmed_at')):
            raise AlphaError('Verified session required.',401)
        return user['id']

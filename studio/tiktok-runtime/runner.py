"""Approved-job subprocess. Never emits secrets or raw provider responses."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE/'source'))


def run(job):
    m=job['manifest']
    if m['account']!='@jamesaucreates' or m['visibility'] not in ('private','public'):
        return {'state':'needs_review','reason':'Account or visibility mismatch.'}
    with open(m['path'],'rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=m['sha256']:
            return {'state':'needs_review','reason':'Media changed.'}
    # Own browser session: identity before every dispatch, never the filename label alone.
    check=subprocess.run([sys.executable,str(BASE/'verify_session.py')],capture_output=True,text=True,timeout=100)
    signals=[]
    for line in check.stdout.splitlines():
        try: signals.append(json.loads(line))
        except ValueError: pass
    if not any(x.get('state')=='identity_verified' and x.get('account')=='@jamesaucreates' for x in signals):
        return {'state':'needs_review','reason':'TikTok session identity could not be verified. Complete login or any challenge, then prepare a new review.'}
    from tiktok_uploader import tiktok
    import requests
    final_attempt=False
    acknowledged=False
    original=requests.sessions.Session.request
    expected={'visibility_type':1 if m['visibility']=='private' else 0,'allow_comment':int(m['comments']),'allow_duet':int(m['duet']),'allow_stitch':int(m['stitch'])}
    def request(session,method,url,**kwargs):
        nonlocal final_attempt,acknowledged
        final=urlsplit(url).path=='/tiktok/web/project/post/v1/'
        if final:
            if final_attempt: raise RuntimeError('duplicate_blocked')
            payload=json.loads(kwargs['data'])
            if payload['feature_common_info_list'][0]['privacy_setting_info']!=expected: raise RuntimeError('privacy_mismatch')
            if payload['single_post_req_list'][0]['single_post_feature_info']['text']!=m['caption']: raise RuntimeError('caption_mismatch')
            final_attempt=True
        kwargs.setdefault('timeout',(15,60))
        response=original(session,method,url,**kwargs)
        if final:
            try: acknowledged=response.status_code==200 and response.json().get('status_code')==0
            except ValueError: pass
        return response
    def signer(js,agent,url):
        result=subprocess.run(['node',js,url,agent],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=60)
        return result.stdout.decode() if result.returncode==0 else None
    requests.sessions.Session.request=request
    tiktok.subprocess_jsvmp=signer
    try:
        tiktok.upload_video('jamesaucreates',m['path'],m['caption'],visibility_type=expected['visibility_type'],allow_comment=expected['allow_comment'],allow_duet=expected['allow_duet'],allow_stitch=expected['allow_stitch'])
    finally:
        requests.sessions.Session.request=original
    return {'state':'submitted' if acknowledged else 'unresolved','reason':'TikTok acknowledged the post; independently verify it on your profile.' if acknowledged else 'No confirmed acknowledgment. Check TikTok before any new attempt.'}


if __name__=='__main__':
    result={'state':'unresolved','reason':'Uploader interrupted. No automatic retry.'}
    try:
        raw=sys.stdin.read(32769)
        if len(raw)>32768: raise ValueError('job_too_large')
        job=json.loads(raw)
        with open(os.devnull,'w') as silent,contextlib.redirect_stdout(silent),contextlib.redirect_stderr(silent):
            result=run(job)
    except BaseException:
        pass
    print(json.dumps(result))

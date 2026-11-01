"""1000 simultaneous synthetic user arrivals, 64 bounded worker threads.

Exercises shipping adapter/publisher/read-back against an injected 2 ms provider.
No provider traffic, real accounts, production DB, agent model calls or publication.
It measures this in-process harness only, not hosted infrastructure capacity.
"""
import asyncio
import concurrent.futures
import json
import statistics
import threading
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from datetime import datetime, timezone
from types import SimpleNamespace
from contextlib import nullcontext
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.wave3_connectors import PinterestProvider

USERS, WORKERS = 1000, 64
SCOPES = ['user_accounts:read','boards:read','pins:read','pins:write']
active, peak, lock = 0, 0, threading.Lock()


def user(index):
    global active, peak
    with lock:
        active += 1; peak = max(peak, active)
    try:
        account, board, pin_id = str(1000000+index), str(2000000+index), str(3000000+index)
        post_count, calls = 0, 0
        def transport(method,url,**kw):
            nonlocal post_count, calls
            calls += 1; time.sleep(.002)
            if url.endswith('/v5/user_account'):
                body={'id':account,'username':f'synthetic{index}'}
            elif '/v5/boards?' in url:
                body={'items':[{'id':board,'name':'Synthetic','privacy':'PUBLIC'}]}
            elif method=='POST' and url.endswith('/v5/pins'):
                post_count += 1
                # A lost create response remains uncertain. Never create another Pin.
                body={} if index%50==0 else {'id':pin_id}
            elif method=='GET' and url.endswith('/v5/pins/'+pin_id):
                body={'id':pin_id,'board_id':board,'description':'Synthetic load test','title':'Synthetic',
                      'link':'https://example.com/load','media':{'media_type':'image'}}
            else: raise AssertionError('Unexpected synthetic route')
            return {'status':200,'body':body}
        provider= PinterestProvider('1615884','MOCK',sandbox=True,transport=transport,production_reviewed=True)
        grant=provider._grant({'access_token':f'MOCK-{index}','scope':' '.join(SCOPES)})
        def token_for_worker(workspace,connection):
            assert workspace==f'w{index}' and connection==f'c{index}'
            return {'accessToken':grant['accessToken'],'scopes':SCOPES}
        social=HostedSocial(SimpleNamespace(token_for_worker=token_for_worker,pinterest_dispatch=lambda *a:nullcontext({})),{'pinterest':provider},
            assets=SimpleNamespace(storage=SimpleNamespace(signed_url=lambda *a:'https://example.com/image.png')))
        manifest={'workspaceId':f'w{index}','channelId':f'c{index}','platform':'Pinterest','providerAccountId':account,
            'payload':{'text':'Synthetic load test'},'media':[{'id':f'image{index}','mime':'image/png','bytes':1024,'alt':'Synthetic'}],
            'publishOptions':{'boardId':board,'title':'Synthetic','link':'https://example.com/load'}}
        submitted=social.submit(manifest)
        result=social.reconcile(manifest,{'providerReference':submitted.get('reference')})
        expected='uncertain' if index%50==0 else 'verified'
        assert result['state']==expected, (index,result)
        assert post_count==1
        return {'status':result['state'],'calls':calls,'posts':post_count}
    finally:
        with lock: active-=1


async def main():
    loop=asyncio.get_running_loop()
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS)
    loop.set_default_executor(pool)
    gate=asyncio.Event()
    async def arrival(index):
        await gate.wait(); started=time.perf_counter()
        try:
            result=await asyncio.to_thread(user,index)
            return {**result,'latencyMs':(time.perf_counter()-started)*1000}
        except Exception as error:
            return {'status':'failed','errorType':type(error).__name__,'latencyMs':(time.perf_counter()-started)*1000}
    tasks=[asyncio.create_task(arrival(i)) for i in range(USERS)]
    await asyncio.sleep(0); start=time.perf_counter(); gate.set()
    results=await asyncio.gather(*tasks); seconds=time.perf_counter()-start
    latencies=sorted(r['latencyMs'] for r in results)
    counts={s:sum(r['status']==s for r in results) for s in ('verified','uncertain','failed')}
    report={'at':datetime.now(timezone.utc).isoformat(),'execution':'synthetic_in_process',
        'users':USERS,'simultaneousArrivals':USERS,'workerLimit':WORKERS,'observedPeakWorkers':peak,
        'simulatedProviderLatencyMs':2,'elapsedSeconds':seconds,'usersPerSecond':USERS/seconds,
        'latencyMs':{'p50':statistics.median(latencies),'p95':latencies[int(USERS*.95)-1],'p99':latencies[int(USERS*.99)-1]},
        'outcomes':counts,'unexpectedFailureRate':counts['failed']/USERS,
        'failureTypes':sorted({r.get('errorType') for r in results if r.get('errorType')}),
        'injectedLostCreateResponses':20,'lostResponsesPreservedUncertain':counts['uncertain']==20,
        'createCalls':sum(r.get('posts',0) for r in results),'providerCalls':0,
        'limitations':['No HTTP hosting, database scheduler, production OAuth or provider rate-limit measurement.','Lost responses need manual provider reconciliation; no automatic resubmission.']}
    print('PINTEREST_SYNTHETIC_LOAD '+json.dumps(report,sort_keys=True),flush=True)
    assert counts=={'verified':980,'uncertain':20,'failed':0},counts
    assert report['createCalls']==USERS
    pool.shutdown()


if __name__=='__main__': asyncio.run(main())

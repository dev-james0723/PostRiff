"""Prepared local-synthetic runner. NEVER starts, probes, migrates or owns PG.

Requires the parent's additive dev-harness adapter in REPORT.md and a previously
prepared real Next build. Refuses occupied HTTP ports; cleans only child process
groups it created. No installs, dependency writes, builds or external network.
This file was not executed against servers/browser in candidate preparation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request

EVIDENCE_ROOT = Path('/private/tmp/rafii-pricing-v2-recovery-20261002/task13-pricing-browser-fixture')
PYTHON = '/Users/ouxianxing/Documents/James-Au-Studio-product-growth/.venv-growth/bin/python'


def require_free_http_ports(ports):
    if len(set(ports)) != len(ports) or any(type(p) is not int or not 1024 <= p <= 65535 or p == 55439 for p in ports):
        raise ValueError('Two distinct unprivileged HTTP ports, never parent PG 55439.')
    for port in ports:
        with socket.socket() as owned_probe:
            owned_probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try: owned_probe.bind(('127.0.0.1', port))
            except OSError as error: raise ValueError(f'HTTP port {port} occupied; refusing adoption/termination.') from error


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-local-synthetic', action='store_true')
    p.add_argument('--repo-root', type=Path, required=True)
    p.add_argument('--database', required=True, help='Parent-created, migrated pricing_v2_local_synthetic_* DB')
    p.add_argument('--api-port', type=int, default=4438)
    p.add_argument('--web-port', type=int, default=4439)
    p.add_argument('--evidence-dir', type=Path, required=True)
    p.add_argument('--next-app', type=Path, required=True, help='Parent-approved existing built Next application')
    p.add_argument('--node', type=Path, required=True)
    p.add_argument('--next-cli', type=Path, required=True)
    p.add_argument('--playwright-module', type=Path, required=True)
    p.add_argument('--chromium', type=Path, required=True, help='Already cached Chromium, NEVER downloaded')
    args = p.parse_args()
    if not args.run_local_synthetic: p.error('Explicit --run-local-synthetic required; this candidate has no approval to run now.')
    root, out = args.repo_root.resolve(), args.evidence_dir.resolve()
    if not out.is_relative_to(EVIDENCE_ROOT) or out == EVIDENCE_ROOT:
        p.error('All logs/browser evidence must stay under the authorized Task13 directory.')
    for file in [root/'scripts/postriff_dev_hosted.py',root/'scripts/pricing_v2_browser_fixture.py',
                 args.node,args.next_cli,args.chromium]:
        if not file.is_file(): p.error('Required parent-prepared file missing: '+str(file))
    if not (args.next_app/'.next/BUILD_ID').is_file(): p.error('Existing real Next build required; runner never builds.')
    if not args.playwright_module.is_dir(): p.error('Existing readonly Playwright module required.')
    base=f'http://127.0.0.1:{args.web_port}';api=f'http://127.0.0.1:{args.api_port}'
    routes_file=args.next_app/'.next/routes-manifest.json'
    if not routes_file.is_file():p.error('Real prebuilt Next routes manifest required.')
    routes=json.loads(routes_file.read_text()).get('rewrites',[])
    if isinstance(routes,dict):routes=[r for group in routes.values() for r in group]
    for prefix in ('api','dev'):
        matches=[r for r in routes if r.get('source')==f'/{prefix}/:path*']
        if len(matches)!=1 or matches[0].get('destination')!=api+f'/{prefix}/:path*':
            p.error('Cached Next build must proxy '+prefix+' to exactly '+api+'; never adopt a build targeting foreign ports.')
    # Validate the adapter's DB namespace without connecting/probing PG.
    import re
    if not re.fullmatch(r'pricing_v2_local_synthetic_[a-z0-9_]{1,32}',args.database): p.error('Isolated database namespace required.')
    require_free_http_ports([args.api_port,args.web_port])
    out.mkdir(parents=True,exist_ok=True)
    secret=secrets.token_urlsafe(32)
    # Credentials/provider keys/VERCEL are excluded. HOME supplies cache location,
    # not consent: all model/Stripe calls are injected local-synthetic transports.
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG')}
    env.update(PYTHONDONTWRITEBYTECODE='1',POSTRIFF_LOCAL_CLI='0',POSTRIFF_RESEARCH='0',
               POSTRIFF_GATEWAY_CATALOG_REFRESH='0',POSTRIFF_PRICING_V2_ENABLED='1',POSTRIFF_CREDITS_ENABLED='1',
               POSTRIFF_CREDIT_PURCHASES_ENABLED='0',POSTRIFF_DEV_WEB_ORIGIN=base,POSTRIFF_API_ORIGIN=api,
               POSTRIFF_DEV_SSR='1',PRICING_V2_FIXTURE_TOKEN=secret,PRICING_V2_WEB_URL=base,
               PRICING_V2_EVIDENCE_DIR=str(out),PLAYWRIGHT_MODULE=str(args.playwright_module),BROWSER_EXECUTABLE=str(args.chromium),
               PRICING_V2_TOURS_FILE=str(root/'web/src/features/onboarding/tours.ts'))
    commands=[('backend',[PYTHON,'-B',str(root/'scripts/postriff_dev_hosted.py'),'--port',str(args.api_port),
                         '--pricing-v2-fixture','--pricing-v2-fixture-database',args.database,
                         '--external-pg-dsn',f'host=127.0.0.1 port=55439 dbname={args.database}']),
              ('frontend',[str(args.node),str(args.next_cli),'start',str(args.next_app),'-p',str(args.web_port),'-H','127.0.0.1'])]
    processes=[];logs=[];status='FAIL';reason=None;code=1
    try:
        for name,cmd in commands:
            log=(out/(name+'.raw.log')).open('w');logs.append(log)
            processes.append(subprocess.Popen(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
        # A newly generated capability proves readiness belongs to OUR fixture.
        # No unauthenticated readiness success is used to adopt a foreign server.
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if any(c.poll() is not None for c in processes): raise RuntimeError('Owned child exited; inspect raw logs.')
            try:
                req=urllib.request.Request(base+'/dev/pricing-v2-local-synthetic/snapshot',data=b'{}',method='POST',
                       headers={'Origin':base,'X-Pricing-V2-Fixture':secret,'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=2) as response:
                    if json.load(response).get('execution')=='local-synthetic-real-http-pg':break
            except (OSError,ValueError):time.sleep(.2)
        else:raise RuntimeError('Owned authenticated Next -> API readiness failed.')
        with (out/'browser.raw.log').open('w') as log:
            child=subprocess.Popen([str(args.node),str(root/'web/tests/pricing-v2-live-api-browser.cjs')],cwd=root,
                  env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append(child);code=child.wait(timeout=600)
        status='PASS' if code==0 else 'FAIL'
    except Exception as error:
        reason=str(error);code=3
    finally:
        # Never discover/kill by port or terminate parent PG. Only these owned PIDs.
        for child in processes:
            if child.poll() is None:os.killpg(child.pid,signal.SIGTERM)
        for child in processes:
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        for log in logs:log.close()
        (out/'runner-receipt.json').write_text(json.dumps({'execution':'local-synthetic-real-http-pg','status':status,
             'reason':reason,'exitCode':code,'ownedChildPids':[c.pid for c in processes],
             'parentPg':'55439 external; not probed, created, migrated or stopped by runner',
             'nextBuildId':(args.next_app/'.next/BUILD_ID').read_text().strip(),
             'nextRoutesSha256':hashlib.sha256(routes_file.read_bytes()).hexdigest(),
             'stripeTestMode':'NOT_RUN','commands':commands},indent=2)+'\n')
    return code


if __name__=='__main__':sys.exit(main())

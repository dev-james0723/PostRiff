"""Tier C: actual Next -> HostedApplication -> disposable PostgreSQL. No trend API mocks.

Identity, observations and destination are explicit test seeds. Real production
TrendService, receipt verification, membership, transactions and Ideas persistence
run unchanged. Only deterministic local Lab jobs run; no providers/models are configured or dispatched.
"""
from __future__ import annotations
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--api-port', type=int, default=4458)
    parser.add_argument('--web-port', type=int, default=4459)
    parser.add_argument('--pg-port', type=int, default=56449)
    parser.add_argument('--skip-build', action='store_true', help='reuse only a matching local .next-trend-live build')
    parser.add_argument('--browser-engine',choices=('chromium','webkit'),default='chromium')
    parser.add_argument('--pool-only', action='store_true', help='only affected Home/Weekly real API checks; historical46 are not rerun')
    parser.add_argument('--learning-only', action='store_true', help='only affected Performance real API checks; historical Radar/Lab/Pool receipts retained')
    parser.add_argument('--metric-admission', action='store_true', help='learning-only: mount a read-only scheduler for one synthetic workspace and prove the others stay disabled')
    args = parser.parse_args()
    if args.pool_only and args.learning_only: parser.error('Choose one bounded mode')
    if args.pool_only and args.browser_engine != 'chromium': parser.error('Pool-only harness supports Chromium; full Radar/Lab supports WebKit')
    if args.metric_admission and not args.learning_only: parser.error('Metric admission requires learning-only')
    dist = '.next-trend-learning' if args.learning_only else '.next-trend-live'
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Keep no provider credentials or inherited feature flags. No dotenv is loaded by Python.
    safe = {k: v for k, v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','TERM','POSTRIFF_PG_BIN','BROWSER_EXECUTABLE')}
    os.environ.clear()
    os.environ.update(safe, LC_ALL='C', PYTHONDONTWRITEBYTECODE='1', POSTRIFF_LOCAL_CLI='0', POSTRIFF_RESEARCH='0')
    for port in (args.api_port, args.web_port, args.pg_port):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))  # Refuse occupied ports; never attach to another task's server.
    blocked = []
    probe = [False]
    def guard(event, values):
        host = None
        if event == 'socket.connect' and isinstance(values[1], tuple):
            host = values[1][0]
        elif event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'):
            host = values[0]
        if host is not None and host not in ('127.0.0.1', '::1', 'localhost'):
            if not probe[0]:
                blocked.append({'event': event, 'host': str(host)})
            raise RuntimeError('Tier C denies non-loopback network and DNS')
    sys.addaudithook(guard)
    probe[0] = True
    try:
        with socket.socket() as s:
            try: s.connect(('192.0.2.1', 443))
            except RuntimeError: pass
            else: raise AssertionError('Network guard did not deny probe')
        try: socket.getaddrinfo('synthetic.invalid', 443)
        except RuntimeError: pass
        else: raise AssertionError('DNS guard did not deny probe')
    finally: probe[0] = False
    from postriff_dev_hosted import start_postgres, DevVerifier, PG
    import psycopg
    from postriff_phase2.hosted import HostedWorkspaceService
    from postriff_phase2.hosted_app import HostedApplication
    from postriff_phase2.coworker.runtime import attach
    from postriff_phase2.growth.trends.config import FLAG_NAMES
    spec = importlib.util.spec_from_file_location('trend_browser_seed', ROOT/'tests/phase2/seed_trend_browser.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    server = None
    data = None
    processes = []
    handles = []
    code = 1
    summary = {'execution': 'real_api_postgresql_synthetic_identity_and_seed', 'network_guard_probe': 'connect_and_dns_denied',
        'trend_api_interception': False, 'provider_or_model_configuration': False}
    summary['browser_engine']=args.browser_engine
    summary['harness_sources'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        'scripts/trend_browser.py', 'tests/phase2/seed_trend_browser.py', 'web/tests/trend-live-api-browser.cjs', 'web/tests/trend-pool-live-api-browser.cjs')}
    ui = json.loads((ROOT/'web/src/features/trends/redesign-validation.json').read_text())
    summary['accepted_ui_runtime_sha256'] = ui['runtime_ui_sha256']
    actual_ui = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in [*ui['runtime_files'], 'web/src/features/trends/opportunity-exposure.ts']}
    summary['ui_runtime_files'] = actual_ui
    summary['ui_runtime_changed_files'] = {name: {'before': ui['runtime_files'].get(name), 'after': digest} for name, digest in actual_ui.items() if digest != ui['runtime_files'].get(name)}
    summary['current_ui_files_json_sha256'] = hashlib.sha256(json.dumps(actual_ui, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if args.pool_only:
        pool_files = ('web/src/features/agent/home-view.tsx', 'web/src/features/coworker/weekly/weekly-view.tsx',
                      'web/src/features/trends/workspace-opportunity-preview.tsx')
        summary['pool_runtime_files'] = {**actual_ui, **{name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in pool_files}}
        summary['pool_runtime_sha256'] = hashlib.sha256(json.dumps(summary['pool_runtime_files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    summary['backend_service_sha256'] = hashlib.sha256((ROOT/'src/postriff_phase2/growth/trends/service.py').read_bytes()).hexdigest()
    if args.learning_only:
        learning_backend_paths = ('src/postriff_phase2/growth/trends/learning.py', 'src/postriff_phase2/growth/trends/learning_options.py', 'src/postriff_phase2/growth/trends/service.py', 'src/postriff_phase2/coworker/service.py')
        summary['learning_backend_start'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in learning_backend_paths}

    # The earlier creator UI receipt is historical. Bind this run to the complete current
    # visual runtime and imported backend method graph, independently of that receipt.
    visual_paths = sorted({*actual_ui, *[
        str(path.relative_to(ROOT)) for path in (ROOT/'web/src/features/trends').glob('*')
        if path.suffix in ('.ts', '.tsx', '.css')
    ], 'web/src/lib/coworker/trend-types.ts', 'web/package.json', 'web/package-lock.json'})
    backend_paths = sorted(str(path.relative_to(ROOT)) for path in (ROOT/'src/postriff_phase2/growth/trends').rglob('*.py'))
    guard_paths = sorted(set(visual_paths + backend_paths + list(summary['harness_sources'])))
    summary['current_source_start'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in guard_paths}
    summary['ui_runtime_matches_frozen_receipt'] = not summary['ui_runtime_changed_files']
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        dsn, data = start_postgres(args.pg_port)
        connect = lambda: psycopg.connect(dsn, client_encoding='utf8', autocommit=False)
        with connect() as db:
            db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        service = HostedWorkspaceService(connect, DevVerifier(connect))
        seeds = seed.seed_browser(service, connect, scenario='learning' if args.learning_only else 'pool_accept' if args.pool_only else 'radar', platform_override='Threads' if not args.pool_only and not args.learning_only else None)
        lab_seeds = [] if args.pool_only or args.learning_only else seed.seed_browser(service, connect, scenario='lab')
        dismiss_seeds = [] if args.learning_only else seed.seed_browser(service, connect, scenario='pool_dismiss' if args.pool_only else 'dismiss')
        flags = {name: '0' for name in FLAG_NAMES}
        flags.update({f'RAFII_TREND_{name}_ENABLED': '1' for name in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','OPPORTUNITY_LAB')})
        flags.update(RAFII_TREND_WORKSPACE_ALLOWLIST=','.join(row['workspace_id'] for row in seeds + lab_seeds + dismiss_seeds),
            RAFII_TREND_CURSOR_SIGNING_KEY='synthetic-browser-cursor-key-not-a-production-secret')
        flags['RAFII_WEEKLY_OPERATOR_ENABLED'] = '1'
        if args.learning_only: flags.update(RAFII_PERFORMANCE_LEARNING_ENABLED='1', RAFII_ADAPTIVE_SKILLS_ENABLED='1')
        attach(service, flags)
        if args.metric_admission:
            from postriff_phase2.growth.metric_schedule import MetricScheduler
            # Actual scheduler admission, no OAuth adapter/grant or insights transport.
            # Explicit stored fixture publications bypass the worker and schedule nothing.
            service.metric_reads = MetricScheduler(connect, None, transport=None, workspace_allowlist={seeds[0]['workspace_id']})
            for row in seeds:
                row['metric_reads_enabled'] = service.metric_reads.workspace_allowed(row['workspace_id'])
            summary['metric_admission'] = {'execution': 'synthetic_workspace_admission_only',
                'allowed_workspaces': 1, 'denied_workspaces': len(seeds)-1, 'native_provider_calls': 0}
        if args.learning_only: seed.seed_learning_sources(service, connect, seeds)
        seed.seed_lab_drafts(service, connect, lab_seeds)
        app = HostedApplication(service, public_auth={'provider':'dev','execution':'dev-synthetic','flow':'dev'})
        class LocalServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True
            request_queue_size = 64
        class Quiet(WSGIRequestHandler):
            def log_message(self, *_): pass
        server = make_server('127.0.0.1', args.api_port, app, server_class=LocalServer, handler_class=Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        seed_path = out/'seed.json'
        seed_path.write_text(json.dumps({'execution': summary['execution'], 'seeds': seeds, 'lab_seeds': lab_seeds, 'dismiss_seeds': dismiss_seeds}, indent=2))
        env = dict(os.environ, NEXT_TELEMETRY_DISABLED='1', NEXT_PUBLIC_SENTRY_DISABLED='1',
            POSTRIFF_DIST_DIR=dist, POSTRIFF_API_ORIGIN=f'http://127.0.0.1:{args.api_port}',
            POSTRIFF_DEV_SSR='1', TREND_WEB_URL=f'http://127.0.0.1:{args.web_port}',
            TREND_EVIDENCE_DIR=str(out), TREND_LIVE_SEED=str(seed_path))
        if not args.skip_build:
            with (out/'build.log').open('w') as log:
                subprocess.run(['npm','run','build','--','--webpack'], cwd=ROOT/'web', env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        manifest = json.loads((ROOT/'web'/dist/'routes-manifest.json').read_text())
        assert any(r['destination']==env['POSTRIFF_API_ORIGIN']+'/api/:path*' for r in manifest['rewrites']['afterFiles']), 'Build proxy origin differs'
        summary['frontend_build'] = {'dist': dist, 'reused': args.skip_build,
            'build_id': (ROOT/'web'/dist/'BUILD_ID').read_text().strip(), 'api_origin': env['POSTRIFF_API_ORIGIN']}
        log = (out/'web.log').open('w'); handles.append(log)
        proc = subprocess.Popen(['node','node_modules/next/dist/bin/next','start','-p',str(args.web_port),'--hostname','127.0.0.1'],
            cwd=ROOT/'web', env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(proc)
        deadline = time.monotonic()+60
        while time.monotonic()<deadline:
            if proc.poll() is not None: raise RuntimeError('Local Next server exited; inspect web.log')
            try:
                with urllib.request.urlopen(env['TREND_WEB_URL']+'/auth/sign-in', timeout=2) as response:
                    if response.status == 200: break
            except Exception: time.sleep(.25)
        else: raise RuntimeError('Local Next readiness deadline exceeded')
        learning_stop = threading.Event()
        learning_errors = []
        learning_thread = None
        if args.learning_only:
            def learning_fixture_events():
                try:
                    pending = {(row['width'], action): row for row in seeds for action in ('publications', 'revoke')}
                    while pending and not learning_stop.wait(.05):
                        for (width, action), row in list(pending.items()):
                            marker = out/f'learning-{width}-{action}-request.json'
                            if not marker.exists(): continue
                            # File-only harness IPC; never an application or hidden fixture URL.
                            value = seed.seed_learning_publications(connect, row) if action == 'publications' else seed.revoke_learning_fixture(connect, row)
                            (out/f'learning-{width}-{action}-done.json').write_text(json.dumps({'result': value}))
                            del pending[width, action]
                except Exception as exc:
                    learning_errors.append(f'{type(exc).__name__}: {exc}')
                    (out/'learning-fixture-error.json').write_text(json.dumps(learning_errors))
            learning_thread = threading.Thread(target=learning_fixture_events, daemon=True)
            learning_thread.start()
        env['POSTRIFF_BROWSER_ENGINE']=args.browser_engine
        code = subprocess.call(['node','web/tests/trend-pool-live-api-browser.cjs' if args.pool_only else 'web/tests/trend-live-api-browser.cjs'], cwd=ROOT, env=env)
        learning_stop.set()
        if learning_thread: learning_thread.join(timeout=5)
        assert not learning_errors, str(learning_errors)
        # Independent DB assertions after browser read/write/reload: exactly one accepted source per workspace.
        persistence = []
        with connect() as db:
            for row in seeds:
                state = db.execute('SELECT state FROM pr_workspaces WHERE id=%s',(row['workspace_id'],)).fetchone()[0]
                sources = [s for s in state.get('sources',[]) if (s.get('origin') or {}).get('trendLineage',{}).get('opportunity_id')==row['opportunity_id']]
                decisions = db.execute('SELECT count(*) FROM pr_trend_opportunity_decisions WHERE workspace_id=%s',(row['workspace_id'],)).fetchone()[0]
                lineage_ok = len(sources)==1 and sources[0]['origin']['trendLineage']['trust_receipt_id']==row['receipt_id']
                if code == 0:
                    assert len(sources)==1 and decisions==1, 'Expected one durable source and acceptance decision'
                    assert lineage_ok
                    assert not state.get('variants'), 'Acceptance must not generate a draft'
                persistence.append({'width':row['width'], 'source_count':len(sources), 'decision_count':decisions, 'server_lineage':lineage_ok})
            lab_persistence = []
            for row in lab_seeds:
                state = db.execute('SELECT state FROM pr_workspaces WHERE id=%s', (row['workspace_id'],)).fetchone()[0]
                draft = next(v for v in state['variants'] if v['id'] == row['draft_id'])
                jobs = db.execute('SELECT state,kind,provider_id,reservation_id FROM pr_trend_jobs WHERE scope_key=%s', ('workspace:'+row['workspace_id'],)).fetchall()
                if code == 0:
                    assert draft['revision'] == 4 and draft['needsReview'] is True
                    assert draft['text'] == 'Demo data: Concurrent saved revision must survive the old Lab suggestion.'
                    assert draft['trendLineage'][0]['trust_receipt_id'] == row['receipt_id']
                    assert jobs == [('succeeded', 'trend.opportunity_lab.local', None, None)] * 2
                    assert not state['phase2'].get('jobs') and not state['phase2'].get('reviews'), 'No publishing or approval authority'
                lab_persistence.append({'width': row['width'], 'draft_revision': draft['revision'], 'needs_review': draft['needsReview'],
                    'lineage_preserved': draft['trendLineage'][0]['trust_receipt_id'] == row['receipt_id'],
                    'jobs': [{'state': j[0], 'kind': j[1], 'provider_id': j[2], 'reservation_id': j[3]} for j in jobs]})
            exposure_persistence = []
            for row in seeds + dismiss_seeds:
                rows = db.execute("SELECT payload FROM pr_trend_projections WHERE scope_key=%s AND kind='exposure'", ('workspace:'+row['workspace_id'],)).fetchall()
                if code == 0:
                    assert len(rows) == 1, 'Exactly one real browser-reported exposure per candidate in this run'
                    assert rows[0][0]['measurement'] == 'client_reported_view'
                    assert rows[0][0]['opportunity_id'] == row['opportunity_id']
                decisions = db.execute('SELECT decision,result FROM pr_trend_opportunity_decisions WHERE workspace_id=%s', (row['workspace_id'],)).fetchall()
                if code == 0:
                    assert len(decisions) == 1
                    assert decisions[0][0] == ('dismiss' if row['scenario'] in ('dismiss', 'pool_dismiss') else 'accept')
                    if row['scenario'] in ('dismiss', 'pool_dismiss'):
                        assert decisions[0][1]['exposure_id'] == rows[0][0]['exposure_id']
                        state = db.execute('SELECT state FROM pr_workspaces WHERE id=%s', (row['workspace_id'],)).fetchone()[0]
                        assert not state['sources'] and not state['variants'], 'Dismissal creates neither source nor draft'
                exposure_persistence.append({'scenario': row['scenario'], 'width': row['width'], 'exposures': len(rows), 'decisions': len(decisions)})
            radar_jobs = db.execute('SELECT count(*) FROM pr_trend_jobs WHERE scope_key = ANY(%s)', (['workspace:'+r['workspace_id'] for r in seeds],)).fetchone()[0]
            assert radar_jobs == 0, 'Stored Radar read/accept cannot queue provider or model work'
            jobs = db.execute('SELECT count(*) FROM pr_trend_jobs').fetchone()[0]
            assert jobs == sum(len(r['jobs']) for r in lab_persistence), 'Only the explicitly requested local Lab jobs may exist'
            assert db.execute("SELECT count(*) FROM pr_trend_jobs WHERE kind <> 'trend.opportunity_lab.local' OR provider_id IS NOT NULL OR reservation_id IS NOT NULL").fetchone()[0] == 0
            assert db.execute('SELECT count(*) FROM pr_model_usage_events').fetchone()[0] == 0, 'No model usage events'
            if args.metric_admission:
                assert db.execute('SELECT count(*) FROM pr_metric_reads').fetchone()[0] == 0, 'Read-only browser admission creates no metric queue'
                assert service.metric_reads.tick()['providerReads'] == 0, 'No provider dispatch from mount or browser GETs'
            assert db.execute('SELECT count(*) FROM pr_trend_budget_reservations').fetchone()[0] == 0, 'No provider/model cost reservations'
            completions = db.execute("SELECT meta FROM pr_audit_events WHERE kind='trend.lab_completed'").fetchall()
            assert all(r[0].get('modelCalls') == 0 for r in completions)
            if code == 0:
                assert len(completions) == (len(lab_seeds) * 2), 'Two genuine local completions per Lab workspace; replay is not a new run'
        if args.learning_only:
            saved_choices=[]
            with connect() as db:
                for row in seeds:
                    revision,state=db.execute('SELECT revision,state FROM pr_workspaces WHERE id=%s',(row['workspace_id'],)).fetchone()
                    choices=state.get('coworker',{}).get('trendLearning',{}).get('metricChoices',[])
                    if code == 0:
                        assert len(choices)==1 and choices[0]['confirmed'] is True
                        assert choices[0]['provider']=='threads' and choices[0]['metric']=='replies' and choices[0]['objective']=='conversation'
                        assert choices[0]['window']=='24h' and choices[0]['denominator_metric']=='views'
                        assert revision==row['initial_revision']+2, 'Exactly one metric save and one explicit publication fixture write'
                        assert not state.get('variants') and len(state['phase2']['jobs'])==2 and all(j.get('execution')=='synthetic-test-only' for j in state['phase2']['jobs']), 'Only explicit stored publication fixtures, no generation or publishing'
                    saved_choices.append({'width':row['width'],'choices':len(choices),'revision_delta':revision-row['initial_revision'],'generated_variants':len(state.get('variants',[])), 'synthetic_stored_publications':len(state['phase2']['jobs'])})
            summary['learning_persistence']=saved_choices
            summary['learning_runtime_files']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('web/src/features/coworker/personalization/personalization-view.tsx','web/src/lib/coworker/trend-types.ts','web/src/features/trends/api.ts')}
        assert not blocked, 'Backend attempted unexpected egress'
        assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest for name,digest in summary['current_source_start'].items()), 'Source changed during current UI acceptance'
        summary.update(model_usage_events=0, provider_model_reservations=0, lab_completion_audit_count=len(completions), status='passed' if code==0 else 'failed', browser_exit_code=code, persistence=persistence, lab_persistence=lab_persistence, exposure_persistence=exposure_persistence, radar_trend_jobs=radar_jobs, trend_jobs=jobs, unexpected_backend_egress=blocked)
        return code
    except Exception as exc:
        summary.update(status='failed', error=f'{type(exc).__name__}: {exc}', unexpected_backend_egress=blocked)
        raise
    finally:
        if server:
            server.shutdown(); server.server_close()
        for proc in processes:
            if proc.poll() is None: os.killpg(proc.pid, signal.SIGTERM)
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); proc.wait()
        for handle in handles: handle.close()
        if data:
            subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'], check=True, stdout=subprocess.DEVNULL)
            import shutil
            shutil.rmtree(data.parent)  # Only the fresh directory returned by our own start_postgres.
        config = ROOT/'web/tsconfig.json'
        value = json.loads(config.read_text())
        own_includes = {f'{dist}/types/**/*.ts', f'{dist}/dev/types/**/*.ts'}
        if any(item in own_includes for item in value.get('include', [])):
            value['include'] = [item for item in value['include'] if item not in own_includes]
            config.write_text(json.dumps(value, indent=2)+'\n')
        if args.learning_only:
            summary['learning_backend_end'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in learning_backend_paths}
            summary['learning_backend_hash_drift'] = [name for name in learning_backend_paths if summary['learning_backend_start'][name] != summary['learning_backend_end'][name]]
        summary['current_source_end'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in guard_paths}
        summary['current_source_drift'] = [name for name in guard_paths if summary['current_source_start'][name] != summary['current_source_end'][name]]
        (out/'harness-result.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':
    sys.exit(main())

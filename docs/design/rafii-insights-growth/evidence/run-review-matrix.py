"""Supplemental matrix checks on the owned PG; synthetic native inputs only."""
import copy
import csv
import io
import json
import os
from pathlib import Path
import runpy
import uuid

ROOT = Path(__file__).resolve().parents[4]
os.chdir(ROOT)
n = runpy.run_path(str(ROOT / 'tests/phase2/postgres_review_boundaries.py'))
host, r, wid, conn, clock = (n[k] for k in ('host', 'r', 'wid', 'conn', 'clock'))
connection, refused, review, models = (n[k] for k in ('connection', 'refused', 'review', 'models'))
scope = n['scope']
# Restore this suite's own account, previously revoked by its negative check.
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'", (wid, conn))
checks = []
p = r.read(wid, 'one', {**scope, 'language': 'en', 'formatIds': ['text'], 'aggregation': 'mean'})
assert p['coverage']['eligible'] == 12
assert p['resolvedContext']['language'] == 'en' and p['resolvedContext']['formatIds'] == ['text']
assert all(g['aggregation'] == 'mean' for g in p['groups'])
assert r.read(wid, 'one', {**scope, 'language': 'zh-Hant'})['coverage']['publications'] == 0
previous = {'kind': 'previous_period', 'publicationPeriod': {'start': review.iso(clock[0]-14*86400), 'end': review.iso(clock[0]-7*86400), 'timezone': 'UTC'}}
compared = r.read(wid, 'one', {**scope, 'comparison': previous})
assert compared['resolvedContext']['comparison'] == previous
assert all(g['baselineValue'] is None for g in compared['groups'])
assert all(c['relativeChange'] is None and c['reason'] for c in compared['comparisons'])
checks.append('real server resolves account, language, format, aggregation and fixed previous-period filters; absent language stays empty and missing baseline never creates growth')

all_metrics = {k: v for k, v in scope.items() if k != 'nativeMetric'}
p = r.read(wid, 'one', all_metrics)
def body(**kw):
    return {'workspaceRevision': host.repository.get(wid, 'one')['revision'], 'idempotencyKey': str(uuid.uuid4()), **kw}
snapshot_body = dict(scope=all_metrics, contextDigest=p['contextDigest'], basisDigest=p['basisDigest'], humanNotes=['=SUM(A1:A2)', '繁體中文註記'], frequency='monthly')
s = r.create_snapshot(wid, 'one', body(**snapshot_body))['record']
before = r.snapshot(wid, 'one', s['snapshotId'], 1, format_='csv')
original = review.format_snapshot
def fail_export(*args, **kwargs):
    raise review.AlphaError('Synthetic renderer unavailable', 503)
review.format_snapshot = fail_export
try:
    refused(503, lambda: r.snapshot(wid, 'one', s['snapshotId'], 1, format_='csv'))
finally:
    review.format_snapshot = original
after = r.snapshot(wid, 'one', s['snapshotId'], 1, format_='csv')
assert before == after
assert r.snapshot(wid, 'one', s['snapshotId'], 1) == s
rows = list(csv.DictReader(io.StringIO(after['content'])))
assert len(rows) == len(s['nativeResults'])
assert all(row['sourceSha'] == os.environ['POSTRIFF_SOURCE_SHA'] for row in rows)
assert any(row['value'] == '0.0' and row['valueState'] == 'measured' for row in rows)
assert any(json.loads(row['value']) is None and row['reason'] for row in rows)
assert all(row['humanNotes'].startswith("'=SUM") and '繁體中文' in row['humanNotes'] for row in rows)
for row in rows:
    if row['valueState'] == 'measured':
        assert row['definitionVersion'] and row['readOffset'] == '24h' and row['nativeWindow'] == 'cumulative_at_observation'
        assert row['observedAt'] and row['ingestedAt'] and row['observationId'] and row['nativePostId']
    else:
        assert json.loads(row['value']) is None and row['reason']
checks.append('monthly fixed report survives a real service renderer failure and repeats byte-identical CSV/payload/renderer version; UTF-8, injection, zero, null reasons, native definitions, IDs and times parsed')

r.save_view(wid, 'one', body(name='Retention reference', expectedRevision=0, filterDefinition=all_metrics))
row = host.repository.get(wid, 'one')
raw = copy.deepcopy(row['state'])
limited = copy.deepcopy(raw)
private = review.review_state(limited)
v = copy.deepcopy(private['views'][0])
private['views'] = [{**v, 'id': 'limit-view-'+str(i), 'status': 'archived'} for i in range(review.MAX_VIEWS)]
private['snapshots'] = [{**copy.deepcopy(s), 'snapshotId': 'rs_limit_'+str(i)} for i in range(review.MAX_SNAPSHOTS)]
with connection() as db:
    db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(limited), wid))
try:
    revision = host.repository.get(wid, 'one')['revision']
    refused(409, lambda: r.save_view(wid, 'one', body(name='Over limit', expectedRevision=0, filterDefinition=scope)))
    p = r.read(wid, 'one', all_metrics)
    refused(409, lambda: r.create_snapshot(wid, 'one', body(**{**snapshot_body, 'contextDigest': p['contextDigest'], 'basisDigest': p['basisDigest']})))
    retained = host.repository.get(wid, 'one')
    assert retained['revision'] == revision and retained['state'] == limited
finally:
    with connection() as db:
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(raw), wid))
checks.append('actual PG limit guards reject view 33 including archived history and snapshot version 65; state and revision roll back without overwriting retained records')
assert not models.calls
evidence = {'status':'PASS', 'execution':'real owned disposable PG/services; explicitly synthetic native data and renderer failure', 'sourceSha':os.environ['POSTRIFF_SOURCE_SHA'], 'checks':checks, 'realProviderCalls':0, 'realModelCalls':0, 'nativeAcceptance':False}
Path(os.environ['POSTRIFF_REVIEW_EVIDENCE_DIR'], 'matrix.json').write_text(json.dumps(evidence, indent=2)+'\n')
print(json.dumps(evidence, ensure_ascii=False))

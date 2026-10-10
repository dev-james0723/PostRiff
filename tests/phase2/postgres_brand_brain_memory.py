"""Real workspace/API/run receipt integration using a recording, zero-cost writer (no paid AI)."""
import runpy
from pathlib import Path
fixture = runpy.run_path(str(Path(__file__).with_name('postgres_memory_egress.py')))
locals().update({key: fixture[key] for key in ('service', 'ideas', 'wid', 'cid', 'cloud', 'connection', 'act', 'check', 'passed')})
from postriff_phase2 import memory

run = ideas.turn(wid, 'one', cid, {'text': 'Draft one post for LinkedIn.', 'model': cloud.model, 'timeZone': 'Asia/Hong_Kong'})
receipt = run['usage']['memoryReceipt']
check('MEM04 concrete cloud denial records zero files', receipt['filesIncluded'] == [] and receipt['cloudMemoryAllowed'] is False)
check('MEM10 completed receipt has exact route and no private raw values', receipt['writerRoute'] == f'cloud:{cloud.provider}:{cloud.model}' and 'SECRET-' not in str(receipt))
with connection() as db:
    stored = db.execute('SELECT artifact,usage FROM public.pr_agent_runs WHERE id=%s', (run['runId'],)).fetchone()
check('MEM10 durable run artifact and usage agree', stored[0]['memoryReceipt'] == stored[1]['memoryReceipt'])
act('memory_egress', {'confirmed': True, 'cloud': True})
run = ideas.turn(wid, 'one', cid, {'text': 'Draft another post for LinkedIn.', 'model': cloud.model, 'timeZone': 'Asia/Hong_Kong'})
receipt = run['usage']['memoryReceipt']
check('MEM05 cloud neutral request accurately lists files', receipt['filesIncluded'] == [f['name'] for f in cloud.requests[-1]['memory']])
check('MEM05 filtered boundaries counted in receipt', receipt['withheldBoundaries'] == 1)
check('MEM10 actual supplied fragment digests agree', all(f['digest'] == memory.fingerprint(next(x['body'] for x in cloud.requests[-1]['memory'] if x['name'] == f['name'])) for f in receipt['fragments']))
manual_run = ideas.turn(wid, 'one', cid, {'text': 'Use my approved authored voice for LinkedIn.', 'model': cloud.model, 'voiceMode': 'personalized', 'voiceSourceIds': [], 'timeZone': 'Asia/Hong_Kong'})
check('manual approved voice supports explicit personalized with zero samples', manual_run['usage']['memoryReceipt']['effectiveVoiceMode'] == 'approved' and 'VOICE.md' in manual_run['usage']['memoryReceipt']['filesIncluded'])
applied = ideas.apply(wid, 'one', service.get(wid, 'one')['revision'], manual_run['runId'], manual_run['artifactHash'])
saved = next(v for v in service.get(wid, 'one')['state']['variants'] if v.get('runId') == manual_run['runId'])
check('MEM10 applied draft carries its exact draftId and original run receipt', saved['memoryReceipt']['draftId'] == saved['id'] and saved['memoryReceipt']['runId'] == manual_run['runId'])
act('brand_brain_identity', {'confirmed': True, 'fields': {'audience': 'Independent makers', 'identitySentence': 'A local ceramics studio'}})
try:
    ideas.apply(wid, 'one', service.get(wid, 'one')['revision'], run['runId'], run['artifactHash'])
    raise AssertionError('stale rendered identity must block apply')
except fixture['AlphaError'] as error:
    check('MEM11 memory changes reject a stale completed candidate', error.status == 409)
view = ideas.memory_files(wid, 'one')
check('MEM02 identity readback reflects canonical fields', 'Independent makers' in next(f['body'] for f in view['files'] if f['name'] == 'IDENTITY.md'))
check('MEM02 snapshot workspace revision agrees with current state', view['snapshot']['workspaceRevision'] == service.get(wid, 'one')['revision'])
act('brand_brain_boundaries', {'confirmed': True, 'fields': [{'id': 'new-private', 'label': 'Client privacy', 'value': 'TEST-PRIVATE-MUST-STAY-LOCAL', 'privacy': 'private'}]})
view = ideas.memory_files(wid, 'one')
check('MEM13 owner local diagnostic retains authorized private rule', 'TEST-PRIVATE-MUST-STAY-LOCAL' in str(view['routeViews']['local']))
check('MEM13 cloud diagnostic removes private rule', 'TEST-PRIVATE-MUST-STAY-LOCAL' not in str(view['routeViews']['cloud']))
check('MEM01 legacy Memory route still returns exactly five files', [f['name'] for f in view['files']] == list(memory.FILE_ORDER))
print(f'postgres_brand_brain_memory: {len(passed)}/{len(passed)} checks passed')

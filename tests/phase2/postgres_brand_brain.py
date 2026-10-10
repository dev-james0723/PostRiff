"""Brand Brain real PostgreSQL repository, membership, audit and schedule holds.

Runs only against the disposable database; injected/local writers, no paid calls.
"""
import copy
import io
import json
import os
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedWorkspaceService

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ONE = '00000000-0000-0000-0000-000000000001'
TWO = '00000000-0000-0000-0000-000000000002'
THREE = '00000000-0000-0000-0000-000000000003'
def connection(): return psycopg.connect(DSN)
def verify(token):
    if token not in ('one', 'two', 'three'):
        raise AlphaError('Sign in', 401)
    return {'one': ONE, 'two': TWO, 'three': THREE}[token]
verify.auth_time = lambda token, actor: time.time()
verify.session_id = lambda token, actor: 'brand-brain-postgres-session'
service = HostedWorkspaceService(connection, verify)
snapshot = service.bootstrap('one', 'studio')
wid = snapshot['workspaceId']
service.repository.command(wid, 'one', snapshot['revision'], lambda state, actor: initial_phase2_state(wid, ONE, 'Owner', 'studio', time.time(), execution='hosted-candidate'))
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active') ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='editor',status='active'", (wid, TWO))
sequence = 0
checks = []
def act(action, payload=None, token='one'):
    global sequence
    sequence += 1
    payload = {**(payload or {})}
    if action.startswith('brand_brain_'):
        payload.setdefault('requestId', f'postgres-brand-brain-{sequence:04}')
    current = service.get(wid, token)
    return service.mutate(wid, token, current['revision'], action, payload)
def denied(call, status):
    try: call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
    else: raise AssertionError('Expected denial')

act('mode', {'mode': 'personal'})
act('context', {'purpose': 'Share useful practice', 'audience': 'Readers', 'subject': 'Practice', 'speaker': 'Owner', 'layers': []})
act('profile_propose', {'tone': 'warm'})
act('profile_decide', {'decision': 'approve'})
act('runtime', {'selected': 'deterministic-preview'})
for activation_action in ('profile_finish', 'import_decide'):
    denied(lambda: act(activation_action, {'approve': True}, 'two'), 403)
seeded = act('source', {'kind': 'sample'})
source = seeded['state']['sources'][-1]
act('approve_source', {'sourceId': source['id'], 'factIds': [fact['id'] for fact in source['facts']]})
act('generate', {'platform': 'LinkedIn', 'language': 'English'})
current = service.get(wid, 'one')
variant = current['state']['variants'][-1]
act('p2_variant_review', {'variantId': variant['id'], 'variantRevision': variant['revision'], 'confirmed': True, 'excludedUnknowns': variant['unknowns']})
channel = {'id': uuid.uuid4().hex, 'platform': 'LinkedIn', 'account': 'Fixture account', 'accountType': 'member', 'language': 'English', 'scopes': ['w_member_social'], 'verifiedAt': time.time(), 'expiresAt': time.time()+86400, 'capabilityVersion': 1, 'providerAccountId': 'urn:li:person:fixture'}
current = service.get(wid, 'one')
service.repository.command(wid, 'one', current['revision'], lambda state, actor: service.commands.upsert_verified_channel(state, actor, channel))
reviewed = act('p2_review', {'channelId': channel['id'], 'variantId': variant['id'], 'localTime': datetime.fromtimestamp(time.time()+600, timezone.utc).replace(tzinfo=None).isoformat(), 'timeZone': 'UTC', 'acknowledgedWarnings': variant['warnings']})
review = reviewed['state']['phase2']['reviews'][-1]
act('p2_approve', {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})

payload = {'format': 'pasted', 'text': 'Hello friends.\nA short update on practice.', 'authorshipConfirmed': True, 'retentionConfirmed': True, 'requestId': 'postgres-idempotent-import-01'}
saved = act('brand_brain_import', payload, 'two')
sid = saved['state']['sources'][-1]['id']
replayed = act('brand_brain_import', payload, 'two')
assert len(saved['state']['sources']) == len(replayed['state']['sources'])
act('voice_sample_select', {'sourceId': sid, 'selected': True})
grants = [{'purpose': 'analysis', 'route': 'local-rules'}, {'purpose': 'generation', 'route': 'local-cli'}]
denied(lambda: act('voice_sample_grant', {'sourceId': sid, 'grants': grants, 'confirmed': True}, 'two'), 403)
act('voice_sample_grant', {'sourceId': sid, 'grants': grants, 'confirmed': True})
active = service.get(wid, 'one')['state']['speaker']['activeRevision']
analysed = act('brand_brain_analyze', {'sourceIds': [sid]}, 'two')
assert analysed['state']['speaker']['activeRevision'] == active
proposal_digest = analysed['state']['brandBrain']['proposalDigest']
preview = act('brand_brain_preview', {'proposalDigest': proposal_digest, 'prompt': 'Share a practice reflection', 'platform': 'LinkedIn', 'language': 'en', 'model': 'deterministic-preview'})
assert preview['state']['speaker']['activeRevision'] == active
assert preview['state']['brandBrain']['preview']['receipt']['generationKind'] == 'template'
assert preview['state']['brandBrain']['preview']['generated']
checks.append('canonical analysis and actual paired template writer preserve active voice')

current = service.get(wid, 'one')
proposal_digest = current['state']['brandBrain']['proposalDigest']
impact_digest = current['state']['brandBrain']['impact']['impactDigest']
assert current['state']['brandBrain']['impact']['heldPosts'] == 1
approval = {'proposalDigest': proposal_digest, 'impactDigest': impact_digest, 'confirmed': True}
denied(lambda: act('brand_brain_approve', approval, 'two'), 403)
denied(lambda: act('profile_decide', {'decision': 'approve'}), 409)
denied(lambda: service.mutate(wid, 'one', current['revision']-1, 'brand_brain_approve', {**approval, 'requestId': 'postgres-stale-approve-01'}), 409)
old_version = copy.deepcopy(current['state']['speaker']['revisions'][0])
approved = act('brand_brain_approve', approval)
assert approved['state']['speaker']['activeRevision'] == active+1
assert approved['state']['speaker']['revisions'][0] == old_version
assert all(v['needsReview'] for v in approved['state']['variants'])
assert approved['state']['phase2']['jobs'][0]['state'] == 'held'
assert approved['state']['brandBrain']['lastReceipt']['heldPosts'] == 1
checks.append('real repository owner and stale fencing plus draft invalidation and schedule holds')

restored = act('brand_brain_restore', {'revision': 2, 'impactDigest': approved['state']['brandBrain']['impact']['impactDigest'], 'confirmed': True})
assert restored['state']['speaker']['activeRevision'] == 3
assert restored['state']['speaker']['revisions'][-1]['restoredFrom'] == 2
act('voice_sample_revoke', {'sourceId': sid, 'confirmed': True})
current = service.get(wid, 'one')
assert not next(v for v in current['state']['brandBrain']['versions'] if v['revision'] == 2)['restoreEligible']
assert 'Hello friends.' not in json.dumps(current['state']['speaker']['revisions'])
denied(lambda: act('brand_brain_restore', {'revision': 2, 'impactDigest': current['state']['brandBrain']['impact']['impactDigest'], 'confirmed': True}), 409)
denied(lambda: service.export_profile(wid, 'one'), 409)
denied(lambda: act('brand_brain_analyze', {'sourceIds': ['foreign-source-id']}), 404)
checks.append('append-only restore activation and revocation prevents restored evidence use')

# A real membership boundary remains indistinguishable for an unrelated workspace.
with connection() as db:
    db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT(id) DO NOTHING', (THREE,))
foreign = service.bootstrap('three', 'studio')['workspaceId']
assert foreign != wid
denied(lambda: service.get(foreign, 'one'), 403)
denied(lambda: service.get(wid, 'three'), 403)
checks.append('workspace isolation and idempotent imports')
# The managed analysis admission, ledger and single-use quote run against real SQL.
# Transport is injected: this is not a paid/live provider acceptance test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from consumer_fixtures import approve_budgets
# The disposable RLS harness seeds legacy allowance plans. Explicitly approve
# its synthetic budgets; never enable a real provider or alter operator policy.
with connection() as db:
    entitlement = service.ledger.ensure_entitlement(db.cursor(), wid, None)
    policy = db.execute("SELECT entitlements->>'creditPolicy' FROM public.pr_plan_terms WHERE id=%s", (entitlement['planTermsId'],)).fetchone()[0]
    assert policy is None, 'This fixture expects the disposable legacy allowance plan'
approve_budgets(connection, wid)
from postriff_phase2.agent_runtime import FixtureAgentRuntime
class AnalysisRuntime(FixtureAgentRuntime):
    provider = 'injected-analysis'
    provider_class = 'cloud'
    cost_class = 'paid'
    model = 'injected-analysis-model'
    calls = 0
    def list_supported_models(self):
        return [{'id': self.model, 'qualified': True, 'costClass': 'paid', 'label': 'Injected analysis'}]
    def quote_voice_analysis(self, projection, model, instructions=''):
        assert projection['route'] == 'cloud:' + self.provider + ':' + self.model
        assert model == self.model
        return 1000
    def analyze_voice(self, projection, model, instructions=''):
        self.calls += 1
        sample = projection['samples'][0]
        return {'output': {'dimensions': [{'id': 'openings', 'observation': 'Starts with a brief greeting.', 'support': [sample['id']], 'counterEvidence': [], 'quotes': [{'sourceId': sample['id'], 'text': 'Hello again.'}]}]}, 'usage': {'costUsd': 0.0001, 'modelRequests': 1}}
runtime = AnalysisRuntime()
service.ideas.runtimes.append(runtime)
saved = act('brand_brain_import', {'text': 'Hello again. A measured update.', 'authorshipConfirmed': True, 'retentionConfirmed': True})
cloud_sid = saved['state']['sources'][-1]['id']
route = 'cloud:' + runtime.provider + ':' + runtime.model
act('voice_sample_select', {'sourceId': cloud_sid, 'selected': True})
act('voice_sample_grant', {'sourceId': cloud_sid, 'confirmed': True, 'grants': [{'purpose': 'analysis', 'route': route}]})
analysis_inputs = {'sourceIds': [cloud_sid], 'route': route, 'model': runtime.model}
quoted = act('brand_brain_quote', analysis_inputs)
quote = quoted['state']['brandBrain']['analysisQuote']
assert quote['estimatedMicroUsd'] == 1000
assert runtime.calls == 0
active = quoted['state']['speaker']['activeRevision']
denied(lambda: act('brand_brain_analyze', {**analysis_inputs, 'quoteId': 'wrong-quote', 'confirmed': True}), 409)
result = act('brand_brain_analyze', {**analysis_inputs, 'quoteId': quote['id'], 'confirmed': True})
assert runtime.calls == 1
assert result['state']['speaker']['activeRevision'] == active
assert result['state']['speaker']['provisional']['analysisMethod'] == 'ai'
assert result['state']['brandBrain']['analysisQuote']['status'] == 'consumed'
denied(lambda: act('brand_brain_analyze', {**analysis_inputs, 'quoteId': quote['id'], 'confirmed': True}), 409)
assert runtime.calls == 1
checks.append('single-use exact quote, real reservation/settlement, injected AI result and no auto activation')
# Exercise the same route with the existing opt-in credit wallet, synthetic
# funding only. No application billing configuration or payment provider is used.
from postriff_phase2.billing import Ledger
from postriff_phase2.credit_meter import POLICY_VERSION
with connection() as db:
    if db.execute("SELECT to_regclass('public.pr_credit_quotes')").fetchone()[0] is None:
        db.execute((Path(__file__).resolve().parents[2] / 'migrations/postriff/020_credit_quotes.sql').read_text())
    terms = {'writingBatches': 10, 'mediaCredits': 1, 'members': 1, 'connectedAccounts': 3, 'storageMb': 200, 'creditPolicy': POLICY_VERSION}
    db.execute("INSERT INTO public.pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('brand-brain-test-credits','studio',998,'Synthetic Brand Brain credits',0,'active',%s::jsonb)", (json.dumps(terms),))
    db.execute("UPDATE public.pr_entitlements SET plan_terms_id='brand-brain-test-credits' WHERE workspace_id=%s", (wid,))
service.ledger = Ledger(credits_enabled=True)
denied(lambda: act('brand_brain_quote', analysis_inputs), 402)
assert runtime.calls == 1
with connection() as db:
    service.ledger.credits.grant(db.cursor(), wid, ONE, 'brand-brain-test-funding', 30000, time.time()+600)
quoted = act('brand_brain_quote', analysis_inputs)
quote = quoted['state']['brandBrain']['analysisQuote']
assert quote['creditLimit']['maxMilliCredits'] == 300
assert runtime.calls == 1
denied(lambda: act('brand_brain_analyze', {**analysis_inputs, 'quoteId': quote['id'], 'confirmed': False}), 400)
result = act('brand_brain_analyze', {**analysis_inputs, 'quoteId': quote['id'], 'confirmed': True})
assert runtime.calls == 2
assert result['state']['speaker']['activeRevision'] == active
with connection() as db:
    wallet = service.ledger.credits.view(db.cursor(), wid)
    claim = db.execute('SELECT reservation_id FROM public.pr_credit_quotes WHERE id=%s', (quote['creditLimit']['quoteId'],)).fetchone()[0]
assert claim is not None
assert wallet['usedMilliCredits'] == 100 and wallet['heldMilliCredits'] == 0
assert wallet['availableMilliCredits'] == 29900
denied(lambda: act('brand_brain_analyze', {**analysis_inputs, 'quoteId': quote['id'], 'confirmed': True}), 409)
assert runtime.calls == 2
checks.append('existing CreditBook exact limit approval, insufficient balance denial, claimed quote and real credit settlement')
# Export uses the approved voice plus current canonical identity/boundaries,
# while remaining a read-only snapshot with no new field approval or grants.
manual = act('brand_brain_manual', {'mode': 'personal', 'context': {'purpose': 'Share useful practice', 'audience': 'Readers', 'subject': 'Practice', 'speaker': 'Owner'}, 'tone': 'direct'})
approved = act('brand_brain_approve', {'proposalDigest': manual['state']['brandBrain']['proposalDigest'], 'impactDigest': manual['state']['brandBrain']['impact']['impactDigest'], 'confirmed': True})
act('brand_brain_identity', {'confirmed': True, 'fields': {'audience': 'Export readers'}})
act('brand_brain_boundaries', {'confirmed': True, 'fields': [
    {'id': 'export-public', 'label': 'Public rule', 'value': 'Approved public rule', 'privacy': 'public'},
    {'id': 'export-private', 'label': 'Private rule', 'value': 'EXPORT-PRIVATE-MUST-NOT-LEAVE', 'privacy': 'private'}]})
act('brand_brain_manual', {'mode': 'personal', 'context': {'purpose': 'PENDING-EXPORT-MUST-NOT-LEAVE', 'audience': 'Readers', 'subject': 'Practice', 'speaker': 'Owner'}, 'tone': 'warm'})
before_export = service.get(wid, 'one')
for token in ('one', 'two'):
    archive = zipfile.ZipFile(io.BytesIO(service.export_profile(wid, token)))
    assert set(('VOICE.md', 'IDENTITY.md', 'BOUNDARIES.md', 'BRAND.md', 'AGENT.md')).issubset(archive.namelist())
    exported = '\n'.join(archive.read(name).decode() for name in archive.namelist())
    assert 'Export readers' in exported and 'Approved public rule' in exported
    assert 'EXPORT-PRIVATE-MUST-NOT-LEAVE' not in exported and 'PENDING-EXPORT-MUST-NOT-LEAVE' not in exported
    assert 'Hello again.' not in exported
    manifest = json.loads(archive.read('manifest.json'))
    assert manifest['profileRevision'] == approved['state']['speaker']['activeRevision']
    assert not any(manifest['permissions'].values())
with connection() as db:
    db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (wid, TWO))
assert 'VOICE.md' in zipfile.ZipFile(io.BytesIO(service.export_profile(wid, 'two'))).namelist()
denied(lambda: service.export_profile(wid, 'three'), 403)
assert service.get(wid, 'one')['revision'] == before_export['revision']
checks.append('approved canonical ZIP export, restricted data omission, read-role access and foreign workspace denial')
with connection() as db:
    audit_count = db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'voice.%%'", (wid,)).fetchone()[0]
assert audit_count > 0
checks.append('durable content-free audit rows')
print(json.dumps({'status': 'pass', 'checks': checks, 'execution': 'disposable-postgresql; no paid providers'}, indent=2))

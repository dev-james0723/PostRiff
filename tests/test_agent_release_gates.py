"""Pure/service contract tests. Synthetic receipts below are NOT live release evidence."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch
from postriff_phase2.agent_runtime_v2 import release_gates as gates

NOW = 1791633600
WS = str(uuid.uuid4())
SHA = 'a' * 40
PINS = {'registryDigest': '1' * 64, 'assetsDigest': '2' * 64, 'provider': 'openai', 'model': 'test-model',
        'libraryHashes': {'consumer': '3' * 64, 'founder': '4' * 64}}


def receipt(profile='full'):
    return {'contract': gates.CONTRACT, 'execution': 'live-browser+database', 'workspaceId': WS, 'releaseSha': SHA,
            'pins': copy.deepcopy(PINS), 'corpus': {'id': gates.CORPUS_ID, 'sha256': gates.CORPUS_SHA},
            'profile': profile, 'policy': copy.deepcopy(gates.PROFILES[profile]), 'startedAt': NOW-100, 'finishedAt': NOW-1,
            'runId': str(uuid.uuid4()), 'browserEvidenceSha256': '5' * 64, 'deploymentEvidenceSha256': '6' * 64,
            'cases': [{'caseId': c, 'artifactId': str(uuid.uuid4()), 'attemptIds': [str(uuid.uuid4())],
                       'firstPass': True, 'functional': True, 'rendered': True, 'sourceHash': '7' * 64,
                       'manifestHash': gates.digest({}), 'promptHash': '8' * 64, 'browserCaseSha256': '9' * 64}
                      for c in gates.CASE_IDS]}


def physical(r):
    rows = []
    for case in r['cases']:
        for index, ident in enumerate(case['attemptIds']):
            final = index == len(case['attemptIds'])-1
            scope = 'founder' if case['caseId'].startswith('J09-') else 'workspace'
            rows.append([ident, case['artifactId'], 'generate' if index==0 else 'repair', 'ready' if final else 'failed',
                         None if index==0 else case['attemptIds'][0], 1, 'known', 1,
                         {'provider': PINS['provider'], 'model': PINS['model']}, scope,
                         PINS['libraryHashes']['founder' if scope=='founder' else 'consumer'], case['promptHash'], {},
                         case['sourceHash'] if final else None, {'accepted': final}, NOW-90, NOW-2])
    return rows


class Cursor:
    def __init__(self, rows): self.rows, self.calls = rows, []
    def execute(self, sql, params=None): self.calls.append((sql, params))
    def fetchall(self): return self.rows
    def fetchone(self): return self.one
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass


class ReceiptTests(unittest.TestCase):
    def valid(self, r): return gates.validate(r, WS, SHA, PINS, now=NOW)

    def test_exact_fixed_sixty_matches_live_plan(self):
        from importlib.util import spec_from_file_location, module_from_spec
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'scripts/agent_ui_live.py'
        spec=spec_from_file_location('release_gate_live_plan',path);mod=module_from_spec(spec);spec.loader.exec_module(mod)
        p=mod.sample_plan()
        self.assertEqual(tuple(c['caseId'] for c in p['normal']), gates.CASE_IDS)
        self.assertEqual(p['corpus']['sha256'], gates.CORPUS_SHA)
        self.assertTrue(self.valid(receipt()))

    def test_every_pin_and_identity_is_required(self):
        for key,value in [('execution','fixture'),('workspaceId',str(uuid.uuid4())),('releaseSha','b'*40),
                          ('corpus',{'id':gates.CORPUS_ID,'sha256':'0'*64}),('pins',{**PINS,'model':'other'}),
                          ('startedAt',NOW-gates.MAX_AGE-1),('finishedAt',NOW+1),('browserEvidenceSha256',''),
                          ('deploymentEvidenceSha256',''),('policy',{}),('runId','fake')]:
            with self.subTest(key=key):
                r=receipt();r[key]=value;self.assertFalse(self.valid(r))

    def test_all_cases_required_ordered_rendered_functional(self):
        for mutation in [lambda r:r['cases'].pop(), lambda r:r['cases'].reverse(),
                         lambda r:r['cases'][0].update(rendered=False), lambda r:r['cases'][0].update(functional=False),
                         lambda r:r['cases'][0].update(firstPass=1),lambda r:r['cases'][0].update(sourceHash=''),
                         lambda r:r['cases'][0].update(prompt='private text'),lambda r:r.update(rawBrowser='private')]:
            r=receipt();mutation(r);self.assertFalse(self.valid(r))

    def test_at_most_one_repair_and_59_first_pass(self):
        r=receipt();r['cases'][0]['firstPass']=False;r['cases'][0]['attemptIds'].append(str(uuid.uuid4()))
        self.assertTrue(self.valid(r))
        r['cases'][1]['firstPass']=False;r['cases'][1]['attemptIds'].append(str(uuid.uuid4()))
        self.assertFalse(self.valid(r))
        r['cases'][1]['firstPass']=True;r['cases'][1]['attemptIds'].pop();r['cases'][0]['attemptIds'].append(str(uuid.uuid4()))
        self.assertFalse(self.valid(r))

    def test_reused_artifacts_or_attempts_are_rejected(self):
        for key in ('artifactId','attemptIds'):
            r=receipt();r['cases'][1][key]=r['cases'][0][key];self.assertFalse(self.valid(r))

    def test_physical_proof_rejects_unknown_cost_fake_dispatch_and_wrong_scope(self):
        r=receipt();self.assertTrue(gates._physical(Cursor(physical(r)),r))
        for index,value in [(3,'failed'),(5,0),(5,2),(6,'unknown'),(7,None),(8,{'provider':'fixture','model':'test-model'}),
                            (9,'founder'),(10,'x'*64),(11,'x'*64),(12,{'wrong':'manifest'}),(13,'x'*64),
                            (14,{'accepted':False}),(15,NOW-200),(16,NOW+1)]:
            with self.subTest(index=index,value=value):
                rows=physical(r);rows[0][index]=value;self.assertFalse(gates._physical(Cursor(rows),r))

    def test_no_omitted_attempts_and_correct_repair_parent(self):
        r=receipt();rows=physical(r);self.assertFalse(gates._physical(Cursor(rows[:-1]),r))
        self.assertFalse(gates._physical(Cursor(rows+rows[:1]),r))
        r['cases'][0]['firstPass']=False;r['cases'][0]['attemptIds'].append(str(uuid.uuid4()))
        self.assertTrue(gates._physical(Cursor(physical(r)),r))
        rows=physical(r);rows[1][4]=None;self.assertFalse(gates._physical(Cursor(rows),r))

    def test_record_requires_independent_verifier_and_exact_replay(self):
        r=receipt();cur=Cursor(physical(r));cur.one=(gates.digest(r),)
        with self.assertRaises(ValueError):gates.record(cur,r,PINS,verifier=None,now=NOW)
        gates.record(cur,r,PINS,verifier=lambda _:True,now=NOW)
        self.assertTrue(any('INSERT INTO' in sql for sql,_ in cur.calls))
        cur.one=('different',)
        with self.assertRaises(ValueError):gates.record(cur,r,PINS,verifier=lambda _:True,now=NOW)

    def test_reader_requires_both_independent_current_runs(self):
        a,b=receipt(),receipt('recommended_narrowed')
        cur=Cursor([(a,gates.digest(a)),(b,gates.digest(b))])
        with patch.object(gates,'pins',return_value=PINS):
            ready=gates.reader(lambda:cur,object(),clock=lambda:NOW)
            self.assertTrue(ready(WS,SHA));self.assertFalse(ready(WS,'b'*40))
            cur.rows=[(a,gates.digest(a))];self.assertFalse(ready(WS,SHA))
            b['cases'][0]['artifactId']=a['cases'][0]['artifactId'];cur.rows=[(a,gates.digest(a)),(b,gates.digest(b))]
            self.assertFalse(ready(WS,SHA))
            b=receipt('recommended_narrowed');cur.rows=[(a,'tampered'),(b,gates.digest(b))]
            self.assertFalse(ready(WS,SHA))

    def test_missing_storage_and_changed_model_fail_closed(self):
        with patch.object(gates,'pins',side_effect=RuntimeError('unavailable')):
            self.assertFalse(gates.reader(lambda:None,object())(WS,SHA))
        a,b=receipt(),receipt('recommended_narrowed');cur=Cursor([(a,gates.digest(a)),(b,gates.digest(b))])
        with patch.object(gates,'pins',return_value={**PINS,'model':'new'}):
            self.assertFalse(gates.reader(lambda:cur,object(),clock=lambda:NOW)(WS,SHA))

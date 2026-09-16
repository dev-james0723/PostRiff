"""Durable, explicitly authorized local worker; never started by the fixture launcher."""
import hashlib
import json
from postriff_alpha.domain import AlphaError
from . import contracts as c
from .adapters import ExecutionPermit


class AuthorizedWorker:
    def __init__(self, store, adapter):
        self.store, self.adapter = store, adapter

    def _member(self, db, wid, token):
        return db.execute(
            "SELECT d.user_id,m.role FROM alpha_devices d JOIN alpha_memberships m "
            "ON m.workspace_id=d.workspace_id AND m.user_id=d.user_id "
            "WHERE d.workspace_id=? AND d.credential_hash=? AND d.status='active' "
            "AND m.status='active'", (wid, hashlib.sha256(token.encode()).hexdigest())
        ).fetchone()

    def execute(self, wid, token, run_id, permit):
        c.require(isinstance(permit, ExecutionPermit), 'Execution permit required.', 403)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.store._row(db, wid, token)
            state = json.loads(row['state'])
            data = self.store.load_runtime(db, wid)
            job = c.item(data['jobs'], run_id)
            member = self._member(db, wid, token)
            c.require(member and member['role'] in ('owner', 'editor') and
                      member['user_id'] == job['actor'] and job['deviceId'] is None,
                      'Run authority unavailable.', 403)
            c.require(job['status'] == 'prepared' and job['route'] == permit.route and
                      permit.input_hash == job['inputHash'] and
                      min(permit.expires_at, job['expiresAt']) > self.store.clock() and
                      0 < permit.max_cost_usd <= .05,
                      'Run already started, expired or changed. Reconcile before retry.', 409)
            manifest = job['manifest']
            c.require(self._current(state, data, job), 'Source snapshot changed.', 409)
            if job['route'] == 'managed':
                trial = state['phase2']['trial']
                reservations = sum(j['route'] == 'managed' and j['status'] == 'running'
                                   for j in data['jobs'])
                c.require(trial['expiresAt'] > self.store.clock() and
                          trial['writingUsed'] + reservations < trial['writingGrant'],
                          'Writing allowance unavailable.', 409)
            job.update(status='running', attempt=c.uid(), leaseUntil=self.store.clock() + 60,
                       authorization={'model': permit.model, 'maxCostUsd': permit.max_cost_usd,
                                      'qualification': permit.qualification_id})
            attempt = job['attempt']
            c.event(job, 'running', self.store.clock())
            self.store.save_runtime(db, wid, data)

        def emit(event):
            if event.get('type') != 'text':
                return
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                data = self.store.load_runtime(db, wid)
                current = next((j for j in data['jobs'] if j['id'] == run_id), None)
                if current and current['status'] == 'running' and current['attempt'] == attempt:
                    c.event(current, 'text', self.store.clock(), event.get('text', ''))
                    self.store.save_runtime(db, wid, data)

        result = None
        try:
            result = self.adapter.start(manifest, permit, emit)
        except Exception:
            pass  # No provider diagnostics or credentials in persisted errors.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM workspaces WHERE id=?', (wid,)).fetchone()
            data = self.store.load_runtime(db, wid)
            job = next((j for j in data['jobs'] if j['id'] == run_id), None)
            if row is None or job is None:
                return {'status': 'revoked', 'allowanceCharged': False}
            # Retain accounting after revocation without accepting or returning a draft.
            job['providerCost'] = {'provenance': 'Unavailable', 'maxAuthorizedUsd': permit.max_cost_usd}
            if isinstance(result, dict) and isinstance(result.get('usage'), dict):
                job['usage'] = result['usage']
            state = json.loads(row['state'])
            authorized = False
            try:
                self.store._row(db, wid, token)
                member = self._member(db, wid, token)
                authorized = bool(member and member['role'] in ('owner', 'editor') and
                                  member['user_id'] == job['actor'])
            except AlphaError:
                pass
            valid = (authorized and job['status'] == 'running' and job['attempt'] == attempt and
                     min(job['expiresAt'], job['leaseUntil']) > self.store.clock() and
                     self._current(state, data, job))
            candidate = None
            if valid and isinstance(result, dict) and result.get('artifact'):
                try:
                    candidate = c.artifact(result['artifact'], manifest)
                except (AlphaError, TypeError, ValueError, KeyError):
                    pass
            if candidate:
                job.update(artifact=candidate, artifactHash=c.digest(candidate), status='completed')
                if job['route'] == 'managed' and not job['allowanceCharged']:
                    state['phase2']['trial']['writingUsed'] += 1
                    job['allowanceCharged'] = True
                    db.execute('UPDATE workspaces SET revision=revision+1,state=? WHERE id=?',
                               (json.dumps(state), wid))
                c.event(job, 'completed', self.store.clock())
            elif job['status'] == 'running':
                job['status'] = 'interrupted' if authorized else 'revoked'
                c.event(job, job['status'], self.store.clock(),
                        'No accepted result. Provider cost may exist; reconcile before another request.')
            self.store.save_runtime(db, wid, data)
            if not authorized:
                return {'status': 'revoked', 'allowanceCharged': False}
            return {'status': job['status'], 'usage': job['usage'],
                    'allowanceCharged': job['allowanceCharged']}

    @staticmethod
    def _current(state, data, job):
        try:
            manifest = job['manifest']
            return job['inputHash'] == c.digest(c.snapshot(
                state, data, [s['id'] for s in manifest['sources']],
                manifest['operation'], job['route'] == 'managed'))
        except (AlphaError, KeyError, TypeError, ValueError):
            return False

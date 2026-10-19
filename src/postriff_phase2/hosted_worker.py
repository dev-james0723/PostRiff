"""Bounded PostgreSQL worker for browser-independent Phase 2 schedules."""
import copy
import json
import math
import os
import threading
import time
import uuid

from postriff_alpha.domain import AlphaError
from .store import IN_FLIGHT, TERMINAL, find
from .hosted import HostedPhase2Commands
from .contracts import digest
from .hosted_social import HostedSocial
from .outcomes import normalize_result, unknown
from .permissions import Membership, require
from .learning_service import record_published
from .youtube.agent import assert_job_authority
from .discord import worker as discord_worker
from .discord.rate_limits import UnconsumedPublishPermit


def configured_worker_limits(values=None):
    """Server-only tuning; existing cron defaults and safe per-invocation bounds."""
    values = os.environ if values is None else values
    try:
        jobs = int(values.get('POSTRIFF_WORKER_MAX_JOBS', 10))
        seconds = float(values.get('POSTRIFF_WORKER_MAX_SECONDS', 20))
    except (ValueError, TypeError, OverflowError):
        raise AlphaError('Worker budgets require one to 25 jobs and one to 45 seconds.', 503,
                         code='worker_budget_configuration') from None
    if not 1 <= jobs <= 25 or not 1 <= seconds <= 45:
        raise AlphaError('Worker budgets require one to 25 jobs and one to 45 seconds.', 503,
                         code='worker_budget_configuration')
    return jobs, seconds


def due_workspaces_sql(capacity_ready=True, *, youtube_only=False, exclude_youtube=False, operations_ready=True, linkedin_only=False, discord_only=False, exclude_discord=False, discord_projected=False):
    """The actual bounded selection, shared with disposable query-plan acceptance."""
    dispatch_join = 'LEFT JOIN public.pr_worker_tenants dispatch ON dispatch.workspace_id=w.id' if capacity_ready else ''
    dispatch_order = 'dispatch.last_claimed_at NULLS FIRST,w.id' if capacity_ready else 'w.id'
    if discord_only:
        # Other-provider claims update the generic tenant cursor. Discord's own
        # compatible JSON service cursor prevents those updates from starving
        # a tenant's Discord queue; no new schema or independent queue is added.
        dispatch_order = "coalesce((w.state#>>'{phase2,discordWorkerCursor,lastClaimedAt}')::double precision,0),w.id"
    if (youtube_only and (exclude_youtube or linkedin_only or discord_only)
            or discord_only and (linkedin_only or exclude_discord)):
        raise AlphaError('Worker platform filters conflict.', 503, code='worker_platform_filter')
    if youtube_only and capacity_ready and operations_ready:
        from .youtube.operations import WORKER_SQL
        return WORKER_SQL
    if discord_only and discord_projected:
        # Migration126 mirrors due/lease/cursor hints in the SAME workspace
        # transaction. The locked source checks below still own authorization.
        return """SELECT w.id::text,w.revision,w.state FROM public.pr_workspaces w
            JOIN public.pr_discord_worker_projection hint ON hint.workspace_id=w.id
            WHERE hint.next_at<=least(%s,%s) AND NOT w.id=ANY(%s::uuid[])
            ORDER BY hint.last_claimed_at,w.id LIMIT 1 FOR UPDATE OF w SKIP LOCKED"""
    platform_filter = (" AND j#>>'{manifest,platform}'='Discord'" if discord_only else
                       " AND j#>>'{manifest,platform}'='LinkedIn'" if linkedin_only else
                       " AND j#>>'{manifest,platform}'='YouTube'" if youtube_only else
                       " AND coalesce(j#>>'{manifest,platform}','')<>'YouTube'" if exclude_youtube else '')
    if exclude_discord:
        platform_filter += " AND coalesce(j#>>'{manifest,platform}','')<>'Discord'"
    tenant_gate = (""" AND NOT w.id=ANY(%s::uuid[])
          AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) a
            WHERE a#>>'{manifest,platform}'='Discord' AND a->>'leaseOwner' IS NOT NULL
              AND coalesce((a->>'leaseUntil')::double precision,0)>extract(epoch from clock_timestamp()))"""
                   if discord_only else '')
    return """SELECT w.id::text,w.revision,w.state FROM public.pr_workspaces w
        """ + dispatch_join + """
        WHERE w.state ? 'phase2' AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
            WHERE coalesce(j->>'state','') NOT IN ('verified','failed','canceled','held')
              AND coalesce((j->>'leaseUntil')::double precision,0)<=%s
              AND coalesce((j->>'nextAt')::double precision,0)<=%s""" + platform_filter + """)
        """ + tenant_gate + """ ORDER BY """ + dispatch_order + (" LIMIT 1" if discord_only else " LIMIT 100") + " FOR UPDATE OF w SKIP LOCKED"


NO_SUBMISSION_CONFIRMED = 'Live provider transport is not configured; nothing was submitted'
PREVIEW_PENDING_MESSAGE = 'Approved preview post; choose Publish approved post when due.'


def _no_provider_effect(job):
    return not any(job.get(key) for key in ('providerReference', 'container', 'providerUpload',
                                            'providerAssets', 'providerThread', 'progress', 'url', 'verification'))


def defer_pinterest_budget(job, result, reconciliation):
    """A trusted pre-POST budget wait consumes no provider-write retry, but keeps an audit event."""
    if (job.get('manifest', {}).get('platform') != 'Pinterest' or reconciliation or job.get('providerReference')
            or not isinstance(result, dict) or result.get('state') != 'scheduled'
            or result.get('pinterestBudgetDeferred') is not True):
        return False
    attempts = job.get('attempts') or []
    if attempts and attempts[-1].get('idempotencyKey') == job['manifest'].get('idempotencyKey'):
        attempts.pop()
    job['pinterestBudgetDeferrals'] = job.get('pinterestBudgetDeferrals', 0) + 1
    return True



class DisabledHostedSocial:
    """Fail closed until an exact provider transport and token vault are configured."""
    def submit(self, _manifest):
        return {"state": "held", "confirmed": NO_SUBMISSION_CONFIRMED}

    def reconcile(self, _manifest, _job):
        return {"state": "uncertain", "confirmed": "Provider reconciliation is unavailable; do not resubmit"}


class PostgresWorker:
    def __init__(self, connection_factory, social=None, clock=time.time, worker_id=None, on_verified=None, youtube_maintenance=None, worker_binding=None, discord_workers=None):
        self.connection_factory = connection_factory
        self.social = social or DisabledHostedSocial()
        self.clock = clock
        self.worker_id = worker_id or "worker-" + uuid.uuid4().hex
        self.commands = HostedPhase2Commands(clock, worker_binding=worker_binding)
        self.worker_binding = self.commands.engine.worker_binding
        # Optional server-side hook (e.g. native insights ingestion) run in the same transaction once verified.
        self.on_verified = on_verified
        self.youtube_maintenance = youtube_maintenance
        self.capacity_intervention = None
        self.discord_workers = discord_worker.enabled() if discord_workers is None else discord_workers is True
        self._lifecycle_lock = threading.RLock()
        self._stopping = False
        self.claim_contended = False
        self.discord_stats = dict.fromkeys(('claims', 'claimMisses', 'renewals', 'recoveries', 'leaseLost', 'contention',
                                          'retries', 'rateDelays', 'held', 'uncertain', 'deadLetters', 'shutdownReleased'), 0)

    def _event(self, job, state, message, *, at=None):
        previous = job.get('state')
        job["state"] = state
        job.setdefault("events", []).append({"at": self.clock() if at is None else at, "state": state, "message": message, "execution": "hosted-worker"})
        if (state in ('held', 'uncertain') and previous != state and job.get('manifest', {}).get('platform') == 'Discord'
                and (self.discord_workers or discord_worker.managed(job))):
            self.discord_stats[state] += 1

    @staticmethod
    def _db_now(cur):
        # now()/CURRENT_TIMESTAMP are transaction-start time and may be stale
        # after a row/credential lock wait. Check wall time after acquiring locks.
        cur.execute('SELECT extract(epoch from clock_timestamp())::double precision')
        now = cur.fetchone()[0]
        if not discord_worker.finite(now):
            raise AlphaError('Worker database clock is unavailable.', 503, code='discord_worker_clock')
        return now

    def _lease_now(self, cur, job):
        return self._db_now(cur) if discord_worker.managed(job) else self.clock()

    def _owns(self, job, claimed, now):
        if discord_worker.managed(job):
            return discord_worker.owns(job, claimed, self.worker_id, now)
        return (job.get('leaseOwner') == self.worker_id and job.get('leaseId') == claimed['job'].get('leaseId')
                and job.get('leaseUntil', 0) > now)

    def request_shutdown(self):
        """Stop admission after the current short claim commits, without provider IO."""
        with self._lifecycle_lock:
            self._stopping = True

    def _ensure_lifecycle(self):
        # Existing control fixtures and worker subclasses may initialize only
        # the legacy fields. Missing new policy always means default-off.
        if not hasattr(self, '_lifecycle_lock'):
            self._lifecycle_lock = threading.RLock()
        if not hasattr(self, '_stopping'):
            self._stopping = False
        if not hasattr(self, 'discord_workers'):
            self.discord_workers = False
        if not hasattr(self, 'worker_binding'):
            self.worker_binding = None
        if not hasattr(self, 'discord_stats'):
            self.discord_stats = dict.fromkeys(('claims', 'claimMisses', 'renewals', 'recoveries', 'leaseLost', 'contention',
                                               'retries', 'rateDelays', 'held', 'uncertain', 'deadLetters', 'shutdownReleased'), 0)

    def _discord_candidates(self, cur):
        # Lock one row per selection, at most eight examined tenants per claim.
        # There is no global lock in this lane; peer workers can use other rows.
        excluded = []
        cur.execute("SELECT to_regclass('public.pr_discord_worker_projection')")
        projected = cur.fetchone()[0] is not None
        for _ in range(discord_worker.MAX_CANDIDATES):
            now = self._db_now(cur)
            cur.execute(due_workspaces_sql(discord_only=True,discord_projected=projected), (now, now, excluded))
            row = cur.fetchone()
            if not row:
                return
            excluded.append(row[0])
            yield row

    def _current_discord_grant(self, cur, workspace_id, job):
        from .discord.authorization import grant_matches
        oauth = getattr(self.social, 'oauth', None)
        providers = getattr(self.social, 'providers', None)
        provider = providers.get('discord') if isinstance(providers, dict) else None
        if (provider is None or not getattr(provider, 'authorization_v2_enabled', False)
                or not callable(getattr(oauth, 'discord_grant_for_worker', None))):
            raise AlphaError('Discord transport or grant custody is unavailable; dispatch paused.', 409)
        if job['manifest'].get('operation') == 'discord.reply':
            from .discord.engagement import ready
            if not ready(provider):
                raise AlphaError('Discord engagement rollout or shared coordinator is paused.', 409)
            from .discord.message_content import assert_binding
            assert_binding(provider, job['manifest']['discord']['target'], job['manifest']['engagementReply'], self._db_now(cur))
        grant = oauth.discord_grant_for_worker(workspace_id, job['manifest']['channelId'], cur=cur)
        if (provider is None or not getattr(provider, 'authorization_v2_enabled', False)
                or not grant_matches(job['manifest'], grant, provider.session(grant['accessToken']))):
            raise AlphaError('Discord connection changed.', 409)
        return grant

    @staticmethod
    def _hold_discord_destination(state, job, now):
        # Never poison a newer independently reauthorized destination from an
        # old worker response. The frozen approval itself is left untouched.
        target = job['manifest'].get('discord', {}).get('target') or {}
        for channel in state.get('phase2', {}).get('channels', []):
            if channel.get('id') != job['manifest'].get('channelId'):
                continue
            for destination in channel.get('discordDestinations', []):
                if (destination.get('id') == target.get('id') and destination.get('status') == 'authorized'
                        and destination.get('authorizationGeneration') == target.get('authorizationGeneration')
                        and destination.get('resourceGeneration') == target.get('resourceGeneration')):
                    destination.update(status='verification_required', resourceGeneration=str(uuid.uuid4()),
                                       heldAt=now, nextAction='Verify Discord permission and explicitly authorize this destination again')

    def renew_discord_lease(self, claimed):
        """Renew one live fence, never approval validity; no provider IO under locks."""
        if self._stopping or not discord_worker.managed(claimed.get('job') or {}):
            return False
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
            row = cur.fetchone()
            if not row:
                return False
            revision, raw = row
            state = json.loads(raw) if isinstance(raw, str) else raw
            job = find(state.get('phase2', {}).get('jobs', []), claimed['job']['id'])
            now = self._db_now(cur)
            if not self._owns(job, claimed, now):
                self.discord_stats['leaseLost'] += 1
                return False
            try:
                self._current_discord_grant(cur, claimed['workspaceId'], job)
                now = self._db_now(cur)
                allowed = (not self._stopping and self._owns(job, claimed, now) and not job.get('cancelRequested')
                           and job.get('state') not in (*TERMINAL, 'held') and self._binding_matches(job)
                           and (not claimed.get('dispatchPrincipal') or self._requester_may_approve(cur, claimed['workspaceId'], claimed['dispatchPrincipal'], job))
                           and self._approved(cur, claimed['workspaceId'], state, job, now=now))
            except AlphaError:
                allowed = False
            # Membership/credential reads can wait too; recheck expiry at the end.
            now = self._db_now(cur)
            if not self._owns(job, claimed, now) or job['manifest']['expiresAt'] < now:
                self.discord_stats['leaseLost'] += 1
                return False
            if not allowed:
                self._event(job, 'uncertain' if discord_worker.has_effect(job) else 'held',
                            'Discord authority changed during renewal; no new dispatch is permitted', at=now)
                job['leaseOwner'], job['leaseUntil'] = None, 0
            else:
                job['leaseUntil'] = min(now + discord_worker.LEASE_SECONDS, job['manifest']['expiresAt'])
                job[discord_worker.KEY]['renewals'] += 1
                self._event(job, job['state'], 'Hosted worker renewed the same Discord fence', at=now)
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                        (json.dumps(state), claimed['workspaceId'], revision))
            if cur.rowcount != 1:
                raise AlphaError('Discord renewal lost its workspace revision.', 409)
            if allowed:
                claimed['job'] = copy.deepcopy(job)
                self.discord_stats['renewals'] += 1
            return allowed

    def release_discord_unsent(self, claimed, *, reason='shutdown', retry_after_seconds=None, rate_cause=None):
        """Only the current owner can release a proven pre-intent operation."""
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
            row = cur.fetchone()
            if not row:
                return False
            revision, raw = row
            state = json.loads(raw) if isinstance(raw, str) else raw
            job = find(state.get('phase2', {}).get('jobs', []), claimed['job']['id'])
            now = self._db_now(cur)
            if (not self._owns(job, claimed, now) or job.get('state') not in ('claimed', 'submitting')
                    or not discord_worker.pending_unsent(job)):
                return False
            status = discord_worker.release_unsent(job, now, reason, retry_after_seconds=retry_after_seconds)
            if rate_cause == 'provider_429':
                operation = job[discord_worker.KEY]
                operation['rateReadRetries'] = operation.get('rateReadRetries',0)+1
                if operation['rateReadRetries'] >= self.social.discord_read_attempt_limit():
                    status = job['state'] = 'held'
                    job['nextAction'] = 'Repeated Discord read rejection requires rate-policy review; the approved destination remains frozen'
            if job.get('cancelRequested'):
                status = 'canceled'
            self._event(job, status, 'Proven unsent Discord operation released: ' + reason, at=now)
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                        (json.dumps(state), claimed['workspaceId'], revision))
            if cur.rowcount != 1:
                raise AlphaError('Discord release lost its workspace revision.', 409)
            counter = ('rateDelays' if reason == 'rate_delayed' else
                       'shutdownReleased' if reason == 'shutdown' else
                       'deadLetters' if status == 'failed' else 'retries')
            self.discord_stats[counter] += 1
            return True

    def _binding_matches(self, job):
        manifest = job.get('manifest') or {}
        if 'workerBinding' in manifest and 'workerBinding' in job and manifest['workerBinding'] != job['workerBinding']:
            return False
        binding = job.get('workerBinding', manifest.get('workerBinding'))
        return binding == self.worker_binding

    def _may_adopt_legacy_hold(self, job):
        """One definitive disabled-transport result, never an unknown provider outcome."""
        attempts = job.get('attempts') or []
        event = (job.get('events') or [{}])[-1]
        return bool(self.worker_binding is not None and 'workerBinding' not in job
                    and 'workerBinding' not in (job.get('manifest') or {})
                    and job.get('state') == 'held' and not job.get('cancelRequested')
                    and job.get('resultSchema') == 'postriff.result.v1' and _no_provider_effect(job)
                    and job.get('providerConfirmed') == NO_SUBMISSION_CONFIRMED
                    and event.get('state') == 'held' and event.get('message') == NO_SUBMISSION_CONFIRMED
                    and len(attempts) == 1 and attempts[0].get('number') == 1
                    and type(attempts[0].get('startedAt')) in (int, float)
                    and type(attempts[0].get('endedAt')) in (int, float)
                    and math.isfinite(attempts[0]['startedAt']) and math.isfinite(attempts[0]['endedAt'])
                    and attempts[0]['endedAt'] >= attempts[0]['startedAt'])

    def _preview_hold(self, job):
        event = (job.get('events') or [{}])[-1]
        return bool(self.worker_binding is not None and self._binding_matches(job)
                    and job.get('manifest', {}).get('workerBinding') == self.worker_binding
                    and job.get('state') == 'held' and job.get('previewDispatchPending') is True
                    and not job.get('attempts') and _no_provider_effect(job)
                    and event.get('state') == 'held' and event.get('message') == PREVIEW_PENDING_MESSAGE)

    def _invalidate_owned(self, state):
        # A shared database may contain approvals from another deployment. Filter before
        # invalidation as well as before claim; neither reviews nor jobs may cross that boundary.
        data = state['phase2']
        view = {**state, 'phase2': {**data,
                'jobs': [job for job in data['jobs'] if self._binding_matches(job)
                         and not (job.get('manifest', {}).get('platform') == 'Discord'
                                  and (self.discord_workers or discord_worker.managed(job)))],
                'reviews': [review for review in data.get('reviews', []) if self._binding_matches({'manifest': review['manifest']})]}}
        self.commands.engine.invalidate(view)

    def _approved(self, cur, workspace_id, state, job, *, allow_reverification=False, now=None):
        from .billing import require_publishing
        try:
            now = self.clock() if now is None else now
            if job.get('privacyErased') or job.get('youtubeProviderDataRemoved') or job.get('manifest', {}).get('privacyErased'):
                return False
            if state.get('accountDeletion') or state.get('accountBlock'): return False
            # RAPv2 security hold on the approver is checked at claim and before dispatch.
            from . import security_holds
            security_holds.assert_clear(cur, job.get('approvedBy'), authorized_at=job.get('approvedAt'))
            require_publishing(cur, workspace_id, now)
            assert_job_authority(state, job, now)
            manifest = job['manifest']
            channel = find(state['phase2']['channels'], manifest['channelId'])
            if manifest.get('platform') == 'Discord':
                from .discord.authorization import job_authorized
                if not job_authorized(state, channel, job, now=now):
                    return False
            reply_job = job['manifest'].get('operation') == 'discord.reply'
            permission_column = 'can_reply' if reply_job else 'can_publish'
            cur.execute(f"SELECT m.role,m.{permission_column} FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job['approvedBy']))
            member = cur.fetchone()
            expires = manifest['expiresAt']
            recovery = job.get('youtubeRecoveryApproval') or {}
            if (manifest.get('platform') == 'YouTube' and recovery.get('digest') == job.get('approvalDigest')
                    and recovery.get('approvedBy') == job.get('approvedBy')
                    and type(recovery.get('approvedAt')) in (int, float)
                    and type(recovery.get('expiresAt')) in (int, float)
                    and recovery['approvedAt'] <= now
                    and recovery['approvedAt'] < recovery['expiresAt'] <= recovery['approvedAt'] + 36 * 3600):
                expires = max(expires, recovery['expiresAt'])
            return bool(member and Membership.from_row(member[0], **{permission_column: member[1]}).allows('reply' if reply_job else 'approve')
                        and (not job.get('youtubeAgent') or member[0] == 'owner')
                        and job['approvalDigest'] == digest(manifest) and job['approvedBy'] == manifest['actor']
                        and self.commands.engine.current(state, manifest)
                        and (self.commands.engine.channel_state(channel) == 'Ready for posting'
                             or (allow_reverification and channel.get('platform') == 'LinkedIn'
                                 and self.commands.engine.channel_reverification_due(channel)))
                        and expires >= now)
        except (AlphaError, KeyError, TypeError):
            return False

    @staticmethod
    def _requester_may_approve(cur, workspace_id, principal, job=None):
        reply_job = (job or {}).get('manifest', {}).get('operation') == 'discord.reply'
        permission_column = 'can_reply' if reply_job else 'can_publish'
        cur.execute(f"SELECT m.role,m.{permission_column} FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, principal))
        member = cur.fetchone()
        return bool(member and Membership.from_row(member[0], **{permission_column: member[1]}).allows('reply' if reply_job else 'approve'))

    def execute_job(self, repository, workspace_id, token, job_id, approval_digest):
        """An authenticated nudge of one existing approval, never a new or forced submission."""
        if (not isinstance(approval_digest, str) or len(approval_digest) != 64
                or set(approval_digest) - set('0123456789abcdef')):
            raise AlphaError('Send the exact stored approval for this post.', 409)
        with repository.transaction(token, workspace_id) as (_, row, principal):
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            if state.get('workspace', {}).get('sample'):
                raise AlphaError('Hosted sample workspaces are read-only.', 403)
            job = find(state.get('phase2', {}).get('jobs', []), job_id)
            require(Membership.from_row(*row[2:7]), 'reply' if job['manifest'].get('operation') == 'discord.reply' else 'approve')
            if job['manifest'].get('platform') not in ('Discord', 'LinkedIn'):
                raise AlphaError('Select an approved Discord or LinkedIn post for this action.', 409)
            if (job['manifest'].get('workspaceId') != workspace_id
                    or approval_digest != job.get('approvalDigest') or approval_digest != digest(job['manifest'])):
                raise AlphaError('This approval changed. Reload the post before continuing.', 409)
            if not self._binding_matches(job) and not self._may_adopt_legacy_hold(job):
                raise AlphaError('Open this approved post in the deployment where it was reviewed.', 409)
        processed = self.step(workspace_id=workspace_id, job_id=job_id, approval_digest=approval_digest,
                              dispatch_principal=principal)
        return {'processed': int(processed), 'execution': 'hosted-worker', 'jobId': job_id}

    def claim(self, *, workspace_id=None, job_id=None, approval_digest=None, dispatch_principal=None, youtube_only=False, exclude_youtube=False, linkedin_only=False, discord_only=False, exclude_discord=False):
        self._ensure_lifecycle()
        with self._lifecycle_lock:
            if self._stopping:
                self.claim_contended = False
                return None
            selected = self._claim(workspace_id=workspace_id, job_id=job_id, approval_digest=approval_digest,
                               dispatch_principal=dispatch_principal, youtube_only=youtube_only,
                               exclude_youtube=exclude_youtube, linkedin_only=linkedin_only,
                               discord_only=discord_only, exclude_discord=exclude_discord)
            if discord_only and not selected:
                self.discord_stats['claimMisses'] += 1
            return selected

    def _claim(self, *, workspace_id=None, job_id=None, approval_digest=None, dispatch_principal=None, youtube_only=False, exclude_youtube=False, linkedin_only=False, discord_only=False, exclude_discord=False):
        self.claim_contended = False
        scoped = any(value is not None for value in (workspace_id, job_id, approval_digest, dispatch_principal))
        if scoped and not all(isinstance(value, str) and value for value in (workspace_id, job_id, approval_digest, dispatch_principal)):
            raise AlphaError('Select one workspace, job and exact approval.', 409)
        if (youtube_only and (exclude_youtube or linkedin_only or discord_only)
                or discord_only and (linkedin_only or exclude_discord)):
            raise AlphaError('Worker platform filters conflict.', 503, code='worker_platform_filter')
        if discord_only and not self.discord_workers:
            return None
        with self.connection_factory() as db:
            with db.cursor() as cur:
                if not discord_only:
                    cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('postriff-worker-v1',0))")
                    if not cur.fetchone()[0]:
                        self.claim_contended = True
                        self.discord_stats['contention'] += 1
                        return None
                cur.execute("SELECT to_regclass('public.pr_worker_tenants')")
                capacity_ready = cur.fetchone()[0] is not None
                self.capacity_intervention = None if capacity_ready else {
                    'code': 'youtube_capacity_schema', 'youtubeDispatch': 'paused',
                    'message': 'YouTube dispatch requires reviewed migration 097. No YouTube provider request is sent; other platforms continue.',
                    'nextAction': 'Review and apply migration 097, then verify admission and worker execution.'}
                if discord_only and not capacity_ready:
                    self.capacity_intervention = {'code': 'discord_worker_cursor_schema', 'discordDispatch': 'paused',
                        'message': 'Discord parallel dispatch requires the existing reviewed worker cursor schema.'}
                    return None
                # A founder account block freezes the workspace like a pending deletion; lifting it resumes the same jobs.
                # Select only tenants with due work, oldest dispatch first. The
                # durable cursor survives cron/worker restarts; a busy tenant
                # cannot monopolize every chunk lease by sorting before others.
                from .youtube.operations import schema_ready
                indexed = not scoped and youtube_only and capacity_ready and schema_ready(cur)
                if discord_only and not scoped:
                    candidates = self._discord_candidates(cur)
                elif scoped:
                    cur.execute("SELECT id::text,revision,state FROM public.pr_workspaces WHERE state ? 'phase2' AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock' AND id=%s FOR UPDATE SKIP LOCKED", (workspace_id,))
                    candidates = cur.fetchall()
                else:
                    cur.execute(due_workspaces_sql(capacity_ready, youtube_only=youtube_only, exclude_youtube=exclude_youtube,
                                                  operations_ready=indexed, linkedin_only=linkedin_only,
                                                  exclude_discord=exclude_discord), (self.clock(), self.clock()))
                    candidates = cur.fetchall()
                for candidate in candidates:
                    if indexed:
                        workspace_id, revision = candidate
                        # The selector owns the row lock. Fetch only the state
                        # considered for this claim, rather than 100 histories.
                        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace_id,))
                        row = cur.fetchone()
                        if not row:
                            continue
                        raw_state = row[0]
                    else:
                        workspace_id, revision, raw_state = candidate
                    state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
                    # Projections are selection hints, never account authority.
                    if not state.get('phase2') or 'accountDeletion' in state or 'accountBlock' in state:
                        continue
                    original = json.dumps(state, sort_keys=True)
                    if scoped:
                        target = find(state['phase2']['jobs'], job_id)
                        if not self._requester_may_approve(cur, workspace_id, dispatch_principal, target):
                            raise AlphaError('This action needs the permission for its approved operation.', 403)
                        if (target['manifest'].get('workspaceId') != workspace_id
                                or approval_digest != target.get('approvalDigest')
                                or approval_digest != digest(target['manifest'])):
                            raise AlphaError('This approval changed. Reload the post before continuing.', 409)
                    else:
                        if youtube_only or exclude_youtube or linkedin_only or discord_only or exclude_discord:
                            # Invalidation can hold jobs too; isolated lanes must
                            # not mutate another platform's approval or queued job.
                            data = state['phase2']
                            jobs, reviews = data['jobs'], data['reviews']
                            def selected_platform(item):
                                platform = item.get('manifest', {}).get('platform')
                                if discord_only:
                                    return platform == 'Discord'
                                if exclude_discord and platform == 'Discord':
                                    return False
                                if linkedin_only:
                                    return platform == 'LinkedIn'
                                match = platform == 'YouTube'
                                return match if youtube_only else not match if exclude_youtube else True
                            data['jobs'] = [job for job in jobs if selected_platform(job)]
                            data['reviews'] = [review for review in reviews if selected_platform(review)]
                            try:
                                self._invalidate_owned(state)
                            finally:
                                data['jobs'], data['reviews'] = jobs, reviews
                        else:
                            self._invalidate_owned(state)
                    selected = None
                    for job in sorted(state["phase2"]["jobs"], key=lambda item: item.get('lastDispatchedAt', 0)):
                        if scoped and job.get('id') != job_id:
                            continue
                        is_youtube = job.get('manifest', {}).get('platform') == 'YouTube'
                        is_discord = job.get('manifest', {}).get('platform') == 'Discord'
                        if ((youtube_only and not is_youtube) or (exclude_youtube and is_youtube)
                                or (linkedin_only and job.get('manifest', {}).get('platform') != 'LinkedIn')
                                or (discord_only and not is_discord) or (exclude_discord and is_discord)):
                            continue
                        adopt_legacy = scoped and self._may_adopt_legacy_hold(job)
                        if not self._binding_matches(job) and not adopt_legacy:
                            if scoped:
                                raise AlphaError('Open this approved post in the deployment where it was reviewed.', 409)
                            continue
                        discord_managed = is_discord and (self.discord_workers or discord_worker.managed(job))
                        now = self._db_now(cur) if discord_managed else self.clock()
                        if job.get("leaseUntil", 0) > now or job.get("nextAt", 0) > now or job.get("state") in TERMINAL:
                            continue
                        if discord_managed:
                            if not capacity_ready:
                                self._event(job, 'held', 'Discord worker cursor schema is unavailable; dispatch paused', at=now)
                                continue
                            if discord_worker.in_flight(state['phase2']['jobs'], now, excluding=job['id']):
                                continue
                            recovery = discord_worker.recovery(job, now)
                            if recovery == 'unsent':
                                status = discord_worker.release_unsent(job, now, 'lease_expired')
                                self._event(job, status, 'Expired Discord fence was provably unsent; bounded recovery recorded', at=now)
                                self.discord_stats['recoveries'] += 1
                                self.discord_stats['deadLetters' if status == 'failed' else 'retries'] += 1
                                continue
                            if recovery == 'reconcile':
                                self._event(job, 'uncertain', 'Expired Discord intent requires reconciliation; never repost', at=now)
                        release_hold = scoped and (self._preview_hold(job) or adopt_legacy)
                        if job.get('state') == 'held' and not release_hold:
                            continue
                        if job['manifest'].get('platform') == 'Discord' and not job.get('providerReference'):
                            from .discord.authorization import digest as discord_digest
                            # A late receipt is evidence, not ownership of a newer lease.
                            for receipt in reversed(job.get('discordReceipts', [])):
                                if (receipt.get('reference') and receipt.get('publicationId') == job['id']
                                        and receipt.get('manifestDigest') == discord_digest(job['manifest'])
                                        and receipt.get('authorizationDigest') == job.get('discordAuthorization', {}).get('digest')):
                                    job['providerReference'] = receipt['reference']
                                    self._event(job, 'uncertain', 'Late Discord receipt retained; reconcile the original channel without resubmission')
                                    break
                        if scoped and job.get('providerReference') and job.get('state') not in IN_FLIGHT:
                            self._event(job, 'uncertain', 'Known provider receipt retained; reconcile without creating another post')
                        stage = job.get('progress', {}).get('stage')
                        from .official_publishers import ASYNC_PLATFORMS, FORWARD_STAGES
                        official = (job['manifest']['platform'] in ASYNC_PLATFORMS and hasattr(self.social, 'official_enabled')
                                    and self.social.official_enabled(job['manifest']))
                        instagram = official or (job['manifest']['platform'] == 'Instagram' and hasattr(self.social, 'advance_instagram'))
                        if instagram and job.get('container') and not stage:
                            self._event(job, 'uncertain', 'Legacy container has no durable stage; reconcile without creating or publishing again')
                        forward = instagram and stage in FORWARD_STAGES and job['state'] == 'processing'
                        youtube_forward = (job['manifest']['platform'] == 'YouTube' and bool(getattr(self.social, 'youtube', None))
                                           and (stage not in ('native_scheduled', 'native_schedule_reconciling') or job.get('cancelRequested')))
                        pinterest_forward = (job['manifest']['platform'] == 'Pinterest'
                                             and isinstance(self.social, HostedSocial)
                                             and job.get('state') not in IN_FLIGHT)
                        if job.get("cancelRequested") and (job.get("state") not in IN_FLIGHT or forward):
                            self._event(job, "held" if job.get('providerThread') else "canceled", "Further thread creation stopped; already-created provider posts remain" if job.get('providerThread') else "Canceled before provider submission")
                            continue
                        if job['manifest']['platform'] == 'YouTube' and not capacity_ready:
                            # Preserve the operation, approval and journal. Once
                            # the schema exists this same due job can resume;
                            # no lease, provider attempt or replacement is made.
                            if not job.get('capacityIntervention'):
                                self._event(job, job['state'], self.capacity_intervention['message'])
                            job['capacityIntervention'] = dict(self.capacity_intervention)
                            job['nextAction'] = self.capacity_intervention['nextAction']
                            job['nextAt'] = now + 60
                            continue
                        job.pop('capacityIntervention', None)
                        if job.get("state") == "submitting":
                            self._event(job, "uncertain", "Worker lease expired after submission started; reconcile before retry")
                        reconciliation = job.get("state") in IN_FLIGHT and not forward
                        linkedin_reverify = False
                        if job['manifest']['platform'] == 'LinkedIn' and not reconciliation:
                            try:
                                channel = find(state['phase2']['channels'], job['manifest']['channelId'])
                            except AlphaError:
                                self._event(job, 'held', 'LinkedIn connection is unavailable; a new review is required')
                                continue
                            linkedin_reverify = self.commands.engine.channel_reverification_due(channel)
                        authority_options = {'allow_reverification': True} if linkedin_reverify else {}
                        if is_discord and not reconciliation and not self._approved(cur, workspace_id, state, job, now=now):
                            self._event(job, 'held', 'Discord needs a current human approval bound to this exact destination and content')
                            continue
                        if (forward or (scoped and not reconciliation)) and not self._approved(cur, workspace_id, state, job, now=now, **authority_options):
                            self._event(job, 'held', 'Approval, account, media, timing or permission changed; a new review is required')
                            continue
                        if not reconciliation:
                            from .billing import require_publishing
                            try:
                                require_publishing(cur, workspace_id, now)
                                assert_job_authority(state, job, now)
                            except AlphaError as error:
                                self._event(job, "held", str(error))
                                continue
                            reply_job = job['manifest'].get('operation') == 'discord.reply'
                            permission_column = 'can_reply' if reply_job else 'can_publish'
                            cur.execute(f"SELECT m.role,m.{permission_column} FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job['approvedBy']))
                            member = cur.fetchone()
                            # Re-authorize at claim time: the approver must still hold approve authority.
                            if (not member or not Membership.from_row(member[0], **{permission_column: member[1]}).allows("reply" if reply_job else "approve")
                                    or (job.get('youtubeAgent') and member[0] != 'owner')
                                    or job['approvalDigest'] != digest(job['manifest'])
                                    or job['approvedBy'] != job['manifest']['actor']):
                                self._event(job, 'held', 'Approval authority changed; a new review is required')
                                continue
                        attempts = discord_worker.attempt_count(job) if discord_managed else len(job.get('attempts', []))
                        if not reconciliation and not forward and attempts >= 3:
                            self._event(job, "failed", "Bounded retry limit reached")
                            if discord_managed:
                                job.setdefault(discord_worker.KEY, {'version': 1})['deadLetter'] = {
                                    'at': now, 'reason': 'pre_handoff_exhausted', 'attempts': attempts}
                                self.discord_stats['deadLetters'] += 1
                            from . import product_events
                            product_events.publish_outcome(cur, workspace_id, job, "failed")
                            continue
                        if release_hold:
                            if adopt_legacy:
                                # Retain the original exact manifest/digest and attempt history.
                                # The requester authorizes this server-owned deployment binding now.
                                job['workerBinding'] = copy.deepcopy(self.worker_binding)
                            job.pop('previewDispatchPending', None)
                            self._event(job, 'scheduled', 'Approved preview post released by the authenticated exact-job worker action')
                        youtube_generation = None
                        if is_youtube:
                            from .youtube import workspace_provider_data as youtube_data
                            cur.execute("SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR NO KEY UPDATE",
                                        (workspace_id, job['manifest'].get('channelId')))
                            credential = cur.fetchone()
                            youtube_generation = credential[0] if credential else None
                            prior_source = job.get(youtube_data.KEY) if isinstance(job.get(youtube_data.KEY), dict) else {}
                            if (not youtube_generation or job.get(youtube_data.REMOVED)
                                    or (prior_source and prior_source.get('authorizationGeneration') != youtube_generation)):
                                youtube_data.scrub_job(job, 'youtube_authorization_data_removed', now)
                                continue
                        previous_state = job['state']
                        if discord_managed:
                            now = self._db_now(cur)
                            if not reconciliation and job['manifest']['expiresAt'] <= now:
                                self._event(job, 'held', 'Discord approval expired during claim checks; a new review is required', at=now)
                                continue
                        job["leaseOwner"] = self.worker_id
                        job["leaseUntil"] = min(now + discord_worker.LEASE_SECONDS, job['manifest']['expiresAt']) if discord_managed and not reconciliation else now + 45
                        job["leaseId"] = uuid.uuid4().hex
                        job['lastDispatchedAt'] = now
                        if reconciliation:
                            job["checks"] = job.get("checks", 0) + 1
                        elif not forward:
                            self._event(job, "claimed", "Hosted worker acquired the fenced lease")
                            if not youtube_forward and not pinterest_forward and not linkedin_reverify:
                                job.setdefault("attempts", []).append({"number": len(job.get("attempts", [])) + 1, "startedAt": now, "idempotencyKey": job["manifest"]["idempotencyKey"]})
                                self._event(job, "submitting", "Hosted worker began the approved provider operation")
                        if discord_managed:
                            discord_worker.begin(job, now, reconciliation)
                        selected = {"workspaceId": workspace_id, "job": copy.deepcopy(job), "reconciliation": reconciliation}
                        if scoped:
                            selected['dispatchPrincipal'] = dispatch_principal
                        if official and reconciliation and job.get('cancelRequested') and job['manifest'].get('nativeScheduleAt') and job.get('providerReference'):
                            if job.get('progress', {}).get('stage') != 'cancel_attempted':
                                job['progress'] = {'version': 1, 'stage': 'cancel_attempted'}
                                selected.update(job=copy.deepcopy(job), nativeCancel=True)
                        if is_youtube:
                            selected['youtubeAuthorizationGeneration'] = youtube_generation
                        if youtube_forward:
                            selected.update(youtubeForward=True, previousState=previous_state)
                        if pinterest_forward:
                            selected.update(pinterestForward=True, previousState=previous_state)
                        if linkedin_reverify:
                            selected.update(linkedinForward=True, previousState=previous_state)
                        if instagram and not reconciliation:
                            action = 'status' if stage in ('container_created', 'children_created', 'assets_uploaded') else 'parent' if stage == 'children_ready' else 'publish' if stage in ('container_ready', 'thread_ready') else 'upload' if stage == 'upload_session' else 'finalize' if stage == 'upload_finalizable' else 'metadata' if stage == 'metadata_pending' else 'create'
                            if action != 'status' and not linkedin_reverify:
                                job['progress'] = {'version': 1, 'stage': action + '_attempted'}
                                self._event(job, 'submitting', 'Durable provider ' + action + ' intent recorded')
                            selected.update(job=copy.deepcopy(job), instagramAction=action, officialAction=official)
                        break
                    if discord_only or selected and discord_worker.managed(selected['job']):
                        state['phase2'][discord_worker.CURSOR] = {'version': 1, 'lastClaimedAt': self._db_now(cur)}
                    if selected or json.dumps(state, sort_keys=True) != original:
                        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), workspace_id, revision))
                        if cur.rowcount != 1:
                            raise AlphaError("Worker claim lost its workspace revision.", 409)
                    if selected:
                        if capacity_ready:
                            cur.execute('''INSERT INTO public.pr_worker_tenants(workspace_id,last_claimed_at) VALUES(%s,to_timestamp(%s))
                                ON CONFLICT(workspace_id) DO UPDATE SET last_claimed_at=excluded.last_claimed_at''', (workspace_id, now))
                        if selected['job']['manifest'].get('platform') == 'Discord':
                            self.discord_stats['claims'] += 1
                        return selected
        return None

    def complete(self, claimed, result):
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (claimed["workspaceId"],))
                row = cur.fetchone()
                if not row:
                    return False
                revision, raw_state = row
                state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
                job = find(state["phase2"]["jobs"], claimed["job"]["id"])
                now = self._lease_now(cur, job)
                owns_lease = self._owns(job, claimed, now)
                # Legacy non-Discord completion may carry only job/lease IDs.
                # Either Discord snapshot still requires receipt fencing.
                if (job.get('manifest', {}).get('platform') == 'Discord'
                        or claimed['job'].get('manifest', {}).get('platform') == 'Discord'):
                    if not isinstance(claimed['job'].get('manifest'), dict):
                        return False
                    from .discord.authorization import record_receipt
                    evidence = normalize_result(result, claimed['job'], claimed['reconciliation'])
                    if record_receipt(job, claimed, evidence, now, not owns_lease) and not owns_lease:
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                                    (json.dumps(state), claimed['workspaceId'], revision))
                if not owns_lease:
                    return False
                youtube_source = None
                if job.get('manifest', {}).get('platform') == 'YouTube':
                    from .youtube import workspace_provider_data as youtube_data
                    try:
                        generation = youtube_data.assert_completion(cur, claimed['workspaceId'], job, claimed, now)
                        youtube_source = youtube_data.source(claimed['workspaceId'], job, generation, now)
                        if youtube_source['expiresAt'] <= now:
                            raise AlphaError('The previous YouTube runtime output expired.', 409, code='youtube_stale_completion')
                    except AlphaError:
                        youtube_data.scrub_job(job, 'youtube_stale_result_removed', now)
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                                    (json.dumps(state), claimed['workspaceId'], revision))
                        return False
                defer_pinterest_budget(job, result, claimed['reconciliation'])
                result = normalize_result(result, job, claimed['reconciliation'])
                if result.get('discordReadDeferred') is True:
                    # A provider429 DID spend a GET. Only the private signal
                    # minted before HTTP can refund a verification check.
                    if result.get('discordReadAdmissionDenied') is True:
                        job['checks'] = max(0, job.get('checks', 0) - 1)
                    job['discordReadDeferrals'] = job.get('discordReadDeferrals', 0) + 1
                self._event(job, result["state"], result["confirmed"], at=now)
                if discord_worker.managed(job):
                    job[discord_worker.KEY]['stage'] = 'done'
                    if (result['state'] == 'held' and result.get('discordDeliveryEvidence') in ('not_sent', 'rejected')
                            and result.get('discordRateLimited') is not True):
                        self._hold_discord_destination(state, job, now)
                if result.get("reference"):
                    job["providerReference"] = result["reference"]
                if "providerUpload" in result:
                    job["providerUpload"] = result["providerUpload"]
                if "providerAssets" in result:
                    job["providerAssets"] = result["providerAssets"]
                for key in ('providerThread', 'threadChecked'):
                    if key in result: job[key] = result[key]
                job["providerConfirmed"] = result["confirmed"]
                if result.get('visibility'):
                    job['providerVisibility'] = result['visibility']
                job["verification"] = {"method": result.get("verification"), "at": now if job['manifest'].get('platform') == 'Discord' else self.clock()} if result["state"] == "verified" else None
                if result.get("container"):
                    job["container"] = result["container"]
                if result.get("url"):
                    job["url"] = result["url"]
                job['resultSchema'] = result.get('schema')
                if result.get('progress'):
                    job['progress'] = result['progress']
                if youtube_source is not None:
                    job[youtube_data.KEY] = youtube_source
                published = result['state'] == 'verified' and (job['manifest']['platform'] != 'YouTube' or (result.get('progress') or {}).get('stage') == 'published')
                if published and self.on_verified:
                    try:
                        self.on_verified(cur, claimed["workspaceId"], job)
                    except Exception:
                        job["insights"] = {"availability": "unavailable", "note": "Insights ingestion failed; publication verification is unaffected."}
                if published:
                    # Learning signal (ids and numbers only); a failure to record never affects the publication.
                    record_published(cur, claimed["workspaceId"], job, now)
                if result["state"] in ("verified", "failed"):
                    from . import product_events
                    # Product taxonomy (PRD §8.6): publish.verified|failed behind its own savepoint; never affects the job.
                    product_events.publish_outcome(cur, claimed["workspaceId"], job, result["state"])
                if job.get("attempts") and not claimed["reconciliation"]:
                    job["attempts"][-1]["endedAt"] = now
                job["leaseOwner"], job["leaseUntil"] = None, 0
                job["nextAt"] = now + (60 if result["state"] in ('scheduled', 'processing') else 5)
                if result.get('retryAfterSeconds'):
                    job['nextAt'] = now + result['retryAfterSeconds']
                youtube_progress = job['manifest']['platform'] == 'YouTube' and (result.get('progress') or {}).get('version') == 2
                if youtube_progress:
                    progress = result['progress']
                    retry_at = progress.get('retryAt')
                    job['nextAt'] = max(now + 1, retry_at) if isinstance(retry_at, (int, float)) else now + 60
                    if progress.get('stage') == 'native_scheduled':
                        job['nextAt'] = now + 300
                    job['nextAction'] = 'Reconcile the existing YouTube session or immutable Video ID; never re-upload this operation'
                if result['state'] == 'processing':
                    job['processingChecks'] = job.get('processingChecks', 0) + 1
                    if job['processingChecks'] >= (20 if getattr(self.social, 'official_enabled', lambda _: False)(job.get('manifest') or {}) else 6) and job.get('progress', {}).get('stage') in ('container_created', 'children_created', 'assets_uploaded'):
                        self._event(job, 'held', 'Container processing did not finish within bounded checks; review before continuing')
                if result['state'] == 'native_scheduled':
                    job['nextAt'] = max(now+60, job['manifest']['nativeScheduleAt'])
                if job.get("checks", 0) >= 5 and job["state"] in IN_FLIGHT and job['state'] != 'native_scheduled' and not youtube_progress:
                    job["nextAt"] = now + 86400
                    job["nextAction"] = "Manual provider review required; do not resubmit"
                elif job["state"] == "held":
                    job["nextAction"] = ('Discord returned 429; keep this publication held until shared cooldown and explicit human review'
                                         if job['manifest']['platform'] == 'Discord' and result.get('discordRateLimited') is True else
                                         'Review the frozen Discord destination, permission and rollout status; obtain a fresh approval if needed'
                                         if job['manifest']['platform'] == 'Discord' else 'Review provider permission and configuration')
                elif job["state"] == "failed":
                    job["nextAction"] = "Correct the cause and create a new exact approval"
                elif job["state"] in TERMINAL:
                    job["nextAction"] = "Inspect receipt"
                else:
                    job["nextAction"] = "Await container processing; not published" if job['state'] == 'processing' else "Await provider reconciliation; do not resubmit"
                if result.get('retryAfterSeconds'):
                    job['nextAction'] = 'Await LinkedIn retry backoff; the same approval and bounded retry limit apply'
                if youtube_progress and progress.get('stage') == 'quota_delayed':
                    job['nextAction'] = 'Publishing delayed by capacity controls; the same approved upload resumes after retryAt. Review the time if approval or publication time expires.'
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), claimed["workspaceId"], revision))
                return cur.rowcount == 1

    def authorize_dispatch(self, claimed, *, youtube_verified=False, pinterest_verified=False, linkedin_verified=False):
        """Re-read cancellation, exact approval and fence immediately before forward work."""
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
                row = cur.fetchone()
                if not row:
                    return False
                state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                job = find(state['phase2']['jobs'], claimed['job']['id'])
                now = self._lease_now(cur, job)
                if not self._owns(job, claimed, now):
                    return False
                if self._stopping and discord_worker.managed(job):
                    if discord_worker.pending_unsent(job) and job.get('state') in ('claimed', 'submitting'):
                        status = discord_worker.release_unsent(job, now, 'shutdown')
                        self._event(job, status, 'Shutdown released proven unsent Discord work', at=now)
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                                    (json.dumps(state), claimed['workspaceId']))
                        self.discord_stats['shutdownReleased'] += 1
                    return False
                if job.get('state') in (*TERMINAL, 'held'):
                    # Disconnect/cancellation may have ended a claimed operation
                    # while verification was in flight. A later reconnect never
                    # makes that same stale worker's lease a fresh approval.
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                if job.get('manifest', {}).get('platform') == 'YouTube':
                    from .youtube import workspace_provider_data as youtube_data
                    try:
                        youtube_data.assert_completion(cur, claimed['workspaceId'], job, claimed, self.clock())
                    except AlphaError:
                        youtube_data.scrub_job(job, 'youtube_stale_result_removed', self.clock())
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                        return False
                youtube_cancel = (claimed.get('youtubeForward') and claimed['reconciliation']
                                  and claimed['job'].get('cancelRequested') is True)
                if (claimed.get('youtubeForward') and claimed['reconciliation']
                        and job.get('cancelRequested') and not youtube_cancel):
                    # The claimed copy would continue uploading. Release this fence
                    # so the next reconciliation observes the pending cancellation.
                    self._event(job, job['state'], 'Cancellation changed during verification; reconcile a fresh fenced snapshot')
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    job['nextAt'] = self.clock() + 1
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                requester_allowed = (not claimed.get('dispatchPrincipal') or self._requester_may_approve(cur, claimed['workspaceId'], claimed['dispatchPrincipal'], job))
                if (not requester_allowed or not self._binding_matches(job)
                        or (job.get('cancelRequested') and not youtube_cancel)
                        or (claimed.get('youtubeForward') and not youtube_verified)
                        or (claimed.get('linkedinForward') and not linkedin_verified)
                        or (claimed.get('pinterestForward') and not pinterest_verified)
                        or (claimed.get('dispatchPrincipal') and not self._requester_may_approve(cur, claimed['workspaceId'], claimed['dispatchPrincipal'], job))
                        or not self._approved(cur, claimed['workspaceId'], state, job, now=now)):
                    # No call has been made by this fenced dispatch. Preserve any prior container.
                    stopped = 'canceled' if job.get('cancelRequested') and not claimed['reconciliation'] else 'held'
                    self._event(job, stopped, 'Stopped before provider dispatch; cancellation or approval changed')
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                if (claimed.get('youtubeForward') or claimed.get('pinterestForward') or claimed.get('linkedinForward')) and not claimed['reconciliation']:
                    job.setdefault('attempts', []).append({'number': len(job.get('attempts', [])) + 1,
                        'startedAt': self.clock(), 'idempotencyKey': job['manifest']['idempotencyKey']})
                    if claimed.get('linkedinForward') and claimed.get('instagramAction') not in (None, 'status'):
                        job['progress'] = {'version': 1, 'stage': claimed['instagramAction'] + '_attempted'}
                    self._event(job, 'submitting', 'Hosted worker began the approved provider operation')
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    claimed['job'] = copy.deepcopy(job)
                if job['manifest'].get('platform') == 'Discord':
                    return self._seal_discord_dispatch(cur, state, job, claimed)
                return True

    def _seal_discord_dispatch(self, cur, state, job, claimed):
        """Linearization point under workspace -> credential locks. No provider IO.

        Once this intent commits, expiry/recovery may only reconcile it. A
        revocation before this transaction blocks; an already transmitted POST
        cannot be recalled by a later edit or disconnect.
        """
        from .discord.authorization import digest as discord_digest, job_authorized
        from .discord.rate_limits import publish_binding, RateCoordinatorUnavailable, RateDelayed
        prepared = claimed.get('discordPrepared') or {}
        manifest = job['manifest']
        channel = find(state['phase2']['channels'], manifest['channelId'])
        now = self._lease_now(cur, job)
        if (not job_authorized(state, channel, job, now=now)
                or prepared.get('manifestDigest') != discord_digest(manifest)
                or prepared.get('wireDigest') != manifest['discord']['wireDigest']):
            self._event(job, 'held', 'Discord approval or preflight changed before the final handoff; nothing was posted')
            job['leaseOwner'], job['leaseUntil'] = None, 0
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                        (json.dumps(state), claimed['workspaceId']))
            return False
        intents = job.setdefault('discordDispatchIntents', [])
        if intents:
            # P0 has no automatic Discord re-POST path, even after a definite
            # rejection. Fix the cause and issue a new human approval instead.
            self._event(job, 'uncertain', 'Discord dispatch intent already exists; reconcile without resubmission')
            job['leaseOwner'], job['leaseUntil'] = None, 0
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                        (json.dumps(state), claimed['workspaceId']))
            return False
        try:
            grant = self._current_discord_grant(cur, claimed['workspaceId'], job)
            if prepared.get('grant', {}).get('authorizationGeneration') != grant['authorizationGeneration']:
                raise AlphaError('Discord connection changed before dispatch.', 409)
        except AlphaError:
            self._event(job, 'held', 'Discord connection changed before dispatch; a new approval is required')
            job['leaseOwner'], job['leaseUntil'] = None, 0
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                        (json.dumps(state), claimed['workspaceId']))
            return False
        now = self._lease_now(cur, job)
        if discord_worker.managed(job):
            if self._stopping or not self._owns(job, claimed, now) or manifest['expiresAt'] < now:
                self.discord_stats['leaseLost'] += 1
                return False
            job['leaseUntil'] = min(now + discord_worker.LEASE_SECONDS, manifest['expiresAt'])
        intent = {'id': job['leaseId'], 'publicationId': job['id'], 'manifestDigest': discord_digest(manifest),
                  'authorizationDigest': job['discordAuthorization']['digest'],
                  'authorizationGeneration': grant['authorizationGeneration'], 'at': now}
        provider = getattr(self.social,'providers',{}).get('discord')
        if getattr(provider,'rate_v1_enabled',False):
            binding = publish_binding(job,claimed['workspaceId'],self.worker_id)
            try:
                provider.rate_limiter.seal(cur,prepared.get('ratePermit'),binding,intent['id'],
                                          min(job['leaseUntil'],manifest['expiresAt']))
            except RateDelayed as error:
                operation = job.get(discord_worker.KEY) or {}
                if (discord_worker.managed(job) and discord_worker.pending_unsent(job)
                        and operation.get('ratePermitRetries',0) < discord_worker.MAX_UNCONSUMED_PERMIT_RECOVERIES):
                    operation['ratePermitRetries'] = operation.get('ratePermitRetries',0) + 1
                    status = discord_worker.release_unsent(job, now, 'rate_delayed',
                        retry_after_seconds=error.retry_after_seconds)
                    self._event(job, status, 'Discord rate permit expired before intent; frozen approval waits without a POST', at=now)
                    self.discord_stats['rateDelays'] += 1
                else:
                    self._event(job,'held','Discord pre-intent permit recovery limit reached; nothing was posted',at=now)
                    job['leaseOwner'],job['leaseUntil'] = None,0
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                            (json.dumps(state),claimed['workspaceId']))
                return False
            except RateCoordinatorUnavailable:
                self._event(job,'held','Discord rate permit expired or changed before sealing; nothing was posted',at=now)
                job['leaseOwner'],job['leaseUntil'] = None,0
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                            (json.dumps(state),claimed['workspaceId']))
                return False
            intent['rateAdmissionId'] = prepared['ratePermit'].id
            prepared['rateBinding'] = binding
            prepared['rateAuthorize'] = lambda cursor: self._authorize_discord_rate_send(cursor,claimed,intent,binding)
        if discord_worker.managed(job):
            job[discord_worker.KEY].update(stage='sealed', sealedAt=now)
        intents.append(intent)
        if job.get('attempts'):
            job['attempts'][-1]['discordIntentId'] = intent['id']
        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                    (json.dumps(state), claimed['workspaceId']))
        # Only the sanitized intent enters durable state. The credential and
        # verified media bytes stay in this worker's private in-memory handoff.
        claimed['discordIntent'] = copy.deepcopy(intent)
        claimed['discordDispatch'] = {**prepared, 'grant': grant, 'intent': copy.deepcopy(intent)}
        claimed['job'] = copy.deepcopy(job)
        return True

    def _authorize_discord_rate_send(self, cur, claimed, intent, binding):
        """Post-commit live workspace/credential guard, before permit consumption.

        The coordinator takes the admission lock only after this guard. No
        rate-scope locks or provider calls occur while this workspace is locked.
        """
        from .discord.rate_limits import publish_binding, RateCoordinatorUnavailable
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(claimed['workspaceId'],))
        row = cur.fetchone()
        if not row:
            raise RateCoordinatorUnavailable()
        state = json.loads(row[0]) if isinstance(row[0],str) else row[0]
        job = find(state.get('phase2',{}).get('jobs',[]),claimed['job']['id'])
        now = self._db_now(cur)
        if (self._stopping or not self._owns(job,claimed,now) or job.get('cancelRequested')
                or job.get('state') not in ('claimed','submitting') or not self._binding_matches(job)
                or publish_binding(job,claimed['workspaceId'],self.worker_id) != binding
                or not any(i == intent for i in job.get('discordDispatchIntents',[]))
                or not self._approved(cur,claimed['workspaceId'],state,job,now=now)
                or claimed.get('dispatchPrincipal') and not self._requester_may_approve(cur,claimed['workspaceId'],claimed['dispatchPrincipal'],job)):
            raise RateCoordinatorUnavailable()
        self._current_discord_grant(cur,claimed['workspaceId'],job)
        now = self._db_now(cur)  # credential/member lock waits cannot revive an expired fence
        if not self._owns(job,claimed,now) or job['manifest']['expiresAt'] <= now:
            raise RateCoordinatorUnavailable()
        return min(job['leaseUntil'],job['manifest']['expiresAt'])

    def release_discord_expired_permit(self, claimed, error):
        """Recover only this live worker's conclusively unconsumed rate permit."""
        from .discord.rate_limits import UnconsumedPublishPermit
        prepared = claimed.get('discordPrepared') or {}
        permit, binding, intent = prepared.get('ratePermit'), prepared.get('rateBinding'), claimed.get('discordIntent')
        if (not isinstance(error, UnconsumedPublishPermit) or not permit or error.permit_id != permit.id
                or not binding or not intent):
            return False
        provider = getattr(self.social, 'providers', {}).get('discord')
        with self.connection_factory() as db, db.cursor() as cur:
            # Reuse the final live approval/member/grant/lease guard and its
            # workspace -> credential lock order before locking the admission.
            self._authorize_discord_rate_send(cur, claimed, intent, binding)
            cur.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
            row = cur.fetchone()
            revision, raw_state = row
            state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
            job = find(state['phase2']['jobs'], claimed['job']['id'])
            if (job.get('discordDispatchIntents') != [intent] or not discord_worker.managed(job)
                    or job[discord_worker.KEY].get('stage') != 'sealed'
                    or job[discord_worker.KEY].get('ratePermitRetries', 0) >= discord_worker.MAX_UNCONSUMED_PERMIT_RECOVERIES
                    or not any(a.get('discordIntentId') == intent['id'] for a in job.get('attempts', []))
                    or any(job.get(k) for k in ('discordReceipts','providerReference','container',
                        'providerUpload','providerAssets','providerThread','progress','url','verification'))):
                return False
            provider.rate_limiter.abandon_expired_publish(cur, permit, binding, intent['id'])
            now = self._db_now(cur)
            if not self._owns(job, claimed, now) or job['manifest']['expiresAt'] <= now:
                raise AlphaError('Discord authority expired during unsent recovery.', 409)
            job.setdefault('discordUnsentDispatches', []).append({**intent,
                'unsentProof': 'expired_unconsumed_admission', 'abandonedAt': now})
            job['discordDispatchIntents'] = []
            for attempt in job.get('attempts', []):
                if attempt.get('discordIntentId') == intent['id']:
                    attempt['discordUnsentIntentId'] = attempt.pop('discordIntentId')
            job[discord_worker.KEY]['stage'] = 'pending'
            job[discord_worker.KEY]['ratePermitRetries'] = job[discord_worker.KEY].get('ratePermitRetries', 0) + 1
            status = discord_worker.release_unsent(job, now, 'rate_delayed',
                retry_after_seconds=error.retry_after_seconds)
            self._event(job, status, 'Expired Discord permit was never consumed; intent archived before safe rate wait', at=now)
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                (json.dumps(state), claimed['workspaceId'], revision))
            if cur.rowcount != 1:
                raise AlphaError('Discord unsent recovery lost its workspace revision.', 409)
        return True

    def defer_youtube_dispatch(self, claimed):
        return self._defer_verified_dispatch(claimed, 'YouTube')

    def _defer_verified_dispatch(self, claimed, platform):
        """Release only this unsent lease; a transient read never consumes a write attempt."""
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
            row = cur.fetchone()
            if not row:
                return False
            state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            job = find(state['phase2']['jobs'], claimed['job']['id'])
            if (job.get('leaseOwner') != self.worker_id or job.get('leaseId') != claimed['job'].get('leaseId')
                    or job.get('leaseUntil', 0) <= self.clock()):
                return False
            if job['state'] == 'claimed':
                platform = job['manifest']['platform']
                self._event(job, claimed['previousState'], f'{platform} verification unavailable; no provider operation was sent')
            job['leaseOwner'], job['leaseUntil'] = None, 0
            job['nextAt'] = self.clock() + 60
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
            return True

    def _discord_reply_read_guard(self, claimed, *, reconciliation=False):
        """No provider read after withdrawal, role loss or a changed installation.

        The live lease, DB clock and credential-origin fence are rechecked at
        each GET, including permission preflight and known-receipt reconciliation.
        A canceled or revoked unknown delivery is retained for manual review.
        """
        def authorize():
            from .discord.authorization import job_authorized
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
                row = cur.fetchone()
                if not row:
                    raise AlphaError('Discord reply workspace is unavailable.', 409)
                state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                job = find(state.get('phase2', {}).get('jobs', []), claimed['job']['id'])
                now = self._db_now(cur)
                channel = find(state['phase2']['channels'], job['manifest']['channelId'])
                if (self._stopping or state.get('accountDeletion') or state.get('accountBlock')
                        or job.get('privacyErased') or job.get('cancelRequested')
                        or not self._owns(job, claimed, now) or not self._binding_matches(job)
                        or not job_authorized(state, channel, job, now=now)
                        or not self._requester_may_approve(cur, claimed['workspaceId'], job['approvedBy'], job)):
                    raise AlphaError('Discord reply consent or permission changed.', 409)
                self._current_discord_grant(cur, claimed['workspaceId'], job)
                from .security_holds import assert_clear
                assert_clear(cur, job['approvedBy'], authorized_at=job['approvedAt'])
                if not reconciliation and not self._approved(cur, claimed['workspaceId'], state, job, now=self._db_now(cur)):
                    raise AlphaError('Discord reply approval changed.', 409)
                if not self._owns(job, claimed, self._db_now(cur)):
                    raise AlphaError('Discord reply lease expired during read authorization.', 409)
            return True
        return authorize

    def step(self, crash=None, *, workspace_id=None, job_id=None, approval_digest=None, dispatch_principal=None, youtube_only=False, exclude_youtube=False, linkedin_only=False, discord_only=False, exclude_discord=False):
        scope = (workspace_id, job_id, approval_digest, dispatch_principal)
        claimed = self.claim(workspace_id=workspace_id, job_id=job_id, approval_digest=approval_digest, dispatch_principal=dispatch_principal, youtube_only=youtube_only, exclude_youtube=exclude_youtube, linkedin_only=linkedin_only, discord_only=discord_only, exclude_discord=exclude_discord) if any(value is not None for value in scope) or youtube_only or exclude_youtube or linkedin_only or discord_only or exclude_discord else self.claim()
        if not claimed or crash == "after_claim":
            return bool(claimed)
        if claimed['job']['manifest'].get('platform') == 'Discord' and not claimed['reconciliation']:
            managed = discord_worker.managed(claimed['job'])
            if managed and self._stopping:
                self.release_discord_unsent(claimed)
                return True
            try:
                from .discord.rate_limits import RateDelayed, RateCoordinatorUnavailable
                read_options = ({'read_authorize': self._discord_reply_read_guard(claimed)}
                                if claimed['job']['manifest'].get('operation') == 'discord.reply' else {})
                claimed['discordPrepared'] = self.social.prepare_discord_dispatch(claimed['job']['manifest'], **read_options)
                # Preflight refreshes an expired linked identity outside SQL locks.
                # The unchanged strict renewal must pass before reserving any
                # publish permit; final authorization still rechecks every fence.
                if managed and not self.renew_discord_lease(claimed):
                    return True
                # P4: reserve shared bot capacity BEFORE the P0 durable intent.
                # Denied budget is proven unsent and must not consume an attempt.
                claimed['discordPrepared']['ratePermit'] = self.social.reserve_discord_send(
                    claimed['job']['manifest'],job=claimed['job'],workspace_id=claimed['workspaceId'],worker_id=self.worker_id)
            except Exception as error:
                if managed and isinstance(error, (RateDelayed, RateCoordinatorUnavailable)):
                    self.release_discord_unsent(
                        claimed, reason='rate_delayed',
                        retry_after_seconds=getattr(error, 'retry_after_seconds', 300),
                        rate_cause=getattr(error,'rate_cause',None))
                    return True
                if managed and discord_worker.transient_preflight(error):
                    self.release_discord_unsent(claimed, reason='preflight_transient')
                    return True
                self.complete(claimed, {'state': 'held', 'confirmed': 'Discord destination, grant, media or rollout verification is unavailable. Nothing was posted.',
                                        'discordDeliveryEvidence': 'not_sent'})
                return True
        if claimed.get('linkedinForward'):
            try:
                verification = self.social.oauth.reverify_for_worker(claimed['workspaceId'], claimed['job']['manifest']['channelId'])
            except AlphaError as error:
                verification = {'state': 'reauthorization_required' if error.status == 404 or error.code == 'reauthorization_required' else 'verification_unavailable'}
            if verification.get('state') == 'verification_unavailable':
                self.defer_youtube_dispatch(claimed)
                return True
            verified = verification.get('state') == 'read_verified' and verification.get('ready') is True
            if not self.authorize_dispatch(claimed, linkedin_verified=verified):
                return True
        elif claimed.get('youtubeForward'):
            try:
                verification = self.social.youtube.oauth.reverify_for_worker(claimed['workspaceId'], claimed['job']['manifest']['channelId'])
            except AlphaError as error:
                verification = {'state': 'reauthorization_required' if error.status == 404 or error.code == 'youtube_revoked_oauth' else 'verification_unavailable'}
            if verification.get('state') == 'verification_unavailable':
                self.defer_youtube_dispatch(claimed)
                return True
            verified = verification.get('state') == 'read_verified' and verification.get('ready') is True
            if not self.authorize_dispatch(claimed, youtube_verified=verified):
                return True
        elif claimed.get('pinterestForward'):
            try:
                verification = self.social.oauth.reverify_for_worker(claimed['workspaceId'], claimed['job']['manifest']['channelId'])
            except AlphaError as error:
                verification = {'state': 'reauthorization_required' if error.status == 404 else 'verification_unavailable'}
            except (AttributeError, OSError, KeyError, TypeError, ValueError):
                verification = {'state': 'verification_unavailable'}
            if verification.get('state') == 'verification_unavailable':
                self._defer_verified_dispatch(claimed, 'Pinterest')
                return True
            verified = verification.get('state') == 'read_verified' and verification.get('ready') is True
            if not self.authorize_dispatch(claimed, pinterest_verified=verified):
                return True
        elif not claimed['reconciliation'] and not self.authorize_dispatch(claimed):
            return True
        if self._stopping and discord_worker.managed(claimed['job']):
            # If intent already committed, retain it for reconciliation even
            # though shutdown stops this process before POST. Never erase it.
            return True
        if (discord_worker.managed(claimed['job']) and not claimed['reconciliation']
                and not self.renew_discord_lease(claimed)):
            # Commit latency or withdrawal after sealing can invalidate the
            # lease before POST. Retain the sealed intent, never create a retry.
            return True
        try:
            if claimed.get('instagramAction'):
                advance = self.social.advance_official if claimed.get('officialAction') else self.social.advance_instagram
                result = advance(claimed['job']['manifest'], claimed['job'], claimed['instagramAction'])
            elif claimed.get("nativeCancel"):
                result = self.social.cancel_native(claimed["job"]["manifest"], claimed["job"])
            elif claimed['reconciliation'] and claimed['job']['manifest'].get('operation') == 'discord.reply':
                result = self.social.reconcile_discord(claimed['job']['manifest'], claimed['job'],
                                                       read_authorize=self._discord_reply_read_guard(claimed, reconciliation=True))
            elif claimed["reconciliation"]:
                result = self.social.reconcile(claimed["job"]["manifest"], claimed["job"])
            elif claimed['job']['manifest'].get('platform') == 'Discord':
                result = self.social.submit_discord_authorized(claimed['job']['manifest'], claimed['discordDispatch'])
            else:
                manifest = claimed['job']['manifest']
                if manifest.get('platform') == 'Pinterest' and isinstance(self.social, HostedSocial):
                    result = self.social.submit(manifest, dispatch_context={'leaseId': claimed['job'].get('leaseId'), 'leaseOwner': self.worker_id})
                else:
                    result = self.social.submit(manifest)
        except UnconsumedPublishPermit as error:
            try:
                if self.release_discord_expired_permit(claimed, error):
                    return True
            except Exception:
                pass  # Unknown commit/authority state can never authorize retry.
            result = unknown('Unsent Discord permit could not be safely reconciled; manual review required')
        except Exception:
            result = unknown()
        if crash == "after_provider":
            return True
        self.complete(claimed, result)
        return True

    def tick(self, max_jobs=None, max_seconds=None):
        from .youtube.fleet import enabled
        fleet_owns_youtube = enabled()
        return self._tick(max_jobs, max_seconds, exclude_youtube=fleet_owns_youtube)

    def tick_linkedin(self, max_jobs=25, max_seconds=45):
        """Bounded server-only LinkedIn lane; no other platform or maintenance I/O."""
        if type(max_jobs) is not int or not 1 <= max_jobs <= 25 or type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 45:
            raise AlphaError('Use bounded LinkedIn worker limits.', 503)
        started, processed = time.monotonic(), 0
        while processed < max_jobs and time.monotonic() - started < max_seconds:
            if self.step(linkedin_only=True):
                processed += 1
            elif self.claim_contended:
                # A peer owns only the short SQL claim transaction. Remain in
                # this bounded lane rather than abandoning a ready queue.
                time.sleep(.02)
            else:
                break
        return {'processed': processed, 'execution': 'hosted-worker', 'platform': 'LinkedIn',
                'externalExecution': not isinstance(self.social, DisabledHostedSocial),
                'budget': {'maxJobs': max_jobs, 'maxSeconds': max_seconds}}

    def tick_youtube(self, max_jobs, max_seconds):
        """Dedicated lane: no other platform or maintenance dispatch can run."""
        return self._tick(max_jobs, max_seconds, youtube_only=True)

    def tick_discord(self, max_jobs=10, max_seconds=20):
        """Server-only opt-in lane inside the existing scheduler, no other IO."""
        return self._tick(max_jobs, max_seconds, discord_only=True)

    def discord_report(self):
        """Internal aggregates only; bounded sample, never a tenant-facing list."""
        queue = {'status': 'unavailable', 'sampled': True, 'workspaceLimit': discord_worker.QUEUE_WORKSPACE_LIMIT,
                 'jobLimit': 4096}
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute('''WITH sample AS MATERIALIZED (
                    SELECT state FROM public.pr_workspaces WHERE state ? 'phase2'
                      AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'
                    ORDER BY id LIMIT 256), jobs AS MATERIALIZED (
                    SELECT j FROM sample s CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.state#>'{phase2,jobs}','[]'::jsonb)) j
                    WHERE j#>>'{manifest,platform}'='Discord'
                      AND coalesce(j->'workerBinding',j#>'{manifest,workerBinding}','null'::jsonb)=%s::jsonb
                    LIMIT 4096), observed AS (SELECT extract(epoch from clock_timestamp())::double precision AS at)
                    SELECT count(*) FILTER(WHERE j->>'state' NOT IN ('verified','failed','canceled','held')),
                      coalesce(max(greatest(0,observed.at-coalesce((j->>'nextAt')::double precision,observed.at)))
                        FILTER(WHERE j->>'state' NOT IN ('verified','failed','canceled','held')
                          AND coalesce((j->>'leaseUntil')::double precision,0)<=observed.at),0),
                      count(*) FILTER(WHERE j->>'state'='held'),count(*) FILTER(WHERE j->>'state'='uncertain'),
                      count(*) FILTER(WHERE j#>'{discordWorker,deadLetter}' IS NOT NULL)
                    FROM jobs CROSS JOIN observed''', (json.dumps(self.worker_binding),))
                row = cur.fetchone()
                queue.update(status='observed_sample', depth=int(row[0]), oldestEligibleLagSeconds=float(row[1]),
                             held=int(row[2]), uncertain=int(row[3]), deadLetters=int(row[4]))
        except Exception:
            pass  # Monitoring failure cannot activate or weaken dispatch.
        provider = getattr(self.social,'providers',{}).get('discord')
        limiter = getattr(provider,'rate_limiter',None)
        rate = limiter.report() if getattr(provider,'rate_v1_enabled',False) and limiter is not None else {'status':'disabled'}
        return {'version': 1, 'enabled': self.discord_workers, 'stopping': self._stopping,
                'counterScope': 'worker-instance', 'counters': dict(self.discord_stats), 'queue': queue,'rateLimits':rate}

    def _tick(self, max_jobs=None, max_seconds=None, *, youtube_only=False, exclude_youtube=False, discord_only=False):
        self._ensure_lifecycle()
        if max_jobs is None or max_seconds is None:
            configured_jobs, configured_seconds = configured_worker_limits()
            max_jobs = configured_jobs if max_jobs is None else max_jobs
            max_seconds = configured_seconds if max_seconds is None else max_seconds
        if type(max_jobs) is not int or not 1 <= max_jobs <= 25 or type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 45:
            raise AlphaError("Use bounded worker limits.")
        started, processed = time.monotonic(), 0
        youtube = getattr(self.social, 'youtube', None) or getattr(self, 'youtube_maintenance', None)
        maintenance = ({'enabled': False, 'scheduler': 'discord_lane'} if discord_only else
                       {'enabled': False, 'scheduler': 'isolated_upload_lane'} if youtube_only else
                       youtube.maintenance(dispatch=False) if youtube and exclude_youtube else
                       youtube.maintenance() if youtube else {'enabled': False})
        def step():
            if discord_only:
                return self.step(discord_only=True)
            if self.discord_workers and not youtube_only:
                # Alternate provider lanes when both are busy; each lane retains
                # its existing approval and claim path. No Discord global lock.
                lanes = (lambda: self.step(discord_only=True),
                         lambda: self.step(exclude_youtube=exclude_youtube, exclude_discord=True))
                first = processed % 2
                return lanes[first]() or lanes[1-first]()
            return (self.step(youtube_only=youtube_only, exclude_youtube=exclude_youtube)
                    if youtube_only or exclude_youtube else self.step())
        while not self._stopping and processed < max_jobs and time.monotonic() - started < max_seconds and step():
            processed += 1
        result = {"processed": processed, "execution": "hosted-worker", "externalExecution": not isinstance(self.social, DisabledHostedSocial),
                "youtubeMaintenance": maintenance, "capacityIntervention": getattr(self, 'capacity_intervention', None),
                "budget": {"maxJobs": max_jobs, "maxSeconds": max_seconds}}
        if self.discord_workers or discord_only:
            result['discordWorker'] = self.discord_report()
        return result

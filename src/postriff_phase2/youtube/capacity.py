"""Conservative, atomic Rafii admission accounting; never Google's remaining quota.

Reservations commit before network I/O and are never refunded for uncertain requests.
Only fresh Google project evidence can raise the documented default ceilings.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import time
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError
from .model import YouTubeError, fresh_evidence, quota_reset

DEFAULT_LIMITS = {'videoUploads': 100, 'search': 100, 'general': 10000}
# Verified configured Analytics defaults (2026-10-08), measured in requests, not Data units.
DEFAULT_ANALYTICS_LIMITS = {'requestsPerDay': 100000, 'requestsPerMinute': 720}
ANALYTICS_DAILY_BUCKET = 'analyticsRequests'
ANALYTICS_MINUTE_PREFIX = 'analyticsMinute:'
LIMIT_ENV = {'videoUploads': 'POSTRIFF_YOUTUBE_UPLOAD_DAILY_LIMIT',
             'search': 'POSTRIFF_YOUTUBE_SEARCH_DAILY_LIMIT',
             'general': 'POSTRIFF_YOUTUBE_GENERAL_DAILY_LIMIT'}


def positive(value, default, maximum):
    try:
        # A malformed limit never turns off admission control.
        parsed = int(value) if not isinstance(value, bool) else 0
    except (ValueError, TypeError, OverflowError):
        parsed = 0
    return min(parsed, maximum) if parsed > 0 else min(default, maximum)


@dataclass(frozen=True)
class CapacityPolicy:
    project_key: str
    limits: dict = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    workspace_limits: dict = field(default_factory=lambda: {'videoUploads': 5, 'search': 20, 'general': 2000})
    requests_per_minute: int = 120
    pending_per_workspace: int = 20
    approved_evidence: bool = False
    analytics_daily_limit: int = 100000
    analytics_project_per_minute: int = 720
    analytics_workspace_daily_limit: int = 2000

    @classmethod
    def from_environment(cls, provider, values=None):
        values, evidence = values or {}, getattr(provider, 'project_evidence', {}) or {}
        proof = evidence.get('quota') if isinstance(evidence.get('quota'), dict) else {}
        client = getattr(provider, 'client_id', '') or ''
        bound_project = bool(evidence.get('projectId') and evidence.get('clientId') == client)
        approved = bool(bound_project
                        and proof.get('status') == 'verified' and proof.get('source') == 'google_platform'
                        and proof.get('reference') and fresh_evidence(proof.get('observedAt'))
                        and proof.get('projectId', evidence['projectId']) == evidence['projectId'])
        supplied = proof.get('limits') if approved and isinstance(proof.get('limits'), dict) else {}
        limits = {}
        for bucket, default in DEFAULT_LIMITS.items():
            ceiling = supplied.get(bucket, default)
            if type(ceiling) is not int or ceiling <= 0:
                ceiling = default
            limits[bucket] = positive(values.get(LIMIT_ENV[bucket]), ceiling, ceiling)
        workspace = {bucket: positive(values.get('POSTRIFF_YOUTUBE_WORKSPACE_' + bucket.upper() + '_DAILY_LIMIT'),
                                      {'videoUploads': 5, 'search': 20, 'general': 2000}[bucket], limit)
                     for bucket, limit in limits.items()}
        # Verified project ID shares one budget across OAuth clients. Otherwise use
        # a non-secret client fingerprint, never an operator-supplied escape key.
        key = str(evidence['projectId']) if bound_project else 'client:' + hashlib.sha256(client.encode()).hexdigest()
        analytics_proof = proof.get('analyticsLimits') if approved and isinstance(proof.get('analyticsLimits'), dict) else {}
        analytics = {}
        for name, variable in (('requestsPerDay', 'POSTRIFF_YOUTUBE_ANALYTICS_DAILY_LIMIT'),
                               ('requestsPerMinute', 'POSTRIFF_YOUTUBE_ANALYTICS_PROJECT_REQUESTS_PER_MINUTE')):
            ceiling = analytics_proof.get(name, DEFAULT_ANALYTICS_LIMITS[name])
            if type(ceiling) is not int or ceiling <= 0:
                ceiling = DEFAULT_ANALYTICS_LIMITS[name]
            analytics[name] = positive(values.get(variable), ceiling, ceiling)
        analytics_workspace = positive(values.get('POSTRIFF_YOUTUBE_ANALYTICS_WORKSPACE_DAILY_LIMIT'),
                                       2000, analytics['requestsPerDay'])
        return cls(key, limits, workspace,
                   positive(values.get('POSTRIFF_YOUTUBE_WORKSPACE_REQUESTS_PER_MINUTE'), 120, 600),
                   positive(values.get('POSTRIFF_YOUTUBE_PENDING_PER_WORKSPACE'), 20, 200), approved,
                   analytics['requestsPerDay'], analytics['requestsPerMinute'], analytics_workspace)


def budget_decision(policy, bucket, units, project_used, workspace_used, requests, now):
    """Pure decision used inside the database lock, including DST-correct reset."""
    if requests >= policy.requests_per_minute:
        return ('workspace_rate', math.floor(now / 60) * 60 + 60)
    if units is not None:
        if type(units) is not int or units < 0 or bucket not in policy.limits:
            raise AlphaError('The YouTube method has an invalid quota contract.', 503, code='youtube_capacity_contract')
        if project_used + units > policy.limits[bucket]:
            return ('project_daily', quota_reset(now))
        if workspace_used + units > policy.workspace_limits[bucket]:
            return ('workspace_daily', quota_reset(now))
    return None


def analytics_budget_decision(policy, project_used, workspace_used, project_requests, workspace_requests, now):
    """Separate query-count admission; Analytics has no documented Data unit cost."""
    if project_used >= policy.analytics_daily_limit:
        return ('analytics_project_daily', quota_reset(now))
    if workspace_used >= policy.analytics_workspace_daily_limit:
        return ('analytics_workspace_daily', quota_reset(now))
    if project_requests >= policy.analytics_project_per_minute:
        return ('analytics_project_rate', math.floor(now / 60) * 60 + 60)
    if workspace_requests >= policy.requests_per_minute:
        return ('workspace_rate', math.floor(now / 60) * 60 + 60)
    return None


class CapacityController:
    def __init__(self, connection_factory, policy, *, clock=time.time):
        self.connection_factory, self.policy, self.clock = connection_factory, policy, clock

    def assert_queue_capacity(self, state, additional=1):
        if type(additional) is not int or additional < 0:
            raise AlphaError('Invalid pending YouTube queue admission.', 503, code='youtube_queue_capacity_contract')
        pending = sum(1 for job in (state.get('phase2') or {}).get('jobs', [])
                      if (job.get('manifest') or {}).get('platform') == 'YouTube'
                      and job.get('state') not in ('verified', 'failed', 'canceled'))
        if pending + additional > self.policy.pending_per_workspace:
            raise AlphaError('This workspace has reached its pending YouTube queue limit. Finish or cancel an existing workflow first.',
                             429, code='youtube_queue_capacity')

    def record(self, workspace, connection, method, bucket, units):
        if not isinstance(connection, str) or not connection:
            raise AlphaError('A connected-channel quota attempt requires its connection identity.', 503,
                             code='youtube_capacity_contract')
        self._reserve(workspace, connection, method, bucket, units)

    def record_identity(self, workspace):
        """Reserve initial discovery before a connection exists, outside workspace locks.

        The trusted OAuth coordinator supplies the claimed workspace and exact
        provider policy. Daily/rate counters remain durable without inventing a
        channel identifier for the connection-specific attempt log.
        """
        self._reserve(workspace, None, 'channels.list', 'general', 1)

    def _reserve(self, workspace, connection, method, bucket, units):
        if bucket == 'analytics':
            if units is not None or not method.startswith('analytics.'):
                raise AlphaError('Analytics admission requires its separate request-count contract.', 503,
                                 code='youtube_capacity_contract')
            return self._reserve_analytics(workspace, connection, method)
        now, policy = self.clock(), self.policy
        quota_date = datetime.fromtimestamp(now, ZoneInfo('America/Los_Angeles')).date()
        minute = datetime.fromtimestamp(math.floor(now / 60) * 60, timezone.utc)
        denied = None
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT to_regclass('public.pr_youtube_quota_daily')")
            if cur.fetchone()[0] is None:
                raise AlphaError('YouTube capacity admission requires reviewed migration 097. No provider request was sent.',
                                 503, code='youtube_capacity_schema')
            # Short transaction only; this lock never spans a provider call.
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('youtube-capacity:' + policy.project_key,))
            cur.execute('SELECT scope_key,used_units FROM public.pr_youtube_quota_daily WHERE project_key=%s AND quota_date=%s AND bucket=%s AND scope_key IN (%s,%s)',
                        (policy.project_key, quota_date, bucket, 'project', workspace))
            used = dict(cur.fetchall())
            cur.execute('SELECT requests FROM public.pr_youtube_rate_windows WHERE project_key=%s AND workspace_id=%s AND window_start=%s',
                        (policy.project_key, workspace, minute))
            row = cur.fetchone()
            denied = budget_decision(policy, bucket, units, used.get('project', 0), used.get(workspace, 0), row[0] if row else 0, now)
            admitted = denied is None
            for scope, workspace_id in (('project', None), (workspace, workspace)):
                cur.execute('''INSERT INTO public.pr_youtube_quota_daily(project_key,quota_date,bucket,scope_key,workspace_id,used_units,admitted_requests,denied_requests)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(project_key,quota_date,bucket,scope_key)
                    DO UPDATE SET used_units=pr_youtube_quota_daily.used_units+excluded.used_units,
                      admitted_requests=pr_youtube_quota_daily.admitted_requests+excluded.admitted_requests,
                      denied_requests=pr_youtube_quota_daily.denied_requests+excluded.denied_requests,updated_at=now()''',
                    (policy.project_key, quota_date, bucket, scope, workspace_id, (units or 0) if admitted else 0, int(admitted), int(not admitted)))
            if admitted:
                cur.execute('''INSERT INTO public.pr_youtube_rate_windows(project_key,workspace_id,window_start,requests) VALUES(%s,%s,%s,1)
                    ON CONFLICT(project_key,workspace_id,window_start) DO UPDATE SET requests=pr_youtube_rate_windows.requests+1''',
                    (policy.project_key, workspace, minute))
            if connection is not None:
                cur.execute('INSERT INTO public.pr_youtube_usage(workspace_id,connection_id,method,bucket,estimated_units,project_key,admitted) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                            (workspace, connection, method, bucket, units if admitted else 0, policy.project_key, admitted))
        if denied:
            error = YouTubeError('capacity_delay', 'YouTube publishing is delayed by Rafii capacity controls. The approved operation is kept; no provider request was sent.',
                                 status=429, retryable=True, retry_at=denied[1])
            error.capacity_reason = denied[0]
            raise error

    def _reserve_analytics(self, workspace, connection, method):
        now, policy = self.clock(), self.policy
        quota_date = datetime.fromtimestamp(now, ZoneInfo('America/Los_Angeles')).date()
        minute_number = math.floor(now / 60)
        minute = datetime.fromtimestamp(minute_number * 60, timezone.utc)
        minute_bucket = ANALYTICS_MINUTE_PREFIX + str(minute_number)
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT to_regclass('public.pr_youtube_quota_daily')")
            if cur.fetchone()[0] is None:
                raise AlphaError('Analytics admission requires reviewed migration 097. No provider request was sent.',
                                 503, code='youtube_capacity_schema')
            # All OAuth clients in the bound project serialize on the same lock.
            # Counters commit before transport; neither crashes nor tenant deletion refund project admission.
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('youtube-capacity:' + policy.project_key,))
            cur.execute('SELECT scope_key,used_units FROM public.pr_youtube_quota_daily WHERE project_key=%s AND quota_date=%s AND bucket=%s AND scope_key IN (%s,%s)',
                        (policy.project_key, quota_date, ANALYTICS_DAILY_BUCKET, 'project', workspace))
            used = dict(cur.fetchall())
            cur.execute("SELECT used_units FROM public.pr_youtube_quota_daily WHERE project_key=%s AND quota_date=%s AND bucket=%s AND scope_key='project'",
                        (policy.project_key, quota_date, minute_bucket))
            minute_row = cur.fetchone()
            cur.execute('SELECT requests FROM public.pr_youtube_rate_windows WHERE project_key=%s AND workspace_id=%s AND window_start=%s',
                        (policy.project_key, workspace, minute))
            workspace_row = cur.fetchone()
            denied = analytics_budget_decision(policy, used.get('project', 0), used.get(workspace, 0),
                                               minute_row[0] if minute_row else 0,
                                               workspace_row[0] if workspace_row else 0, now)
            admitted = denied is None
            for bucket, scope, workspace_id in ((ANALYTICS_DAILY_BUCKET, 'project', None),
                                                (ANALYTICS_DAILY_BUCKET, workspace, workspace),
                                                (minute_bucket, 'project', None)):
                cur.execute('''INSERT INTO public.pr_youtube_quota_daily(project_key,quota_date,bucket,scope_key,workspace_id,used_units,admitted_requests,denied_requests)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(project_key,quota_date,bucket,scope_key)
                    DO UPDATE SET used_units=pr_youtube_quota_daily.used_units+excluded.used_units,
                      admitted_requests=pr_youtube_quota_daily.admitted_requests+excluded.admitted_requests,
                      denied_requests=pr_youtube_quota_daily.denied_requests+excluded.denied_requests,updated_at=now()''',
                            (policy.project_key, quota_date, bucket, scope, workspace_id, int(admitted), int(admitted), int(not admitted)))
            if admitted:
                cur.execute('''INSERT INTO public.pr_youtube_rate_windows(project_key,workspace_id,window_start,requests) VALUES(%s,%s,%s,1)
                    ON CONFLICT(project_key,workspace_id,window_start) DO UPDATE SET requests=pr_youtube_rate_windows.requests+1''',
                            (policy.project_key, workspace, minute))
            cur.execute('INSERT INTO public.pr_youtube_usage(workspace_id,connection_id,method,bucket,estimated_units,project_key,admitted) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                        (workspace, connection, method, 'analytics', None, policy.project_key, admitted))
        if denied:
            error = YouTubeError('capacity_delay', 'YouTube Analytics is delayed by Rafii request-count admission. No provider request was sent.',
                                 status=429, retryable=True, retry_at=denied[1])
            error.capacity_reason = denied[0]
            raise error

    def snapshot(self, workspace):
        today = datetime.fromtimestamp(self.clock(), ZoneInfo('America/Los_Angeles')).date()
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT bucket,used_units,admitted_requests,denied_requests FROM public.pr_youtube_quota_daily WHERE project_key=%s AND quota_date=%s AND scope_key=%s',
                        (self.policy.project_key, today, workspace))
            rows = cur.fetchall()
            usage = {r[0]: {'reservedUnits': r[1], 'admittedRequests': r[2], 'delayedRequests': r[3]}
                     for r in rows if r[0] != ANALYTICS_DAILY_BUCKET}
            analytics_row = next((r for r in rows if r[0] == ANALYTICS_DAILY_BUCKET), None)
        analytics = {'unit': 'requests; Data API unit cost remains unknown',
                     'configuredProjectDailyLimit': self.policy.analytics_daily_limit,
                     'configuredProjectRequestsPerMinute': self.policy.analytics_project_per_minute,
                     'workspaceDailyLimit': self.policy.analytics_workspace_daily_limit,
                     'sharedWorkspaceRequestsPerMinute': self.policy.requests_per_minute,
                     'workspaceReservedRequestsToday': analytics_row[1] if analytics_row else 0,
                     'workspaceAdmittedRequestsToday': analytics_row[2] if analytics_row else 0,
                     'workspaceDelayedRequestsToday': analytics_row[3] if analytics_row else 0,
                     'actualGoogleRemaining': None}
        return {'source': 'Rafii atomic admission accounting; not Google remaining quota',
                'configuredProjectCeilings': dict(self.policy.limits), 'workspaceCeilings': dict(self.policy.workspace_limits),
                'approvedQuotaEvidence': self.policy.approved_evidence, 'workspaceUsageToday': usage,
                'pendingQueueLimit': self.policy.pending_per_workspace, 'requestsPerMinute': self.policy.requests_per_minute,
                'analyticsAdmission': analytics,
                'resetAt': quota_reset(self.clock()), 'resetTimeZone': 'America/Los_Angeles', 'actualGoogleRemaining': None}

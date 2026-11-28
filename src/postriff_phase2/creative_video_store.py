"""Workspace-scoped editorial records. All operations run under the canonical workspace transaction lock."""
import json
import uuid

from postriff_alpha.domain import AlphaError


def project_id(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise AlphaError("Creative project unavailable.", 404) from None


class ProjectStore:
    @staticmethod
    def paused_models(cur, environment):
        cur.execute("SELECT model FROM public.pr_creative_video_model_policy WHERE environment=%s AND paused", (environment,))
        return {row[0] for row in cur.fetchall()}

    def list(self, cur, workspace):
        cur.execute("""SELECT p.id::text,p.brief->>'title',p.revision,jsonb_array_length(r.scenes)
                       FROM public.pr_creative_video_projects p JOIN public.pr_creative_video_revisions r
                       ON (p.workspace_id,p.id,p.revision)=(r.workspace_id,r.project_id,r.revision)
                       WHERE p.workspace_id=%s ORDER BY p.created_at DESC,p.id LIMIT 100""", (workspace,))
        return [dict(zip(("id", "title", "revision", "sceneCount"), row)) for row in cur.fetchall()]

    def request(self, cur, workspace, key, fingerprint):
        cur.execute("""SELECT id::text,request_digest FROM public.pr_creative_video_projects
                       WHERE workspace_id=%s AND request_key=%s""", (workspace, key))
        row = cur.fetchone()
        if row and row[1] != fingerprint:
            raise AlphaError("This creation request already belongs to another brief.", 409)
        return row[0] if row else None

    def create(self, cur, workspace, actor, key, fingerprint, brief, scenes):
        pid = str(uuid.uuid4())
        cur.execute("""INSERT INTO public.pr_creative_video_projects(workspace_id,id,request_key,
                       request_digest,revision,brief,created_by) VALUES(%s,%s,%s,%s,1,%s::jsonb,%s)""",
                    (workspace, pid, key, fingerprint, json.dumps(brief), actor))
        self._insert_revision(cur, workspace, pid, 1, scenes, actor)
        return pid

    def get(self, cur, workspace, pid, revision=None):
        pid = project_id(pid)
        cur.execute("""SELECT p.brief,p.revision,r.scenes,r.export,r.revision FROM public.pr_creative_video_projects p
                       JOIN public.pr_creative_video_revisions r ON p.workspace_id=r.workspace_id AND p.id=r.project_id
                       AND r.revision=coalesce(%s,p.revision) WHERE p.workspace_id=%s AND p.id=%s""",
                    (revision, workspace, pid))
        row = cur.fetchone()
        if not row:
            raise AlphaError("Creative project unavailable.", 404)
        return {**row[0], "id": pid, "headRevision": row[1], "scenes": row[2], "export": row[3], "revision": row[4]}

    def history(self, cur, workspace, pid):
        cur.execute("""SELECT revision,jsonb_array_length(scenes) FROM public.pr_creative_video_revisions
                       WHERE workspace_id=%s AND project_id=%s ORDER BY revision DESC""", (workspace, pid))
        return [{"revision": r, "sceneCount": n} for r, n in cur.fetchall()]

    def _insert_revision(self, cur, workspace, pid, revision, scenes, actor):
        cur.execute("""INSERT INTO public.pr_creative_video_revisions(workspace_id,project_id,revision,scenes,created_by)
                       VALUES(%s,%s,%s,%s::jsonb,%s)""", (workspace, pid, revision, json.dumps(scenes), actor))

    def edit(self, cur, workspace, project, scenes, actor):
        revision = project["revision"] + 1
        cur.execute("""UPDATE public.pr_creative_video_projects SET revision=%s
                       WHERE workspace_id=%s AND id=%s AND revision=%s""",
                    (revision, workspace, project["id"], project["revision"]))
        if cur.rowcount != 1:
            raise AlphaError("The project changed. Reload it before editing.", 409)
        self._insert_revision(cur, workspace, project["id"], revision, scenes, actor)

    def export(self, cur, workspace, pid, revision, receipt):
        cur.execute("""UPDATE public.pr_creative_video_revisions SET export=%s::jsonb
                       WHERE workspace_id=%s AND project_id=%s AND revision=%s""",
                    (json.dumps(receipt), workspace, pid, revision))

    def issue_quote(self, cur, workspace, pid, actor, scene_id, binding):
        cur.execute("""INSERT INTO public.pr_creative_video_quotes(workspace_id,project_id,actor,scene_id,expires_at,binding)
                     VALUES(%s,%s,%s,%s,now()+interval '10 minutes',%s::jsonb)
                     ON CONFLICT (workspace_id,project_id,actor,scene_id) DO UPDATE
                     SET id=excluded.id,expires_at=excluded.expires_at,binding=excluded.binding
                     RETURNING id::text,extract(epoch from expires_at)""",
                    (workspace, pid, actor, scene_id, json.dumps(binding)))
        ident, expiry = cur.fetchone()
        return ident, float(expiry)

    def reviewed_quote(self, cur, workspace, pid, actor, scene_id, ident):
        cur.execute("""SELECT binding FROM public.pr_creative_video_quotes
                       WHERE workspace_id=%s AND project_id=%s AND actor=%s AND scene_id=%s
                       AND id=%s AND expires_at>now() FOR UPDATE""", (workspace, pid, actor, scene_id, ident))
        row = cur.fetchone()
        if not row:
            raise AlphaError("This scene quote expired or changed. Review a fresh estimate.", 409, code="creative_quote_changed")
        return row[0]

    def remember_usage(self, cur, workspace, job, receipt):
        cur.execute("""UPDATE public.pr_jobs SET body=jsonb_set(body,'{providerUsage}',%s::jsonb),revision=revision+1
                     WHERE workspace_id=%s AND body->>'idempotencyKey'=%s AND body->>'operation'=%s
                     AND body->>'state' IN ('pending','completed','failed','cancelled') AND NOT (body ? 'providerUsage')""",
                    (json.dumps(receipt),workspace,job["idempotencyKey"],job["operation"]))
        if not cur.rowcount:
            cur.execute("""SELECT body->'providerUsage' FROM public.pr_jobs WHERE workspace_id=%s
                         AND body->>'idempotencyKey'=%s AND body->>'operation'=%s""",
                        (workspace,job["idempotencyKey"],job["operation"]))
            row = cur.fetchone()
            return bool(row and row[0] == receipt)
        return True

    def locked_usage_job(self, cur, workspace, job):
        cur.execute("""SELECT body FROM public.pr_jobs WHERE workspace_id=%s AND body->>'kind'='creative_video_scene'
                     AND body->>'idempotencyKey'=%s AND body->>'operation'=%s FOR UPDATE""",
                    (workspace, job["idempotencyKey"], job["operation"]))
        row = cur.fetchone()
        return row[0] if row else {}

    def jobs(self, cur, workspace, scenes):
        keys = [self.key(s) for s in scenes]
        cur.execute("""SELECT j.body,settled.cost_state,settled.actual_usd_micro FROM public.pr_jobs j
                       LEFT JOIN LATERAL (
                           SELECT u.cost_state,u.actual_usd_micro FROM public.pr_usage_ledger u
                           WHERE u.workspace_id=j.workspace_id AND u.reservation_id=(j.body->>'reservationId')::uuid
                           AND u.cost_state IN ('actual','released') AND u.kind IN ('settle','release') LIMIT 1
                       ) settled ON true
                       WHERE j.workspace_id=%s AND j.body->>'idempotencyKey'=ANY(%s)
                       AND j.body->>'kind'='creative_video_scene'""", (workspace, keys))
        jobs = {}
        for data, cost_state, actual in cur.fetchall():
            job = dict(data)
            if cost_state:
                job["actualUsdMicro"] = int(actual)
                if job["state"] == "unknown":
                    job.update(state="failed", reason="submission_reconciled_without_clip")
            job["settlementState"] = cost_state or ("free" if job.get("mediaKind") == "composed" else
                "reconciliation_required" if job.get("state") in ("unknown", "completed", "failed", "cancelled") else "reserved")
            jobs[job["idempotencyKey"]] = job
        return jobs

    @staticmethod
    def key(scene):
        return "creative-video:" + scene["take"]

    def admit_job(self, cur, workspace):
        cur.execute("""SELECT count(*) FROM public.pr_jobs j WHERE j.workspace_id=%s AND
                       j.body->>'kind'='creative_video_scene' AND (j.body->>'state' IN ('submitting','pending')
                       OR (j.body->>'state'='unknown' AND NOT EXISTS (
                           SELECT 1 FROM public.pr_usage_ledger u WHERE u.workspace_id=j.workspace_id
                           AND u.reservation_id=(j.body->>'reservationId')::uuid
                           AND u.cost_state IN ('actual','released') AND u.kind IN ('settle','release'))))""", (workspace,))
        if cur.fetchone()[0] >= 3:
            raise AlphaError("Resolve your outstanding scene generations before starting another.", 429)

    def stale_submissions(self, cur, workspace):
        # A missing submission acknowledgement cannot safely be retried. Three claims is the workspace maximum.
        cur.execute("""SELECT body FROM public.pr_jobs WHERE workspace_id=%s AND body->>'kind'='creative_video_scene'
                       AND body->>'state'='submitting' AND created_at < now() - interval '5 minutes'
                       ORDER BY created_at LIMIT 3 FOR UPDATE""", (workspace,))
        return [row[0] for row in cur.fetchall()]

    def insert_job(self, cur, workspace, job, approval):
        cur.execute("INSERT INTO public.pr_approvals(workspace_id,body) VALUES(%s,%s::jsonb)",
                    (workspace, json.dumps(approval)))
        cur.execute("INSERT INTO public.pr_jobs(workspace_id,body) VALUES(%s,%s::jsonb)", (workspace, json.dumps(job)))

    def update_job(self, cur, workspace, key, previous, fields):
        cur.execute("""UPDATE public.pr_jobs j SET body=body || %s::jsonb,revision=revision+1 WHERE workspace_id=%s
                       AND body->>'idempotencyKey'=%s AND body->>'state'=%s
                       AND (body->>'state'<>'unknown' OR NOT EXISTS (
                           SELECT 1 FROM public.pr_usage_ledger u WHERE u.workspace_id=j.workspace_id
                           AND u.reservation_id=(j.body->>'reservationId')::uuid
                           AND u.cost_state IN ('actual','released') AND u.kind IN ('settle','release')))""",
                    (json.dumps(fields), workspace, key, previous))
        return cur.rowcount == 1

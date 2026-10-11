"""Mastodon account operations inside the existing workspace, grants and audit boundary.

Every mutation is a persisted exact-action preview followed by human approval. Unknown
outcomes are never resubmitted. Read responses stay ephemeral and out of AI/history.
"""
import json
import re

from postriff_alpha.domain import AlphaError
from .contracts import digest
from .permissions import require
from .mastodon_protocol import ID, discover, has_scopes, status_options, validate_status


class ApplicationCache:
    def __init__(self, oauth, provider):
        self.oauth, self.provider = oauth, provider

    def __call__(self, host, redirect, scopes, value=None):
        binding = digest({"redirect": redirect, "scopes": sorted(scopes), "website": self.provider.website})
        with self.oauth.repository.connection_factory() as db, db.cursor() as cur:
            # Serialize per binding across processes; do not register thousands of duplicate apps.
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("mastodon-app:" + host + binding,))
            cur.execute("SELECT credentials_ciphertext,key_id FROM public.pr_mastodon_applications WHERE instance=%s AND binding_digest=%s", (host, binding))
            stored = cur.fetchone()
            if stored:
                credentials = json.loads(self.oauth.vault.decrypt(stored[0], stored[1]))
                expiry = credentials.get("client_secret_expires_at", 0)
                if type(expiry) is int and (expiry == 0 or expiry > self.oauth.clock() + 600):
                    return credentials
            response = self.provider.transport("POST", "https://" + host + "/api/v1/apps", form={
                "client_name": "Rafii", "redirect_uris": redirect, "scopes": " ".join(scopes), "website": self.provider.website})
            body = self.provider._ok(response, "client_id", "client_secret")
            credentials = {key: body[key] for key in ("client_id", "client_secret", "client_secret_expires_at") if key in body}
            ciphertext, key_id = self.oauth.vault.encrypt(json.dumps(credentials))
            cur.execute("INSERT INTO public.pr_mastodon_applications(instance,binding_digest,credentials_ciphertext,key_id) VALUES(%s,%s,%s,%s) ON CONFLICT(instance,binding_digest) DO UPDATE SET credentials_ciphertext=excluded.credentials_ciphertext,key_id=excluded.key_id,updated_at=now()", (host, binding, ciphertext, key_id))
            return credentials


READS = {
    "profile": ("/api/v1/accounts/verify_credentials", ("read:accounts",)),
    "home": ("/api/v1/timelines/home?limit=40", ("read:statuses",)),
    "notifications": ("/api/v1/notifications?limit=40", ("read:notifications",)),
    "bookmarks": ("/api/v1/bookmarks?limit=40", ("read:bookmarks",)),
    "favourites": ("/api/v1/favourites?limit=40", ("read:favourites",)),
    "lists": ("/api/v1/lists", ("read:lists",)),
    "preferences": ("/api/v1/preferences", ("read:accounts",)),
    "scheduled": ("/api/v1/scheduled_statuses?limit=40", ("read:statuses",)),
    "mutes": ("/api/v1/mutes?limit=40", ("read:mutes",)),
    "blocks": ("/api/v1/blocks?limit=40", ("read:blocks",)),
    "trending_tags": ("/api/v1/trends/tags?limit=20", ("read:statuses",)),
    "trending_statuses": ("/api/v1/trends/statuses?limit=20", ("read:statuses",)),
}
STATUS_ACTIONS = {
    "favourite": "write:favourites", "unfavourite": "write:favourites",
    "reblog": "write:statuses", "unreblog": "write:statuses",
    "bookmark": "write:bookmarks", "unbookmark": "write:bookmarks",
}
ACCOUNT_ACTIONS = {"follow": "write:follows", "unfollow": "write:follows", "mute": "write:mutes",
                   "unmute": "write:mutes", "block": "write:blocks", "unblock": "write:blocks"}


def maintain(connection_factory, limit=100):
    """Bounded service-only cleanup; interrupted effects become uncertain, never retried."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Mastodon maintenance requires a bound of 1–1000 rows.')
    with connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_mastodon_actions') IS NOT NULL")
        if not cur.fetchone()[0]: return {'state': 'schema_unavailable'}
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('mastodon-retention-v1',0))")
        if not cur.fetchone()[0]: return {'state': 'busy'}
        cur.execute("UPDATE public.pr_mastodon_actions SET status='uncertain',receipt=%s::jsonb,updated_at=now() WHERE id IN (SELECT id FROM public.pr_mastodon_actions WHERE status='running' AND updated_at < now()-interval '5 minutes' ORDER BY updated_at,id LIMIT %s FOR UPDATE SKIP LOCKED)",
                    (json.dumps({'state': 'uncertain', 'reason': 'The action worker stopped before a conclusive receipt. Check Mastodon; this action will not be resent.'}), limit))
        recovered = cur.rowcount
        cur.execute("DELETE FROM public.pr_mastodon_actions WHERE id IN (SELECT id FROM public.pr_mastodon_actions WHERE created_at < now()-interval '7 days' ORDER BY created_at,id LIMIT %s FOR UPDATE SKIP LOCKED)", (limit,))
        actions = cur.rowcount
        cur.execute("DELETE FROM public.pr_metric_observations WHERE id IN (SELECT id FROM public.pr_metric_observations WHERE provider='mastodon' AND observed_at < now()-interval '90 days' ORDER BY observed_at,id LIMIT %s FOR UPDATE SKIP LOCKED)", (limit,))
        observations = cur.rowcount
        cur.execute("DELETE FROM public.pr_metric_reads WHERE id IN (SELECT id FROM public.pr_metric_reads WHERE provider='mastodon' AND status IN ('done','cancelled','dead','unavailable') AND updated_at < now()-interval '90 days' ORDER BY updated_at,id LIMIT %s FOR UPDATE SKIP LOCKED)", (limit,))
        return {'state': 'ok', 'interruptedActions': recovered, 'expiredActions': actions, 'expiredMetrics': observations, 'expiredReads': cur.rowcount}


def action_spec(action, payload, capabilities, *, now):
    """No arbitrary URLs/methods; the allowlist defines exact authority and canonical data."""
    if not isinstance(payload, dict):
        raise AlphaError("Expected structured Mastodon action settings.", 400)
    target = payload.get("targetId")
    if action not in ("profile_update", "list_create", "native_schedule"):
        if not isinstance(target, str) or not ID.fullmatch(target):
            raise AlphaError("Choose a valid Mastodon account, post or schedule ID.", 400)
    if action in STATUS_ACTIONS:
        return "POST", f"/api/v1/statuses/{target}/{action}", {}, (STATUS_ACTIONS[action],), "approve"
    if action in ACCOUNT_ACTIONS:
        return "POST", f"/api/v1/accounts/{target}/{action}", {}, (ACCOUNT_ACTIONS[action],), "moderate" if action in ("mute", "unmute", "block", "unblock") else "manage_connections"
    if action in ("edit", "delete"):
        if action == "edit" and not capabilities.get("edit"):
            raise AlphaError("Editing is unavailable on this server version.", 409)
        body = {} if action == "delete" else validate_status(payload.get("text"), payload.get("options", {}), (), capabilities, now=now)
        # Mastodon edits cannot change visibility, reply parent, quote target or scheduled time.
        if action == "edit":
            body = {k: v for k, v in body.items() if k in ("status", "spoiler_text", "sensitive", "language", "poll")}
        return ("PUT" if action == "edit" else "DELETE"), f"/api/v1/statuses/{target}", body, ("read:statuses", "write:statuses"), "approve"
    if action in ("native_cancel", "native_reschedule"):
        if not capabilities.get("schedule"):
            raise AlphaError("Native scheduling is unavailable on this server.", 409)
        body = {} if action == "native_cancel" else {"scheduled_at": status_options({"scheduled_at": payload.get("scheduled_at")}, capabilities=capabilities, now=now)["scheduled_at"]}
        return ("DELETE" if action == "native_cancel" else "PUT"), f"/api/v1/scheduled_statuses/{target}", body, ("read:statuses", "write:statuses"), "approve"
    if action == "native_schedule":
        if not isinstance(payload.get('options', {}), dict):
            raise AlphaError('Choose valid Mastodon post settings.', 400)
        options = {**payload.get("options", {}), "scheduled_at": payload.get("scheduled_at")}
        body = validate_status(payload.get("text"), options, (), capabilities, now=now)
        return "POST", "/api/v1/statuses", body, ("write:statuses",), "approve"
    if action == "profile_update":
        from .mastodon_profile import profile_fields
        fields = profile_fields(payload, capabilities)
        return "PATCH", "/api/v1/accounts/update_credentials", fields, ("write:accounts",), "manage_connections"
    if action in ("list_create", "list_update", "list_delete", "list_add", "list_remove"):
        path = "/api/v1/lists" + ("" if action == "list_create" else "/" + target)
        if action in ("list_add", "list_remove"):
            accounts = payload.get("account_ids")
            if not isinstance(accounts, list) or not 1 <= len(accounts) <= 20 or not all(isinstance(x, str) and ID.fullmatch(x) for x in accounts):
                raise AlphaError("Choose up to 20 valid account IDs for this list.", 400)
            return ("POST" if action == "list_add" else "DELETE"), path + "/accounts", {"account_ids": accounts}, ("write:lists",), "manage_connections"
        body = {}
        if action != "list_delete":
            title = payload.get("title")
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
                raise AlphaError("Give the list a title of at most 100 characters.", 400)
            body = {"title": title.strip()}
        return {"list_create": "POST", "list_update": "PUT", "list_delete": "DELETE"}[action], path, body, ("write:lists",), "manage_connections"
    raise AlphaError("This Mastodon action is unavailable.", 404)


class MastodonManagement:
    def __init__(self, service):
        self.service, self.oauth = service, service.oauth
        self.repository, self.clock = service.repository, service.oauth.clock

    def _grant(self, workspace, token, connection, requirement="read"):
        # Admission precedes token re-verification, which itself contacts the
        # instance. An exhausted local read budget must cause zero remote calls.
        from .hosted import throttle, _membership
        with self.repository.transaction(token, workspace) as (cur, row, _actor):
            require(_membership(row), requirement)
            cur.execute("SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon' AND revoked_at IS NULL", (workspace, connection))
            stored = cur.fetchone()
            if not stored or not isinstance(stored[0], str):
                raise AlphaError('Choose a Mastodon connection.', 404)
            account, separator, host = stored[0].partition('@')
            if (not separator or not re.fullmatch(r'[0-9]{1,40}', account)
                    or not re.fullmatch(r'[a-z0-9.-]{1,253}', host)):
                raise AlphaError('The connected Mastodon account binding is invalid. Reconnect.', 409)
            throttle(cur, 'mastodon-read-instance:' + host, 250, 300)
            throttle(cur, 'mastodon-read-account:' + workspace + connection, 60, 300)
        provider, grant = self.oauth._member_grant(workspace, token, connection, requirement)
        if provider.id != 'mastodon' or grant['providerAccountId'] != stored[0]:
            raise AlphaError('The connected account changed. Prepare a fresh request.', 409)
        session = provider.session(grant['accessToken'])
        if session['instance'] != host:
            raise AlphaError('The connected Mastodon instance changed. Reconnect.', 409)
        return provider, grant, session

    @staticmethod
    def _scopes(grant, required):
        if not has_scopes(grant.get("scopes", []), required):
            raise AlphaError("Reconnect this account with the required Mastodon permissions.", 403)

    @staticmethod
    def _result(response):
        status = response.get("status")
        if status == 429:
            raise AlphaError("This Mastodon server is rate limiting requests. Try again after its reset time.", 429)
        if status in (401, 403):
            raise AlphaError("Mastodon denied access. Reconnect or review the account's permissions.", 409)
        if status != 200 or not isinstance(response.get("body"), (dict, list)):
            raise AlphaError("The Mastodon server could not complete this request.", 503)
        return response["body"]

    def _read_fence(self, workspace, token, connection, grant):
        """Authorize the returned snapshot against the current member and exact credential after network reads."""
        from .hosted import _membership
        with self.repository.transaction(token, workspace) as (cur, row, _actor):
            require(_membership(row), 'read')
            cur.execute("SELECT access_ciphertext,key_id,provider_account_id,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon' AND revoked_at IS NULL", (workspace, connection))
            current = cur.fetchone()
            if (not current or current[2] != grant['providerAccountId']
                    or self.oauth.vault.decrypt(current[0], current[1]) != grant['accessToken']
                    or not has_scopes(current[3], grant.get('scopes') or [])):
                raise AlphaError('The connection changed during this read. Read again after reconnecting.', 409,
                                 code='mastodon_read_changed')

    def read(self, workspace, token, connection, resource):
        if resource == 'health':
            from .hosted import _membership
            with self.repository.transaction(token, workspace) as (cur, row, _actor):
                require(_membership(row), 'read')
                cur.execute("SELECT revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon'", (workspace, connection))
                credential = cur.fetchone()
                if not credential:
                    raise AlphaError('Choose a Mastodon connection in this workspace.', 404)
                if credential[0]:
                    return {'connectionId': connection, 'resource': resource, 'data': {'state': 'reauthorization_required', 'reason': 'Reconnect this account; its token is no longer active.'}}
                cur.execute("SELECT to_regclass('public.pr_mastodon_health') IS NOT NULL")
                if not cur.fetchone()[0]:
                    return {'connectionId': connection, 'resource': resource, 'data': {'state': 'schema_unavailable'}}
                cur.execute("SELECT state,extract(epoch from checked_at),extract(epoch from next_at),failures FROM public.pr_mastodon_health WHERE workspace_id=%s AND connection_id=%s", (workspace, connection))
                observed = cur.fetchone()
                data = ({'state': observed[0], 'checkedAt': float(observed[1]) if observed[1] is not None else None,
                         'nextCheckAt': float(observed[2]), 'failedChecks': observed[3]} if observed else {'state': 'pending', 'checkedAt': None})
            return {'connectionId': connection, 'resource': resource, 'data': data}
        provider, grant, session = self._grant(workspace, token, connection)
        if resource == 'live_events':
            self._scopes(grant, ('read:statuses', 'read:notifications'))
            from .mastodon_streaming import read_window
            window = read_window(provider, session)
            # Recheck current membership/credential after the window before returning
            # private excerpts; revocation during the read must not leak its result.
            self._read_fence(workspace, token, connection, grant)
            return {'connectionId': connection, 'instance': session['instance'], 'resource': resource,
                    **{k: v for k, v in window.items() if k != 'events'}, 'data': window['events']}
        if resource == "capabilities":
            capabilities = discover(provider.transport, session["instance"])
            return {"connectionId": connection, "accountId": grant["providerAccountId"], "permissions": grant["scopes"], "capabilities": capabilities,
                    "privateContentPolicy": "Private content is returned only to this workspace; it is not imported into AI or shared analytics."}
        if resource in ("posts", "analytics"):
            self._scopes(grant, ("read:accounts", "read:statuses"))
            account_id = grant["providerAccountId"].split("@", 1)[0]
            rows = self._result(provider.api(session, "GET", f"/api/v1/accounts/{account_id}/statuses?limit=40&exclude_reblogs=true"))
            if not isinstance(rows, list):
                raise AlphaError("Mastodon returned invalid post data.", 502)
            self._read_fence(workspace, token, connection, grant)
            if resource == "posts":
                return {"connectionId": connection, "instance": session["instance"], "posts": rows, "coverage": "latest 40; not complete history"}
            # Only public/unlisted authored posts may enter this broader analytics response.
            metrics = [{"id": r["id"], "url": r.get("url"), "createdAt": r.get("created_at"),
                        "favourites": r.get("favourites_count"), "boosts": r.get("reblogs_count"), "replies": r.get("replies_count")}
                       for r in rows if isinstance(r, dict) and r.get("id") and r.get("visibility") in ("public", "unlisted")
                       and not r.get("reblog") and str((r.get("account") or {}).get("id")) == account_id]
            profile = self._result(provider.api(session, "GET", "/api/v1/accounts/verify_credentials"))
            self._read_fence(workspace, token, connection, grant)
            from .mastodon_analytics import history
            with self.repository.transaction(token, workspace) as (cur, _row, _actor):
                collected = history(cur, workspace, connection, session['instance'], [r['id'] for r in metrics])
            return {"connectionId": connection, "instance": session["instance"], "followers": profile.get("followers_count"),
                    "following": profile.get("following_count"), "postCount": profile.get("statuses_count"), "posts": metrics,
                    "coverage": "latest 40 public/unlisted posts; counts observed by this instance",
                    "unavailableMetrics": ["impressions", "reach", "demographics"], "historicalTrends": collected}
        spec = READS.get(resource)
        if not spec:
            raise AlphaError("This Mastodon resource is unavailable.", 404)
        self._scopes(grant, spec[1])
        data = self._result(provider.api(session, "GET", spec[0]))
        self._read_fence(workspace, token, connection, grant)
        return {"connectionId": connection, "instance": session["instance"], "resource": resource,
                "data": data, "coverage": "instance-local, bounded page"}

    def preview(self, workspace, token, connection, payload):
        if not isinstance(payload, dict):
            raise AlphaError('Choose a structured Mastodon action.', 400)
        action = payload.get("action")
        provider, grant, session = self._grant(workspace, token, connection)
        capabilities = discover(provider.transport, session["instance"])
        method, path, body, scopes, permission = action_spec(action, payload, capabilities, now=self.clock())
        self._scopes(grant, scopes)
        from .hosted import _membership, audit, throttle
        preview = {"connectionId": connection, "accountId": grant["providerAccountId"], "instance": session["instance"],
                   "action": action, "targetId": payload.get('targetId'), "method": method, "path": path, "body": body, "scopes": list(scopes), "permission": permission}
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), permission)
            if action == 'profile_update' and payload.get('profileMedia'):
                from .mastodon_profile import freeze_images
                if self.service.assets is None:
                    raise AlphaError('Private profile image storage is unavailable.', 503)
                preview['media'] = freeze_images(row[1], payload['profileMedia'])
            fingerprint = digest(preview)
            throttle(cur, "mastodon-preview:" + workspace, 30, 600)
            cur.execute("DELETE FROM public.pr_mastodon_actions WHERE workspace_id=%s AND created_at < now()-interval '7 days' AND status != 'running'", (workspace,))
            cur.execute("INSERT INTO public.pr_mastodon_actions(workspace_id,connection_id,actor_id,action,preview,digest) VALUES(%s,%s,%s,%s,%s::jsonb,%s) RETURNING id::text", (workspace, connection, actor, action, json.dumps(preview), fingerprint))
            action_id = cur.fetchone()[0]
            audit(cur, workspace, actor, "mastodon.action_previewed", action_id, {"action": action, "connectionId": connection})
        return {"actionId": action_id, "digest": fingerprint, "preview": preview, "expiresAt": self.clock() + 600,
                "confirmation": "Approve this exact account, action and content. Automation authority is separate."}

    def saved_preview(self, workspace, token, connection, action_id):
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            from .hosted import _membership
            cur.execute("SELECT preview,digest,status,actor_id::text,extract(epoch from expires_at)::float8 FROM public.pr_mastodon_actions WHERE workspace_id=%s AND connection_id=%s AND id::text=%s", (workspace, connection, action_id))
            stored = cur.fetchone()
            if not stored or stored[3] != actor:
                raise AlphaError('Action preview unavailable.', 404)
            require(_membership(row), stored[0]['permission'])
            if stored[2] != 'preview' or stored[4] <= self.clock():
                raise AlphaError('Prepare a fresh action preview; this preview expired or was already handled.', 409)
            return {'actionId': action_id, 'digest': stored[1], 'preview': stored[0], 'expiresAt': stored[4]}

    def execute(self, workspace, token, connection, action_id, payload):
        if payload.get("confirmed") is not True or not isinstance(payload.get("digest"), str):
            raise AlphaError("Approve the exact Mastodon action preview first.", 403)
        from .hosted import _membership, audit, throttle
        provider, grant, session = self._grant(workspace, token, connection)
        if not provider.production_reviewed:
            raise AlphaError('Mastodon live execution is awaiting production acceptance. Nothing was sent.', 409)
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            cur.execute("SELECT preview,digest,status,receipt,actor_id::text,extract(epoch from expires_at)::float8 FROM public.pr_mastodon_actions WHERE workspace_id=%s AND connection_id=%s AND id::text=%s FOR UPDATE", (workspace, connection, action_id))
            stored = cur.fetchone()
            if not stored or stored[4] != actor:
                raise AlphaError("Action preview unavailable.", 404)
            preview, fingerprint, state, receipt, _, expires = stored
            require(_membership(row), preview["permission"])
            if payload["digest"] != fingerprint or digest(preview) != fingerprint:
                raise AlphaError("The action changed. Prepare and approve a new preview.", 409)
            if state != "preview":
                return {"actionId": action_id, "state": state, "receipt": receipt, "replayed": True}
            if expires <= self.clock() or preview["accountId"] != grant["providerAccountId"]:
                raise AlphaError("This approval expired or the connected account changed.", 409)
            self._scopes(grant, preview["scopes"])
            throttle(cur, "mastodon-instance:" + session["instance"], 250, 300)
            throttle(cur, "mastodon-account:" + workspace + connection, 30, 300)
            cur.execute("UPDATE public.pr_mastodon_actions SET status='running',updated_at=now() WHERE workspace_id=%s AND id::text=%s", (workspace, action_id))
            audit(cur, workspace, actor, "mastodon.action_claimed", action_id, {"action": preview["action"], "connectionId": connection})
        # Claim commits BEFORE any effect. A crash/timeout remains running/uncertain and never resends.
        result = {"state": "uncertain", "reason": "Outcome unknown. Check Mastodon before preparing any new action."}
        try:
            with self.repository.transaction(token, workspace) as (cur, row, actor):
                require(_membership(row), preview["permission"])
                cur.execute("SELECT access_ciphertext,key_id,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon' AND revoked_at IS NULL FOR UPDATE", (workspace, connection))
                active = cur.fetchone()
                if not active or active[2] != preview["accountId"] or self.oauth.vault.decrypt(active[0], active[1]) != grant["accessToken"]:
                    raise AlphaError("The connection changed. No action was sent.", 409)
                if preview["action"] in ("edit", "delete"):
                    original = self._result(provider.api(session, "GET", preview["path"]))
                    if str((original.get("account") or {}).get("id")) + "@" + session["instance"] != preview["accountId"]:
                        raise AlphaError("This post does not belong to the approved account. No action was sent.", 403)
                if preview['action'] == 'profile_update':
                    from .mastodon_profile import approved_images, form_fields
                    from .social_connectors import multipart
                    files = approved_images(self.service, workspace, row[1], preview.get('media', {}))
                    data, content_type = multipart(form_fields(preview['body']), files)
                    response = provider.api(session, preview['method'], preview['path'], data=data,
                                            headers={'Content-Type': content_type, 'Idempotency-Key': action_id})
                else:
                    response = provider.api(session, preview["method"], preview["path"], body=preview["body"],
                                            headers={"Idempotency-Key": action_id})
                result = self._receipt(provider, session, preview, response)
                if preview['action'] in ('native_cancel', 'native_reschedule'):
                    from .mastodon_native import synchronize
                    state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                    synced = synchronize(state, connection, preview, result, actor=actor, action_id=action_id,
                                         fingerprint=fingerprint, now=self.clock())
                    if synced:
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))
                        result['syncedJobIds'] = synced
                cur.execute("UPDATE public.pr_mastodon_actions SET status=%s,receipt=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id::text=%s AND status='running'", (result["state"], json.dumps(result), workspace, action_id))
                audit(cur, workspace, actor, "mastodon.action_result", action_id, {"action": preview["action"], "state": result["state"]})
        except AlphaError:
            # Includes failures while proving ownership. Conservatively do not guess whether dispatch occurred.
            with self.repository.connection_factory() as db, db.cursor() as cur:
                cur.execute("UPDATE public.pr_mastodon_actions SET status='uncertain',receipt=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id::text=%s AND status='running'", (json.dumps(result), workspace, action_id))
        return {"actionId": action_id, **result}

    @staticmethod
    def _receipt(provider, session, preview, response):
        status, body = response.get("status"), response.get("body")
        if status in (400, 401, 403, 404, 422, 429):
            return {"state": "rejected", "httpStatus": status, "reason": "Mastodon rejected this action; review permissions, limits or retry after reset.",
                    "retryAfter": response.get("headers", {}).get("retry-after")}
        if status not in (200, 202, 204):
            return {"state": "uncertain", "reason": "No conclusive server acceptance. Do not resend."}
        action = preview["action"]
        result = {"state": "accepted", "httpStatus": status, "instance": session["instance"], "action": action}
        if action == 'profile_update' and (not isinstance(body, dict) or str(body.get('id')) + '@' + session['instance'] != preview['accountId']):
            return {'state': 'uncertain', 'reason': 'The profile response did not identify the approved account. Do not resend.'}
        if isinstance(body, dict):
            result["reference"] = str(body.get("id", ""))
            # URLs are evidence only when this instance returned them, never synthesized publication claims.
            url = body.get("url")
            if isinstance(url, str) and url.startswith("https://" + session["instance"] + "/"):
                result["url"] = url
        if action in ("delete", "native_cancel"):
            checked = provider.api(session, "GET", preview["path"])
            if checked.get("status") == 404:
                result.update(state="verified", verification="provider_lookup_absent")
        elif action in ("native_schedule", "native_reschedule"):
            reference = result.get("reference")
            if action == 'native_reschedule' and reference != preview['path'].rsplit('/', 1)[-1]:
                return {'state': 'uncertain', 'reason': 'The reschedule response identified another schedule. Do not resend.'}
            if reference and ID.fullmatch(reference):
                checked = provider.api(session, "GET", "/api/v1/scheduled_statuses/" + reference)
                value = checked.get("body")
                from .mastodon_native import same_instant
                params = value.get('params') if isinstance(value, dict) and isinstance(value.get('params'), dict) else {}
                content_matches = action == 'native_reschedule' or (
                    params.get('text') == preview['body'].get('status')
                    and params.get('visibility') == preview['body'].get('visibility', 'public')
                    and (params.get('spoiler_text') or '') == preview['body'].get('spoiler_text', '')
                    and params.get('sensitive', False) is preview['body'].get('sensitive', False))
                if (checked.get("status") == 200 and isinstance(value, dict) and str(value.get("id")) == reference
                        and same_instant(value.get('scheduled_at'), preview['body'].get('scheduled_at')) and content_matches):
                    result.update(state="verified", verification="native_schedule_lookup", scheduledAt=value.get("scheduled_at"),
                                  publication="pending; scheduling is not publication")
        return result


def handle(app, environ, start_response, service, token, method, parts):
    # /api/workspaces/{workspace}/channels/{connection}/mastodon/{resource|actions}
    manager = MastodonManagement(service)
    workspace, connection = parts[2], parts[4]
    if len(parts) == 7 and method == "GET":
        return app._json(start_response, 200, manager.read(workspace, token, connection, parts[6]))
    if len(parts) == 7 and parts[6] == "actions" and method == "POST":
        return app._json(start_response, 201, manager.preview(workspace, token, connection, app._body(environ)))
    if len(parts) == 8 and parts[6] == 'actions' and method == 'GET':
        return app._json(start_response, 200, manager.saved_preview(workspace, token, connection, parts[7]))
    if len(parts) == 9 and parts[6] == "actions" and parts[8] == "approve" and method == "POST":
        return app._json(start_response, 200, manager.execute(workspace, token, connection, parts[7], app._body(environ)))
    raise AlphaError("Mastodon route unavailable.", 404)

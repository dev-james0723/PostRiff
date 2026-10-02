"""Bounded, durable comment refresh. Provider text is data, never instructions."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from postriff_alpha.domain import AlphaError, clean
from .permissions import require
from .inbox_providers import adapter_for

MAX_CONNECTIONS = 2
MAX_POSTS = 8
MAX_PAGES = 6
MAX_ITEMS = 150
COOLDOWN_SECONDS = 60
LEASE_SECONDS = 180
POST_HORIZON_SECONDS = 90 * 86400


def eligible_posts(jobs, connection_id, provider, now, *, limit=MAX_POSTS):
    found = {}
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict) or job.get("state") != "verified":
            continue
        manifest = job.get("manifest") or {}
        if manifest.get("channelId") != connection_id or str(manifest.get("platform", "")).lower() != provider:
            continue
        reference = str(job.get("providerReference") or "")
        verified_at = (job.get("verification") or {}).get("at")
        if not reference.isdigit() or not isinstance(verified_at, (int, float)) or not now - POST_HORIZON_SECONDS <= verified_at <= now + 300:
            continue
        found[reference] = max(verified_at, found.get(reference, 0))
    return [reference for reference, _ in sorted(found.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def parse_threads_page(body):
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("Invalid provider page")
    seen, items = set(), []
    for item in body["data"][:MAX_ITEMS + 1]:
        if not isinstance(item, dict) or not str(item.get("id") or "").isdigit():
            continue
        ident = str(item["id"])
        if ident not in seen:
            seen.add(ident)
            items.append(item)
    cursors = (body.get("paging") or {}).get("cursors") or {}
    after = cursors.get("after") if isinstance(cursors, dict) else None
    return items[:MAX_ITEMS], after if isinstance(after, str) and 0 < len(after) <= 256 else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _state(raw):
    return json.loads(raw) if isinstance(raw, str) else raw


class AudienceSync:
    def __init__(self, audience):
        self.audience = audience
        self.repository = audience.repository

    def manual(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self.audience._member(row), "read")
            cur.execute("SELECT c.connection_id,c.provider FROM public.pr_encrypted_credentials c JOIN public.pr_channel_capabilities cap ON cap.workspace_id=c.workspace_id AND cap.connection_id=c.connection_id AND cap.capability='comments_read' AND cap.level='Direct' LEFT JOIN public.pr_audience_sync s ON s.workspace_id=c.workspace_id AND s.connection_id=c.connection_id WHERE c.workspace_id=%s AND c.revoked_at IS NULL ORDER BY s.last_attempt_at NULLS FIRST,c.connection_id LIMIT %s", (workspace_id, MAX_CONNECTIONS))
            connections = cur.fetchall()
        if not connections:
            return {"availability": "unavailable", "reason": "No connected account has verified Direct comment reading.", "connections": [], "lastSyncAt": None}
        return self._many(workspace_id, connections)

    def scheduled(self, max_connections=MAX_CONNECTIONS):
        if not self.audience.sync_enabled:
            return {"availability": "disabled", "processed": 0}
        limit = min(MAX_CONNECTIONS, max(1, int(max_connections)))
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT c.workspace_id::text,c.connection_id,c.provider FROM public.pr_encrypted_credentials c JOIN public.pr_channel_capabilities cap ON cap.workspace_id=c.workspace_id AND cap.connection_id=c.connection_id AND cap.capability='comments_read' AND cap.level='Direct' LEFT JOIN public.pr_audience_sync s ON s.workspace_id=c.workspace_id AND s.connection_id=c.connection_id WHERE c.provider='threads' AND c.revoked_at IS NULL AND (s.lease_until IS NULL OR s.lease_until < now()) AND (s.last_attempt_at IS NULL OR s.last_attempt_at < now()-interval '5 minutes') ORDER BY s.last_attempt_at NULLS FIRST,c.workspace_id,c.connection_id LIMIT %s", (limit,))
                connections = cur.fetchall()
        outcomes = [self.one(wid, cid, provider) for wid, cid, provider in connections]
        return {"availability": "available", "processed": len(outcomes), "connections": outcomes}

    def _many(self, workspace_id, connections):
        results = [self.one(workspace_id, cid, provider) for cid, provider in connections]
        return {"availability": "available" if all(r["availability"] == "available" for r in results) else "unavailable",
                "checkedPosts": sum(r.get("checkedPosts", 0) for r in results),
                "pagesRead": sum(r.get("pagesRead", 0) for r in results),
                "ingested": sum(r.get("ingested", 0) for r in results),
                "updated": sum(r.get("updated", 0) for r in results), "tombstoned": 0,
                "lastSyncAt": max((r.get("lastSyncAt") or 0 for r in results), default=0) or None,
                "connections": results}

    def _claim(self, workspace_id, connection_id, provider, now):
        lease = str(uuid.uuid4())
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("INSERT INTO public.pr_audience_sync(workspace_id,connection_id,provider) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (workspace_id, connection_id, provider))
                cur.execute("UPDATE public.pr_audience_sync SET lease_id=%s,lease_until=to_timestamp(%s),updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND (lease_until IS NULL OR lease_until<now()) AND (last_attempt_at IS NULL OR last_attempt_at<to_timestamp(%s)) RETURNING cursor_state,extract(epoch from last_synced_at)",
                            (lease, now + LEASE_SECONDS, workspace_id, connection_id, now - COOLDOWN_SECONDS))
                row = cur.fetchone()
                if row:
                    return lease, _state(row[0]), float(row[1]) if row[1] is not None else None
                cur.execute("SELECT extract(epoch from last_synced_at),extract(epoch from lease_until),extract(epoch from last_attempt_at) FROM public.pr_audience_sync WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
                previous = cur.fetchone()
        return None, {}, float(previous[0]) if previous and previous[0] is not None else None

    def _live(self, cur, workspace_id, connection_id):
        cur.execute("SELECT c.provider FROM public.pr_encrypted_credentials c JOIN public.pr_workspaces w ON w.id=c.workspace_id AND NOT (w.state ? 'accountDeletion') JOIN public.pr_channel_capabilities cap ON cap.workspace_id=c.workspace_id AND cap.connection_id=c.connection_id AND cap.capability='comments_read' AND cap.level='Direct' WHERE c.workspace_id=%s AND c.connection_id=%s AND c.revoked_at IS NULL", (workspace_id, connection_id))
        row = cur.fetchone()
        return row[0] if row else None

    def one(self, workspace_id, connection_id, provider):
        now = self.audience.clock()
        inbox_adapter = adapter_for(provider)
        if inbox_adapter is None or self.audience.transport is None:
            return {"connectionId": connection_id, "availability": "not_supported", "reason": "Comment sync is supported for verified Threads connections only.", "lastSyncAt": None}
        adapter = self.audience.oauth.providers.get(provider)
        if adapter is None or not adapter.production_reviewed:
            return {"connectionId": connection_id, "availability": "unavailable", "reason": "Provider review is not verified.", "lastSyncAt": None}
        lease, cursor_state, previous_sync = self._claim(workspace_id, connection_id, provider, now)
        if not lease:
            return {"connectionId": connection_id, "availability": "cooldown", "reason": "A refresh is running or the server cooldown is active.", "lastSyncAt": previous_sync, "retryAfterSeconds": COOLDOWN_SECONDS}
        response = {"connectionId": connection_id, "availability": "unavailable", "reason": "No provider attempt was made.",
                    "checkedPosts": 0, "pagesRead": 0, "ingested": 0, "updated": 0, "tombstoned": 0, "lastSyncAt": previous_sync}
        attempted = False
        collected = []
        next_state = dict(cursor_state) if isinstance(cursor_state, dict) else {}
        try:
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s AND NOT state ? 'accountDeletion'", (workspace_id,))
                    row = cur.fetchone()
                    if not row or self._live(cur, workspace_id, connection_id) != provider:
                        raise AlphaError("Connection unavailable.", 409)
                    jobs = (_state(row[0]).get("phase2") or {}).get("jobs") or []
            posts = eligible_posts(jobs, connection_id, provider, now)
            if not posts:
                response.update(availability="unavailable", reason="No verified recent Threads posts are available to check.")
                return response
            grant = self.audience.oauth.token_for_worker(workspace_id, connection_id)
            if not set(adapter.capability_scopes("comments_read")).issubset(grant.get("scopes") or []):
                raise AlphaError("The comment-read permission is no longer in the current grant.", 409)
            seen = set()
            for post in posts:
                if response["pagesRead"] >= MAX_PAGES or len(collected) >= MAX_ITEMS:
                    break
                response["checkedPosts"] += 1
                afters = [None]
                saved = next_state.get(post)
                if isinstance(saved, str) and 0 < len(saved) <= 256:
                    afters.append(saved)
                while afters and response["pagesRead"] < MAX_PAGES and len(collected) < MAX_ITEMS:
                    after = afters.pop(0)
                    attempted = True
                    provider_result = inbox_adapter.list_comments(post, grant["accessToken"], self.audience.transport, after=after, limit=50)
                    response["pagesRead"] += 1
                    status = provider_result.get("status") if isinstance(provider_result, dict) else None
                    if status != 200:
                        response.update(inbox_adapter.error(status))
                        return response
                    items, next_cursor = parse_threads_page(provider_result.get("body"))
                    for item in items:
                        ident = str(item["id"])
                        if ident not in seen and len(collected) < MAX_ITEMS:
                            seen.add(ident)
                            collected.append((post, item))
                    if next_cursor and next_cursor != after:
                        next_state[post] = next_cursor
                        if not afters and response["pagesRead"] < MAX_PAGES:
                            afters.append(next_cursor)
                    else:
                        next_state.pop(post, None)
            response.update(availability="available", reason=None)
            return response
        except (AlphaError, ValueError, TypeError) as error:
            response.update(availability="unavailable", reason=str(error)[:180], errorCode="provider_unavailable" if attempted else "connection_unavailable")
            return response
        except Exception:
            # Network and provider transport failures are expected at this boundary. Do not
            # expose an exception containing tokens or comment content to the Inbox.
            response.update(availability="unavailable", reason="Threads refresh failed; comments were left unchanged.",
                            errorCode="provider_transport_error" if attempted else "connection_unavailable")
            return response
        finally:
            finished = self.audience.clock()
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT lease_id FROM public.pr_audience_sync WHERE workspace_id=%s AND connection_id=%s FOR UPDATE", (workspace_id, connection_id))
                    row = cur.fetchone()
                    if row and str(row[0]) == lease:
                        if response["availability"] == "available" and self._live(cur, workspace_id, connection_id) == provider:
                            for post, item in collected:
                                author = clean(item.get("username") or "", 100)
                                body = clean(item.get("text") or "", 4000)
                                permalink = inbox_adapter.source_permalink(item.get("permalink"))
                                timestamp = _timestamp(item.get("timestamp"))
                                cur.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text,permalink,created_at_provider) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT DO NOTHING RETURNING id", (workspace_id, connection_id, provider, post, str(item["id"]), author, body, permalink, timestamp))
                                if cur.fetchone():
                                    response["ingested"] += 1
                                else:
                                    cur.execute("UPDATE public.pr_audience_threads SET author_handle=%s,text=%s,permalink=%s,tombstoned_at=NULL WHERE workspace_id=%s AND provider=%s AND provider_comment_id=%s AND (author_handle,text,permalink,tombstoned_at) IS DISTINCT FROM (%s,%s,%s,NULL)", (author, body, permalink, workspace_id, provider, str(item["id"]), author, body, permalink))
                                    response["updated"] += cur.rowcount
                            response["lastSyncAt"] = finished if attempted else previous_sync
                        elif response["availability"] == "available":
                            response.update(availability="unavailable", reason="Connection changed during refresh.", errorCode="connection_changed")
                        cur.execute("UPDATE public.pr_audience_sync SET last_attempt_at=to_timestamp(%s),last_synced_at=CASE WHEN %s THEN to_timestamp(%s) ELSE last_synced_at END,cursor_state=%s::jsonb,last_result=%s::jsonb,last_error_code=%s,lease_id=NULL,lease_until=NULL,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND lease_id=%s",
                                    (finished, response["availability"] == "available" and attempted, finished, json.dumps(next_state), json.dumps({k: v for k, v in response.items() if k != "lastSyncAt"}), response.get("errorCode"), workspace_id, connection_id, lease))
                    else:
                        response.update(availability="unavailable", reason="The workspace or refresh lease changed during refresh.", errorCode="connection_changed")

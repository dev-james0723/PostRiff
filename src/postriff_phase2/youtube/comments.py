"""Preserve thread, top-level comment, reply, video and channel IDs in Rafii's existing Inbox."""
from datetime import datetime


def ingest(connection_factory, workspace, connection, channel_id, threads, now):
    with connection_factory() as db, db.cursor() as cur:
        for thread in threads:
            snippet = thread.get('snippet') or {}
            # allThreadsRelatedToChannelId can return a comment written by the channel elsewhere.
            if snippet.get('channelId') != channel_id:
                continue
            top = snippet.get('topLevelComment') or {}
            comments = [top, *((thread.get('replies') or {}).get('comments') or [])]
            for comment in comments:
                value = comment.get('snippet') or {}
                if not comment.get('id'):
                    continue
                created = value.get('publishedAt')
                try:
                    created = datetime.fromisoformat(created.replace('Z', '+00:00')) if created else None
                except (TypeError, ValueError):
                    created = None
                cur.execute('INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text,created_at_provider,provider_thread_id,provider_parent_id,provider_channel_id,moderation_state) VALUES(%s,%s,\'youtube\',%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,provider,provider_comment_id) DO UPDATE SET text=excluded.text,ingested_at=now(),moderation_state=excluded.moderation_state,provider_parent_id=excluded.provider_parent_id,provider_thread_id=excluded.provider_thread_id', (workspace, connection, snippet.get('videoId') or value.get('videoId') or '', comment['id'], value.get('authorDisplayName', ''), value.get('textOriginal') or value.get('textDisplay', ''), created, thread['id'], value.get('parentId'), channel_id, value.get('moderationStatus', 'published')))


def reply_target(connection_factory, workspace, thread_id):
    with connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT connection_id,provider_comment_id,provider_parent_id FROM public.pr_audience_threads WHERE workspace_id=%s AND id::text=%s AND provider='youtube' AND tombstoned_at IS NULL AND ingested_at>now()-interval '30 days'", (workspace, thread_id))
        row = cur.fetchone()
    return {'connectionId': row[0], 'commentId': row[2] or row[1]} if row else None

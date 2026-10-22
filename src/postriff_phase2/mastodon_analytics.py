"""Bounded history of legitimately collected native counts; no content or invented reach."""
import math
from datetime import datetime, timezone

from .mastodon_protocol import ID

METRICS = ('likes', 'reposts', 'replies', 'quotes')
OFFSETS = ('t0', '1h', '24h', '7d', 'backfill')


def history(cur, workspace, connection, instance, public_ids):
    ids = [str(x) for x in public_ids if ID.fullmatch(str(x))][:40]
    if not ids:
        return {'readings': [], 'trends': [], 'truncated': False, 'coverage': 'No current public/unlisted posts in the latest account page.'}
    cur.execute("SELECT provider_post_id,metric,value,extract(epoch from observed_at),read_offset FROM public.pr_metric_observations WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon' AND provider_post_id=ANY(%s::text[]) AND metric=ANY(%s::text[]) AND availability='available' AND observed_at >= now()-interval '90 days' AND source_endpoint LIKE %s ORDER BY observed_at,id LIMIT 501",
                (workspace, connection, ids, list(METRICS), 'https://' + instance + '/api/v1/statuses/%'))
    rows = cur.fetchall()
    readings = []
    for post, metric, value, observed, offset in rows[:500]:
        try:
            numeric, stamp = float(value), float(observed)
            if (not ID.fullmatch(str(post)) or metric not in METRICS or offset not in (*OFFSETS, None)
                    or not math.isfinite(numeric) or not numeric.is_integer() or not 0 <= numeric <= 2**53 - 1
                    or not math.isfinite(stamp) or stamp <= 0): continue
            at = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError, OSError): continue
        readings.append({'postId': str(post), 'metric': metric, 'value': int(numeric), 'observedAt': at, 'readOffset': offset})
    groups = {}
    for row in readings:
        groups.setdefault((row['postId'], row['metric']), []).append(row)
    trends = [{'postId': post, 'metric': metric, 'from': values[0]['observedAt'], 'to': values[-1]['observedAt'],
               'first': values[0]['value'], 'latest': values[-1]['value'], 'change': values[-1]['value'] - values[0]['value']}
              for (post, metric), values in groups.items() if len(values) >= 2 and values[-1]['observedAt'] != values[0]['observedAt']]
    return {'readings': readings, 'trends': trends, 'truncated': len(rows) > 500,
            'coverage': 'Up to 500 numeric readings over 90 days for currently public/unlisted posts in the latest 40 account posts. Counts observed by this instance; changes within a post are not cross-post comparisons.'}

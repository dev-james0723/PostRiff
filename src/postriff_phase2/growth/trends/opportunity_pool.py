"""Stored, bounded Home/Weekly selection; no scores, GET writes or planned-slot changes."""
from ... import suggestions
from . import opportunities
from .notifications import COOLDOWN_SECONDS

SCAN_LIMIT = 20
OUTPUT_LIMIT = 3


def eligible(row, item, trend, state, now, surface):
    p = row['payload']
    if (item['state'] != 'ready' or item['verification_state'] != 'verified'
            or not item['angles'] or not item['platform_targets']
            or item['workspace_fit']['sufficient'] is not True
            or opportunities.epoch(item['expires_at']) <= now):
        return False
    fit = item['workspace_fit']
    if any(isinstance(v, dict) and v.get('assessment') == 'concern' for v in fit.values()):
        return False
    if surface == 'home' and (p.get('qualified') is not True
            or fit['confidence']['assessment'] != 'supported'
            or trend['inferred']['calibration_state'] != 'qualified'
            or trend['inferred']['confidence'] != 'high'):
        return False
    old = (state.get('raffi') or {}).get('suggestions', [])
    candidate = {'kind': 'trend_opportunity', 'evidence': [{'id': item['id']}]}
    # The existing suggestion cooldown applies across changed source revisions.
    if suggestions._recently_dismissed(old, candidate, now):
        return False
    return not any(s.get('kind') == 'trend_opportunity'
        and any(e.get('id') == item['id'] for e in s.get('evidence', []))
        and (s.get('status') == 'accepted' or (s.get('status') == 'snoozed' and s.get('snoozedUntil', 0) > now)) for s in old)


def quiet_ids(store, cur, wid, actor, ids, now):
    """No source payloads from expired nodes are read to reconstruct a view history.

    A bounded incomplete exposure page abstains from proactive selection. The
    durable content-free dismissal rows preserve the existing seven-day cooldown.
    """
    cur.execute("""SELECT DISTINCT object_id::text FROM public.pr_trend_opportunity_decisions
        WHERE workspace_id=%s AND object_id=ANY(%s::uuid[]) AND decision='dismiss'
        AND created_at>=%s::timestamptz""", (wid, ids, opportunities.iso(now-suggestions.DISMISS_COOLDOWN)))
    quiet = {r[0] for r in cur.fetchall()}
    page = store.list_projections(wid, actor, kind='exposure', limit=100,
        as_of=opportunities.iso(now), filters={'since': opportunities.iso(now-COOLDOWN_SECONDS)}, cursor=cur)
    if page.get('next_key'):
        return set(ids), False
    for row in page['items']:
        payload = row['payload']
        try:
            recent = now-COOLDOWN_SECONDS <= opportunities.epoch(payload['recorded_at']) <= now
        except (KeyError, ValueError, TypeError):
            return set(ids), False
        if row.get('validity') == 'valid' and recent:
            quiet.add(payload.get('opportunity_id'))
    return quiet, True

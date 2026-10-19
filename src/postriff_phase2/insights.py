"""Analytics with native definitions (architecture §15): store observations with provider,
definition version, observation/ingestion time, availability; present `Unavailable`, never
zero; rates with numerator/denominator; like-for-like cohorts; < 3 comparable → insufficient.
"""
from fractions import Fraction
import math
from urllib.parse import quote, urlencode
from postriff_alpha.domain import AlphaError
from .providers import GRAPH_VERSION
from . import locales

DEFINITION_VERSION = "2026-09"
FAMILIES = {
    "attention": ("views", "reach"),
    "resonance": ("likes", "comments", "replies", "reposts", "quotes", "shares", "saved"),
}
INSIGHT_METRICS = {"threads": ("views", "likes", "replies", "reposts", "quotes", "shares"), "instagram": ("reach", "views", "likes", "comments", "saved", "shares")}
INSIGHT_METRICS['pinterest'] = ('impressions', 'saves', 'pin_clicks', 'outbound_clicks')
MIN_COMPARABLE = 3
# Cross-post comparisons (coworker performance, campaign triggers) read every post at the same age: the +24h scheduled
# reading, or a legacy row with no offset. Values read at t0, +1h, +7d or by a backfill are not like-for-like.
COMPARISON_BASIS = "24h"
# Event triggers that must fire within a day of posting (campaign "strong post", withinDays >= 1) compare at +1h.
TRIGGER_BASIS = "1h"
_READ_OFFSET = {"present": False, "checked": None}
READ_OFFSET_RECHECK_SECONDS = 300


def read_offset_column(cur, now=None):
    """SQL for an observation's read offset: the column once migration 035 is applied, else NULL. Presence is cached
    for the process (a column is never dropped); absence is re-checked at most every five minutes, so databases
    without 032 do not pay a catalog query per read."""
    import time as _time
    now = _time.monotonic() if now is None else now
    checked = _READ_OFFSET["checked"]
    if not _READ_OFFSET["present"] and (checked is None or now - checked >= READ_OFFSET_RECHECK_SECONDS):
        cur.execute("SELECT 1 FROM pg_attribute WHERE attrelid='public.pr_metric_observations'::regclass AND attname='read_offset' AND NOT attisdropped")
        _READ_OFFSET["present"] = cur.fetchone() is not None
        _READ_OFFSET["checked"] = now
    return "o.read_offset" if _READ_OFFSET["present"] else "NULL::text"


def insights_endpoint(provider, provider_post_id):
    base = "https://graph.threads.net" if provider == "threads" else "https://graph.instagram.com"
    return f"{base}/{GRAPH_VERSION}/{quote(provider_post_id)}/insights"


def fetch_post_insights(transport, access_token, provider, provider_post_id, *, provider_adapter=None, period_start=None, now=None):
    """One insights GET, no database. {"status", "found": {metric: value}, "endpoint"}; transport errors propagate."""
    if provider == 'pinterest':
        if provider_adapter is None:
            raise AlphaError('Pinterest analytics requires bound provider custody.', 503)
        return provider_adapter.pin_analytics(access_token, provider_post_id, start_at=period_start, end_at=now)
    metrics = INSIGHT_METRICS[provider]
    endpoint = insights_endpoint(provider, provider_post_id)
    response = transport("GET", endpoint + "?" + urlencode({"metric": ",".join(metrics), "access_token": access_token}))
    found = {}
    if response.get("status") == 200:
        for item in (response.get("body") or {}).get("data", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            values = item.get("values") or []
            total = item.get("total_value", {}).get("value") if isinstance(item.get("total_value"), dict) else None
            value = total if total is not None else (values[0].get("value") if values and isinstance(values[0], dict) else None)
            if name in metrics and type(value) in (int, float) and math.isfinite(value) and value >= 0:
                found[name] = value
    return {"status": response.get("status"), "found": found, "endpoint": endpoint}


def record_observations(cur, workspace_id, connection_id, provider, provider_post_id, job_id, found, endpoint, now, read_offset=None, period_start=None):
    """One row per native metric: available with its value, else unavailable (never zero). `read_offset` and
    `period_start` are written only when given, so callers on databases without migration 035 are unaffected."""
    recorded = []
    extra_cols = ",read_offset,period_start" if read_offset is not None else ""
    extra_vals = ",%s,to_timestamp(%s)" if read_offset is not None else ""
    for metric in INSIGHT_METRICS[provider]:
        available = type(found.get(metric)) in (int, float) and math.isfinite(found[metric]) and found[metric] >= 0
        definition = 'pinterest-pin-utc-window-v1' if provider == 'pinterest' else DEFINITION_VERSION
        params = [workspace_id, connection_id, provider, provider_post_id, job_id, metric, definition, found.get(metric) if available else None, "available" if available else "unavailable", now, endpoint]
        if read_offset is not None:
            params += [read_offset, period_start]
        cur.execute(f"INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,source_endpoint{extra_cols}) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'count',%s,to_timestamp(%s),%s{extra_vals})", params)
        recorded.append({"metric": metric, "availability": "available" if available else "unavailable"})
    return recorded


def ingest_post_insights(cur, transport, oauth, workspace_id, connection_id, provider, provider_post_id, job_id, now):
    """Server-only: read native insights for a post PostRiff created; record availability per metric."""
    metrics = INSIGHT_METRICS.get(provider)
    if not metrics:
        cur.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,source_endpoint) VALUES(%s,%s,%s,%s,%s,'all',%s,NULL,'count','not_supported',to_timestamp(%s),'')", (workspace_id, connection_id, provider, provider_post_id, job_id, DEFINITION_VERSION, now))
        return {"provider": provider, "availability": "not_supported"}
    extra = {}
    if provider == 'pinterest':
        from .pinterest_analytics import enabled
        if not enabled(oauth.providers.get(provider)):
            raise AlphaError('Pinterest analytics is not enabled for this integration.', 403)
    grant = oauth.token_for_worker(workspace_id, connection_id)
    if provider == 'pinterest':
        extra = {'provider_adapter': oauth._provider_for_access(provider, grant['accessToken']), 'period_start': now, 'now': now}
    fetched = fetch_post_insights(transport, grant["accessToken"], provider, provider_post_id, **extra)
    if provider == 'pinterest' and fetched.get('outcome') not in ('success', 'no_data'):
        return {"provider": provider, "status": fetched["status"], "outcome": "read_failed", "recorded": []}
    recorded = record_observations(cur, workspace_id, connection_id, provider, provider_post_id, job_id, fetched["found"], fetched["endpoint"], now)
    return {"provider": provider, "status": fetched["status"], "recorded": recorded,
            **({"outcome": fetched['outcome']} if provider == 'pinterest' else {})}


def rate(numerator, denominator):
    if numerator is None or denominator is None:
        return {"value": None, "display": "Unavailable", "numerator": numerator, "denominator": denominator}
    if denominator == 0:
        return {"value": None, "display": "undefined (denominator 0)", "numerator": numerator, "denominator": denominator}
    return {"value": str(Fraction(int(numerator), int(denominator))), "display": f"{numerator}/{denominator}", "numerator": numerator, "denominator": denominator}


def latest_observations(cur, workspace_id, basis=None):
    """Per post and metric: the latest available reading, else the latest reading. Scheduled reads (growth Phase 0)
    take several readings per post; a later reading that lacks a metric must not hide a real earlier value.
    The last column is the reading's offset (t0/1h/24h/7d/backfill, or None); databases without migration 035
    return None. With `basis`, only readings taken at that offset (or legacy rows
    without one) are considered, so every post is read at the same age."""
    offset = read_offset_column(cur)
    period = "extract(epoch from o.period_start)" if offset != "NULL::text" else "NULL::numeric"
    where = "" if basis is None else f" AND coalesce({offset}, %s)=%s"
    params = (workspace_id,) if basis is None else (workspace_id, basis, basis)
    cur.execute(f"SELECT DISTINCT ON (provider,connection_id,provider_post_id,job_id,metric) provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,extract(epoch from observed_at),extract(epoch from ingested_at),connection_id,{offset},{period} FROM public.pr_metric_observations o WHERE workspace_id=%s" + where + " ORDER BY provider,connection_id,provider_post_id,job_id,metric,(availability='available') DESC,observed_at DESC,ingested_at DESC,id DESC", params)
    return cur.fetchall()


def latest_read_outcomes(cur, workspace_id, basis=None):
    """Safe workspace-scoped read receipts, including a first failure with no observations.

    Migration 035 is optional. A savepoint keeps an absent/older queue schema from
    poisoning the caller's transaction or hiding already recorded native metrics.
    """
    if cur is None:
        return [], 'unavailable'
    mark = 'analytics_read_outcomes'
    try:
        cur.execute(f'SAVEPOINT {mark}')
    except Exception:  # noqa: BLE001 - old schemas and lightweight cursors remain compatible
        return [], 'unavailable'
    try:
        params = (workspace_id,) if basis is None else (workspace_id, basis)
        window = '' if basis is None else ' AND read_offset=%s'
        cur.execute("""SELECT DISTINCT ON (provider,connection_id,provider_post_id,job_id)
                       provider,connection_id,provider_post_id,job_id,status,failure_class,last_http_status,
                       extract(epoch from coalesce(observed_at,updated_at)),read_offset
                       FROM public.pr_metric_reads WHERE workspace_id=%s AND attempts>0
                       AND (status IN ('done','unavailable','dead') OR
                            (status IN ('pending','claimed') AND failure_class IS NOT NULL))""" + window +
                    " ORDER BY provider,connection_id,provider_post_id,job_id,coalesce(observed_at,updated_at) DESC,updated_at DESC,id DESC", params)
        rows = cur.fetchall()
        readings = []
        for provider, connection, post, job, status, failure, http, at, offset in rows:
            outcome = ('no_data' if failure == 'no_data' else 'success') if status == 'done' else 'read_failed'
            readings.append({'provider': provider, 'connectionId': connection, 'providerPostId': post,
                             'jobId': job, 'outcome': outcome, 'observedAt': float(at), 'readOffset': offset})
        cur.execute(f'RELEASE SAVEPOINT {mark}')
        return readings, 'available'
    except Exception:  # noqa: BLE001 - no provider body, SQL error text or credential is returned
        try:
            cur.execute(f'ROLLBACK TO SAVEPOINT {mark}')
            cur.execute(f'RELEASE SAVEPOINT {mark}')
        except Exception:  # noqa: BLE001
            pass
        return [], 'unavailable'


def summary(cur, workspace_id, jobs, now, basis=None):
    """Per-post rows with native metrics; families only group, never sum across providers. Display uses the
    latest values (basis None); anything comparing posts passes basis=COMPARISON_BASIS."""
    rows = latest_observations(cur, workspace_id, basis)
    posts = {}
    for provider, post_id, job_id, metric, version, value, unit, availability, observed, ingested, connection_id, read_offset, *period in rows:
        post = posts.setdefault((provider, connection_id, post_id, job_id), {"provider": provider, "providerPostId": post_id, "jobId": job_id, "connectionId": connection_id, "metrics": {}, "freshness": {"observedAt": float(observed), "ingestedAt": float(ingested)}, "definitionVersion": version})
        if availability == "available" and (value is None or not math.isfinite(float(value)) or value < 0):
            availability = "unavailable"
        # readOffset says how long after publishing this value was read; +1h and +7d values are not like-for-like.
        post["metrics"][metric] = {"value": float(value) if availability == "available" else None, "display": (str(int(value)) if value is not None and float(value).is_integer() else str(value)) if availability == "available" else "Unavailable", "availability": availability, "unit": unit, "nativeName": metric, "readOffset": read_offset, "observedAt": float(observed), "ingestedAt": float(ingested), "periodStart": float(period[0]) if period and period[0] is not None else None}
        post["metrics"][metric]["definitionVersion"] = version
    read_outcomes, read_outcome_availability = latest_read_outcomes(cur, workspace_id, basis)
    outcome_index = {(r['provider'], r['connectionId'], r['providerPostId'], r['jobId']): r for r in read_outcomes}
    job_index = {j.get("id"): j for j in jobs if j.get("id") and j.get("providerReference")}
    items = []
    for post in posts.values():
        latest_read = outcome_index.get((post['provider'], post['connectionId'], post['providerPostId'], post['jobId']))
        if latest_read:
            post['latestRead'] = latest_read
        job = job_index.get(post["jobId"], {})
        binding = job.get("manifest", {})
        if (str(job.get("providerReference")) != post["providerPostId"] or binding.get("channelId") != post["connectionId"]
                or str(binding.get("platform", "")).lower() != post["provider"]):
            job = {}
        manifest = job.get("manifest", {})
        post["publishedState"] = job.get("state", "unknown")
        post["contentOrigin"] = "postriff_published" if job else "unknown"
        post["platform"] = manifest.get("platform")
        language = manifest.get("payload", {}).get("language")
        post["language"] = locales.canonical(language) or language  # English and en are one cohort
        post["contentTypeId"] = manifest.get("contentType", {}).get("id")
        post["cohort"] = {"provider": post["provider"], "account": post["connectionId"], "window": basis,
                          "language": post["language"], "contentTypeId": post["contentTypeId"], "definitionVersion": post["definitionVersion"]}
        engagement = post["metrics"].get("likes", {}).get("value")
        reach = (post["metrics"].get("reach") or post["metrics"].get("views") or {}).get("value")
        post["rates"] = {"likesPerView": rate(int(engagement) if engagement is not None else None, int(reach) if reach is not None else None)}
        items.append(post)
    # Connections without any observation are reported explicitly, never as zeros.
    return {"posts": items, "readOutcomes": read_outcomes, "readOutcomeAvailability": read_outcome_availability,
            "families": FAMILIES, "basis": basis, "rules": {"missing": "Unavailable, never 0", "crossPlatformReach": "never unique people; providers are listed side by side", "comparison": "same account, provider, window, language, content type and definition version only", "insufficientSample": f"< {MIN_COMPARABLE} comparable posts"}, "freshnessNow": now}


def compare(posts, metric):
    """Like-for-like comparison; refuses mixed cohorts; insufficient sample under MIN_COMPARABLE."""
    if not posts:
        return {"interpretation": "no_data", "sampleSize": 0}
    cohorts = {tuple(sorted(p["cohort"].items())) for p in posts}
    if len(cohorts) != 1:
        raise AlphaError("These posts can't be compared: their platform, language or post type differ.", 409)
    values = [p["metrics"].get(metric, {}).get("value") for p in posts]
    measured = [v for v in values if v is not None]
    if len(measured) < MIN_COMPARABLE:
        return {"interpretation": "insufficient_sample", "sampleSize": len(posts), "measured": len(measured), "missing": len(values) - len(measured), "minimum": MIN_COMPARABLE}
    return {"interpretation": "observation_only", "sampleSize": len(posts), "measured": len(measured), "missing": len(values) - len(measured), "mean": str(Fraction(int(sum(measured)), len(measured))), "causalityEstablished": False}

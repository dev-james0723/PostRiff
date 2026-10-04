"""Analytics with native definitions (architecture §15): store observations with provider,
definition version, observation/ingestion time, availability; present `Unavailable`, never
zero; rates with numerator/denominator; like-for-like cohorts; < 3 comparable → insufficient.
"""
from fractions import Fraction
from decimal import Decimal
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


def fetch_post_insights(transport, access_token, provider, provider_post_id):
    """One insights GET, no database. {"status", "found": {metric: value}, "endpoint"}; transport errors propagate."""
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
        params = [workspace_id, connection_id, provider, provider_post_id, job_id, metric, DEFINITION_VERSION, found.get(metric) if available else None, "available" if available else "unavailable", now, endpoint]
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
    grant = oauth.token_for_worker(workspace_id, connection_id)
    fetched = fetch_post_insights(transport, grant["accessToken"], provider, provider_post_id)
    recorded = record_observations(cur, workspace_id, connection_id, provider, provider_post_id, job_id, fetched["found"], fetched["endpoint"], now)
    return {"provider": provider, "status": fetched["status"], "recorded": recorded}


def rate(numerator, denominator):
    if numerator is None or denominator is None:
        return {"value": None, "display": "Unavailable", "numerator": numerator, "denominator": denominator}
    if denominator == 0:
        return {"value": None, "display": "undefined (denominator 0)", "numerator": numerator, "denominator": denominator}
    return {"value": str(Fraction(int(numerator), int(denominator))), "display": f"{numerator}/{denominator}", "numerator": numerator, "denominator": denominator}


def latest_observations(cur, workspace_id, basis=None, *, include_identity=False):
    """Per post and metric: the latest available reading, else the latest reading. Scheduled reads (growth Phase 0)
    take several readings per post; a later reading that lacks a metric must not hide a real earlier value.
    The last column is the reading's offset (t0/1h/24h/7d/backfill, or None); databases without migration 035
    return None. With `basis`, only readings taken at that offset (or legacy rows
    without one) are considered, so every post is read at the same age."""
    offset = read_offset_column(cur)
    where = "" if basis is None else f" AND coalesce({offset}, %s)=%s"
    params = (workspace_id,) if basis is None else (workspace_id, basis, basis)
    identity = ",id::text,source_endpoint" if include_identity else ""
    cur.execute(f"SELECT DISTINCT ON (provider,connection_id,provider_post_id,job_id,metric) provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,extract(epoch from observed_at),extract(epoch from ingested_at),connection_id,{offset}{identity} FROM public.pr_metric_observations o WHERE workspace_id=%s" + where + " ORDER BY provider,connection_id,provider_post_id,job_id,metric,(availability='available') DESC,observed_at DESC,ingested_at DESC,id DESC", params)
    return cur.fetchall()


def summary(cur, workspace_id, jobs, now, basis=None):
    """Per-post rows with native metrics; families only group, never sum across providers. Display uses the
    latest values (basis None); anything comparing posts passes basis=COMPARISON_BASIS."""
    rows = latest_observations(cur, workspace_id, basis)
    posts = {}
    for provider, post_id, job_id, metric, version, value, unit, availability, observed, ingested, connection_id, read_offset in rows:
        post = posts.setdefault((provider, connection_id, post_id, job_id), {"provider": provider, "providerPostId": post_id, "jobId": job_id, "connectionId": connection_id, "metrics": {}, "freshness": {"observedAt": float(observed), "ingestedAt": float(ingested)}, "definitionVersion": version})
        if not (type(value) in (int, float) or isinstance(value, Decimal)) or value is None or not math.isfinite(float(value)) or value < 0:
            availability = "unavailable"
        # readOffset says how long after publishing this value was read; +1h and +7d values are not like-for-like.
        post["metrics"][metric] = {"value": float(value) if availability == "available" else None, "display": (str(int(value)) if value is not None and float(value).is_integer() else str(value)) if availability == "available" else "Unavailable", "availability": availability, "unit": unit, "nativeName": metric, "readOffset": read_offset, "observedAt": float(observed), "ingestedAt": float(ingested)}
        post["metrics"][metric]["definitionVersion"] = version
    job_index = {j.get("id"): j for j in jobs if j.get("id") and j.get("providerReference")}
    items = []
    for post in posts.values():
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
        numerator = post["metrics"].get("likes", {})
        denominator = post["metrics"].get("reach") or post["metrics"].get("views") or {}
        keys = ("observedAt", "ingestedAt", "definitionVersion", "unit", "readOffset")
        matched = numerator.get("readOffset") in ("1h", "24h", "7d") and all(numerator.get(k) is not None and numerator.get(k) == denominator.get(k) for k in keys)
        engagement, reach = numerator.get("value"), denominator.get("value")
        result = rate(int(engagement) if matched and engagement is not None else None, int(reach) if matched and reach is not None else None)
        result["reason"] = None if matched and result["value"] is not None else "zero_denominator" if matched and reach == 0 else "missing_reading" if matched else "incompatible_readings"
        # The original readings remain visible even when a ratio is unavailable.
        result.update(numerator=engagement,denominator=reach)
        post["rates"] = {"likesPerView": result}
        items.append(post)
    # Connections without any observation are reported explicitly, never as zeros.
    return {"posts": items, "families": FAMILIES, "basis": basis, "rules": {"missing": "Unavailable, never 0", "crossPlatformReach": "never unique people; providers are listed side by side", "comparison": "same account, provider, window, language, content type and definition version only", "insufficientSample": f"< {MIN_COMPARABLE} comparable posts"}, "freshnessNow": now}


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

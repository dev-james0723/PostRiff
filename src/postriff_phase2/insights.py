"""Analytics with native definitions (architecture §15): store observations with provider,
definition version, observation/ingestion time, availability; present `Unavailable`, never
zero; rates with numerator/denominator; like-for-like cohorts; < 3 comparable → insufficient.
"""
from fractions import Fraction
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
            if name in metrics and type(value) in (int, float) and value >= 0:
                found[name] = value
    return {"status": response.get("status"), "found": found, "endpoint": endpoint}


def record_observations(cur, workspace_id, connection_id, provider, provider_post_id, job_id, found, endpoint, now, read_offset=None, period_start=None):
    """One row per native metric: available with its value, else unavailable (never zero). `read_offset` and
    `period_start` are written only when given, so callers on databases without migration 032 are unaffected."""
    recorded = []
    extra_cols = ",read_offset,period_start" if read_offset is not None else ""
    extra_vals = ",%s,to_timestamp(%s)" if read_offset is not None else ""
    for metric in INSIGHT_METRICS[provider]:
        available = metric in found
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


def latest_observations(cur, workspace_id):
    cur.execute("SELECT DISTINCT ON (provider,provider_post_id,metric) provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,extract(epoch from observed_at),extract(epoch from ingested_at),connection_id FROM public.pr_metric_observations WHERE workspace_id=%s ORDER BY provider,provider_post_id,metric,observed_at DESC", (workspace_id,))
    return cur.fetchall()


def summary(cur, workspace_id, jobs, now):
    """Per-post rows with native metrics; families only group, never sum across providers."""
    rows = latest_observations(cur, workspace_id)
    posts = {}
    for provider, post_id, job_id, metric, version, value, unit, availability, observed, ingested, connection_id in rows:
        post = posts.setdefault((provider, post_id), {"provider": provider, "providerPostId": post_id, "jobId": job_id, "connectionId": connection_id, "metrics": {}, "freshness": {"observedAt": float(observed), "ingestedAt": float(ingested)}, "definitionVersion": version})
        post["metrics"][metric] = {"value": float(value) if availability == "available" else None, "display": (str(int(value)) if value is not None and float(value).is_integer() else str(value)) if availability == "available" else "Unavailable", "availability": availability, "unit": unit, "nativeName": metric}
    job_index = {j.get("providerReference"): j for j in jobs if j.get("providerReference")}
    items = []
    for post in posts.values():
        job = job_index.get(post["providerPostId"], {})
        manifest = job.get("manifest", {})
        post["publishedState"] = job.get("state", "unknown")
        post["contentOrigin"] = "postriff_published" if job else "unknown"
        post["platform"] = manifest.get("platform")
        language = manifest.get("payload", {}).get("language")
        post["language"] = locales.canonical(language) or language  # English and en are one cohort
        post["contentTypeId"] = manifest.get("contentType", {}).get("id")
        post["cohort"] = {"provider": post["provider"], "language": post["language"], "contentTypeId": post["contentTypeId"], "definitionVersion": post["definitionVersion"]}
        engagement = post["metrics"].get("likes", {}).get("value")
        reach = (post["metrics"].get("reach") or post["metrics"].get("views") or {}).get("value")
        post["rates"] = {"likesPerView": rate(int(engagement) if engagement is not None else None, int(reach) if reach is not None else None)}
        items.append(post)
    # Connections without any observation are reported explicitly, never as zeros.
    return {"posts": items, "families": FAMILIES, "rules": {"missing": "Unavailable, never 0", "crossPlatformReach": "never unique people; providers are listed side by side", "comparison": "same provider, language, content type and definition version only", "insufficientSample": f"< {MIN_COMPARABLE} comparable posts"}, "freshnessNow": now}


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

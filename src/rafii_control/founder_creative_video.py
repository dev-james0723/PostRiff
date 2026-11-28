"""Content-free video accounting and per-environment model routing controls."""
from postriff_phase2.creative_video_strategy import model_catalog
from . import http
from .auth import ControlError
from .intelligence import QueryService
from .live_metrics import execute
from .store import MetricStatement


def report(app, principal, request):
    QueryService.require(principal, "metrics.query")
    mode = request["mode"]
    if mode == "demo":
        return {"mode": mode, "models": [], "rows": [], "_dataState": "synthetic"}
    store = app.queries.store
    flags = execute(app.queries, MetricStatement("creative_video_models",
        "SELECT model, paused FROM public.pr_creative_video_model_policy WHERE environment=%s"), (store.environment,))
    rows = execute(app.queries, MetricStatement("creative_video_usage",
        'SELECT * FROM rafii_control.creative_video_usage ORDER BY provider,model,plan LIMIT 201'), (), 201)
    if rows is None or flags is None:
        return {"mode": mode, "rows": [], "models": [], "_dataState": "unavailable", "reason": "source_not_configured"}
    studio = getattr(app.consumer(), "creative_video", None) if app.runtime else None
    paused = {row["model"] for row in flags if row["paused"]}
    models = []
    for entry in model_catalog(studio.environment if studio else {}):
        item = {key:entry.get(key) for key in ("id","label","provider","pricingVersion","reason")}
        item.update(paused=item["id"] in paused, available=entry["available"] and item["id"] not in paused)
        if item["paused"]:
            item["reason"] = "Paused by a Rafii administrator."
        elif studio and studio.deployment != store.environment:
            item.update(available=False, reason="The control and worker environments need verification.")
        elif not studio:
            item.update(available=False, reason="Worker configuration is unavailable on this control mount.")
        models.append(item)
    return {"mode": mode, "rows": rows[:200], "models": models, "truncated": len(rows)>200, "_dataState": "measured"}


def set_model(app, principal, request):
    QueryService.require(principal, "control.settings")
    body = request["body"]
    if request["mode"] != "live" or not isinstance(body, dict) or set(body) != {"model", "paused"} or type(body["paused"]) is not bool:
        raise ControlError("VALIDATION_FAILED", 400)
    if not isinstance(body["model"], str) or not any(m["id"] == body["model"] for m in model_catalog({})):
        raise ControlError("VALIDATION_FAILED", 400)
    store = app.queries.store
    studio = getattr(app.consumer(), "creative_video", None) if app.runtime else None
    if studio and studio.deployment != store.environment:
        raise ControlError("SOURCE_UNAVAILABLE", 503)
    with store.transaction() as con:
        con.execute("""INSERT INTO public.pr_creative_video_model_policy(environment,model,paused,actor)
                       VALUES(%s,%s,%s,%s) ON CONFLICT(environment,model) DO UPDATE
                       SET paused=excluded.paused,actor=excluded.actor,updated_at=now()""",
                    (store.environment, body["model"], body["paused"], principal["operator"]["user_id"]))
    return dict(body)


http.register_route("GET", r"/usage/creative-video", "metrics.query", "founder_creative_video", "report")
http.register_route("POST", r"/usage/creative-video/model", "control.settings", "founder_creative_video", "set_model", step_up=True)

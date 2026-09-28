"""Private, explicitly client-reported page exposures and opportunity dismissals.

No GET writes, source content, model calls, provider calls, or impression certainty.
All writes share the caller's authenticated transaction and current dependency locks.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from . import contracts, opportunities, relevance


def fail(code="invalid_request", status=400):
    from .service import error
    raise error(code,status)


def candidate_ids(items):
    return [{"opportunity_id":p["id"],"revision":p["revision"]} for p in items
            if p["state"] in ("candidate","ready") and p["verification_state"]=="verified"]


def page_token(service, store, cur, wid, actor, state, items, as_of, now):
    eligible=[p for p in items if p["state"] in ("candidate","ready") and p["verification_state"]=="verified"]
    if not eligible or len(eligible)>20 or not all(service._enabled(f) for f in ("INTELLIGENCE","RADAR","TRUST_RECEIPTS")):
        return None
    return service._cursor({"purpose":"trend_exposure","version":1,"workspace":wid,"actor":actor,
        "scopes":store.scope_signature(wid,actor,cursor=cur),"context_digest":relevance.context_revision(state),
        "candidates_digest":contracts.digest(candidate_ids(eligible)),"as_of":opportunities.iso(as_of),
        "expires_at":opportunities.iso(min(now+300,*(opportunities.epoch(p["expires_at"]) for p in eligible)))})


def latest_decision(cur, wid, oid, revision):
    cur.execute("""SELECT decision,actor_id::text,result FROM public.pr_trend_opportunity_decisions
        WHERE workspace_id=%s AND object_id=%s AND revision=%s ORDER BY created_at DESC LIMIT 1""",(wid,oid,revision))
    found=cur.fetchone()
    return {"decision":found[0],"actor_id":found[1],"result":found[2]} if found else None


def require_flags(service):
    if not all(service._enabled(f) for f in ("INTELLIGENCE","RADAR","TRUST_RECEIPTS")):
        fail("forbidden",403)


def parse_candidates(value):
    if not isinstance(value,list) or not 1<=len(value)<=20:fail()
    result=[]
    for item in value:
        if not isinstance(item,dict) or set(item)!={"opportunity_id","revision"} or type(item["revision"]) is not int or item["revision"]<1:fail()
        try:oid=contracts.uuid(item["opportunity_id"])
        except (ValueError,TypeError):fail()
        result.append({"opportunity_id":oid,"revision":item["revision"]})
    if len({p["opportunity_id"] for p in result})!=len(result):fail()
    return result


def current(service, store, cur, wid, actor, state, oid, revision, now, *, eligible=False):
    row=service._get(store,cur,wid,actor,"opportunity",oid,now)
    if row["revision"]!=revision:fail("revision_conflict",409)
    op,trend=service._opportunity_read(store,cur,wid,actor,row,state,now)
    if eligible and op["state"] not in ("candidate","ready"):fail("revision_conflict",409)
    if op["verification_state"]!="verified":fail("evidence_unavailable",410)
    receipt=service._get(store,cur,wid,actor,"receipt",op["trust_receipt_id"],now)
    trend_row=service._get(store,cur,wid,actor,"trend",op["trend_id"],now)
    return row,op,trend_row,receipt


def check_exposure(service, store, cur, wid, actor, op, exposure_id, now):
    if exposure_id is None:return None
    try:exposure_id=contracts.uuid(exposure_id)
    except (ValueError,TypeError):fail()
    row=service._get(store,cur,wid,actor,"exposure",exposure_id,now)
    p=row["payload"]
    if row["scope_key"]!="workspace:"+wid or p.get("actor_id")!=actor:fail("forbidden",403)
    if any(p.get(k)!=op[v] for k,v in (("opportunity_id","id"),("opportunity_revision","revision"),
                                      ("trust_receipt_id","trust_receipt_id"),("context_digest","context_digest"))):
        fail("revision_conflict",409)
    store.lock_dependencies(wid,actor,[{"kind":"exposure","object_id":exposure_id,"revision":row["revision"]}],cursor=cur)
    service._current(row,service.clock())
    return exposure_id


def wire(row, existing):
    p=row["payload"]
    return {k:p[k] for k in ("exposure_id","event_id","opportunity_id","opportunity_revision","trust_receipt_id",
                            "context_digest","measurement","eligible_candidate_count","recorded_at","expires_at")} | {"existing":existing}


def record(service, wid, token, payload):
    from .service import envelope
    required={"event_id","exposure_token","opportunity_id","opportunity_revision","trust_receipt_id","context_digest","eligible_candidates"}
    if not isinstance(payload,dict) or set(payload)!=required:fail()
    if type(payload["opportunity_revision"]) is not int or payload["opportunity_revision"]<1:fail()
    if not isinstance(payload["context_digest"],str) or not 1<=len(payload["context_digest"])<=128:fail()
    try:
        event,oid,rid=(contracts.uuid(payload[k]) for k in ("event_id","opportunity_id","trust_receipt_id"))
    except (ValueError,TypeError):fail()
    candidates=parse_candidates(payload["eligible_candidates"])
    if {"opportunity_id":oid,"revision":payload["opportunity_revision"]} not in candidates:fail()
    with service.transaction(wid,token,"edit") as (store,cur,_record,actor,state,_scopes):
        require_flags(service);now=service.clock();page=service._decode(payload["exposure_token"])
        if page.get("purpose")!="trend_exposure" or page.get("version")!=1:fail()
        if page.get("workspace")!=wid or page.get("actor")!=actor:fail("forbidden",403)
        if (page.get("context_digest")!=relevance.context_revision(state) or payload["context_digest"]!=page.get("context_digest")
                or page.get("scopes")!=store.scope_signature(wid,actor,cursor=cur)):fail("revision_conflict",409)
        if page.get("candidates_digest")!=contracts.digest(candidates):fail()
        if opportunities.epoch(page["expires_at"])<=now:fail("evidence_unavailable",410)
        inputs={k:payload[k] for k in required-{"exposure_token"}}
        fingerprint=contracts.digest({"actor_id":actor,"workspace_id":wid,"input":inputs})
        existing=store.get_projection(wid,actor,"exposure",event,cursor=cur)
        if existing:
            service._current(existing,now)
            if existing["payload"].get("request_digest")!=fingerprint:fail("revision_conflict",409)
        bindings=[]
        for item in candidates:
            row,op,trend,receipt=current(service,store,cur,wid,actor,state,item["opportunity_id"],item["revision"],now,eligible=not bool(existing))
            for r in (row,trend,receipt):bindings.append({"kind":r["kind"],"object_id":r["object_id"],"revision":r["revision"]})
        bindings=list({(b["kind"],b["object_id"]):b for b in bindings}.values())
        store.lock_dependencies(wid,actor,bindings,cursor=cur)
        now=service.clock();refs={};expiry=now+86400;shown=None
        for item in candidates:
            row,op,trend,receipt=current(service,store,cur,wid,actor,state,item["opportunity_id"],item["revision"],now,eligible=not bool(existing))
            if item["opportunity_id"]==oid:shown=op
            for r in (row,trend,receipt):
                if any(r["policy"].get(p) is not True for p in ("derive_metrics","retain_derivatives")):fail("forbidden",403)
                refs[r["scope_key"],r["projection_id"]]={"scope_key":r["scope_key"],"node_id":r["projection_id"]}
                expiry=min(expiry,opportunities.epoch(r["expires_at"]))
        if shown["trust_receipt_id"]!=rid or shown["context_digest"]!=payload["context_digest"]:fail("revision_conflict",409)
        if existing:
            from . import analytics_runtime
            analytics_runtime.record(store,cur,wid,actor,event,values=service.values)
            return envelope(wire(existing,True),now,limitations=["Client-reported view; the candidate set covers this returned page only."])
        scope="workspace:"+wid;store.ensure_scope(scope,cursor=cur)
        at=opportunities.iso(now);until=opportunities.iso(expiry)
        value={"schema_version":"rafii.trend-exposure.v1","purpose":"analytics_observations","workspace_id":wid,"actor_id":actor,
            "exposure_id":event,"event_id":event,"opportunity_id":oid,"opportunity_revision":payload["opportunity_revision"],
            "trust_receipt_id":rid,"context_digest":payload["context_digest"],"measurement":"client_reported_view",
            "eligible_candidates":candidates,"eligible_candidate_count":len(candidates),"candidate_scope":"returned_page",
            "page_as_of":page["as_of"],"recorded_at":at,"expires_at":until,"request_digest":fingerprint}
        manifest=store.put_manifest(scope,list(refs.values()),decision_cutoff=at,available_at=at,retention_until=until,
                                    recipe={"purpose":"analytics_observations","request_digest":fingerprint},cursor=cur)
        artifact=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();version="client-view-"+artifact[:16]
        store.put_method("trend.exposure",version,artifact,{"measurement":"client_reported_view","causal":False},cursor=cur)
        store.put_projection({"scope_key":scope,"kind":"exposure","object_id":event,"revision":1,"manifest_id":manifest["manifest_id"],
            "method_id":"trend.exposure","method_version":version,"decision_cutoff":at,"available_at":at,"retention_until":until,"payload":value},cursor=cur)
        from . import analytics_runtime
        analytics_runtime.record(store,cur,wid,actor,event,values=service.values)
        return envelope(wire({"payload":value},False),now,limitations=["Client-reported view; the candidate set covers this returned page only."])


def dismiss(service, wid, token, oid, payload):
    from .service import envelope
    required={"revision","idempotency_key"}
    if (not isinstance(payload,dict) or not required<=set(payload) or set(payload)-required-{"exposure_id"}
            or type(payload["revision"]) is not int or payload["revision"]<1
            or not isinstance(payload["idempotency_key"],str) or not 1<=len(payload["idempotency_key"])<=200):fail()
    if "exposure_id" in payload:
        try:contracts.uuid(payload["exposure_id"])
        except (ValueError,TypeError):fail()
    with service.transaction(wid,token,"edit") as (store,cur,_record,actor,state,_scopes):
        require_flags(service);now=service.clock()
        row,op,trend,receipt=current(service,store,cur,wid,actor,state,oid,payload["revision"],now)
        if op["state"]=="accepted":fail("revision_conflict",409)
        store.lock_dependencies(wid,actor,[{"kind":r["kind"],"object_id":r["object_id"],"revision":r["revision"]} for r in (row,trend,receipt)],cursor=cur)
        now=service.clock();row,op,trend,receipt=current(service,store,cur,wid,actor,state,oid,payload["revision"],now)
        eid=check_exposure(service,store,cur,wid,actor,op,payload.get("exposure_id"),now)
        prior=latest_decision(cur,wid,oid,payload["revision"])
        result={"trust_receipt_id":op["trust_receipt_id"],"context_digest":op["context_digest"],"exposure_id":eid}
        if prior and (prior["decision"]!="dismiss" or prior["actor_id"]!=actor or prior["result"]!=result):fail("revision_conflict",409)
        decision=store.decide_opportunity(wid,actor,oid,revision=payload["revision"],decision="dismiss",idempotency_key=payload["idempotency_key"],result=result,cursor=cur)
        if decision.get("result")!=result or str(decision.get("actor_id",actor))!=actor:fail("revision_conflict",409)
        return envelope({"opportunity_id":oid,"revision":payload["revision"],"state":"dismissed","exposure_id":eid,"existing":bool(prior)},now)

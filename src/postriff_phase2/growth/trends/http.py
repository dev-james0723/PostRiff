"""The authenticated /coworker/trends boundary. All reads are stored-only."""
from urllib.parse import parse_qs
from postriff_alpha.domain import AlphaError
from .service import error


def query(environ):
    parsed = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True, max_num_fields=30)
    if any(len(v) != 1 for v in parsed.values()):
        raise error("invalid_request", 400)
    return {k: v[0] for k, v in parsed.items()}


def handle(app, environ, start_response, service, workspace_id, token, method, tail):
    # This wrapper also covers authentication/feature/errors. A foreign record never
    # leaks through a shared cache, and no unsupported route falls into an ID reader.
    def private_start(status, headers, *args):
        return start_response(status, [(k, v) for k, v in headers if k.lower() not in ("cache-control", "pragma")] +
                              [("Cache-Control", "private, no-store"), ("Pragma", "no-cache")], *args)

    try:
        q = query(environ)
        body = lambda: app._body(environ)
        status = 200
        # Every static path is resolved before /{trend_id}.
        if not tail and method == "GET":
            data = service.list(workspace_id, token, q)
        elif tail == ["public-sources"] and method == "GET":
            if q: raise error("invalid_request",400)
            from . import meta_sources
            data=meta_sources.read(service,workspace_id,token)
        elif tail == ['public-sources','discovery-requests']:
            if q: raise error('invalid_request',400)
            from . import meta_discovery
            if method == 'GET':
                data=meta_discovery.read(service,workspace_id,token)
            elif method == 'POST':
                data=meta_discovery.submit(service,workspace_id,token,body())
                status=202
            else:
                raise error('not_found',404)
        elif len(tail)==2 and tail[0]=="public-sources" and method=="DELETE":
            if q: raise error("invalid_request",400)
            from . import meta_sources
            data=meta_sources.revoke(service,workspace_id,token,tail[1])
        elif tail in (["methodology"], ["calibration"], ["language-patterns"]) and method == "GET":
            if q:
                raise error("invalid_request", 400)
            data = service.stored(workspace_id, token, tail[0])
        elif tail == ["watches"] and method in ("GET", "POST"):
            if q:
                raise error("invalid_request", 400)
            data = service.watches(workspace_id, token, payload=body() if method == "POST" else None)
            status = 201 if method == "POST" else 200
        elif len(tail) == 2 and tail[0] == "watches" and method in ("PATCH", "DELETE"):
            data = service.watches(workspace_id, token, watch_id=tail[1], delete=method == "DELETE", payload=q if method == "DELETE" else body())
        elif tail == ["exposures"] and method == "POST":
            if q:
                raise error("invalid_request", 400)
            data = service.exposure(workspace_id, token, body())
        elif tail == ['learning'] and method == 'GET':
            if set(q)-{'window'}: raise error('invalid_request',400)
            data=service.learning(workspace_id,token,window=q.get('window','24h'))
        elif tail == ['learning','metric-choices'] and method == 'POST':
            if q: raise error('invalid_request',400)
            data=service.learning(workspace_id,token,payload=body())
        elif tail == ['learning','treatment-assessments'] and method == 'POST':
            if q: raise error('invalid_request',400)
            data=service.learning(workspace_id,token,payload=body(),assessment=True)
        elif len(tail)==2 and tail[0]=='forecasts' and tail[1] in ('evaluate','admit') and method=='POST':
            if q: raise error('invalid_request',400)
            data=service.forecast_operation(workspace_id,token,action=tail[1],payload=body())
        elif len(tail)==2 and tail[0]=='forecasts' and method=='GET':
            if set(q)!={'revision'} or not q['revision'].isdigit():raise error('invalid_request',400)
            data=service.forecast_operation(workspace_id,token,object_id=tail[1],revision=int(q['revision']))
        elif tail == ['media','jobs'] and method == 'POST':
            if environ.get('QUERY_STRING'): raise error('invalid_request',400)
            data=service.media(workspace_id,token,payload=body()); status=201
        elif len(tail)==4 and tail[:2]==['media','jobs'] and tail[3]=='run' and method=='POST':
            if environ.get('QUERY_STRING') or body()!={}: raise error('invalid_request',400)
            data=service.media(workspace_id,token,job_id=tail[2])
        elif len(tail)==5 and tail[:2]==['media','results'] and tail[3]=='artifacts' and method=='GET':
            if environ.get('QUERY_STRING') or environ.get('CONTENT_LENGTH','0') not in ('','0') or environ.get('HTTP_TRANSFER_ENCODING'):
                raise error('invalid_request',400)
            raw=service.media(workspace_id,token,result_id=tail[2],artifact_sha256=tail[4])
            private_start('200 OK',[('Content-Type','image/png'),('Content-Length',str(len(raw))),
                ('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),
                ('Content-Security-Policy',"default-src 'none'; sandbox")])
            return [raw]
        elif len(tail)==3 and tail[:2]==['media','results'] and method=='GET':
            if environ.get('QUERY_STRING') or environ.get('CONTENT_LENGTH','0') not in ('','0') or environ.get('HTTP_TRANSFER_ENCODING'):
                raise error('invalid_request',400)
            data=service.media(workspace_id,token,result_id=tail[2])
        elif len(tail) == 3 and tail[0] == "opportunities" and tail[2] == "angles" and method == "POST":
            if q: raise error("invalid_request", 400)
            data = service.generate_angles(workspace_id, token, tail[1], body())
        elif len(tail) == 2 and tail[0] == "generation-jobs" and method == "GET":
            if q: raise error("invalid_request", 400)
            data = service.generation_status(workspace_id, token, tail[1])
        elif len(tail) == 3 and tail[0] == "opportunities" and tail[2] == "dismiss" and method == "POST":
            if q:
                raise error("invalid_request", 400)
            data = service.dismiss(workspace_id, token, tail[1], body())
        elif tail == ["opportunities", "whitespace"] and method == "GET":
            data = service.stored(workspace_id, token, "whitespace")
        elif tail == ["opportunities"] and method == "GET":
            data = service.list(workspace_id, token, q, kind="opportunity")
        elif len(tail) == 2 and tail[0] == "opportunities" and method == "GET":
            data = service.opportunity(workspace_id, token, tail[1])
        elif len(tail) == 3 and tail[0] == "opportunities" and tail[2] == "accept" and method == "POST":
            data = service.accept(workspace_id, token, tail[1], body())
        elif tail == ["opportunity-lab", "runs"] and method == "POST":
            data = service.lab_create(workspace_id, token, body())
        elif len(tail) == 3 and tail[:2] == ["opportunity-lab", "runs"] and method == "GET":
            data = service.stored(workspace_id, token, "lab", tail[2])
        elif tail == ["refreshes"] and method == "POST":
            body()
            data = service.gated_mutation(workspace_id, token, "PROVIDER_OPERATIONS")
        elif tail and tail[0] in {"public-sources", "generation-jobs", "methodology", "calibration", "language-patterns", "watches", "opportunities", "opportunity-lab", "refreshes", "exposures", "learning", "media", "forecasts"}:
            raise error("not_found", 404)
        elif len(tail) == 1 and method == "GET":
            data = service.get(workspace_id, token, tail[0])
        elif len(tail) == 2 and tail[1] in {"snapshots", "examples", "genome", "propagation", "saturation", "forecast"} and method == "GET":
            data = service.get(workspace_id, token, tail[0], tail[1])
        elif len(tail) == 3 and tail[1] == "receipts" and method == "GET":
            data = service.get(workspace_id, token, tail[0], "receipts", tail[2])
        else:
            raise error("not_found", 404)
        return app._json(private_start, status, data)
    except (ValueError, TypeError):
        exc = error("invalid_request", 400)
        return app._json(private_start, exc.status, {"error": str(exc), "code": exc.code})
    except AlphaError as exc:
        safe = error(exc.code if exc.code in {"invalid_request", "unauthenticated", "forbidden", "not_found", "evidence_unavailable", "revision_conflict", "source_unavailable", "budget_or_rate_limited"} else "source_unavailable", exc.status)
        return app._json(private_start, safe.status, {"error": str(safe), "code": safe.code})

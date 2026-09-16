"""Local-owner manual task routes; never mount outside Studio's owner boundary."""
from fastapi import Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .studio import StudioError
from .studio_delivery import DeliveryService, REVIEW_INPUT


def register_delivery_routes(app, store, body_parser):
    service = DeliveryService(store)
    app.state.delivery_service = service

    async def fields(request, expected):
        value = await body_parser(request)
        if not isinstance(value, dict) or set(value) != set(expected):
            raise StudioError("invalid_delivery_fields", "Only the displayed local handoff fields are accepted.", 422)
        return value

    @app.get("/api/delivery")
    def status():
        return service.status()

    @app.post("/api/delivery/reviews", status_code=201)
    async def review(request: Request):
        return {"review": await run_in_threadpool(service.prepare_review, await fields(request, REVIEW_INPUT))}

    @app.post("/api/delivery/reviews/{review_id}/approve")
    async def approve(review_id: str, request: Request):
        data = await fields(request, {"manifestHash", "expectedRevision"})
        return {"job": await run_in_threadpool(service.approve, review_id, data["manifestHash"], data["expectedRevision"])}

    @app.post("/api/delivery/jobs/{job_id}/cancel")
    async def cancel(job_id: str, request: Request):
        await fields(request, set())
        return {"job": await run_in_threadpool(service.cancel, job_id)}

    @app.post("/api/delivery/jobs/{job_id}/report")
    async def report(job_id: str, request: Request):
        data = await fields(request, {"permalink"})
        return {"job": await run_in_threadpool(service.report, job_id, data["permalink"])}

    @app.get("/api/delivery/jobs/{job_id}/package")
    def package(job_id: str):
        content = service.package(job_id)
        return Response(content, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="manual-handoff-{job_id}.md"'})

    @app.post("/api/delivery/control")
    async def control(request: Request):
        data = await fields(request, {"paused"})
        return {"worker": await run_in_threadpool(service.control, data["paused"])}

    return service

"""Scoped editorial routes; inherited Studio owner boundary is mandatory."""
from fastapi import Request
from starlette.concurrency import run_in_threadpool

from .studio import StudioError


async def _fields(request, expected):
    # Import at call time so create_app can mount this module without a cycle.
    from .studio_api import _body
    data = await _body(request)
    if set(data) != set(expected):
        raise StudioError("invalid_agent_request_fields", "Only the displayed editorial operation fields are accepted.", 422)
    return data


def register_agent_routes(app, service):
    @app.get("/api/agent/status")
    def status():
        return service.status()

    @app.get("/api/agent/conversations")
    def conversations(draftId: str):
        return {"conversations": service.list_conversations(draftId)}

    @app.post("/api/agent/conversations", status_code=201)
    async def create_conversation(request: Request):
        data = await _fields(request, {"draftId", "expectedDraftRevision", "contentType"})
        return {"conversation": await run_in_threadpool(service.create_conversation, data["draftId"], data["expectedDraftRevision"], data["contentType"])}

    @app.get("/api/agent/conversations/{conversation_id}")
    def get_conversation(conversation_id: str):
        return {"conversation": service.get_conversation(conversation_id)}

    @app.post("/api/agent/conversations/{conversation_id}/answer")
    async def answer(conversation_id: str, request: Request):
        data = await _fields(request, {"expectedRevision", "slot", "value"})
        return {"conversation": await run_in_threadpool(service.answer, conversation_id, data["expectedRevision"], data["slot"], data["value"])}

    @app.get("/api/agent/conversations/{conversation_id}/review")
    def review(conversation_id: str):
        return service.review(conversation_id)

    @app.post("/api/agent/conversations/{conversation_id}/runs", status_code=202)
    async def start(conversation_id: str, request: Request):
        data = await _fields(request, {"expectedRevision", "inputHash", "requestId", "consent"})
        return {"run": await run_in_threadpool(service.start_run, conversation_id, data["expectedRevision"], data["inputHash"], data["requestId"], data["consent"])}

    @app.get("/api/agent/runs")
    def runs(draftId: str):
        return {"runs": service.list_runs(draftId)}

    @app.get("/api/agent/runs/{run_id}")
    def get_run(run_id: str):
        return {"run": service.get_run(run_id)}

    @app.post("/api/agent/runs/{run_id}/cancel")
    async def cancel(run_id: str, request: Request):
        await _fields(request, set())
        return {"run": await run_in_threadpool(service.cancel, run_id)}

    @app.post("/api/agent/runs/{run_id}/apply")
    async def apply(run_id: str, request: Request):
        data = await _fields(request, {"expectedDraftRevision", "resultHash", "channels"})
        return await run_in_threadpool(service.apply, run_id, data["expectedDraftRevision"], data["resultHash"], data["channels"])

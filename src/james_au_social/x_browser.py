"""Retired X route. Compatibility endpoints deny execution without browser I/O.

Historical private ledgers remain untouched. X uses Rafii's official API.
"""
from __future__ import annotations
import json

VERSION = "x-direct-only/2"
REASON = "x_direct_only"
MESSAGE = "X actions require an authorized official X API connection in Rafii."


class Stop(ValueError):
    pass


def status():
    return {"provider": "x", "route": "unavailable", "routeDriver": VERSION,
            "state": "unavailable", "publishReady": False, "publishing": False,
            "liveTestVerified": False, "reasonCode": REASON, "reason": MESSAGE,
            "connectUrl": "https://rafii.io/app/channels"}


def execute(*_args, **_kwargs):
    raise Stop(REASON)


def login(*_args, **_kwargs):
    raise Stop(REASON)


def register_routes(app, _data_dir, body_parser):
    from fastapi import Request
    from .studio import StudioError

    @app.get("/api/connections/x-browser/status")
    def retired_status():
        return status()

    @app.post("/api/connections/x-browser/{operation}")
    async def retired_action(operation: str, request: Request):
        raise StudioError(REASON, MESSAGE, 410)


if __name__ == "__main__":
    print(json.dumps(status()))
    raise SystemExit(1)

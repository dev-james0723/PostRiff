"""Manually called bounded provider adapter. No credentials, scheduler or default client."""
from datetime import datetime, timezone
import hashlib
import json
import uuid
from urllib.error import HTTPError, URLError
from .auth import ControlError
from .deadlines import remaining
from .investigations import REPOSITORY, ADAPTER_VERSION, required_manifest, validate_capture


def capture_response(body, sha, requested_at, observed_at, request_id=None):
    """Normalize only safe public check metadata; retain total-count coverage."""
    try:
        runs = body['workflow_runs']
        if not isinstance(runs, list) or len(runs)>100:
            raise ValueError()
        fields = ('id','name','head_sha','status','conclusion','run_number','run_attempt','updated_at','workflow_id')
        safe = [{key:row[key] for key in fields if key in row} for row in runs]
        total = body.get('total_count')
        capture = dict(schemaVersion=1,captureId=str(uuid.uuid4()),repository=REPOSITORY,exactSha=sha,
                       requestId=request_id or str(uuid.uuid4()),requestedAt=requested_at,observedAt=observed_at,
                       resourceUrl=f'https://api.github.com/repos/{REPOSITORY}/actions/runs?head_sha={sha}&event=pull_request&per_page=100&page=1',
                       providerBodyDigest=hashlib.sha256(json.dumps(safe,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
                       workflowRuns=safe,coverage={'complete':type(total) is int and total==len(safe),'returnedRuns':len(safe),'totalRuns':total,'scope':'pull_request_workflow_runs_first_page'},
                       provenance='provider_observed_test',requiredManifest=required_manifest(sha),adapterVersion=ADAPTER_VERSION)
        return validate_capture(capture)
    except (KeyError,TypeError,ValueError):
        raise ControlError('SOURCE_UNAVAILABLE',503)


def manual_fetch(client, sha, clock=None):
    """Client must honor explicit timeout; it is injected only by an authorized caller."""
    clock=clock or (lambda:datetime.now(timezone.utc))
    requested=clock().isoformat()
    required_manifest(sha)
    url=f'https://api.github.com/repos/{REPOSITORY}/actions/runs?head_sha={sha}&event=pull_request&per_page=100&page=1'
    try:
        with client(url,timeout=remaining()) as response:
            raw=response.read(1048577)
        remaining()
        if len(raw)>1048576:raise ControlError('BUDGET_EXCEEDED',400)
        return capture_response(json.loads(raw),sha,requested,clock().isoformat())
    except HTTPError as error:
        raise ControlError('RATE_LIMITED' if error.code==429 else 'SOURCE_UNAVAILABLE',429 if error.code==429 else 503)
    except (URLError,TimeoutError,OSError,ValueError,TypeError):
        raise ControlError('SOURCE_UNAVAILABLE',503)

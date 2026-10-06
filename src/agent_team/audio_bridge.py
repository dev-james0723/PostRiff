"""Same authenticated ingress hosts only; free local report audio, no calls.

The cloud's immutable missing-asset job is checked before each upload. Replaying
an identical WAV is storage-idempotent; no external provider is invoked here.
"""
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .audio import generate_report_audio, validate_report, validate_wav
from .events import canonical
from .transport import NoRedirect


def request_json(url, token, payload=None):
    encoded=canonical(payload).encode() if payload is not None else None
    if encoded is not None and len(encoded)>3*1024*1024:
        raise ValueError('audio_request_limit')
    req=Request(url,data=encoded,method='POST' if encoded is not None else 'GET',
                headers={'Authorization':'Bearer '+token,'Accept':'application/json',
                         'Content-Type':'application/json','Cache-Control':'no-store'})
    with build_opener(NoRedirect).open(req,timeout=5) as response:
        raw=response.read(256*1024+1)
        if response.status!=200 or len(raw)>256*1024:
            raise ValueError('audio_response_limit_or_status')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('audio_response_invalid')
    return value


def produce_pending(endpoint, token_file, canonical_root, *, request=request_json,
                    generate=generate_report_audio, now=None):
    parsed=urlsplit(endpoint)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.netloc!=parsed.hostname
            or parsed.query or parsed.fragment
            or parsed.path!='/api/internal/james-agent-team/events'):
        raise ValueError('dedicated_audio_ingress_required')
    root=Path(canonical_root).resolve()
    path=Path(token_file)
    if (path!=root/'.runtime/cloud-ingress.token' or path.is_symlink()
            or not path.is_file() or path.stat().st_mode&0o077):
        raise ValueError('private_audio_token_required')
    token=path.read_text().strip()
    if not 32<=len(token)<=512 or any(c.isspace() for c in token):
        raise ValueError('invalid_audio_token')
    base=endpoint.removesuffix('/events')
    work=request(base+'/audio-work',token)
    if work.get('state')=='idle':return {'state':'idle','inference':'not_requested'}
    if work.get('state')!='ready' or not isinstance(work.get('job'),dict):
        raise ValueError('audio_job_invalid')
    document=work.get('report');current=now or datetime.now(timezone.utc)
    identity=validate_report(document,now=current)
    job=work['job']
    if (not identity.delivery_eligible or job.get('reportKey')!=identity.period_key
            or job.get('fingerprint')!=identity.fingerprint
            or job.get('version')!=identity.report_version
            or job.get('summaryHash')!=identity.summary_hash):
        raise ValueError('audio_job_identity_mismatch')
    receipt=generate(document,canonical_root=root)
    if (not receipt.delivery_eligible or receipt.execution_state!='generated_local_audio'):
        raise ValueError('audio_not_real_or_delivery_eligible')
    target=Path(receipt.file_path)
    if target!=root/'.runtime/audio'/f'{identity.fingerprint}.wav' or target.is_symlink():
        raise ValueError('audio_asset_path_mismatch')
    with target.open('rb') as stream:raw=stream.read(2*1024*1024+1)
    wav=validate_wav(raw)
    payload={'reportKey':identity.period_key,'fingerprint':identity.fingerprint,
             'version':identity.report_version,'summaryHash':identity.summary_hash,
             'narrationHash':identity.narration_hash,'excerpt':identity.excerpt,
             'sha256':wav['sha256'],'mime':'audio/wav','producer':'macos_say_sinji',
             'observedAt':datetime.now(timezone.utc).isoformat(),
             'data':base64.b64encode(raw).decode('ascii')}
    acknowledgment=request(base+'/audio',token,payload)
    if (acknowledgment.get('reportKey')!=identity.period_key
            or acknowledgment.get('fingerprint')!=identity.fingerprint
            or acknowledgment.get('sha256')!=wav['sha256']):
        raise ValueError('audio_acknowledgment_unverified')
    return {'state':'stored','reportKey':identity.period_key,'fingerprint':identity.fingerprint,
            'sha256':wav['sha256'],'delivery':'authenticated_file_available',
            'playback':'not_verified','inference':'not_requested'}

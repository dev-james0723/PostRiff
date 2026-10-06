"""Explicit bounded ingress transport; no redirects, cookies, profiles or raw source bodies."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .events import canonical


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def send_pending(journal, endpoint, token_file, delivered_at, limit=100):
    u=urlsplit(endpoint)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path!='/api/internal/james-agent-team/events':
        raise ValueError('dedicated_https_ingress_required')
    p=Path(token_file)
    if p.is_symlink() or not p.is_file() or p.stat().st_mode&0o077:raise ValueError('private_scoped_token_file_required')
    token=p.read_text().strip()
    if not 32<=len(token)<=512 or any(c.isspace() for c in token):raise ValueError('invalid_scoped_token')
    rows=journal.pending(limit)
    if not rows:return {'state':'empty','count':0}
    raw=canonical({'events':rows}).encode()
    if len(raw)>256*1024:raise ValueError('batch_payload_limit')
    request=Request(endpoint,data=raw,method='POST',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with build_opener(NoRedirect).open(request,timeout=5) as response:
        raw=response.read(65537)
        if response.status!=200 or len(raw)>65536:raise ValueError('ingress_response_invalid')
    payload=json.loads(raw);accepted=payload.get('accepted')
    known={e['key'] for e in rows}
    if not isinstance(accepted,list) or len(accepted)!=len(set(accepted)) or not set(accepted)<=known:raise ValueError('ingress_ack_invalid')
    journal.acknowledge(accepted,delivered_at)
    return {'state':'acknowledged','count':len(accepted)}

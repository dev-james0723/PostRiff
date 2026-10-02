"""Session-only Phase 1 routes, with an explicit origin guard on anonymous analysis."""
from postriff_alpha.domain import AlphaError
from .service import ACTIONS, GrowthService


def ensure(hosted):
    if not hasattr(hosted,'growth'):
        hosted.growth=GrowthService(hosted)
    return hosted.growth


def public(app,environ,start_response,method,path):
    if path=='/api/post-doctor' and method=='POST':
        app._origin(environ,True)
        service=ensure(app._runtime())
        # Hash in the service; addresses never enter a usage event or stored result.
        ip=environ.get('HTTP_X_FORWARDED_FOR',environ.get('REMOTE_ADDR','unknown')).split(',')[0].strip()[:100]
        return app._json(start_response,200,service.public_check(app._body(environ),ip))
    if path.startswith('/api/content-dna/') and method=='GET':
        return app._json(start_response,200,ensure(app._runtime()).share(path.removeprefix('/api/content-dna/')))
    return None


def handle(app,environ,start_response,hosted,token,method,parts):
    service=ensure(hosted)
    workspace_id,rest=parts[2],parts[4:]
    if rest and rest[0]=='radar':
        radar=service.radar
        if method=='GET' and rest==['radar','catalog']:value=radar.catalog(workspace_id,token)
        elif method=='GET' and rest==['radar','scans']:value=radar.list(workspace_id,token)
        elif method=='POST' and rest==['radar','quotes']:value=radar.quote(workspace_id,token,app._body(environ))
        elif method=='POST' and len(rest)==3 and rest[2]=='start':value=radar.start(workspace_id,token,rest[1],app._body(environ))
        elif method=='POST' and len(rest)==3 and rest[2]=='advance':value=radar.advance(workspace_id,token,rest[1])
        else:raise AlphaError('Radar route unavailable.',404)
        value=radar.response(workspace_id,token,value)
    elif method=='GET' and rest==['catalog']:
        value=service.catalog(workspace_id,token)
    elif method=='GET' and rest==['genome']:
        value=service.genome(workspace_id,token)
    elif method=='GET' and len(rest)==2 and rest[0]=='feedback':
        value=service.feedback(workspace_id,token,rest[1])
    elif method=='POST' and rest==['credit-quotes']:
        value=service.credit_quote(workspace_id,token,app._body(environ))
    elif method=='POST' and rest==['check']:
        value=service.check(workspace_id,token,app._body(environ))
    elif method=='POST' and rest==['rewrite']:
        value=service.rewrite(workspace_id,token,app._body(environ))
    elif method=='POST' and rest==['history']:
        value=service.imports(workspace_id,token,app._body(environ))
    elif method=='GET' and rest==['postmortems']:
        value=service.closed_loop.overview(workspace_id,token)
    elif method=='POST' and rest==['postmortems']:
        value=service.closed_loop.report(workspace_id,token,app._body(environ))
    elif method=='GET' and rest==['audience']:
        value=service.closed_loop.audience(workspace_id,token)
    elif method=='POST' and rest==['audience']:
        value=service.closed_loop.mine(workspace_id,token,app._body(environ))
    else:
        raise AlphaError('Growth route unavailable.',404)
    return app._json(start_response,200,value)

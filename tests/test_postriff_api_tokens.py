"""Token scope is an explicit route allowlist; new routes must opt in."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase2.api_tokens import route_scope


def test_read_allowlist():
    for tail in ['', '/channels', '/memory', '/ideas/conversations', '/ideas/conversations/c/messages', '/ideas/runs/r/events']:
        assert route_scope('GET', ('api/workspaces/w' + tail).split('/')) == 'read'


def test_draft_allowlist():
    for tail in ['/ideas/quick-start', '/ideas/conversations', '/ideas/conversations/c/turns', '/ideas/conversations/c/attachments', '/ideas/runs/r/apply', '/ideas/runs/r/cancel']:
        assert route_scope('POST', ('api/workspaces/w' + tail).split('/')) == 'draft'


def test_every_sensitive_or_unknown_route_denied():
    for path in ['api/me', 'api/auth/verify', 'api/invitations/accept', 'api/workspaces/w/actions', 'api/workspaces/w/tokens', 'api/workspaces/w/tokens/id', 'api/workspaces/w/billing/checkout', 'api/workspaces/w/usage', 'api/workspaces/w/audit', 'api/workspaces/w/members', 'api/workspaces/w/audience/reply-drafts/r/reply', 'api/workspaces/w/channels/c/verify', 'api/workspaces/w/future', 'api/billing/webhook', 'api/cron/worker']:
        for method in ['GET','POST','PATCH','DELETE']:
            assert route_scope(method, path.split('/')) is None, (path, method)

"""Emit synthetic server-produced engagement payloads for the cloud browser test."""
import json
import os
import sys
from pathlib import Path

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Use the approved cloud synthetic engagement fixture.')

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
from test_discord_engagement import EngagementFixture, EngagementControls, WORKSPACE, ACTOR
from postriff_phase2.channels import customer_view, assisted_matrix
from postriff_phase2.discord.engagement import annotate_capabilities

def projected_channel(fixture):
    # This is the exact production customer-view projection and default capability
    # mapping used by OAuthService.channels when no capability rows were seeded.
    # No successful capability level is hardcoded in this fixture.
    raw = next(c for c in fixture.repo.state['phase2']['channels'] if c['id'] == fixture.connection)
    views = [customer_view(raw, assisted_matrix(), fixture.repo.now)]
    annotate_capabilities(views, fixture.repo.state, ACTOR, fixture.repo.now, fixture.provider)
    return views[0]

f = EngagementFixture()
f.provider.engagement_v1_enabled = False
paused = f.service.status(WORKSPACE, 'owner', f.connection)
channel_paused = projected_channel(f)
f.provider.engagement_v1_enabled = True
channel_before = projected_channel(f)
before = f.service.status(WORKSPACE, 'owner', f.connection)
granted = f.grant()
channel_granted = projected_channel(f)
analytics = f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'analytics', 'destinationId': f.destination})
inbox = f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
review = f.preview()
from unittest.mock import patch
with patch('postriff_phase2.security_holds.assert_clear'), patch('postriff_phase2.billing.require_publishing'):
    approval = f.approve(review)
after = f.service.status(WORKSPACE, 'owner', f.connection)
# This additional synthetic record represents a separately approved future app,
# not the real intent-OFF deployment. It exercises the broader-mode UI label.
b = EngagementFixture()
b.provider.message_content_evidence_raw = EngagementControls()._extended_policy()
broader_before = b.service.status(WORKSPACE, 'owner', b.connection)
channel_broader_before = projected_channel(b)
selected = next(d for d in broader_before['destinations'] if d['target']['id'] == b.destination)
broader_granted = b.service.consent(WORKSPACE, 'owner', b.connection,
    {'destinationId': b.destination, 'targetDigest': selected['targetDigest'], 'confirmed': True,
     'permissions': {'analytics': True, 'inbox': True, 'reply': True}, 'contentAccess': 'approved_content'})
channel_broader_granted = projected_channel(b)
b.wire.application_flags = 1 << 18
broader_inbox = b.service.read(WORKSPACE, 'owner', b.connection, {'kind': 'inbox', 'destinationId': b.destination})
target = Path(sys.argv[1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({'paused': paused, 'channelPaused': channel_paused, 'channelBefore': channel_before,
                            'channelGranted': channel_granted, 'channelBroaderBefore': channel_broader_before,
                            'channelBroaderGranted': channel_broader_granted,
                            'before': before, 'granted': granted, 'analytics': analytics, 'inbox': inbox,
                            'review': review, 'approval': approval, 'after': after, 'broaderBefore': broader_before,
                            'broaderGranted': broader_granted, 'broaderInbox': broader_inbox}))
print('Synthetic Discord engagement browser fixture written; no provider writes or actual database.')

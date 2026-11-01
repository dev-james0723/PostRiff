"""Export actual synthetic P0 review/job objects for cloud browser fixtures."""
import copy
import json
import os
import sys
from pathlib import Path

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Cloud synthetic validation only.')
from test_discord_publish_authorization import fixture, review, approve, APP, USER, ACTOR, GUILD, NOW
from postriff_phase2.discord.oauth import stable_id

engine, state, channel, variant = fixture()
entry = review(engine, state, channel, variant)
pending_review = copy.deepcopy(entry)
job = approve(engine, state, entry)
output = Path(sys.argv[1]); output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({'channel': {**channel, 'displayState': engine.channel_state(channel)},
                              'variant': variant, 'review': pending_review, 'job': job,
                              'connections': {'identity': {'id': stable_id('identity', state['workspace']['id'], APP, USER, ACTOR), 'account': 'Synthetic identity', 'userId': USER, 'status': 'linked', 'expiresAt': NOW + 3600, 'discoverGuilds': True},
                                              'guilds': [{'id': GUILD, 'name': 'Synthetic first guild'}, {'id': '666666', 'name': 'Synthetic second guild'}]}}, sort_keys=True))

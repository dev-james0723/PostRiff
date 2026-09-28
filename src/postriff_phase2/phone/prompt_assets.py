"""Fail closed if installed telephone audio no longer matches the reviewed source copy."""
import hashlib
import json
from pathlib import Path

ASSETS = Path(__file__).with_name('assets')


def read(name):
    if name not in ('dial-acceptance', 'dial-inbound', 'dial-inbound-retry', 'dial-repeat'):
        raise ValueError('Unknown telephone prompt')
    spec = json.loads((ASSETS / 'prompts.json').read_text())
    installed = json.loads((ASSETS / 'installed-prompts.json').read_text())[name]
    audio = (ASSETS / (name + '.mulaw')).read_bytes()
    if installed['text'] != spec['prompts'][name] or hashlib.sha256(audio).hexdigest() != installed['sha256']:
        raise ValueError('Telephone prompt review is required')
    if not 8000 <= len(audio) <= (120000 if name == 'dial-acceptance' else 200000):
        raise ValueError('Telephone prompt format is unavailable')
    return audio

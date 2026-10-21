"""OPTIONAL offline differential test against the genuine PR #216 source checkout.

Run separately, after the minimal-import tests, with:
  UPSTREAM_SOURCE_ROOT=/path/to/clean/e891af35/worktree python3 tests/reference_parity.py
No network access, database connections, provider messages or deployment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from a7a0_ping_core import Settings, Reject, verify_ping

UPSTREAM=os.environ.get('UPSTREAM_SOURCE_ROOT')
if not UPSTREAM:
    raise SystemExit('Set UPSTREAM_SOURCE_ROOT to the separately verified unmodified e891af35 checkout')
path=Path(UPSTREAM).resolve()
assert subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip() == 'e891af3591d8baabdb54c05d936ccd61c3299e42'
assert subprocess.check_output(['git','-C',str(path),'diff','--name-only'],text=True).strip() == ''
sys.path.insert(0,str(path/'src'))
from postriff_phase2.discord.interactions import DiscordInteractions
from postriff_alpha.domain import AlphaError

APP='1553164599086555297'
ORIGIN='https://parity-sandbox.example.invalid'
key=Ed25519PrivateKey.generate()
public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex()
provider=SimpleNamespace(client_id=APP,website=ORIGIN,user_install_v1_enabled=True,execution_enabled=True,
 interaction_config_raw={'applicationId':APP,'publicKey':public,'endpoint':ORIGIN+'/api/discord/interactions', 'qualified':False})
original=DiscordInteractions(provider,None,ORIGIN,clock=lambda:1800000000)
minimal=Settings(APP,public,ORIGIN)

def outcome(fn):
    try:
        value=fn()
        return {'status':200,'body':value}
    except (AlphaError,Reject) as e:
        return {'status':e.status}

scenarios=[]
def add(name,packet,delta=0,bad_sig=False,raw_override=None):
    raw=raw_override if raw_override is not None else json.dumps(packet, separators=(',',':')).encode()
    ts=str(1800000000+delta)
    sig='00'*64 if bad_sig else key.sign(ts.encode()+raw).hex()
    with (patch.object(socket.socket,'connect',side_effect=AssertionError('NO_NET')),
          patch.object(socket,'create_connection',side_effect=AssertionError('NO_NET'))):
        a=outcome(lambda:original.receive(raw,ts,sig))
        b=outcome(lambda:verify_ping(raw,ts,sig,minimal,now=1800000000))
    assert a==b,(name,a,b)
    scenarios.append({'name':name,'result':a})

add('valid',{'application_id':APP,'type':1})
add('invalid_signature',{'application_id':APP,'type':1},bad_sig=True)
add('stale_timestamp',{'application_id':APP,'type':1},delta=301)
add('non_ping',{'application_id':APP,'type':2})
add('wrong_application',{'application_id':'5555566666','type':1})
add('boolean_type',{'application_id':APP,'type':True})
add('duplicate_key',None,raw_override=('{"application_id":"'+APP+'","type":1,"type":1}').encode())
add('empty_body',None,raw_override=b'')
add('oversize_body',None,raw_override=b'{' + b' '*65536 + b'}')
print(json.dumps({'source_SHA':'e891af3591d8baabdb54c05d936ccd61c3299e42',
                  'offline_reference_parity':'PASS','cases':scenarios,'provider_requests':0,'db_calls':0},indent=2))

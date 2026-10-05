#!/usr/bin/env python3
"""Verify an owner-authorized, unexpired capture export from stdin without printing content.

The public key file and source SHA MUST come from the independently reviewed
release record, not from the receipt being checked. No network or database I/O.
Optional checks JSON: {"required": ["synthetic marker"], "forbidden": [...]};
only indexed booleans are returned. The input is never written to disk.
"""
import argparse
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from pathlib import Path
import sys
import uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

DOMAIN = b'rafii-model-request-capture-v1\x00'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def safe_id(value):
    return value if isinstance(value,str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,199}",value) else None


def number(value):
    if isinstance(value,bool) or value is None: return None
    try:
        value=Decimal(str(value))
        return str(value) if value.is_finite() and value>=0 else None
    except InvalidOperation: return None


def safe_usage(value):
    if not isinstance(value,dict): return {}
    result={k:value[k] for k in ('prompt_tokens','completion_tokens','total_tokens','input_tokens','output_tokens') if type(value.get(k)) is int and value[k]>=0}
    for key,allowed in (('prompt_tokens_details',('cached_tokens',)),('completion_tokens_details',('reasoning_tokens',)),('input_tokens_details',('cached_tokens',)),('output_tokens_details',('reasoning_tokens',))):
        if isinstance(value.get(key),dict): result[key]={k:value[key][k] for k in allowed if type(value[key].get(k)) is int and value[key][k]>=0}
    if number(value.get('cost')) is not None: result['cost']=number(value['cost'])
    return result


def safe_gateway(value):
    if not isinstance(value,dict): return {}
    result={}
    if safe_id(value.get('generationId')): result['generationId']=value['generationId']
    if number(value.get('cost')) is not None: result['cost']=number(value['cost'])
    if isinstance(value.get('routing'),dict) and safe_id(value['routing'].get('finalProvider')): result['routing']={'finalProvider':value['routing']['finalProvider']}
    return result


def verify(export, public_key, source_sha, checks=None, encryption_key=None):
    def signed(name):
        receipt=export[name]
        if receipt['schema']!='rafii-request-capture-v1': raise ValueError('receipt schema')
        key=Ed25519PublicKey.from_public_bytes(public_key)
        payload=base64.b64decode(receipt['signed_payload_base64'],validate=True)
        if not payload.startswith(DOMAIN): raise ValueError('signature domain')
        manifest=json.loads(payload[len(DOMAIN):])
        if manifest!=receipt['manifest'] or payload!=DOMAIN+canonical(manifest): raise ValueError('manifest mismatch')
        key.verify(base64.b64decode(receipt['signature'],validate=True),payload)
        if manifest['deployment_sha']!=source_sha: raise ValueError('release binding')
        return manifest
    prepared=signed('prepared'); started=signed('network_started'); outcome=signed('outcome')
    if prepared['kind']!='prepared' or started['kind']!='network_started' or outcome['kind']!='response_observed':
        raise ValueError('incomplete dispatch chain')
    uuid.UUID(prepared['physical_attempt_id'])
    digest=hashlib.sha256(base64.b64decode(export['prepared']['signed_payload_base64'],validate=True)+base64.b64decode(export['prepared']['signature'],validate=True)).hexdigest()
    for item in (started,outcome):
        if item['physical_attempt_id']!=prepared['physical_attempt_id'] or item['prepared_sha256']!=digest:
            raise ValueError('attempt chain mismatch')
    if datetime.fromisoformat(prepared['expires_at'])<=datetime.now(timezone.utc): raise ValueError('retention expired')
    if prepared['consent_version']!='rafii-exact-request-v1' or prepared['capture_mode']!='encrypted_exact_body':
        raise ValueError('consent mismatch')
    def plaintext(kind, manifest):
        encoded=export.get(kind+'_base64')
        if encoded is not None: return base64.b64decode(encoded,validate=True)
        if encryption_key is None or len(encryption_key)!=32: raise ValueError('decryption key unavailable')
        envelope=export[kind]
        if envelope['key_id']!=prepared['key_id'] or envelope['kind']!=kind: raise ValueError('envelope mismatch')
        key=HKDF(algorithm=hashes.SHA256(),length=32,salt=prepared['server_nonce'].encode('ascii'),info=DOMAIN+prepared['grant_id'].encode('ascii')).derive(encryption_key)
        return AESGCM(key).decrypt(base64.b64decode(envelope['nonce'],validate=True),base64.b64decode(envelope['ciphertext'],validate=True),canonical({'kind':kind,'manifest':manifest}))
    request=plaintext('request',prepared)
    response=plaintext('response',outcome)
    if len(request)!=prepared['body_bytes'] or hashlib.sha256(request).hexdigest()!=prepared['body_sha256']:
        raise ValueError('request body mismatch')
    if len(response)!=outcome['response_bytes'] or hashlib.sha256(response).hexdigest()!=outcome['response_sha256'] or outcome['response_complete'] is not True:
        raise ValueError('response body mismatch')
    body=json.loads(request); returned=json.loads(response)
    if not isinstance(body,dict) or not isinstance(body.get('messages'),list): raise ValueError('request messages absent')
    roles=[item.get('role') for item in body['messages']]
    if any(role not in ('system','developer','user','assistant','tool','function') for role in roles): raise ValueError('invalid message role')
    if body.get('model')!=prepared['model'] or safe_id(returned.get('model'))!=outcome.get('response_model'): raise ValueError('model mismatch')
    if safe_id(returned.get('id'))!=outcome.get('endpoint_response_id'): raise ValueError('response identity mismatch')
    if safe_usage(returned.get('usage'))!=outcome.get('usage'): raise ValueError('usage mismatch')
    response_meta=returned.get('providerMetadata',returned.get('provider_metadata',{}))
    gateway=response_meta.get('gateway',{}) if isinstance(response_meta,dict) else {}
    if safe_gateway(gateway)!=outcome.get('gateway_metadata'): raise ValueError('gateway metadata mismatch')
    cost=None
    for candidate in (gateway.get('cost') if isinstance(gateway,dict) else None,(returned.get('usage') or {}).get('cost')):
        try:
            parsed=Decimal(str(candidate))
            if parsed.is_finite() and parsed>=0:
                cost=str(parsed); break
        except InvalidOperation: pass
    usage={k:v for k,v in (returned.get('usage') or {}).items() if k in ('prompt_tokens','completion_tokens','total_tokens','input_tokens','output_tokens') and type(v) is int and v>=0}
    text=request.decode('utf-8')
    # Search decoded strings as well, because json.dumps may escape Unicode.
    decoded=json.dumps(body,ensure_ascii=False)
    checks=checks or {}
    required=[marker in text or marker in decoded for marker in checks.get('required',[])]
    forbidden=[marker not in text and marker not in decoded for marker in checks.get('forbidden',[])]
    return {'verified':True,'source_sha_matches':True,'signatures_verified':3,'request_bytes_match':True,'response_bytes_match':True,
        'physical_attempt_uuid_valid':True,'ordered_roles':roles,'request_model':body['model'],'response_model':safe_id(returned.get('model')),
        'request_option_names':sorted(k for k in body if k!='messages'),'http_status':outcome['http_status'],
        'endpoint_request_id_present':bool(outcome.get('endpoint_request_id')),'endpoint_response_id_present':bool(outcome.get('endpoint_response_id')),
        'gateway_generation_id_present':bool(outcome.get('gateway_generation_id')),'usage':usage,
        'response_reported_cost_usd':cost,'cost_status':'response_reported' if cost is not None else 'not_reported_in_response',
        'required_marker_checks':required,'forbidden_marker_absence_checks':forbidden,'content_checks_passed':all(required+forbidden),
        'boundary':'application_http_request_handoff','provider_received_identical_bytes_proven':False,'upstream_provider_exact_body_proven':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-key-file',required=True,help='independently trusted raw-base64 Ed25519 public key')
    parser.add_argument('--source-sha',required=True,help='independently reviewed deployment commit SHA')
    parser.add_argument('--encryption-key-file',help='optional private raw-base64 audit encryption key; used locally, never printed')
    parser.add_argument('--checks-file',help='optional synthetic presence/absence checks; contents never printed')
    args=parser.parse_args()
    try:
        key=base64.b64decode(Path(args.public_key_file).read_text().strip(),validate=True)
        data=json.loads(sys.stdin.buffer.read(4*1024*1024+1))
        checks=json.loads(Path(args.checks_file).read_text()) if args.checks_file else None
        encryption_key=base64.b64decode(Path(args.encryption_key_file).read_text().strip(),validate=True) if args.encryption_key_file else None
        if data.get('schema')=='rafii-private-capture-export-v1':
            if not isinstance(data.get('captures'),list) or not 1<=len(data['captures'])<=3: raise ValueError('export attempts')
            results=[verify(item,key,args.source_sha,checks,encryption_key) for item in data['captures']]
            result={'verified':True,'captures':results,'content_checks_passed':all(item['content_checks_passed'] for item in results)}
        else:
            result=verify(data,key,args.source_sha,checks,encryption_key)
        print(json.dumps(result,sort_keys=True))
        return 0 if result['content_checks_passed'] else 2
    except Exception as error:
        # Never exception message: it might embed plaintext, endpoints or keys.
        print(json.dumps({'verified':False,'error_class':type(error).__name__}))
        return 1


if __name__=='__main__': raise SystemExit(main())

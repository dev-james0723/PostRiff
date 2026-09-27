"""Dial setup receipt. Default is local-only; --provider-read-only performs GETs, never places a call."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from postriff_phase2.phone.providers.dial import DialProvider
from postriff_phase2.phone.config import PhoneConfig


def check(values, *, provider_read_only=False):
    required=('DIAL_API_KEY','DIAL_PHONE_NUMBER','DIAL_AUDIO_SIGNING_SECRET','DIAL_WEBHOOK_SIGNING_SECRET',
              'DIAL_VERIFICATION_SECRET','RAFII_PHONE_PUBLIC_BASE_URL','RAFII_PHONE_ENCRYPTION_KEY')
    missing=[key for key in required if not values.get(key)]
    provider=DialProvider(values)
    config=PhoneConfig(values)
    ready=provider.configured and not missing and config.telephony_rate>0
    result={'status':'configuration_ready' if ready else 'configuration_pending',
        'execution':'read_only_provider' if provider_read_only else 'local_only','missingNames':missing,
        'providerConfigurationValid':provider.configured,'telephonyRateConfigured':config.telephony_rate>0,
        'flags':config.public(),'providerReadiness':'not_checked','deployment':'not_run','liveCall':'not_run'}
    if provider_read_only and provider.configured:
        result['providerReadiness']=provider.readiness()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,help='Read a local server env file; values are never printed')
    parser.add_argument('--provider-read-only',action='store_true',help='Read Dial account, numbers and audio configuration; no writes')
    args=parser.parse_args()
    values=dict(os.environ)
    if args.env_file:
        from check_postriff_hosted_preflight import load_env_file
        values.update(load_env_file(args.env_file))
    try:
        result=check(values,provider_read_only=args.provider_read_only)
    except Exception:
        print(json.dumps({'status':'validation_unavailable','reason':'Setup check could not complete; private error details omitted','liveCall':'not_run'}))
        return 2
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='configuration_ready' and (not args.provider_read_only or (isinstance(result['providerReadiness'],dict) and result['providerReadiness'].get('ready'))) else 1


if __name__=='__main__':raise SystemExit(main())

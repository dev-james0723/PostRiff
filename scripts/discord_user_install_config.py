#!/usr/bin/env python3
"""Offline additive command preview and supplied readback validation; no HTTP.

No live registration option. Run with --application snapshot.json --command
snapshot.json only after separately authorized readback. Never include tokens.
"""
import argparse
import json
import re
from urllib.parse import urlsplit
from pathlib import Path
import sys
# scripts/postriff_phase2.py must not shadow the installed source package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase2.discord.interactions import COMMAND
from postriff_phase2.discord.authorization import snowflake, digest


def valid_application(application):
    if not isinstance(application, dict): return False
    try:
        endpoint = urlsplit(application.get('interactions_endpoint_url', ''))
        params = application['integration_types_config']['1']['oauth2_install_params']
        return (isinstance(application.get('verify_key'), str)
                and re.fullmatch(r'[0-9a-fA-F]{64}', application['verify_key']) is not None
                and endpoint.scheme == 'https' and bool(endpoint.hostname) and not endpoint.username and not endpoint.password
                and endpoint.path == '/api/discord/interactions' and not endpoint.query and not endpoint.fragment
                and params.get('scopes') == ['applications.commands'] and params.get('permissions', '0') == '0')
    except (TypeError, KeyError, ValueError, AttributeError):
        return False


def candidate(application=None, command=None):
    result = {'execution': 'dry-run', 'method': 'POST', 'path': '/applications/{application_id}/commands',
              'body': COMMAND, 'additive': True, 'liveRegistered': False, 'qualified': False, 'executeAllowed': False,
              'registrationPrecondition': 'A separately authorized complete registry readback must show this name/type is absent; Discord POST can replace an existing command of the same name/type.'}
    if application is not None or command is not None:
        if (not valid_application(application) or not isinstance(command, dict) or not snowflake(application.get('id'))
                or command.get('application_id') != application['id'] or not snowflake(command.get('id'))
                or not snowflake(command.get('version')) or any(command.get(k) != v for k, v in COMMAND.items())
                or command.get('options', []) != [] or command.get('guild_id') is not None
                or '1' not in application.get('integration_types_config', {})):
            raise ValueError('Supplied application/command readback does not match this exact private User Install contract.')
        result['registrationNeeded'] = False  # supplied exact matching command; do not create it again
        result['readback'] = {'applicationId': application['id'], 'commandId': command['id'], 'commandVersion': command['version'],
                              'applicationContractVerified': True, 'contractDigest': digest(COMMAND), 'source': 'operator-supplied snapshots, not live verified here'}
        result['configurationCandidate'] = {'applicationId': application['id'], 'publicKey': application['verify_key'],
            'commandId': command['id'], 'commandVersion': command['version'], 'commandName': COMMAND['name'],
            'integrationTypes': COMMAND['integration_types'], 'contexts': COMMAND['contexts'],
            'endpoint': application['interactions_endpoint_url'], 'qualified': False}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--application', type=Path); p.add_argument('--command', type=Path)
    args = p.parse_args()
    print(json.dumps(candidate(json.loads(args.application.read_text()) if args.application else None,
                               json.loads(args.command.read_text()) if args.command else None), indent=2))

if __name__ == '__main__': main()

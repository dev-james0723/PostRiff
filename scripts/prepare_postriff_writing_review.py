#!/usr/bin/env python3
"""Produce an exact fictional request for review. Never reads keys or sends HTTP."""
import argparse
import json
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase3.store import Phase3Store
from postriff_phase3.adapters import ManagedWriting
from postriff_phase3.contracts import digest


def prepare(directory):
    store = Phase3Store(Path(directory) / 'fictional.sqlite3')
    request = {'principalKey': secrets.token_hex(16), 'provider': 'google',
               'proof': 'postriff-fixture-verified', 'requestId': secrets.token_hex(16),
               'verifier': secrets.token_hex(32), 'plan': 'studio'}
    request.update(store.auth.challenge(request))
    current = store.auth.sign_in(request)
    wid, token = current['workspaceId'], current['token']

    def act(action, **payload):
        nonlocal current
        current = store.mutate(wid, token, current['revision'], action, payload)
        return current['state']

    act('mode', mode='personal')
    act('context', purpose='Explain a fictional community seed swap',
        audience='Curious beginners', subject='A fictional free seed swap',
        speaker='Fictional community educator', layers=[])
    state = act('source', kind='text', title='Fictional test facts', text=(
        'A fictional community garden is holding a free Saturday seed swap.\n'
        'Visitors may bring seeds or come to learn.\n'
        'There will be a beginner planting demonstration.'))
    source = state['sources'][0]
    act('approve_source', sourceId=source['id'], factIds=[f['id'] for f in source['facts']])
    act('source_done')
    act('profile_propose', writing='A small step can be a useful beginning.', tone='warm')
    state = act('profile_decide', decision='approve')
    act('p3_profile_visibility', voiceRevision=state['speaker']['activeRevision'], allowCloud=True, confirmed=True)
    act('p3_source_visibility', sourceId=source['id'], visibility='provider_allowed', confirmed=True)
    state = act('p3_prepare', route='managed', sourceIds=[source['id']], operation='draft', idempotencyKey='fictional-review')
    job = state['phase3']['jobs'][0]
    access = {'workspaceId': wid, 'token': token, 'runId': job['id']}
    access_path = Path(directory) / 'local-access.json'
    with access_path.open('x') as file:
        json.dump(access, file)
    access_path.chmod(0o600)
    return job['manifest']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True, help='New private disposable workspace directory')
    parser.add_argument('--model', default='meta-llama/Llama-3.3-70B-Instruct')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Review output already exists; preserve the reviewed request.')
    args.workspace.mkdir(mode=0o700)
    manifest = prepare(args.workspace)
    body = ManagedWriting.request_body(manifest, args.model)
    review = {'execution': 'review-only; zero provider calls', 'endpoint': ManagedWriting.endpoint,
              'account': 'not designated', 'modelAvailability': 'unverified', 'priceQuote': None,
              'authorization': 'pending exact account and price review',
              'maxRequests': 1, 'maxCostUsd': .05, 'timeoutSeconds': 45,
              'manifestHash': digest(manifest), 'requestHash': digest(body),
              'manifest': manifest, 'requestBody': body}
    # Exclusive creation avoids silently changing an already reviewed request.
    with args.output.open('x') as file:
        json.dump(review, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({'execution': review['execution'], 'output': str(args.output.resolve()),
                      'manifestHash': review['manifestHash'], 'requestHash': review['requestHash']}))


if __name__ == '__main__':
    main()

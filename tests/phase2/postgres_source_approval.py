"""Persisted source invalidation through the hosted service; disposable DB only."""
import copy
import json
import postgres_repository as fixture
from postriff_alpha.domain import AlphaError

service, wid = fixture.service, fixture.wid
# Repository's worker recovery check finished its job; this case needs the saved pre-dispatch fixture.
with fixture.connection() as db:
    db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
               (json.dumps(fixture.snapshot['state']), wid))

def act(action, **payload):
    current = service.get(wid, 'fixture-one')
    return service.mutate(wid, 'fixture-one', current['revision'], action, payload)

source = service.get(wid, 'fixture-one')['state']['sources'][0]
facts = [fact['id'] for fact in source['facts']]
changed = act('approve_source', sourceId=source['id'], factIds=facts[:1])
v = changed['state']['variants'][0]
assert changed['state']['phase2']['jobs'][0]['state'] == 'held'
for selected in (facts[:1], facts):
    changed = act('approve_source', sourceId=source['id'], factIds=selected)
    before = copy.deepcopy(changed)
    try:
        act('p2_variant_review', variantId=v['id'], variantRevision=v['revision'],
            confirmed=True, excludedUnknowns=v['unknowns'])
    except AlphaError:
        pass
    else:
        raise AssertionError('source-stale draft was reapproved')
    after = service.get(wid, 'fixture-one')
    assert after['revision'] == before['revision']
    assert after['state']['variants'] == before['state']['variants']

act('preview_update', variantId=v['id'])
changed = act('accept_update', variantId=v['id'])
v = changed['state']['variants'][0]
reviewed = act('p2_variant_review', variantId=v['id'], variantRevision=v['revision'],
               confirmed=True, excludedUnknowns=v['unknowns'])
assert not reviewed['state']['variants'][0]['needsReview']
assert reviewed['state']['phase2']['jobs'][0]['state'] == 'held', 'new content review must not restore an old publication approval'
try:
    service.mutate(wid, 'fixture-two', reviewed['revision'], 'approve_source',
                   {'sourceId': source['id'], 'factIds': facts})
except AlphaError as error:
    assert error.status == 403
else:
    raise AssertionError('foreign user borrowed source authority')
print('postgres_source_approval: stale review rejected and rolled back; fresh replacement accepted; old publication remains held; foreign actor denied')

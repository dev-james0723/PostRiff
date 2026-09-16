"""Explicit derivative selection. Planning never creates executable jobs."""
from .execution import payload_hash

OPERATIONS = {'story_create':'native_story', 'reel_create':'native_video',
              'short_create':'native_video', 'share_primary_to_story':'share_verified_primary',
              'crosspost_reel':'share_verified_primary'}

def plan_derivatives(campaign_id, offered, selected_ids, *, parent=None):
    ids = [x['target_id'] for x in offered]
    if len(ids) != len(set(ids)) or not campaign_id:
        raise ValueError('invalid_offer')
    if selected_ids is not None and (len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= set(ids)):
        raise ValueError('selection_expands_offer')
    targets, assets = [], []
    for item in offered:
        if item['operation'] not in OPERATIONS:
            raise ValueError('unsupported_derivative_operation')
        if not item['eligible']:
            state = 'ineligible_account'
        elif selected_ids is None:
            state = 'awaiting_selection'
        elif item['target_id'] not in selected_ids:
            state = 'declined_by_user'
        else:
            state = 'selected' if item['route_ready'] else 'route_unavailable_draft_only'
            mode = OPERATIONS[item['operation']]
            if mode == 'share_verified_primary':
                if not parent or parent.get('verification') != 'verified_published' or not parent.get('remote_id') or not parent.get('content_hash') or parent.get('account_ref') != item['account_ref']:
                    state = 'blocked_by_parent'
            else:
                assets.append({'target_id':item['target_id'], 'native_format_id':item['native_format_id'], 'mode':mode})
        targets.append({**item, 'state':state})
    body = {'campaign_id':campaign_id, 'offer_hash':payload_hash({'offered':offered}),
            'targets':targets, 'asset_requests':assets, 'publish_jobs':[], 'approval':'pending_user'}
    return {**body, 'plan_hash':payload_hash(body)}

"""Synchronize an exactly approved, verified native schedule amendment with Queue."""
import copy
from datetime import datetime


def same_instant(actual, approved):
    try:
        actual = datetime.fromisoformat(actual.replace('Z', '+00:00'))
        approved = datetime.fromisoformat(approved.replace('Z', '+00:00'))
        return bool(actual.tzinfo and approved.tzinfo and actual.timestamp() == approved.timestamp())
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


def synchronize(state, connection, preview, receipt, *, actor, action_id, fingerprint, now):
    """Local update only after remote read-back; preserve the original approval manifest."""
    action = preview['action']
    if receipt.get('state') != 'verified' or action not in ('native_cancel', 'native_reschedule'):
        return []
    target = preview['path'].rsplit('/', 1)[-1]
    changed = []
    for job in state.get('phase2', {}).get('jobs', []):
        manifest = job.get('manifest') or {}; progress = job.get('progress') or {}
        if (manifest.get('platform') != 'Mastodon' or manifest.get('channelId') != connection
                or manifest.get('providerAccountId') != preview['accountId']
                or progress.get('stage') != 'native_scheduled' or progress.get('reference') != target
                or job.get('state') in ('verified', 'failed', 'canceled')):
            continue
        if action == 'native_cancel':
            if receipt.get('verification') != 'provider_lookup_absent': continue
            job.update(state='canceled', cancelRequested=True, nextAt=0, leaseOwner=None, leaseUntil=0)
            message = 'The exact native schedule was canceled and its absence verified on the connected instance.'
        else:
            if (receipt.get('verification') != 'native_schedule_lookup' or receipt.get('reference') != target
                    or not same_instant(receipt.get('scheduledAt'), preview['body'].get('scheduled_at'))): continue
            amendment = {'actionId': action_id, 'approvalDigest': fingerprint, 'approvedBy': actor, 'approvedAt': now,
                         'scheduleId': target, 'scheduledAt': receipt['scheduledAt'], 'verification': 'native_schedule_lookup',
                         'accountId': preview['accountId'], 'connectionId': connection}
            job['nativeScheduleChange'] = amendment
            progress['scheduledAt'] = receipt['scheduledAt']; progress.pop('retryAt', None)
            # Fence an old in-flight lookup so its completion cannot overwrite
            # the newly verified time with its earlier snapshot.
            job.update(state='processing', nextAt=now + 60, leaseOwner=None, leaseUntil=0, leaseId=None)
            message = 'The exactly approved native schedule time was verified; publication remains pending.'
        job.setdefault('events', []).append({'at': now, 'state': job['state'], 'message': message, 'execution': 'hosted-live'})
        job['nativeScheduleReceipt'] = copy.deepcopy(receipt)
        changed.append(job['id'])
    return changed

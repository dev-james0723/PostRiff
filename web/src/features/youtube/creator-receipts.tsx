'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function CreatorReceipts({ channel }: { channel: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [renew, setRenew] = useState(false);
  const [pushReview, setPushReview] = useState<{
    id: string;
    digest: string;
    manifest: Record<string, unknown>;
  }>();
  const canManage = checkAccess(access, { permission: 'manage_connections' });
  const receipts = useQuery({
    queryKey: ['youtube-receipts', workspaceId, channel],
    queryFn: () => api.youtubeActions(workspaceId, channel),
    enabled: Boolean(channel && open),
    retry: false,
    staleTime: 60_000
  });
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Creator action unavailable.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <details
      className='rounded-lg border p-4'
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className='cursor-pointer text-sm font-medium'>
        Creator receipts and official change notifications
      </summary>
      <div className='mt-4 grid gap-4'>
        {error && (
          <p role='alert' className='text-sm text-destructive'>
            {error}
          </p>
        )}
        {notice && (
          <p role='status' className='text-sm'>
            {notice}
          </p>
        )}
        {receipts.isError && (
          <p role='alert' className='text-sm text-destructive'>
            Creator receipts could not be loaded.
          </p>
        )}
        {receipts.data?.actions.map((action) => (
          <div className='grid gap-2 rounded-md border p-3' key={action.id}>
            <p className='text-sm'>
              {action.action} · {action.status === 'privacy_erased' ? 'Data removed' : action.status} · {action.receipt?.result?.id || action.id}
            </p>
            {action.status === 'privacy_erased' && <p className='text-xs text-muted-foreground'>YouTube data was removed. This operation cannot run again. An accepted YouTube schedule is not canceled by data removal.</p>}
            {action.receipt?.verification?.note && (
              <p className='text-xs text-muted-foreground'>{action.receipt.verification.note}</p>
            )}
            {['accepted', 'started', 'outcome_unknown', 'verified'].includes(action.status) && (
              <Button
                variant='outline'
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const result = await api.youtubeReconcile(workspaceId, channel, action.id);
                    setNotice(
                      `Read-only reconciliation: ${result.status}. The original write was not repeated.`
                    );
                    await client.invalidateQueries({
                      queryKey: ['youtube-receipts', workspaceId, channel]
                    });
                  })
                }
              >
                Read back the accepted result
              </Button>
            )}
          </div>
        ))}
        {canManage && (
          <div className='grid gap-3'>
            <p className='text-xs text-muted-foreground'>
              Official notifications cover uploads and title/description changes. Rafii verifies
              processing and visibility with API read-back.
            </p>
            <Label className='flex items-center gap-2'>
              <input
                aria-label='Automatically renew the official notification lease'
                type='checkbox'
                checked={renew}
                onChange={(event) => setRenew(event.target.checked)}
              />
              Automatically renew the approved notification lease
            </Label>
            <div className='flex flex-wrap gap-2'>
              {(['subscribe', 'unsubscribe'] as const).map((mode) => (
                <Button
                  key={mode}
                  variant='outline'
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      setPushReview(
                        await api.youtubeNotificationPreview(workspaceId, channel, {
                          mode,
                          automaticRenewal: renew
                        })
                      );
                    })
                  }
                >
                  Review {mode === 'subscribe' ? 'notifications' : 'notification removal'}
                </Button>
              ))}
            </div>
            {pushReview && (
              <div className='grid gap-3 rounded-md border p-3'>
                <p className='text-sm'>
                  Approve {String(pushReview.manifest.mode)} for channel{' '}
                  {String(pushReview.manifest.channelId)}.
                </p>
                <p className='break-all text-xs'>
                  Callback: {String(pushReview.manifest.callback)}
                </p>
                <p className='text-xs'>
                  Automatic renewal: {pushReview.manifest.automaticRenewal ? 'Enabled' : 'Off'}.
                </p>
                <div className='flex gap-2'>
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const result = await api.youtubeNotificationApprove(
                          workspaceId,
                          channel,
                          pushReview.id,
                          pushReview.digest
                        );
                        setNotice('Official notification subscription: ' + result.status);
                        setPushReview(undefined);
                      })
                    }
                  >
                    Approve exact subscription
                  </Button>
                  <Button variant='outline' onClick={() => setPushReview(undefined)}>
                    Discard
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </details>
  );
}

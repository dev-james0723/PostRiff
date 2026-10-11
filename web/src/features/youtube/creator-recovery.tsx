'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function UploadRecovery({
  channel,
  operationKey,
  stage
}: {
  channel: string;
  operationKey: string;
  stage: string;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const client = useQueryClient();
  const [review, setReview] = useState<{ manifest: Record<string, unknown>; digest: string }>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  if (stage !== 'held' || !checkAccess(access, { permission: 'approve' })) return null;
  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Upload recovery unavailable.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className='grid gap-3'>
      <Button
        variant='outline'
        disabled={busy}
        onClick={() =>
          void run(async () => {
            setReview(await api.youtubeUploadRecovery(workspaceId, channel, operationKey));
            setMessage('');
          })
        }
      >
        Review recovery of this upload
      </Button>
      {message && (
        <p role='status' className='text-sm'>
          {message}
        </p>
      )}
      {review && (
        <div className='grid gap-3 rounded-md border p-3'>
          <p className='text-sm'>{String(review.manifest.effect)}</p>
          <p className='text-xs'>
            Channel: {String(review.manifest.channelId)}. Video:{' '}
            {String(review.manifest.videoId || 'same resumable session')}.
          </p>
          <details>
            <summary className='cursor-pointer text-sm'>
              Original approved video and declarations
            </summary>
            <pre className='mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs'>
              {JSON.stringify(review.manifest.options, null, 2)}
            </pre>
          </details>
          <div className='flex flex-wrap gap-2'>
            <Button
              disabled={busy || review.manifest.canResume !== true}
              onClick={() =>
                void run(async () => {
                  const result = await api.youtubeResumeUpload(
                    workspaceId,
                    channel,
                    operationKey,
                    review.digest
                  );
                  setMessage(
                    `Upload ${result.status}; ${result.resumed ? 'recovery approved for the same session or Video ID' : 'no recovery was needed'}.`
                  );
                  setReview(undefined);
                  await client.invalidateQueries({ queryKey: ['youtube', workspaceId, channel] });
                })
              }
            >
              Approve exact upload recovery
            </Button>
            <Button variant='outline' onClick={() => setReview(undefined)}>
              Discard
            </Button>
          </div>
          {review.manifest.canResume !== true && (
            <p className='text-xs text-amber-700'>
              This upload cannot safely be resumed. A replacement upload requires a new, separately
              reviewed video approval.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function StreamConfiguration({ channel, streamId }: { channel: string; streamId: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const [configuration, setConfiguration] = useState<Record<string, unknown>>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!checkAccess(access, { role: 'owner' })) return null;
  const ingestion = configuration?.ingestionInfo as Record<string, string> | undefined;
  return (
    <div className='grid gap-3 rounded-md border p-3'>
      <p className='text-sm'>Private ingestion configuration for the selected stream</p>
      <Button
        variant='outline'
        disabled={busy || !streamId}
        onClick={async () => {
          setBusy(true);
          setError('');
          setConfiguration(undefined);
          try {
            setConfiguration(
              (await api.youtubeStreamConfiguration(workspaceId, channel, streamId)).cdn
            );
          } catch (e) {
            setError(e instanceof Error ? e.message : 'Stream configuration unavailable.');
          } finally {
            setBusy(false);
          }
        }}
      >
        Read ingestion configuration after fresh owner sign-in
      </Button>
      {error && (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      )}
      {configuration && (
        <>
          <p className='text-xs'>
            Ingestion: {String(configuration.ingestionType)} · {String(configuration.resolution)} ·{' '}
            {String(configuration.frameRate)}
          </p>
          <p className='break-all text-xs'>Primary address: {ingestion?.ingestionAddress}</p>
          {ingestion?.backupIngestionAddress && (
            <p className='break-all text-xs'>Backup address: {ingestion.backupIngestionAddress}</p>
          )}
          <Label htmlFor='youtube-existing-stream-key'>Stream key</Label>
          <Input
            id='youtube-existing-stream-key'
            type='password'
            value={ingestion?.streamName || ''}
            readOnly
            autoComplete='off'
          />
          <Button variant='outline' onClick={() => setConfiguration(undefined)}>
            Clear private stream configuration
          </Button>
        </>
      )}
    </div>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { keys } from '@/lib/api/hooks';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { hearRecording, UNDERSTAND_SECONDS, type HeardStage } from '../audio-understanding';
import type { LibraryAsset } from '../use-library';
import { Control } from '../ui/controls';

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
/** One automatic attempt per recording per page load; a failure is not retried in a loop. */
const attempted = new Set<string>();

function stageText(stage: HeardStage | null) {
  if (!stage || stage.stage === 'reading') return 'Listening for speech on this device…';
  if (stage.stage === 'checking') return 'Checking whether this is speech or music…';
  if (stage.stage === 'downloading') return `Getting the free speech model (about 77 MB, once per device)${stage.fraction !== null ? ` · ${Math.round(stage.fraction * 100)}%` : '…'}`;
  return `Transcribing on this device · ${clock(stage.seconds)} of ${clock(stage.total)}`;
}

/**
 * Audio without a summary yet: listen on this device (free) and save what was heard — the words, from which the server
 * writes the summary, or "no speech" for music. Runs once on its own for people who can edit; nothing leaves the
 * browser except the resulting text.
 */
export function AudioAutoSummary({ asset, canEdit }: { asset: LibraryAsset; canEdit: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const key = `${workspaceId}:${asset.id}:${asset.hash ?? ''}`;
  const [run, setRun] = useState(0);
  const [stage, setStage] = useState<HeardStage | null>(null);
  const [state, setState] = useState<'idle' | 'working' | 'failed'>('idle');
  const [error, setError] = useState('');
  const saveData = typeof navigator !== 'undefined' && Boolean((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData);
  const automatic = canEdit && !saveData;

  useEffect(() => {
    if (!canEdit || !workspaceId || (run === 0 && (!automatic || attempted.has(key)))) return;
    attempted.add(key);
    const controller = new AbortController();
    setState('working'); setStage(null); setError('');
    (async () => {
      const { url } = await api.libraryFileUrl(workspaceId, asset.id);
      const heard = await hearRecording(url, controller.signal, setStage);
      if (heard.speech) await api.libraryTranscript(workspaceId, asset.id, heard.text, { source: 'browser_whisper' });
      else await api.libraryTranscript(workspaceId, asset.id, '', { source: 'browser_whisper', speech: 'none' });
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) }),
        client.invalidateQueries({ queryKey: ['library-file-detail', workspaceId, asset.id] })
      ]);
      setState('idle');
    })().catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setState('failed');
      setError(reason instanceof Error ? reason.message : 'The recording could not be read here.');
    });
    return () => controller.abort();
  }, [run, automatic, canEdit, key, workspaceId, asset.id, api, client]);

  if (!canEdit) return <p className='text-muted-foreground text-sm'>No summary yet. Someone who can edit this Library can have it listened to.</p>;
  if (state === 'working') {
    return (
      <p role='status' className='text-muted-foreground flex items-center gap-2 text-sm'>
        <Icons.spinner aria-hidden className='size-3.5 shrink-0 animate-spin motion-reduce:animate-none' />
        {stageText(stage)}
      </p>
    );
  }
  return (
    <div className='flex flex-col items-start gap-2'>
      <p className='text-muted-foreground text-sm'>
        {state === 'failed'
          ? `Couldn’t listen to this recording here: ${error}`
          : `No summary yet. Rafii can listen on this device for free: speech is transcribed and summarised${asset.duration && asset.duration > UNDERSTAND_SECONDS ? ` (from the first ${UNDERSTAND_SECONDS / 60} minutes)` : ''}; music is marked as having no transcript.`}
      </p>
      <Control tone='secondary' size='sm' icon={<Icons.sparkles aria-hidden />} onClick={() => setRun(value => value + 1)}>
        {state === 'failed' ? 'Try again' : 'Listen and summarise'}
      </Control>
    </div>
  );
}

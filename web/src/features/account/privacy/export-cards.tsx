'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import { downloadBlob } from '@/lib/download';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { Fingerprint, type FileFingerprint } from './fingerprint';
import { sha256Hex } from './privacy-model';

export interface BusyProps {
  /** Which action on the page is running; the others wait so two downloads cannot race. */
  busy: string | null;
  setBusy: (kind: string | null) => void;
}

const SUCCESS_HOLD_MS = 2000;

/** idle → loading → success/error, and back to idle after a moment so the button can be used again. */
function useButtonState() {
  const [state, setState] = useState<ButtonState>('idle');
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    []
  );
  function settle(next: 'success' | 'error') {
    setState(next);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState('idle'), SUCCESS_HOLD_MS);
  }
  return { state, start: () => setState('loading'), settle };
}

const EXPORT_FILENAME = 'postriff-private-drafts.zip';
const VOICE_FILENAME = 'postriff-personal-voice.zip';

export function ExportCard({ busy, setBusy }: BusyProps) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const button = useButtonState();
  const [file, setFile] = useState<FileFingerprint | null>(null);

  async function exportDrafts() {
    setBusy('export');
    button.start();
    try {
      await api.dataRequest(workspaceId, { kind: 'export' });
      const blob = await api.exportDrafts(workspaceId);
      downloadBlob(blob, EXPORT_FILENAME);
      setFile({ filename: EXPORT_FILENAME, bytes: blob.size, sha256: await sha256Hex(blob) });
      button.settle('success');
      toast.success('Export downloaded. Its fingerprint is on the Export card.');
    } catch (err) {
      button.settle('error');
      toast.error(err instanceof ApiError ? err.message : 'The export could not be downloaded.');
    } finally {
      setBusy(null);
      void client.invalidateQueries({ queryKey: keys.dataRequests(workspaceId) });
    }
  }

  return (
    <Card data-tour='privacy-export' className='min-w-0'>
      <CardHeader>
        <CardTitle>Export</CardTitle>
        <CardDescription>
          Drafts, sources, approvals, receipts and the learned-preference ledger as a zip. No access tokens and no media files.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        <p className='text-muted-foreground text-xs'>Each export adds a row to Data requests with the size and fingerprint PostRiff recorded.</p>
        {file && (
          <Fingerprint
            file={file}
            note='PostRiff records its receipt from a separate copy of the export, so this page does not claim the two match. Keep this fingerprint to show later that your file is unchanged.'
          />
        )}
      </CardContent>
      <CardFooter className='mt-auto'>
        <StatefulButton
          state={button.state}
          loadingText='Preparing…'
          successText='Downloaded'
          errorText='Try again'
          disabled={busy !== null && busy !== 'export'}
          onClick={() => void exportDrafts()}
        >
          Export drafts
        </StatefulButton>
      </CardFooter>
    </Card>
  );
}

export function VoiceProfileCard({ busy, setBusy }: BusyProps) {
  const { api, workspaceId } = useWorkspaceApi();
  const router = useRouter();
  const button = useButtonState();
  const [file, setFile] = useState<FileFingerprint | null>(null);

  async function exportProfile() {
    setBusy('profile');
    button.start();
    try {
      const blob = await api.exportProfile(workspaceId);
      downloadBlob(blob, VOICE_FILENAME);
      setFile({ filename: VOICE_FILENAME, bytes: blob.size, sha256: await sha256Hex(blob) });
      button.settle('success');
      toast.success('Voice profile downloaded.');
    } catch (err) {
      button.settle('error');
      if (err instanceof ApiError) {
        // The server refuses until a voice package is approved field by field; voice setup lives on Brand & voice.
        const approval = /approve/i.test(err.message);
        toast.error(err.message, approval ? { action: { label: 'Open Brand & voice', onClick: () => router.push('/app/workspace/brand') } } : undefined);
      } else {
        toast.error('The voice profile could not be downloaded.');
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card data-tour='privacy-voice' className='min-w-0'>
      <CardHeader>
        <CardTitle>Voice profile</CardTitle>
        <CardDescription>Your approved voice package as a zip, to keep or to use in another tool.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        <p className='text-muted-foreground text-xs'>
          Available once a voice package has been approved field by field. This download does not add a row to Data requests.
        </p>
        {file && <Fingerprint file={file} note='Keep this fingerprint to show later that your file is unchanged.' />}
      </CardContent>
      <CardFooter className='mt-auto'>
        <StatefulButton
          variant='outline'
          state={button.state}
          loadingText='Preparing…'
          successText='Downloaded'
          errorText='Try again'
          disabled={busy !== null && busy !== 'profile'}
          onClick={() => void exportProfile()}
        >
          Export voice profile
        </StatefulButton>
      </CardFooter>
    </Card>
  );
}

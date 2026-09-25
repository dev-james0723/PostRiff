'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import { downloadBlob } from '@/lib/download';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { SettingsSection } from '../settings-section';
import { Fingerprint, type FileFingerprint } from './fingerprint';
import { sha256Hex } from './privacy-model';

export interface BusyProps {
  /** Which action on the page is running; the others wait so two downloads cannot race. */
  busy: string | null;
  setBusy: (kind: string | null) => void;
}

/** The glass recipe on a secondary motion button (DNA §10.2). */
export const GLASS_STATEFUL =
  'rafii-glass hover:rafii-glass-selected h-12 rounded-[var(--rafii-radius-control)] border-0 bg-transparent px-4 text-sm hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent';
/** The inverted primary on a motion button (DNA §10.1). */
export const ACTION_STATEFUL = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-4 text-sm hover:brightness-[1.06]';

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
    } catch (err) {
      button.settle('error');
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t download the export. Try again.');
    } finally {
      setBusy(null);
      void client.invalidateQueries({ queryKey: keys.dataRequests(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
    }
  }

  return (
    <SettingsSection
      id='privacy-export'
      title='Export'
      description='Drafts, sources, approvals, receipts and learned preferences as a zip. No media or tokens.'
      className='h-full'
      bodyClassName='flex-1'
      data-tour='privacy-export'
    >
      {file && (
        <Fingerprint
          file={file}
          note='Keep it to show later that your file is unchanged. The receipt in Data requests is recorded from a separate copy.'
        />
      )}
      <div className='mt-auto pt-1'>
        <StatefulButton
          className={ACTION_STATEFUL}
          state={button.state}
          loadingText='Preparing…'
          successText='Downloaded'
          errorText='Try again'
          disabled={busy !== null && busy !== 'export'}
          onClick={() => void exportDrafts()}
        >
          Export drafts
        </StatefulButton>
      </div>
    </SettingsSection>
  );
}

export function VoiceProfileCard({ busy, setBusy }: BusyProps) {
  const { api, workspaceId } = useWorkspaceApi();
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
    } catch (err) {
      button.settle('error');
      if (err instanceof ApiError) {
        toast.error(err.message);
      } else {
        toast.error('Couldn’t download the voice profile. Try again.');
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <SettingsSection
      id='privacy-voice'
      title='Voice profile'
      description='Your approved voice as a zip.'
      className='h-full'
      bodyClassName='flex-1'
      data-tour='privacy-voice'
    >
      <p className='text-muted-foreground text-xs leading-relaxed'>Available after you approve your voice.</p>
      {file && <Fingerprint file={file} note='Keep it to show later that your file is unchanged.' />}
      <div className='mt-auto pt-1'>
        <StatefulButton
          variant='outline'
          className={GLASS_STATEFUL}
          state={button.state}
          loadingText='Preparing…'
          successText='Downloaded'
          errorText='Try again'
          disabled={busy !== null && busy !== 'profile'}
          onClick={() => void exportProfile()}
        >
          Export voice profile
        </StatefulButton>
      </div>
    </SettingsSection>
  );
}

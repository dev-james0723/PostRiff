'use client';

import { useId, useRef, useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import { newIdempotencyKey } from '@/lib/library/batch';
import { storageNotice } from '@/lib/library/wording';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function failureText(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 503 && error.code === 'library_capability_unavailable') return 'This isn’t available in this version of Rafii yet. Upload a file instead.';
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * The one primary Add control (UI spec §1, A059): upload files, paste a link or write a quick note. Drag and drop,
 * the photo compatibility path and the video/document upload flows stay behind "Upload files".
 */
export function AddMenu({
  disabled,
  busy,
  busyLabel,
  onUploadFiles,
  storage,
  onAdded
}: {
  disabled: boolean;
  busy: boolean;
  busyLabel: string;
  onUploadFiles: () => void;
  storage?: { usedBytes: number; limitBytes: number } | null;
  /** Announce what was added (one polite live region on the page). */
  onAdded: (message: string) => void;
}) {
  const [dialog, setDialog] = useState<'link' | 'note' | null>(null);
  const notice = storage ? storageNotice(storage.usedBytes, storage.limitBytes) : null;
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button data-tour='library-upload' variant='action' size='control' disabled={disabled} aria-label={busy ? `Add · ${busyLabel}` : 'Add to Library'}>
              {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : <Icons.add aria-hidden />}
              Add
              <Icons.chevronDown className='size-3.5 opacity-70' aria-hidden />
            </Button>
          }
        />
        <DropdownMenuContent align='end' className='rafii-elevated w-64 rounded-[var(--rafii-radius-card)] p-1.5'>
          <DropdownMenuItem className='min-h-11 gap-3 px-3' onClick={onUploadFiles}>
            <Icons.upload aria-hidden />
            <span className='flex flex-col'>
              <span>Upload files</span>
              <span className='text-muted-foreground text-xs'>Photos, videos, audio, documents</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem className='min-h-11 gap-3 px-3' onClick={() => setDialog('link')}>
            <Icons.link aria-hidden />
            <span className='flex flex-col'>
              <span>Paste link</span>
              <span className='text-muted-foreground text-xs'>Save a public page privately</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem className='min-h-11 gap-3 px-3' onClick={() => setDialog('note')}>
            <Icons.edit aria-hidden />
            <span className='flex flex-col'>
              <span>Quick note</span>
              <span className='text-muted-foreground text-xs'>Write it here; it stays private</span>
            </span>
          </DropdownMenuItem>
          {notice && notice.level !== 'unknown' ? (
            <>
              <DropdownMenuSeparator />
              <p className={cn('px-3 py-1.5 text-xs', notice.level === 'ok' ? 'text-muted-foreground' : 'text-foreground')}>{notice.label}</p>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
      <PasteLinkDialog open={dialog === 'link'} onOpenChange={(open) => setDialog(open ? 'link' : null)} onAdded={onAdded} />
      <QuickNoteDialog open={dialog === 'note'} onOpenChange={(open) => setDialog(open ? 'note' : null)} onAdded={onAdded} />
    </>
  );
}

function PasteLinkDialog({ open, onOpenChange, onAdded }: { open: boolean; onOpenChange: (open: boolean) => void; onAdded: (message: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const id = useId();
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per link: a retry after a lost response is recognised by the server instead of saving the page twice.
  const key = useRef<{ url: string; key: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = url.trim();
    if (!/^https?:\/\//i.test(value)) {
      setError('Paste a link that starts with http:// or https://');
      return;
    }
    if (!key.current || key.current.url !== value) key.current = { url: value, key: newIdempotencyKey('lib-link', randomKey) };
    setBusy(true);
    setError(null);
    try {
      const result = await api.libraryIngestLink(workspaceId, { url: value, idempotencyKey: key.current.key });
      key.current = null;
      setUrl('');
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      onAdded(result.status === 'duplicate' ? 'This link is already in your Library.' : 'Link saved to your Library. Its text is indexed in the background.');
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(failure, 'The link couldn’t be saved.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='sm'>
        <form onSubmit={(event) => void submit(event)} className='flex min-h-0 flex-1 flex-col'>
          <RafiiDialogHeader title='Paste link' intro='Rafii saves the public page’s text privately in this workspace. It doesn’t sign in anywhere or follow other links.' />
          <RafiiDialogBody className='flex flex-col gap-2'>
            <label htmlFor={`${id}-url`} className='text-sm font-medium'>
              Link
            </label>
            <Input id={`${id}-url`} type='url' inputMode='url' autoComplete='off' value={url} maxLength={2048} onChange={(event) => setUrl(event.target.value)} placeholder='https://' aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-error` : undefined} className='h-11' />
            {error ? (
              <p id={`${id}-error`} role='alert' className='text-destructive text-sm'>
                {error}
              </p>
            ) : null}
          </RafiiDialogBody>
          <RafiiDialogFooter className='flex-row justify-end'>
            <Button type='button' variant='glass' size='control' onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type='submit' variant='action' size='control' disabled={busy || !url.trim()}>
              {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              {busy ? 'Saving…' : 'Save link'}
            </Button>
          </RafiiDialogFooter>
        </form>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

function QuickNoteDialog({ open, onOpenChange, onAdded }: { open: boolean; onOpenChange: (open: boolean) => void; onAdded: (message: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const id = useId();
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  // Never assumed: the person states that they wrote this before it can count as their own words.
  const [authoredByMe, setAuthoredByMe] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<{ digest: string; key: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) {
      setError('Write the note first.');
      return;
    }
    const digest = JSON.stringify([title.trim(), text, authoredByMe]);
    if (!key.current || key.current.digest !== digest) key.current = { digest, key: newIdempotencyKey('lib-note', randomKey) };
    setBusy(true);
    setError(null);
    try {
      await api.libraryIngestNote(workspaceId, { title: title.trim() || 'Quick note', text, authoredByMe, idempotencyKey: key.current.key });
      key.current = null;
      setTitle('');
      setText('');
      setAuthoredByMe(false);
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      onAdded('Note saved to your Library.');
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(failure, 'The note couldn’t be saved.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='sm'>
        <form onSubmit={(event) => void submit(event)} className='flex min-h-0 flex-1 flex-col'>
          <RafiiDialogHeader title='Quick note' intro='Notes stay private to this workspace, like every Library item.' />
          <RafiiDialogBody className='flex flex-col gap-3'>
            <label htmlFor={`${id}-title`} className='flex flex-col gap-1.5 text-sm font-medium'>
              Title
              <Input id={`${id}-title`} value={title} maxLength={160} onChange={(event) => setTitle(event.target.value)} placeholder='Quick note' className='h-11 font-normal' />
            </label>
            <label htmlFor={`${id}-text`} className='flex flex-col gap-1.5 text-sm font-medium'>
              Note
              <textarea
                id={`${id}-text`}
                value={text}
                maxLength={20000}
                onChange={(event) => setText(event.target.value)}
                className='rafii-field rafii-focus min-h-40 w-full rounded-[var(--rafii-radius-control)] p-3 text-base font-normal md:text-sm'
              />
            </label>
            <label htmlFor={`${id}-mine`} className='flex min-h-11 items-start gap-3 text-sm'>
              <input id={`${id}-mine`} type='checkbox' checked={authoredByMe} onChange={(event) => setAuthoredByMe(event.target.checked)} className='accent-foreground mt-1 size-5 shrink-0' />
              <span className='flex flex-col gap-0.5'>
                <span className='font-medium'>I wrote this</span>
                <span className='text-muted-foreground text-xs'>Leave this off for quotes, copied text or someone else’s words. Only your own writing can ever teach Rafii your voice, and only after you approve it.</span>
              </span>
            </label>
            {error ? (
              <p role='alert' className='text-destructive text-sm'>
                {error}
              </p>
            ) : null}
          </RafiiDialogBody>
          <RafiiDialogFooter className='flex-row justify-end'>
            <Button type='button' variant='glass' size='control' onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type='submit' variant='action' size='control' disabled={busy || !text.trim()}>
              {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              {busy ? 'Saving…' : 'Save note'}
            </Button>
          </RafiiDialogFooter>
        </form>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

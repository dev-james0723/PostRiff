'use client';

import { useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import {
  RafiiDialog,
  RafiiDialogContent,
  RafiiDialogHeader,
  RafiiDialogTrigger
} from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { FolderEditor, type EditorDraft } from '@/features/channels/channel-bloom/folder-editor';
import type { FolderAccount } from '@/lib/channels/folders';

const ACCOUNTS: FolderAccount[] = [
  'Instagram',
  'Threads',
  'LinkedIn',
  'YouTube',
  'TikTok',
  'Facebook'
].map((platform) => ({
  id: platform.toLowerCase(),
  platform,
  account: '@your.studio',
  connected: true,
  state: 'Preview account'
}));
const EMPTY: EditorDraft = { name: '', symbol: 'folder', pinned: false, accountIds: [] };

/** Local review of the real editor, with synthetic accounts and no API writes. */
export function FolderMotionDemo() {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<EditorDraft>(EMPTY);
  const [saved, setSaved] = useState<EditorDraft | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <main className='relative isolate flex min-h-svh flex-col items-center justify-center gap-5 p-6'>
      <div aria-hidden className='rafii-ambient' />
      <span className='rafii-eyebrow'>Local motion preview</span>
      <h1 className='text-3xl font-medium tracking-tight'>
        A home for your <em className='rafii-serif'>accounts.</em>
      </h1>
      <p className='text-muted-foreground max-w-sm text-center text-sm'>
        Sample accounts only. Open the folder, then add a few apps to see them drop inside.
      </p>
      <RafiiDialog open={open} onOpenChange={setOpen}>
        <RafiiDialogTrigger
          render={<Button variant='action' size='control' />}
          onClick={() => setDraft(EMPTY)}
        >
          New folder
        </RafiiDialogTrigger>
        {saved && (
          <Button
            variant='quiet'
            onClick={() => {
              setDraft(saved);
              setOpen(true);
            }}
          >
            Edit saved preview
          </Button>
        )}
        <RafiiDialogContent
          size='md'
          className='h-[calc(100dvh-1.25rem)] md:h-[min(53.75rem,93dvh)]'
          initialFocus={nameRef}
        >
          <RafiiDialogHeader
            eyebrow='New folder'
            title='Keep a good'
            accent='group.'
            intro='A name, a few accounts. Ready for next time.'
          />
          <FolderEditor
            draft={draft}
            onChange={setDraft}
            folders={[]}
            accounts={ACCOUNTS}
            draftable={() => true}
            keepIds={[]}
            error={null}
            busy={false}
            onSave={() => {
              setSaved(draft);
              setOpen(false);
            }}
            onCancel={() => setOpen(false)}
            nameRef={nameRef}
          />
        </RafiiDialogContent>
      </RafiiDialog>
      <Button variant='quiet' onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}>
        Switch appearance
      </Button>
      {saved && (
        <p role='status' className='text-muted-foreground text-sm'>
          Preview saved: {saved.name} · {saved.accountIds.length} accounts (local only)
        </p>
      )}
    </main>
  );
}

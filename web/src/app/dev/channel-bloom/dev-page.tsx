'use client';

import { Suspense, useMemo, useState } from 'react';
import { AppGate } from '@/components/layout/app-gate';
import { Button } from '@/components/ui/button';
import { ChannelBloomDialog, toFolderAccounts } from '@/features/channels/channel-bloom';
import { useDestinations } from '@/features/agent/use-destinations';
import { useSnapshot } from '@/lib/api/hooks';
import { AuthProvider } from '@/lib/auth/session';
import { WorkspaceProvider } from '@/lib/workspace/provider';

/**
 * Mounts the dialog on the real workspace (dev identity, disposable database) until Stream E
 * wires it into Home. Everything shown comes from the snapshot: accounts from
 * `phase2.channels`, folders from `phase2.channelFolders`; the committed selection lives in
 * `useDestinations` (session storage per workspace).
 */
export function ChannelBloomDevPage() {
  return (
    <AuthProvider>
      <WorkspaceProvider>
        <Suspense fallback={null}>
          <AppGate>
            <Stage />
          </AppGate>
        </Suspense>
      </WorkspaceProvider>
    </AuthProvider>
  );
}

function Stage() {
  const snapshot = useSnapshot();
  const channels = snapshot.data?.state?.phase2?.channels;
  const accounts = useMemo(() => toFolderAccounts(channels), [channels]);
  const folders = snapshot.data?.state?.phase2?.channelFolders ?? [];
  const destinations = useDestinations(accounts);
  const [open, setOpen] = useState(false);

  return (
    <main className='relative isolate flex min-h-svh flex-col items-start gap-4 p-6 md:p-10'>
      <div aria-hidden className='rafii-ambient' />
      <span className='rafii-eyebrow'>Development · Channel Bloom</span>
      <h1 className='text-foreground text-2xl font-medium tracking-tight'>
        Where should it <em className='rafii-serif'>go?</em>
      </h1>
      <p className='text-muted-foreground max-w-prose text-sm leading-relaxed'>
        {accounts.length} connected {accounts.length === 1 ? 'account' : 'accounts'}, {folders.length} {folders.length === 1 ? 'folder' : 'folders'} in this workspace. Committed selection: <strong className='text-foreground'>{destinations.summary}</strong>
        {destinations.selected.length > 0 && <span> ({destinations.selected.join(', ')})</span>}.
      </p>
      <div className='flex flex-wrap items-center gap-2'>
        <Button variant='action' size='control' onClick={() => setOpen(true)} aria-haspopup='dialog' aria-expanded={open}>
          Choose channels
        </Button>
        <Button variant='quiet' size='control' onClick={destinations.clear} disabled={destinations.selected.length === 0 && !destinations.context}>
          Clear committed selection
        </Button>
      </div>
      <ChannelBloomDialog open={open} onOpenChange={setOpen} accounts={accounts} folders={folders} selected={destinations.selected} context={destinations.context} onCommit={destinations.commit} />
    </main>
  );
}

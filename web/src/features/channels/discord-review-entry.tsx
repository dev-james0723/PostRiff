'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useWorkspace } from '@/lib/workspace/provider';
import { usePreferences } from '@/lib/preferences';
import { discordCopy } from '@/lib/channels/discord-copy';
import { StateMessage } from '@/components/rafii';

/** A link has no bearer authority: validate the signed-in actor before switching. */
export function DiscordReviewEntry() {
  const params = useSearchParams();
  const router = useRouter();
  const workspace = useWorkspace();
  const copy = discordCopy(usePreferences().locale);
  const target = params.get('workspaceId') ?? '';
  const identity = params.get('identityId') ?? '';
  const [approvedContext, setApprovedContext] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    let current = true;
    setApprovedContext(null); setDenied(false);
    if (workspace.status !== 'ready') return () => { current = false; };
    if (!workspace.workspaces.some(w => w.workspaceId === target) || !identity) {
      setDenied(true); return () => { current = false; };
    }
    workspace.api.discordPrivateReview(target, identity).then(result => {
      if (!current) return;
      if (result.ready !== true || result.workspaceId !== target) { setDenied(true); return; }
      setApprovedContext(target); workspace.switchTo(target);
    }).catch(() => { if (current) setDenied(true); });
    return () => { current = false; };
  }, [workspace.api, workspace.status, workspace.workspaces, workspace.switchTo, target, identity]);
  useEffect(() => {
    if (!denied && approvedContext === target && workspace.workspaceId === target) router.replace('/app/queue');
  }, [approvedContext, denied, target, workspace.workspaceId, router]);
  return <div className='mx-auto flex max-w-xl flex-col gap-4 p-5'>
    <StateMessage kind={denied ? 'error' : 'loading'} title={denied ? copy.privateDenied : copy.privateOpening} />
    {denied && <Link href='/app/channels' className='rafii-focus min-h-11 rounded px-3 py-2 underline'>{copy.openChannels}</Link>}
  </div>;
}

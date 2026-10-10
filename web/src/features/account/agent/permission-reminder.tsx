'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { permissionsUiEnabled } from '@/lib/agent-permissions/model';
import { useWorkspace } from '@/lib/workspace/provider';
import type { AgentPermissionsView } from '@/lib/api/agent-permissions-types';
import { useAgentPermissionChanges, useAgentPermissions } from './use-agent-permissions';

/** A quiet card after Welcome. Showing or dismissing it never writes a grant. */
export function PermissionReminder() {
  const { workspaceId } = useWorkspace();
  return permissionsUiEnabled() && workspaceId ? <ReminderCard key={workspaceId} /> : null;
}

function ReminderCard() {
  const query = useAgentPermissions();
  const changes = useAgentPermissionChanges();
  const prompted = useRef(false);
  const [view, setView] = useState<AgentPermissionsView | null>(null);
  const [closed, setClosed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    if (!prompted.current && query.data?.available && query.data.state.needsChoice && query.data.reminder.due) {
      prompted.current = true;
      setView(query.data);
      void changes.remind('shown');
    }
  }, [query.data, changes]);
  if (!view || closed || (query.data && !query.data.state.needsChoice)) return null;

  async function save() {
    setBusy(true);
    const result = await changes.save(view!, { preset: 'recommended', source: 'onboarding' }, { confirmed: confirming });
    setBusy(false);
    if (result.kind === 'saved') setClosed(true);
    else if (result.kind === 'confirm') setConfirming(true);
    else {
      setConfirming(false);
      setMessage(result.message);
      if (result.kind === 'reload' && query.data) setView(query.data);
    }
  }

  return <aside aria-label='Choose Rafii permissions' className='rafii-glass-strong fixed bottom-20 start-3 z-30 flex max-h-[70dvh] w-[min(24rem,calc(100vw-1.5rem))] flex-col gap-3 overflow-y-auto rounded-xl p-4 shadow-lg md:bottom-4'>
    <p className='text-sm font-medium'>{view.copy.reminder.title}</p>
    <p className='text-muted-foreground text-sm'>{view.copy.reminder.summary}</p>
    <label className='flex min-h-11 items-start gap-3 text-sm'>
      <input type='radio' aria-label={view.copy.presets.recommended.title} name='permission-reminder-preset' checked readOnly className='mt-1 size-4 shrink-0' />
      <span><strong>{view.copy.presets.recommended.title}</strong><br />{view.copy.presets.recommended.summary}</span>
    </label>
    {view.mode === 'shadow' && <p className='text-muted-foreground text-sm'>{view.copy.shadow}</p>}
    {confirming && <p className='text-sm'>This lets Rafii do more, including organizing drafts from your conversation. Allow Recommended?</p>}
    <p role='status' aria-live='polite' className='text-sm'>{message}</p>
    <div className='flex flex-wrap items-center gap-2'>
      <Button variant='action' size='control' className='min-h-11' disabled={busy} onClick={() => void save()}>{confirming ? 'Allow Recommended' : view.copy.reminder.save}</Button>
      <Button variant='quiet' size='control' className='min-h-11' disabled={busy} onClick={() => { setClosed(true); void changes.remind('not_now'); }}>{view.copy.reminder.notNow}</Button>
      <Link href='/app/account/agent' className='rafii-focus inline-flex min-h-11 items-center px-2 text-sm underline' onClick={() => { setClosed(true); void changes.remind('dismissed'); }}>All settings</Link>
    </div>
  </aside>;
}

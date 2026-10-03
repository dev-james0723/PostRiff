'use client';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { SettingsSection } from './settings-section';

export function SupportCard() {
  const { api, workspaceId } = useWorkspaceApi(); const [category, setCategory] = useState('technical'); const [message, setMessage] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const tickets = useQuery({ queryKey: ['support', workspaceId], queryFn: () => api.supportTickets(workspaceId) });
  const detail = useQuery({ queryKey: ['support', workspaceId, selected], enabled: Boolean(selected), queryFn: () => api.supportTicket(workspaceId, selected!) });
  const send = useMutation({ mutationFn: () => api.supportMessage(workspaceId, { requestId, message, ...(selected ? {} : { category }) }, selected ?? undefined),
    onSuccess: async () => { setMessage(''); setRequestId(crypto.randomUUID()); await tickets.refetch(); if (selected) await detail.refetch(); } });
  return <SettingsSection id='profile-support' title='Support' description='Contact Rafii support and read replies inside your workspace.'>
    {tickets.isError ? <StateMessage kind='error' layout='inline' title='Support is unavailable' /> : <ul className='space-y-2'>{tickets.data?.tickets.map((t) => <li key={t.id}><Button variant='quiet' onClick={() => { setSelected(t.id); setMessage(''); setRequestId(crypto.randomUUID()); }}>{t.category} · {t.status.replaceAll('_', ' ')}</Button></li>)}</ul>}
    {selected && <><Button variant='quiet' onClick={() => { setSelected(null); setMessage(''); setRequestId(crypto.randomUUID()); }}>Start a new ticket</Button>{detail.data?.messages.map((m, i) => <p className='whitespace-pre-wrap break-words text-sm' key={i}>{m.role}: {m.body}</p>)}</>}
    <form className='mt-3 flex flex-col gap-3' onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
      {!selected && <label className='flex flex-col gap-2 text-sm'>Category<select className='rafii-quiet rounded-lg p-2' value={category} onChange={(e) => { setCategory(e.target.value); setRequestId(crypto.randomUUID()); }}>{['technical', 'billing', 'account', 'other'].map((v) => <option value={v} key={v}>{v}</option>)}</select></label>}
      <label className='flex flex-col gap-2 text-sm'>Message<textarea aria-label='Message' className='rafii-quiet rounded-lg p-3' maxLength={8000} value={message} onChange={(e) => { setMessage(e.target.value); setRequestId(crypto.randomUUID()); }} /></label>
      <Button type='submit' variant='action' disabled={send.isPending || !message.trim()}>{send.isPending ? 'Sending…' : 'Send support message'}</Button>
      {send.isSuccess && <p role='status' className='text-sm'>Message sent to support.</p>}{send.isError && <StateMessage kind='error' layout='inline' title='Support message was not sent' description='Retry the same message to reuse its request key.' />}
    </form>
  </SettingsSection>;
}

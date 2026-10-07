'use client';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { founderFetch } from '@/lib/founder/api';
import type { Envelope } from '@/lib/founder/types';
import { useCapability, useFounderScope } from '../customers/kit/api';
import { Panel } from '../customers/kit/page-frame';

type Ticket = { id: string; category: string; status: string; revision: number; createdAt: string; identityVisibility: string };
type Reveal = { email: string | null; messages: { role: string; body: string; createdAt: string }[] };

export function SupportInbox() {
  const scope = useFounderScope(); const canReply = useCapability('followups.write'); const canReveal = useCapability('control.settings');
  const [selected, setSelected] = useState<Ticket | null>(null); const [reply, setReply] = useState(''); const [reveal, setReveal] = useState<Reveal | null>(null);
  const replyRequest = useRef<{ signature: string; id: string } | null>(null);
  function sendReply() {
    if (!selected) return;
    const signature = JSON.stringify([selected.id, selected.revision, reply]);
    if (replyRequest.current?.signature !== signature) replyRequest.current = { signature, id: crypto.randomUUID() };
    mutate.mutate({ operation: 'reply', body: { requestId: replyRequest.current.id, message: reply, revision: selected.revision } });
  }
  const query = useQuery({ queryKey: scope.key('support-tickets'), enabled: scope.ready && scope.mode === 'live', queryFn: async ({ signal }) => (await founderFetch<Envelope<{ tickets: Ticket[] }>>('/support/tickets', { signal })).data });
  const mutate = useMutation({ mutationFn: async ({ operation, body }: { operation: string; body: unknown }) => (await founderFetch<Envelope<Reveal>>(`/support/tickets/${selected?.id}/${operation}`, { method: 'POST', body })).data,
    onSuccess: async (data, variables) => { if (variables.operation === 'reveal') setReveal(data); else { setReply(''); setSelected(null); setReveal(null); await query.refetch(); } } });
  if (scope.mode === 'demo') return <StateMessage kind='empty' layout='inline' title='Demo support uses fictional records' description='Select Live to read the in-app ticket source.' />;
  return <Panel title='In-app support inbox' description='Customer identity and original messages stay masked until an explicit support reveal.'>
    {query.isPending ? <p>Loading tickets…</p> : query.isError ? <StateMessage kind='error' layout='inline' title='Support source unavailable' description='The ticket projection could not be read.' /> : query.data?.tickets.length === 0 ? <p className='text-muted-foreground text-sm'>No support tickets yet.</p> : <ul className='space-y-2'>{query.data?.tickets.map((t) => <li key={t.id}><Button variant='quiet' onClick={() => { setSelected(t); setReveal(null); mutate.reset(); }}>{t.category} · {t.status.replaceAll('_', ' ')} · …{t.id.slice(-8)}</Button></li>)}</ul>}
    {selected && <div className='rafii-quiet mt-4 flex flex-col gap-3 rounded-lg p-4'>
      <p>{selected.category} · {selected.status.replaceAll('_', ' ')} · identity masked</p>
      <Button variant='quiet' disabled={!canReveal || mutate.isPending} onClick={() => mutate.mutate({ operation: 'reveal', body: { confirmation: 'REVEAL', reasonCode: 'support_investigation' } })}>Reveal original support message and identity</Button>
      {reveal && <div><p className='break-all text-sm'>{reveal.email ?? 'Email unavailable'}</p>{reveal.messages.map((m, i) => <p key={i} className='mt-2 whitespace-pre-wrap break-words text-sm'>{m.role}: {m.body}</p>)}</div>}
      <label className='flex flex-col gap-2 text-sm'>In-app reply<textarea aria-label='In-app reply' className='rafii-quiet rounded-lg p-3' maxLength={8000} value={reply} onChange={(e) => setReply(e.target.value)} disabled={!canReply} /></label>
      <div className='flex flex-wrap gap-2'><Button variant='action' disabled={!canReply || mutate.isPending || !reply.trim()} onClick={sendReply}>Send in-app reply</Button>
        <Button variant='quiet' disabled={!canReply || mutate.isPending} onClick={() => mutate.mutate({ operation: 'status', body: { revision: selected.revision, status: selected.status === 'resolved' ? 'open' : 'resolved' } })}>{selected.status === 'resolved' ? 'Reopen ticket' : 'Resolve ticket'}</Button>
        <Button variant='quiet' onClick={() => { setSelected(null); setReveal(null); setReply(''); }}>Close</Button></div>
      {mutate.isError && <StateMessage kind='error' layout='inline' title='Support action was not completed' description='Reload a stale ticket or complete a recent second factor for identity reveal, then retry.' />}
    </div>}
  </Panel>;
}

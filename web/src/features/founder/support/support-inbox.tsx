'use client';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { founderFetch } from '@/lib/founder/api';
import type { Envelope } from '@/lib/founder/types';
import { useCapability, useFounderScope } from '../customers/kit/api';
import { Panel } from '../customers/kit/page-frame';

type Ticket = { id: string; category: string; status: string; revision: number; createdAt: string; identityVisibility: string;
  priority: string; assigneeId: string | null; duplicateOfTicketId: string | null };
type Reveal = { ticketId: string; email: string | null; messages: { role: string; body: string; createdAt: string }[]; hasEarlierMessages?: boolean };
type WorkflowEvent = { id: string; kind: string; actorRole: string; revision: number; occurredAt: string; relatedTicketId: string | null };
type Change = { ticketId: string; operation: string; body: unknown };
type Result = { ticket?: Ticket } & Partial<Reveal>;

export function SupportInbox() {
  const scope = useFounderScope();
  if (scope.mode === 'demo') return <StateMessage kind='empty' layout='inline' title='Demo support uses fictional records' description='Select Live to read the in-app ticket source.' />;
  if (!scope.ready) return <StateMessage kind='empty' layout='inline' title='Waiting for your Founder session' />;
  // Scope changes and a lost session unmount all selections and revealed data.
  return <LiveSupportInbox key={JSON.stringify(scope.key('support-selection'))} />;
}

function LiveSupportInbox() {
  const scope = useFounderScope();
  const canReply = useCapability('followups.write'), canReveal = useCapability('control.settings');
  const [selected, setSelected] = useState<Ticket | null>(null);
  const selectedId = useRef<string | null>(null);
  const [reply, setReply] = useState(''), [reveal, setReveal] = useState<Reveal | null>(null);
  const [priority, setPriority] = useState('normal'), [assignee, setAssignee] = useState('keep');
  const [status, setStatus] = useState('open'), [target, setTarget] = useState(''), [relation, setRelation] = useState('duplicate');
  const request = useRef<{ signature: string; id: string } | null>(null);
  async function read<T>(path: string, signal?: AbortSignal) {
    const envelope = await founderFetch<Envelope<T>>(path, { signal });
    if (envelope.environment !== scope.environment) throw new Error('Support response scope changed.');
    return envelope.data;
  }
  const query = useQuery({ queryKey: scope.key('support-tickets'), queryFn: ({ signal }) => read<{ tickets: Ticket[] }>('/support/tickets', signal) });
  const events = useQuery({ queryKey: scope.key('support-history', selected?.id), enabled: selected !== null,
    queryFn: ({ signal }) => read<{ events: WorkflowEvent[]; hasEarlierEvents: boolean }>(`/support/tickets/${selected!.id}/history`, signal) });
  const mutate = useMutation({ gcTime: 0,
    mutationFn: async ({ ticketId, operation, body }: Change) => {
      const envelope = await founderFetch<Envelope<Result>>(`/support/tickets/${ticketId}/${operation}`, { method: 'POST', body });
      if (envelope.environment !== scope.environment) throw new Error('Support response scope changed.');
      return envelope.data;
    },
    onSuccess: async (data, variables) => {
      if (selectedId.current !== variables.ticketId) return;
      if (variables.operation === 'reveal') {
        if (data.ticketId === variables.ticketId && Array.isArray(data.messages)) setReveal(data as Reveal);
        return;
      }
      if (data.ticket?.id === variables.ticketId) { setSelected(data.ticket); setStatus(data.ticket.status); setPriority(data.ticket.priority); }
      if (variables.operation === 'reply') setReply('');
      await Promise.all([query.refetch(), events.refetch()]);
    }
  });
  function select(ticket: Ticket | null) {
    selectedId.current = ticket?.id ?? null; setSelected(ticket); setReveal(null); setReply(''); setTarget(''); setAssignee('keep');
    setPriority(ticket?.priority ?? 'normal'); setStatus(ticket?.status ?? 'open'); request.current = null; mutate.reset();
  }
  function change(operation: string, fields: Record<string, unknown>) {
    if (!selected) return;
    const body = { revision: selected.revision, ...fields };
    const signature = JSON.stringify([selected.id, operation, body]);
    if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
    mutate.mutate({ ticketId: selected.id, operation, body: { ...body, requestId: request.current.id } });
  }
  return <Panel title='In-app support inbox' description='Customer identity and original messages stay masked until an explicit support reveal.'>
    {query.isPending ? <p>Loading tickets…</p> : query.isError ? <StateMessage kind='error' layout='inline' title='Support source unavailable' description='The ticket projection could not be read.' /> : query.data?.tickets.length === 0 ? <p className='text-muted-foreground text-sm'>No support tickets yet.</p> : <ul className='space-y-2'>{query.data?.tickets.map((ticket) => <li key={ticket.id}><Button variant='quiet' onClick={() => select(ticket)}>{ticket.category} · {ticket.priority} · {ticket.status.replaceAll('_', ' ')} · …{ticket.id.slice(-8)}</Button></li>)}</ul>}
    {selected && <div className='rafii-quiet mt-4 flex flex-col gap-3 rounded-lg p-4'>
      <p>{selected.category} · {selected.status.replaceAll('_', ' ')} · identity {reveal ? 'revealed for this support session' : 'masked'}</p>
      <p className='break-all text-xs'>Ticket: {selected.id}</p>
      <p className='text-sm'>{selected.assigneeId ? 'Assigned to Founder support' : 'Unassigned'}</p>
      <div className='flex flex-wrap gap-3'>
        <label className='flex flex-col gap-1 text-sm'>Priority<select aria-label='Ticket priority' className='rafii-quiet rounded-lg p-2' value={priority} onChange={(event) => setPriority(event.target.value)} disabled={!canReply || mutate.isPending}>{['low', 'normal', 'high', 'urgent'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className='flex flex-col gap-1 text-sm'>Assignee<select aria-label='Ticket assignee' className='rafii-quiet rounded-lg p-2' value={assignee} onChange={(event) => setAssignee(event.target.value)} disabled={!canReply || mutate.isPending}><option value='keep'>Keep current assignee</option><option value='me'>Assign to me</option><option value='unassigned'>Unassigned</option></select></label>
        <Button variant='quiet' disabled={!canReply || mutate.isPending} onClick={() => change('triage', { priority, assignee })}>Save triage</Button>
      </div>
      <Button variant='quiet' disabled={!canReveal || mutate.isPending} onClick={() => mutate.mutate({ ticketId: selected.id, operation: 'reveal', body: { confirmation: 'REVEAL', reasonCode: 'support_investigation' } })}>Reveal original support message and identity</Button>
      {reveal && <div><p className='break-all text-sm'>{reveal.email ?? 'Email unavailable'}</p>{reveal.messages.map((message, index) => <p key={index} className='mt-2 whitespace-pre-wrap break-words text-sm'>{message.role}: {message.body}</p>)}{reveal.hasEarlierMessages && <p className='text-muted-foreground text-xs'>Showing the most recent 200 messages. Earlier messages remain in the original ticket.</p>}</div>}
      <label className='flex flex-col gap-2 text-sm'>In-app reply<textarea aria-label='In-app reply' className='rafii-quiet rounded-lg p-3' maxLength={8000} value={reply} onChange={(event) => setReply(event.target.value)} disabled={!canReply || mutate.isPending} /></label>
      <Button variant='action' disabled={!canReply || mutate.isPending || !reply.trim()} onClick={() => change('reply', { message: reply })}>Send in-app reply</Button>
      <div className='flex flex-wrap gap-3'><label className='flex flex-col gap-1 text-sm'>Status<select aria-label='Ticket status' className='rafii-quiet rounded-lg p-2' value={status} onChange={(event) => setStatus(event.target.value)} disabled={!canReply || mutate.isPending}>{[...new Set([selected.status, 'open', 'waiting_customer', 'resolved', 'closed', 'spam'])].map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label><Button variant='quiet' disabled={!canReply || mutate.isPending || status === selected.status || status === 'duplicate'} onClick={() => change('status', { status })}>Update status</Button></div>
      <label className='flex flex-col gap-1 text-sm'>Related ticket ID<input aria-label='Related ticket ID' className='rafii-quiet rounded-lg p-2' maxLength={36} value={target} onChange={(event) => setTarget(event.target.value)} disabled={!canReply || mutate.isPending} /></label>
      <label className='flex flex-col gap-1 text-sm'>Relationship<select aria-label='Ticket relationship' className='rafii-quiet rounded-lg p-2' value={relation} onChange={(event) => setRelation(event.target.value)} disabled={!canReply || mutate.isPending}><option value='duplicate'>Duplicate of the related ticket</option><option value='verified_recurrence'>Verified same issue recurrence after resolution</option></select></label>
      <div className='flex flex-wrap gap-2'><Button variant='quiet' disabled={!canReply || mutate.isPending || !/^[0-9a-f-]{36}$/i.test(target)} onClick={() => change('link', { targetTicketId: target, relation })}>Link ticket</Button>{selected.duplicateOfTicketId && <Button variant='quiet' disabled={!canReply || mutate.isPending} onClick={() => change('unlink', {})}>Remove duplicate link and reopen</Button>}<Button variant='quiet' onClick={() => select(null)}>Close</Button></div>
      <div><p className='text-sm font-medium'>Workflow history</p>{events.isPending ? <p>Loading history…</p> : events.isError ? <p>Workflow history is unavailable.</p> : <ul className='space-y-1 text-sm'>{events.data?.events.map((event) => <li key={event.id} className='break-words'>{event.kind.replaceAll('_', ' ')} · {event.actorRole} · {event.occurredAt}</li>)}</ul>}{events.data?.hasEarlierEvents && <p className='text-muted-foreground text-xs'>Showing the most recent 100 workflow events. Earlier events remain in the ticket history.</p>}<p className='text-muted-foreground text-xs'>Only observed workflow events are shown. Business-time SLA and CSAT have no configured source.</p></div>
      {mutate.isError && <StateMessage kind='error' layout='inline' title='Support action was not completed' description='Reload a stale ticket, or complete a recent second factor if the application requests it for identity reveal.' />}
    </div>}
  </Panel>;
}

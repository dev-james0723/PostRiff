'use client';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { SettingsSection } from './settings-section';

export function SupportCard() {
  const { workspaceId } = useWorkspaceApi();
  return <WorkspaceSupportCard key={workspaceId} />;
}

function WorkspaceSupportCard() {
  const { api, workspaceId } = useWorkspaceApi();
  const [category, setCategory] = useState('technical'), [message, setMessage] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const surveyRequest = useRef<{ signature: string; id: string } | null>(null);
  const tickets = useQuery({ queryKey: ['support', workspaceId], queryFn: () => api.supportTickets(workspaceId) });
  const detail = useQuery({ queryKey: ['support', workspaceId, selected], enabled: selected !== null, queryFn: () => api.supportTicket(workspaceId, selected!) });
  const send = useMutation({ gcTime: 0,
    mutationFn: ({ ticketId, ...body }: { ticketId: string | null; requestId: string; message: string; category?: string }) => api.supportMessage(workspaceId, body, ticketId ?? undefined),
    onSuccess: async () => { setMessage(''); setRequestId(crypto.randomUUID()); await tickets.refetch(); if (selected) await detail.refetch(); } });
  const answer = useMutation({ gcTime: 0,
    mutationFn: ({ ticketId, ...body }: { ticketId: string; surveyId: string; requestId: string; helpful: boolean }) => api.supportSurvey(workspaceId, ticketId, body),
    onSuccess: async () => { await detail.refetch(); } });
  const pending = send.isPending || answer.isPending;
  const survey = detail.data?.survey;
  function select(ticketId: string | null) {
    setSelected(ticketId); setMessage(''); setRequestId(crypto.randomUUID()); surveyRequest.current = null; send.reset(); answer.reset();
  }
  function respond(helpful: boolean) {
    if (selected === null || !survey || survey.state !== 'eligible') return;
    const signature = JSON.stringify([selected, survey.id, helpful]);
    if (surveyRequest.current?.signature !== signature) surveyRequest.current = { signature, id: crypto.randomUUID() };
    answer.mutate({ ticketId: selected, surveyId: survey.id, requestId: surveyRequest.current.id, helpful });
  }
  return <SettingsSection id='profile-support' title='Support' description='Contact Rafii support and read replies inside your workspace.'>
    {tickets.isError ? <StateMessage kind='error' layout='inline' title='Support is unavailable' /> : <ul className='space-y-2'>{tickets.data?.tickets.map((ticket) => <li key={ticket.id}><Button variant='quiet' disabled={pending} onClick={() => select(ticket.id)}>{ticket.category} · {ticket.status.replaceAll('_', ' ')}</Button></li>)}</ul>}
    {selected && <>
      <Button variant='quiet' disabled={pending} onClick={() => select(null)}>Start a new ticket</Button>
      {detail.isError && <StateMessage kind='error' layout='inline' title='This support ticket is unavailable' />}
      {detail.data?.messages.map((item, index) => <p className='whitespace-pre-wrap break-words text-sm' key={index}>{item.role}: {item.body}</p>)}
      {detail.data?.hasEarlierMessages && <p className='text-muted-foreground text-xs'>Showing the most recent 200 messages. Earlier messages remain in this ticket.</p>}
      <p className='text-sm font-medium'>Workflow history</p>
      <ul className='text-sm'>{detail.data?.history?.map((event, index) => <li key={index}>{event.kind.replaceAll('_', ' ')} · {event.actorRole} · {event.occurredAt}</li>)}</ul>
      {detail.data?.hasEarlierEvents && <p className='text-muted-foreground text-xs'>Showing the most recent 100 events. Earlier events remain in this ticket.</p>}
      {survey?.state === 'eligible' && <div className='rafii-quiet mt-3 rounded-lg p-3' aria-label='Support resolution feedback'>
        <p className='text-sm'>{survey.question}</p><p className='text-muted-foreground text-xs'>Optional feedback about this resolution.</p>
        <div className='mt-2 flex gap-2'><Button variant='quiet' disabled={pending} onClick={() => respond(true)}>Yes, it helped</Button><Button variant='quiet' disabled={pending} onClick={() => respond(false)}>No, it did not help</Button></div>
      </div>}
      {survey?.state === 'answered' && <p role='status' className='text-sm'>Your feedback for this resolution is recorded.</p>}
      {answer.isError && <StateMessage kind='error' layout='inline' title='Feedback save could not be confirmed' description='Retry your choice, or reload if this ticket has reopened.' />}
    </>}
    <form className='mt-3 flex flex-col gap-3' onSubmit={(event) => { event.preventDefault(); send.mutate({ ticketId: selected, requestId, message, ...(selected ? {} : { category }) }); }}>
      {!selected && <label className='flex flex-col gap-2 text-sm'>Category<select className='rafii-quiet rounded-lg p-2' value={category} disabled={pending} onChange={(event) => { setCategory(event.target.value); setRequestId(crypto.randomUUID()); }}>{['technical', 'billing', 'account', 'other'].map((value) => <option value={value} key={value}>{value}</option>)}</select></label>}
      <label className='flex flex-col gap-2 text-sm'>Message<textarea aria-label='Message' className='rafii-quiet rounded-lg p-3' maxLength={8000} value={message} disabled={pending} onChange={(event) => { setMessage(event.target.value); setRequestId(crypto.randomUUID()); }} /></label>
      <Button type='submit' variant='action' disabled={pending || !message.trim()}>{send.isPending ? 'Sending…' : 'Send support message'}</Button>
      {send.isSuccess && <p role='status' className='text-sm'>Message sent to support.</p>}{send.isError && <StateMessage kind='error' layout='inline' title='Support message save could not be confirmed' description='Retry the same message to reuse its request key.' />}
    </form>
  </SettingsSection>;
}
